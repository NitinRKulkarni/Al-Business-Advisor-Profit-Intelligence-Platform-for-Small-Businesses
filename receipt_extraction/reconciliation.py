"""
reconciliation
================

Merges independent per-engine extractions (`EngineExtraction`, one per
OCR engine) into a single `ReceiptData` plus a `FieldDecision` per field
recording what each engine said, whether they agreed, and why the final
value was selected.

Core rule: OCR confidence is never the tiebreaker
----------------------------------------------------
This module never picks "whichever engine had higher `ocr_confidence`".
That has been measured, on this project's own data, to be an unreliable
signal (an image scored the dataset's highest Tesseract confidence while
recognising only three words). Selection instead follows this order of
evidence, strongest first:

1. **Agreement.** Both engines produced the same value (within a small
   numeric tolerance / normalized text match) -> high confidence, source
   records both engines.
2. **Arithmetic consistency.** Engines disagree, but one candidate is the
   one that makes `subtotal - discount + tax ~= total` (or
   `sum(item amounts) ~= subtotal`) hold -> that candidate is selected,
   source="arithmetic", and the disagreement is recorded rather than
   hidden.
3. **Single-engine evidence.** Only one engine produced a usable value at
   all (the other returned nothing / unparseable) -> use it, but at
   reduced confidence relative to agreement.
4. **Unresolved disagreement.** Engines disagree and no arithmetic
   evidence can decide between them -> value is None, both candidates are
   preserved in `FieldDecision.candidates` for a human (or a future,
   stronger engine) to resolve. This is the direct implementation of
   "wrong data is worse than missing data": the module would rather
   return null than guess between two engines that disagree.

Nothing here ever invents a digit. Every candidate value reconciled here
came from an actual `ReceiptData` produced by `extract_from_ocr()` on a
real engine's OCR text.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .models import EngineExtraction, FieldDecision, LineItem, ReceiptData

_NUMERIC_ABS_TOLERANCE = 1.0
_NUMERIC_REL_TOLERANCE = 0.02

_SCALAR_TEXT_FIELDS = (
    "document_type", "vendor_name", "customer_name",
    "invoice_number", "receipt_number", "date", "time", "currency",
    "payment_method",
)
_NUMERIC_FIELDS = ("subtotal", "tax", "discount")  # "total" is handled separately (arithmetic fallback)

# Two thresholds for cross-engine item matching (see
# `_match_items_across_engines`):
#
# - `_ITEM_DESC_MATCH_RATIO_POSITIONAL` (low) applies ONLY when the two
#   candidate rows are also at the SAME index in their respective
#   engine's item list -- i.e. both engines are looking at the same
#   physical table row in reading order, so even a heavily OCR-mangled
#   description ("Back Cover" / "Back Covr") is trusted to be the same
#   row. Position is the strong signal here, text similarity is just a
#   sanity floor.
# - `_ITEM_DESC_MATCH_RATIO_TEXT_ONLY` (high) applies when position does
#   NOT line up (e.g. one engine skipped a row, shifting later indices).
#   Without position to lean on, text similarity alone must be very high
#   before two rows are merged -- otherwise genuinely different items
#   that happen to share most of their wording ("Widget A" vs "Widget B"
#   is 87% similar as plain strings) would be wrongly merged into one.
_ITEM_DESC_MATCH_RATIO_POSITIONAL = 0.3
_ITEM_DESC_MATCH_RATIO_TEXT_ONLY = 0.85


def _numbers_agree(a: float, b: float) -> bool:
    return abs(a - b) <= max(_NUMERIC_ABS_TOLERANCE, abs(b) * _NUMERIC_REL_TOLERANCE)


def _digits_of(value: float) -> str:
    """
    Digit string of a money value, with a trailing ".00" dropped.

    OCR routinely reads the same amount as "850" and "850.00"; comparing
    digit SHAPE (not the float) is what makes the classifications below
    meaningful, so an incidental decimal-formatting difference must not be
    mistaken for a digit-level corruption.
    """
    if value == int(value):
        return str(abs(int(value)))
    return str(abs(value)).replace(".", "")


def classify_numeric_disagreement(a: float, b: float) -> str | None:
    """
    Name the digit-level SHAPE of a disagreement between two OCR readings
    of the same number, or None if it does not match a known pattern.

    This is purely diagnostic -- it never selects, corrects or invents a
    value. Its purpose is to turn "the engines disagree" into a specific,
    actionable reason on the review queue, because these particular
    corruptions are the recognisable signatures of OCR digit failure that
    this project has repeatedly measured (a dropped trailing digit turning
    1550 into 155, a decimal-point shift turning 1250.00 into 125000, a
    leading digit lost from 1121 leaving 121).

    Deliberately pattern-based, not value-based: it compares digit strings
    and magnitudes, so it applies to any pair of numbers on any receipt and
    hardcodes no amount, vendor or filename.
    """
    if a == b:
        return None

    da, db = _digits_of(a), _digits_of(b)

    # Decimal point moved: the SAME digit sequence at a different
    # magnitude ("12.50" vs "125.00"). Checked first and required to have
    # identical digits, because a case like 1250 -> 125 also happens to
    # differ by a factor of ten but is better described as a lost trailing
    # digit (the digit sequence itself changed).
    if da == db and a != 0 and b != 0:
        ratio = max(abs(a), abs(b)) / min(abs(a), abs(b))
        for power in (10.0, 100.0, 1000.0):
            if abs(ratio - power) <= 0.01:
                return "decimal_place_shift"

    longer, shorter = (da, db) if len(da) >= len(db) else (db, da)

    # A digit dropped from the END: "1550" read as "155".
    if len(longer) == len(shorter) + 1 and longer.startswith(shorter):
        return "trailing_digit_lost"

    # A digit dropped from the FRONT: "1121" read as "121" (measured on a
    # real receipt in this dataset).
    if len(longer) == len(shorter) + 1 and longer.endswith(shorter):
        return "leading_digit_lost"

    # Same digits, different order: "1250" vs "1205".
    if len(da) == len(db) and sorted(da) == sorted(db) and da != db:
        return "digit_transposition"

    # Same length, exactly one digit differs: a straight substitution
    # ("430" vs "410", "8" misread as "0").
    if len(da) == len(db):
        differing = sum(1 for x, y in zip(da, db) if x != y)
        if differing == 1:
            return "single_digit_substitution"

    return None


def _normalize_text(value: str) -> str:
    return " ".join(str(value).lower().split())


def _text_agree(a: str, b: str) -> bool:
    na, nb = _normalize_text(a), _normalize_text(b)
    if na == nb or na in nb or nb in na:
        return True
    # Space-agnostic fallback: one engine can merge/split word boundaries
    # differently from another while reading the exact same text (measured
    # example: Tesseract "New Star Electricals" vs EasyOCR "NewStar
    # Electricals" -- same vendor name, EasyOCR just fused two words).
    # Comparing with ALL whitespace stripped recovers agreement in that
    # case without weakening the check for genuinely different text,
    # since two different vendor names would still differ once spaces are
    # removed too.
    return na.replace(" ", "") == nb.replace(" ", "")


def _describe_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize_text(a), _normalize_text(b)).ratio()


# Minimum normalized-description length for `_describe_containment_match`
# to consider a substring relationship meaningful -- below this length a
# containment match is too likely to be coincidental (e.g. a bare unit
# word) to trust regardless of position.
_ITEM_DESC_CONTAINMENT_MIN_LEN = 4


def _describe_containment_match(a: str | None, b: str | None) -> bool:
    """
    True when one description is a substring of the other after
    normalization -- e.g. "Sugac" / "Sugac kg", or "Tea Powder" / "Tea
    Powder 250,gm" (one engine appended a trailing unit the other engine
    dropped or OCR'd differently). This is a SAFER off-position signal
    than a raw similarity ratio: two genuinely different items with
    similar wording ("Widget A" / "Widget B") never satisfy containment
    (neither is a substring of the other), whereas plain
    `SequenceMatcher` ratio can score them just as high as a real
    unit-suffix variant (~0.87-0.88 either way) -- containment
    disambiguates exactly the cases ratio alone cannot.
    """
    na = _normalize_text(a) if a else ""
    nb = _normalize_text(b) if b else ""
    if len(na) < _ITEM_DESC_CONTAINMENT_MIN_LEN or len(nb) < _ITEM_DESC_CONTAINMENT_MIN_LEN:
        return False
    return na in nb or nb in na


def _disagreement_pattern(candidates: list[tuple[str, object]]) -> str | None:
    """
    First recognised digit-corruption pattern among any pair of numeric
    candidates, for attaching to a disagreement reason. Diagnostic only.
    """
    numeric = [v for _, v in candidates if isinstance(v, (int, float))]
    for i in range(len(numeric)):
        for j in range(i + 1, len(numeric)):
            pattern = classify_numeric_disagreement(float(numeric[i]), float(numeric[j]))
            if pattern:
                return pattern
    return None


def _collect_candidates(extractions: list[EngineExtraction], field_name: str) -> list[tuple[str, object]]:
    """(engine, value) pairs for every extraction that produced a non-None value."""
    out = []
    for ext in extractions:
        value = getattr(ext.receipt, field_name)
        if value is not None:
            out.append((ext.engine, value))
    return out


def _reconcile_scalar(field_name: str, candidates: list[tuple[str, object]]) -> FieldDecision:
    """
    Reconcile a text-like field (vendor, date, ids, ...): agreement if all
    candidates match after normalization, otherwise the first non-empty
    candidate is kept but flagged as a single-source or disagreement.
    """
    if not candidates:
        return FieldDecision(value=None, confidence=0.0, agreement=None, source="none")

    if len(candidates) == 1:
        engine, value = candidates[0]
        return FieldDecision(
            value=value, confidence=55.0, agreement=None, source=engine,
            reason="only_one_engine_produced_a_value",
        )

    first_engine, first_value = candidates[0]
    all_agree = all(_text_agree(first_value, v) for _, v in candidates[1:])
    if all_agree:
        return FieldDecision(
            value=first_value, confidence=90.0, agreement=True,
            source="+".join(e for e, _ in candidates),
            reason="engines_agree",
        )

    # Disagreement: no safe way to prefer one engine's text over another's
    # for a non-numeric field (no arithmetic to check it against), so this
    # is reported rather than guessed.
    return FieldDecision(
        value=None, confidence=25.0, agreement=False, source="disagreement",
        candidates=[{"engine": e, "value": v} for e, v in candidates],
        reason="engines_disagree_no_arithmetic_evidence_available_for_text_field",
    )


def _reconcile_numeric(field_name: str, candidates: list[tuple[str, object]]) -> FieldDecision:
    """Reconcile a plain numeric field (subtotal/tax/discount) -- no arithmetic fallback needed here."""
    if not candidates:
        return FieldDecision(value=None, confidence=0.0, agreement=None, source="none")

    if len(candidates) == 1:
        engine, value = candidates[0]
        return FieldDecision(
            value=value, confidence=55.0, agreement=None, source=engine,
            reason="only_one_engine_produced_a_value",
        )

    first_engine, first_value = candidates[0]
    all_agree = all(_numbers_agree(first_value, v) for _, v in candidates[1:])
    if all_agree:
        return FieldDecision(
            value=first_value, confidence=95.0, agreement=True,
            source="+".join(e for e, _ in candidates),
            reason="engines_agree",
        )

    reason = f"engines_disagree_on_{field_name}_no_resolving_evidence"
    pattern = _disagreement_pattern(candidates)
    if pattern:
        reason = f"{reason}:suspicious_pattern={pattern}"
    return FieldDecision(
        value=None, confidence=20.0, agreement=False, source="disagreement",
        candidates=[{"engine": e, "value": v} for e, v in candidates],
        reason=reason,
    )


def _reconcile_total(
    candidates: list[tuple[str, object]],
    subtotal_decision: FieldDecision,
    tax_decision: FieldDecision,
    discount_decision: FieldDecision,
    item_amount_sum: float | None,
) -> FieldDecision:
    """
    Reconcile `total` specifically, with an arithmetic fallback when
    engines disagree: if exactly one candidate is consistent with
    `subtotal - discount + tax` (using whatever of those was itself
    successfully reconciled) or with the sum of reconciled item amounts,
    that candidate is selected on evidence rather than by engine
    preference. This is the direct implementation of the "select 410 if
    supported by OCR evidence" requirement.
    """
    if not candidates:
        return FieldDecision(value=None, confidence=0.0, agreement=None, source="none")

    if len(candidates) == 1:
        engine, value = candidates[0]
        return FieldDecision(
            value=value, confidence=55.0, agreement=None, source=engine,
            reason="only_one_engine_produced_a_value",
        )

    first_engine, first_value = candidates[0]
    if all(_numbers_agree(first_value, v) for _, v in candidates[1:]):
        return FieldDecision(
            value=first_value, confidence=95.0, agreement=True,
            source="+".join(e for e, _ in candidates),
            reason="engines_agree",
        )

    # Disagreement -- try to resolve via arithmetic evidence.
    #
    # `item_amount_sum` is the sum of the receipt's own line items, which
    # is a proxy for `subtotal` (the pre-discount/tax figure), NOT for
    # `total` directly. Comparing it against `total` candidates without
    # applying the same discount/tax adjustment used for
    # `expected_from_subtotal` below would let a candidate that merely
    # matches the SUBTOTAL be mistaken for a match on the TOTAL --
    # measured concretely: a receipt with subtotal=430, discount=20,
    # true total=410 had one engine mis-OCR the total as 430 (the
    # subtotal figure, i.e. it missed the discount line). Item amounts
    # summed to 430 too, so an unadjusted comparison would call 430
    # "arithmetically confirmed" against the item sum and turn a
    # resolvable disagreement into an ambiguous tie -> null, throwing
    # away a total that was in fact resolvable via discount/tax. Applying
    # the identical adjustment here as for `expected_from_subtotal` fixes
    # that without weakening the check: when there is no discount/tax,
    # the adjustment is a no-op and item_amount_sum still matches a total
    # with no adjustments, exactly as before.
    expected_from_subtotal = None
    if isinstance(subtotal_decision.value, (int, float)):
        expected_from_subtotal = float(subtotal_decision.value)
        if isinstance(discount_decision.value, (int, float)):
            expected_from_subtotal -= float(discount_decision.value)
        if isinstance(tax_decision.value, (int, float)):
            expected_from_subtotal += float(tax_decision.value)

    expected_from_items = None
    if item_amount_sum is not None:
        expected_from_items = float(item_amount_sum)
        if isinstance(discount_decision.value, (int, float)):
            expected_from_items -= float(discount_decision.value)
        if isinstance(tax_decision.value, (int, float)):
            expected_from_items += float(tax_decision.value)

    consistent = []
    for engine, value in candidates:
        matches_subtotal_math = (
            expected_from_subtotal is not None and _numbers_agree(expected_from_subtotal, value)
        )
        matches_item_sum = (
            expected_from_items is not None and _numbers_agree(expected_from_items, value)
        )
        if matches_subtotal_math or matches_item_sum:
            consistent.append((engine, value, matches_subtotal_math, matches_item_sum))

    if len(consistent) == 1:
        engine, value, via_subtotal, via_items = consistent[0]
        reason = "arithmetic_match_subtotal_discount_tax" if via_subtotal else "arithmetic_match_item_sum"
        return FieldDecision(
            value=value, confidence=85.0, agreement=False, source="arithmetic",
            candidates=[{"engine": e, "value": v} for e, v in candidates],
            reason=reason,
        )

    # Either no candidate is arithmetically supported, or more than one
    # is (ambiguous) -- neither case is safe to resolve automatically.
    reason = "engines_disagree_on_total_and_arithmetic_evidence_did_not_resolve_it"
    pattern = _disagreement_pattern(candidates)
    if pattern:
        reason = f"{reason}:suspicious_pattern={pattern}"
    return FieldDecision(
        value=None, confidence=15.0, agreement=False, source="disagreement",
        candidates=[{"engine": e, "value": v} for e, v in candidates],
        reason=reason,
    )


def _match_items_across_engines(extractions: list[EngineExtraction]) -> list[list[tuple[str, LineItem]]]:
    """
    Group line items across engines into clusters that likely represent
    the same physical row, using ROW POSITION as the primary signal and
    description similarity as a sanity check (or, absent a position
    match, as a much stricter fallback signal on its own).

    Both engines read a receipt's table top-to-bottom, so item N from one
    engine and item N from another are very likely the same physical row
    even when OCR mangled the description badly ("Back Cover" ->
    "Back Covr") -- text similarity alone cannot be trusted at a loose
    threshold, because two DIFFERENT items can share most of their
    wording ("Widget A" vs "Widget B"). Position resolves that ambiguity;
    see the two threshold constants above for exactly how.
    """
    clusters: list[list[tuple[str, LineItem, int]]] = []  # (engine, item, original_index)
    for ext in extractions:
        for index, item in enumerate(ext.receipt.items):
            best_index = -1
            best_score = -1.0
            for cluster_index, cluster in enumerate(clusters):
                # A cluster already containing a row from THIS engine can
                # never receive another row from the same engine: within
                # one engine's own output, its items are already correctly
                # segmented, so two of its own rows are never the same
                # physical row.
                if any(engine == ext.engine for engine, _, _ in cluster):
                    continue
                for _, existing, existing_position in cluster:
                    text_score = _describe_similarity(item.description, existing.description)
                    same_position = existing_position == index
                    # Position drift: one engine skipped/added an earlier
                    # row (measured example: Tesseract missed the first
                    # item on a 5-row receipt, shifting every later item's
                    # index down by one relative to EasyOCR). A small
                    # index difference plus a CONTAINMENT match (one
                    # description is literally a substring of the other,
                    # e.g. "Sugac" / "Sugac kg") is trusted even though
                    # position does not line up exactly -- containment
                    # cannot be satisfied by two genuinely different items
                    # ("Widget A" / "Widget B" contain neither each
                    # other), unlike a raw similarity ratio which scores
                    # that pair just as high as a real variant.
                    near_position = abs(existing_position - index) <= 2
                    if (
                        not same_position
                        and near_position
                        and _describe_containment_match(item.description, existing.description)
                    ):
                        same_position = True  # reuse the loose threshold path below
                    threshold = (
                        _ITEM_DESC_MATCH_RATIO_POSITIONAL if same_position
                        else _ITEM_DESC_MATCH_RATIO_TEXT_ONLY
                    )
                    if text_score >= threshold and text_score > best_score:
                        best_score = text_score
                        best_index = cluster_index
            if best_index >= 0:
                clusters[best_index].append((ext.engine, item, index))
            else:
                clusters.append([(ext.engine, item, index)])

    return [[(engine, item) for engine, item, _ in cluster] for cluster in clusters]


def _reconcile_item_cluster(cluster: list[tuple[str, LineItem]]) -> LineItem:
    """
    Merge one matched cluster into a single `LineItem`, reconciling each
    of quantity/unit_price/amount independently by the same agreement
    rule used for scalar numeric fields, and setting `description` to the
    longest candidate (more OCR text recovered, not a correctness signal
    but a reasonable tie-break with no downside).
    """
    descriptions = [item.description for _, item in cluster if item.description]
    description = max(descriptions, key=len) if descriptions else None

    warnings: list[str] = []
    values: dict[str, float | None] = {}
    confidences: list[float] = []

    for field_name in ("quantity", "unit_price", "amount"):
        candidates = [
            (engine, getattr(item, field_name))
            for engine, item in cluster
            if getattr(item, field_name) is not None
        ]
        if not candidates:
            values[field_name] = None
            continue
        if len(candidates) == 1:
            values[field_name] = candidates[0][1]
            confidences.append(50.0)
            continue
        first_value = candidates[0][1]
        if all(_numbers_agree(first_value, v) for _, v in candidates[1:]):
            values[field_name] = first_value
            confidences.append(95.0)
        else:
            values[field_name] = None
            confidences.append(15.0)
            detail = ",".join(f"{e}={v}" for e, v in candidates)
            pattern = _disagreement_pattern(candidates)
            if pattern:
                detail = f"{detail}:suspicious_pattern={pattern}"
            warnings.append(f"item_{field_name}_disagreement:{detail}")

    item_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    if len(cluster) > 1:
        warnings.append("item_matched_across_engines")

    return LineItem(
        description=description,
        quantity=values.get("quantity"),
        unit_price=values.get("unit_price"),
        amount=values.get("amount"),
        confidence=round(item_confidence, 2),
        warnings=warnings,
    )


def reconcile_extractions(
    extractions: list[EngineExtraction],
) -> tuple[ReceiptData, dict[str, FieldDecision], list[str]]:
    """
    Reconcile N independent per-engine extractions into one `ReceiptData`.

    Parameters
    ----------
    extractions:
        One `EngineExtraction` per engine that produced usable OCR text.
        Engines that failed OCR entirely should not be included here (the
        caller decides that before invoking reconciliation).

    Returns
    -------
    (receipt, field_decisions, warnings)
        `receipt` carries the SELECTED value per field (None where no
        selection could be made safely). `field_decisions` carries the
        full evidence trail per field for the output contract. `warnings`
        surfaces disagreement/low-confidence conditions for the caller to
        fold into `ExtractionResult.warnings`.
    """
    if not extractions:
        return ReceiptData(), {}, ["reconciliation_no_extractions_provided"]

    if len(extractions) == 1:
        # Nothing to reconcile against; pass the single engine's receipt
        # through unchanged, but still emit FieldDecisions so the output
        # contract is uniform whether one or many engines ran.
        ext = extractions[0]
        decisions: dict[str, FieldDecision] = {}
        for field_name in _SCALAR_TEXT_FIELDS + _NUMERIC_FIELDS + ("total",):
            value = getattr(ext.receipt, field_name)
            decisions[field_name] = FieldDecision(
                value=value, confidence=55.0 if value is not None else 0.0,
                agreement=None, source=ext.engine if value is not None else "none",
                reason="single_engine_no_reconciliation_possible",
            )
        return ext.receipt, decisions, []

    warnings: list[str] = []
    decisions: dict[str, FieldDecision] = {}

    for field_name in _SCALAR_TEXT_FIELDS:
        candidates = _collect_candidates(extractions, field_name)
        decisions[field_name] = _reconcile_scalar(field_name, candidates)

    for field_name in _NUMERIC_FIELDS:
        candidates = _collect_candidates(extractions, field_name)
        decisions[field_name] = _reconcile_numeric(field_name, candidates)

    item_clusters = _match_items_across_engines(extractions)
    items = [_reconcile_item_cluster(cluster) for cluster in item_clusters]
    item_amount_sum = None
    amounts = [i.amount for i in items if i.amount is not None]
    if amounts and len(amounts) == len(items):
        item_amount_sum = sum(amounts)

    total_candidates = _collect_candidates(extractions, "total")
    decisions["total"] = _reconcile_total(
        total_candidates,
        decisions["subtotal"], decisions["tax"], decisions["discount"],
        item_amount_sum,
    )

    for field_name, decision in decisions.items():
        if decision.agreement is False:
            warnings.append(f"{field_name}_reconciliation_{decision.source}:{decision.reason}")

    for item in items:
        warnings.extend(item.warnings)

    receipt = ReceiptData(
        document_type=decisions["document_type"].value,
        vendor_name=decisions["vendor_name"].value,
        customer_name=decisions["customer_name"].value,
        invoice_number=decisions["invoice_number"].value,
        receipt_number=decisions["receipt_number"].value,
        date=decisions["date"].value,
        time=decisions["time"].value,
        currency=decisions["currency"].value,
        subtotal=decisions["subtotal"].value,
        tax=decisions["tax"].value,
        discount=decisions["discount"].value,
        total=decisions["total"].value,
        payment_method=decisions["payment_method"].value,
        items=items,
    )

    return receipt, decisions, warnings
