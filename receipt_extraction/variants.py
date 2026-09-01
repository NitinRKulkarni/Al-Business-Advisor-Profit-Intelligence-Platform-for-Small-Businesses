"""
variants
==========

Multi-variant OCR support: decide WHICH preprocessing variants of an image
are worth running OCR on, and pick the best resulting extraction using
hard evidence rather than OCR confidence.

Why this module exists
------------------------
`preprocess_image()` already produces several intermediate images
(`grayscale`, `contrast`, `shadow_corrected`, `thresholded`, ...) but the
pipeline previously passed only ONE of them (`final`) to OCR and discarded
the rest. That single choice is sometimes actively the worst one. Measured
on this project's own dataset (`batch2_invoice_087`, a dark/shadowed
photo):

    variant           words  OCR confidence
    final (shadowed)      3           87.54   <- what the pipeline used
    grayscale            21           34.92
    thresholded          39           28.20

The pipeline's chosen variant recovered three words while a discarded one
recovered thirty-nine. Note also that the WORST variant carried the
HIGHEST confidence -- which is exactly why selection here must not be
driven by confidence.

Two rules shape everything below
----------------------------------
1. **Generate candidates only where quality analysis suggests value.**
   Running every engine over every variant is expensive (EasyOCR is slow)
   and pointless on a clean image where the enhancement pipeline did
   nothing. `select_variant_stages()` therefore gates variant generation
   on what preprocessing actually did and what the quality analysis
   flagged.

2. **Select by evidence, never by confidence.** Binarization and contrast
   enhancement can destroy decimal points, thin handwriting strokes and
   digits -- so a variant is never trusted just because it produced more
   text or scored a higher confidence. `score_candidate()` weights
   arithmetic self-consistency and structural completeness far above text
   volume, and uses OCR confidence only as a last-resort tiebreak. A
   variant whose binarization ate the decimal points will fail the
   arithmetic checks and lose to a quieter but self-consistent variant.

Independence caveat (important)
---------------------------------
Two variants of the SAME engine agreeing is NOT independent corroboration
-- it is one model with one set of failure modes reading two versions of
one image. So variants are collapsed to a single best candidate PER
ENGINE here, and only then handed to `reconcile_extractions()`, whose
cross-engine agreement logic depends on its inputs being genuinely
independent. This module never inflates apparent agreement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ExtractionResult

# Stage names (produced by `preprocess_image`) that are meaningful OCR
# inputs. Deliberately excludes colour/geometry-only intermediates
# (`original`, `resized`, `deskewed`, `perspective_corrected`): those are
# BGR or pre-grayscale stages that the grayscale-family stages below are
# already derived from, so OCR-ing them adds cost without adding a
# genuinely different rendering of the ink.
_OCR_CANDIDATE_STAGES = ("final", "grayscale", "thresholded")

# Preprocessing operations that rewrite pixel intensities and can
# therefore plausibly HURT OCR as easily as help it (each is already
# individually quality-gated and improvement-checked upstream, but those
# checks measure image statistics, not OCR usefulness). When any of these
# ran, the un-enhanced `grayscale` stage becomes worth OCR-ing as a
# control, because `final` is no longer simply "the grayscale image".
_INTENSITY_REWRITING_OPERATIONS = frozenset({
    "exposure_normalization",
    "shadow_correction",
    "denoise",
    "contrast_enhancement",
    "sharpen",
})

# Quality warnings indicating faded/uneven ink, where a binarized
# rendering can recover strokes that stay below the recognition threshold
# in grayscale. Binarization is offered as a CANDIDATE only -- scoring
# decides whether it actually helped.
_BINARIZATION_WORTH_TRYING_WARNINGS = frozenset({
    "low_contrast",
    "uneven_lighting_or_shadow",
    "underexposed",
    "overexposed",
})

# ---------------------------------------------------------------- scoring
#
# Weights encode the project's priority order: arithmetic self-consistency
# is the strongest available evidence that OCR read the numbers correctly,
# because it is very unlikely that a misread digit still satisfies
# quantity x unit_price = amount and subtotal - discount + tax = total.
# Field/structure coverage comes next (a variant that found a total and
# complete item rows recovered more usable structure). Text volume is a
# weak positive, capped so that a noisy variant cannot win on bulk alone.
# OCR confidence is deliberately the smallest term -- present only to
# break otherwise-exact ties deterministically, never to drive selection.
_WEIGHT_ARITHMETIC = 50.0
_WEIGHT_FIELD_COVERAGE = 25.0
_WEIGHT_ITEM_STRUCTURE = 15.0
_WEIGHT_TEXT_COVERAGE = 8.0
_WEIGHT_OCR_CONFIDENCE = 2.0

# Word count at which the text-coverage term saturates. Beyond this, more
# words are assumed to be noise rather than recovered content, so a
# variant cannot keep climbing the score by emitting garbage.
_TEXT_COVERAGE_SATURATION_WORDS = 40

# Financial fields whose presence indicates genuinely useful recovery.
_COVERAGE_FIELDS = ("total", "subtotal", "date", "vendor_name")


@dataclass
class VariantCandidate:
    """One (engine, preprocessing variant) OCR+extraction attempt."""

    engine: str
    variant: str
    extraction: ExtractionResult
    ocr_confidence: float | None
    word_count: int
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)


def select_variant_stages(
    operations_applied: list[str],
    quality_warnings: list[str],
) -> list[str]:
    """
    Which preprocessing stages are worth OCR-ing for this image.

    Always includes `final` (the pipeline's own adaptive choice, and the
    only stage used before multi-variant OCR existed -- so single-variant
    behaviour is always still represented among the candidates).

    Adds:
      * `grayscale` when preprocessing rewrote pixel intensities, so the
        un-enhanced image acts as a control against an enhancement that
        may have destroyed strokes.
      * `thresholded` when quality analysis flagged faded/uneven ink,
        where binarization can lift ink above the recognition threshold.

    On a clean, well-exposed image none of the extra conditions fire and
    this returns just `["final"]` -- identical work to the original
    single-variant path, so clean images pay no extra cost.

    Returns stage NAMES; the caller resolves them to actual images and
    silently skips any that this image does not have.
    """
    stages = ["final"]
    operations = set(operations_applied or ())
    warnings = set(quality_warnings or ())

    if operations & _INTENSITY_REWRITING_OPERATIONS:
        stages.append("grayscale")

    if warnings & _BINARIZATION_WORTH_TRYING_WARNINGS:
        stages.append("thresholded")

    # Preserve the canonical order and drop anything unknown/duplicated.
    return [s for s in _OCR_CANDIDATE_STAGES if s in stages]


def _arithmetic_score(extraction: ExtractionResult) -> float:
    """
    0-1 fraction of applicable arithmetic cross-checks that passed.

    Reuses `validation_confidence`, which is computed by
    `confidence.compute_validation_confidence` over exactly the checks
    this project cares about (item quantity x price, item sum vs subtotal,
    subtotal - discount + tax vs total).

    Returns 0.0 when no check was applicable. That is deliberate: a
    variant that recovered so little that nothing could be cross-checked
    has produced no arithmetic evidence, and must not be rewarded as if
    it had passed. It can still win on the coverage terms if no variant
    produced checkable arithmetic.
    """
    value = extraction.validation_confidence
    if value is None:
        return 0.0
    return max(0.0, min(1.0, value / 100.0))


def _field_coverage_score(extraction: ExtractionResult) -> float:
    """0-1 fraction of the key financial/identity fields that are present."""
    receipt = extraction.receipt
    present = sum(1 for name in _COVERAGE_FIELDS if getattr(receipt, name, None) is not None)
    return present / len(_COVERAGE_FIELDS)


def _item_structure_score(extraction: ExtractionResult) -> float:
    """
    0-1 measure of how completely line-item rows were reconstructed.

    A row with quantity, unit_price AND amount indicates the table's
    column structure was genuinely recovered (spatially or textually); a
    row with only an amount is much weaker evidence. Scoring the fraction
    of fully-populated rows rewards real table reconstruction rather than
    the mere number of rows found, so a variant that emits many
    half-parsed rows does not beat one that parsed fewer rows properly.
    """
    items = extraction.receipt.items
    if not items:
        return 0.0
    complete = sum(
        1 for i in items
        if i.quantity is not None and i.unit_price is not None and i.amount is not None
    )
    return complete / len(items)


def _text_coverage_score(word_count: int) -> float:
    """0-1 text volume, saturating (see `_TEXT_COVERAGE_SATURATION_WORDS`)."""
    if word_count <= 0:
        return 0.0
    return min(1.0, word_count / _TEXT_COVERAGE_SATURATION_WORDS)


def score_candidate(candidate: VariantCandidate) -> VariantCandidate:
    """
    Attach an evidence-based quality score to `candidate` (in place, and
    returned for chaining).

    Scoring is intentionally dominated by arithmetic self-consistency and
    structural recovery. OCR confidence contributes at most
    `_WEIGHT_OCR_CONFIDENCE` points out of ~100, so the documented failure
    case this project measured -- a variant with 87.5 confidence and three
    recognised words -- cannot outrank a variant with lower confidence
    that actually recovered a self-consistent receipt.
    """
    extraction = candidate.extraction
    if not extraction.success:
        candidate.score = 0.0
        candidate.score_breakdown = {"failed": 0.0}
        return candidate

    arithmetic = _arithmetic_score(extraction)
    coverage = _field_coverage_score(extraction)
    structure = _item_structure_score(extraction)
    text = _text_coverage_score(candidate.word_count)
    confidence = max(0.0, min(1.0, (candidate.ocr_confidence or 0.0) / 100.0))

    breakdown = {
        "arithmetic": round(arithmetic * _WEIGHT_ARITHMETIC, 3),
        "field_coverage": round(coverage * _WEIGHT_FIELD_COVERAGE, 3),
        "item_structure": round(structure * _WEIGHT_ITEM_STRUCTURE, 3),
        "text_coverage": round(text * _WEIGHT_TEXT_COVERAGE, 3),
        "ocr_confidence": round(confidence * _WEIGHT_OCR_CONFIDENCE, 3),
    }
    candidate.score_breakdown = breakdown
    candidate.score = round(sum(breakdown.values()), 3)
    return candidate


def choose_best_per_engine(
    candidates: list[VariantCandidate],
) -> tuple[list[VariantCandidate], list[str]]:
    """
    Collapse many (engine, variant) candidates to the single best variant
    PER ENGINE.

    Why per engine, and not one global winner: `reconcile_extractions()`
    treats its inputs as independent sources and raises confidence when
    they agree. Two variants of the same engine are not independent (same
    model, same failure modes, same image), so letting both through would
    manufacture false agreement. Collapsing per engine keeps exactly one
    independent voice per engine, which is what reconciliation expects.

    Arithmetic-corroboration requirement (measured safety guard)
    -------------------------------------------------------------
    A non-`final` variant may only displace the pipeline's own adaptive
    choice when it carries POSITIVE arithmetic corroboration -- i.e. at
    least one real cross-check (item quantity x price, item sum vs
    subtotal, subtotal - discount + tax vs total) actually passed on it.

    This guard exists because of a measured regression, not a theory. The
    score's `field_coverage` term rewards a field being PRESENT, and
    presence of a WRONG value scores identically to presence of a right
    one. On a sparse receipt (a single `Total`, no subtotal/tax/qty
    columns) NO arithmetic check is applicable, so that term decided the
    outcome -- and on `batch2_invoice_105` it promoted a binarized variant
    that read the total as 352 when the receipt says 850, replacing a
    correct null with a plausible wrong number. Benchmarked over 11
    receipts, unguarded selection moved financial accuracy 40.8% -> 39.8%
    and DOUBLED wrong non-null values (1 -> 2).

    Requiring positive arithmetic evidence before switching keeps the
    upside (variants that demonstrably reconstruct a self-consistent
    receipt can still win) while removing the failure mode (coverage alone
    can never promote an unverifiable value). Where no variant has
    arithmetic evidence, `final` is kept -- the pipeline's own choice,
    i.e. exactly the pre-existing behaviour.

    Returns (winners, notes) where `notes` records which variant won for
    each engine and whether a non-default variant was preferred, so the
    decision is visible in the output rather than silent.
    """
    scored = [score_candidate(c) for c in candidates]
    by_engine: dict[str, list[VariantCandidate]] = {}
    for candidate in scored:
        by_engine.setdefault(candidate.engine, []).append(candidate)

    winners: list[VariantCandidate] = []
    notes: list[str] = []
    for engine, engine_candidates in by_engine.items():
        usable = [c for c in engine_candidates if c.extraction.success]
        pool = usable or engine_candidates
        best = max(pool, key=lambda c: c.score)

        default = next((c for c in pool if c.variant == "final"), None)
        if (
            best.variant != "final"
            and default is not None
            and _arithmetic_score(best.extraction) <= 0.0
        ):
            # No arithmetic corroboration for the challenger: keep the
            # pipeline's adaptive choice rather than switching on
            # coverage/text volume alone (see docstring).
            notes.append(
                f"variant_switch_declined_no_arithmetic_evidence:{engine}"
                f":candidate={best.variant}"
            )
            best = default

        winners.append(best)
        if len(engine_candidates) > 1:
            notes.append(
                f"variant_selected:{engine}={best.variant}"
                f":score={best.score}"
                f":considered={len(engine_candidates)}"
            )
            if best.variant != "final":
                # Surfaced as its own note because it means the adaptive
                # preprocessing pipeline's own choice was measurably NOT
                # the best OCR input for this image, AND the replacement
                # passed the arithmetic-corroboration guard above.
                notes.append(f"non_default_variant_preferred:{engine}={best.variant}")

    return winners, notes
