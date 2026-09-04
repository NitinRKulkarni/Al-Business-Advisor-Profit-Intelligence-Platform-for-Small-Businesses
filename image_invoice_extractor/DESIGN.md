# Design

Architecture and rationale for the receipt image-processing and extraction
component. This document explains *why* the pipeline is built the way it is,
including approaches that were implemented, measured, and then rejected.

For installation and usage, see [`README.md`](README.md).

---

## 1. The problem and the constraint that shapes everything

Input is an arbitrary photograph of a receipt or invoice: printed or
handwritten, clean or messy, well-lit or dark, flat or skewed, high-resolution
or a low-resolution phone snap. Output must be structured financial data that a
database and analytics layer can consume.

The binding constraint is not accuracy — it is **the cost asymmetry between
error types**:

- A **missing** value (`null`) is visible. Downstream can skip the record,
  queue it for review, or ask the user.
- A **wrong** value is invisible. It silently corrupts every total, margin, and
  recommendation computed from it, and there is no way to detect it later.

So the pipeline is designed to *decline* rather than guess. Every design
decision below follows from that. It also means raw accuracy percentages
understate the system's usefulness: a large share of the gap between the score
and 100% is deliberate `null`s that are flagged, not wrong values shipped.

---

## 2. Pipeline stages

```
                  ┌──────────────────────────────────────────┐
   image path ──▶ │ image_processing/quality_analysis.py     │
                  │  blur, contrast, brightness, noise,      │
                  │  stroke width, skew, document boundary   │
                  │        ↓ emits WARNINGS                  │
                  │ image_processing/preprocessing.py        │
                  │  each transformation gated on a warning  │
                  │  + verified to actually improve          │
                  └──────────────────────────────────────────┘
                                    │  OCR-ready image(s)
                                    ▼
                  ┌──────────────────────────────────────────┐
                  │ ocr/  (OcrEngine protocol)               │
                  │  Tesseract          EasyOCR              │
                  │  → OcrResult: text + per-token bbox      │
                  │    + per-token confidence                │
                  └──────────────────────────────────────────┘
                         │                        │
                         ▼                        ▼
                  ┌──────────────────────────────────────────┐
                  │ receipt_extraction/extractor.py          │
                  │  text path (regex over lines)            │
                  │  spatial path (layout.py, bboxes)        │
                  │  → the more self-consistent one wins     │
                  └──────────────────────────────────────────┘
                                    │  one ReceiptData per engine
                                    ▼
                  ┌──────────────────────────────────────────┐
                  │ receipt_extraction/reconciliation.py     │
                  │  per-field merge on EVIDENCE:            │
                  │  agreement > arithmetic > single > null  │
                  └──────────────────────────────────────────┘
                                    ▼
                  ┌──────────────────────────────────────────┐
                  │ validators.py   → flag, never correct    │
                  │ confidence.py   → 4 signals + review     │
                  └──────────────────────────────────────────┘
                                    ▼
                    ExtractionResult (flat or grouped JSON)
```

---

## 3. Preprocessing: adaptive, not a fixed chain

**Decision.** Every transformation is gated on a specific quality warning, and
the aggressive ones must *prove* they helped or they are discarded.

**Why.** Aggressive preprocessing destroys exactly the features that matter
most on receipts: decimal points, thin pen strokes, small digits, commas, ₹
glyphs, and table rules. A fixed "always denoise, always threshold" chain
improves clean images and ruins marginal ones.

**Implementation.** `quality_analysis.py` computes metrics and emits warnings
(`low_contrast`, `high_noise`, `uneven_lighting_or_shadow`, `underexposed`,
`possible_skew`, `low_resolution`, …). `preprocessing.py` consumes those
warnings as its policy — the warning list *is* the decision mechanism. There is
no separate rules engine.

Three stages (exposure normalization, CLAHE contrast, sharpening) additionally
run an improvement check and are **rolled back** if the measured statistic does
not improve, recording e.g. `contrast_enhancement_skipped_no_improvement`.

Binarization is always computed but **never** selected as the final image. It
is retained only as an optional OCR candidate (§6), because binarizing
handwriting frequently eats decimal points.

**Known weakness.** Geometry correction (deskew / perspective) requires a
detected document boundary covering ≥25% of the frame. Tightly-cropped receipt
images are classified `fills_frame`, so correction is skipped by design.
There is no Hough-line fallback skew estimator. Correction is also capped at
20°, so a heavily rotated image is left uncorrected rather than badly guessed.

---

## 4. OCR abstraction

**Decision.** A structural `OcrEngine` protocol: a `name` property and
`recognize(image_path) -> OcrResult`. Nothing downstream imports Tesseract or
EasyOCR directly.

**Why.** Azure or another engine will be evaluated later. Extraction must not
need rewriting when that happens — adding an engine should mean adding it to a
list.

`OcrResult` deliberately preserves more than text: `tokens` carries per-token
bounding box **and** per-token confidence, plus reading order via newline-joined
lines. Discarding geometry early would make spatial table reconstruction (§5)
impossible.

**A real bug this abstraction did not prevent.** `EasyOcrEngine._assemble()`
kept a stale 5-tuple unpack after `OcrToken` grew to 7 fields, so EasyOCR raised
`ValueError` on *every* call and was 100% broken with zero test coverage. Fixed,
and `tests/test_easyocr_engine.py` now guards it. Lesson: a protocol enforces
shape, not correctness — each implementation needs its own tests.

---

## 5. Line items: two paths, arbitrated by self-consistency

**Decision.** Run both a text/regex path and a spatial/bounding-box path, then
keep whichever produced the more *arithmetically self-consistent* item set.

**Why not text only.** Once OCR mangles the whitespace between table cells, a
whitespace split cannot tell which number is quantity and which is rate.

**Why not spatial only.** Column-band detection needs either a recognizable
header row or enough aligned numeric rows. Both are frequently absent — on
several receipts Tesseract does not recognize the header line at all.

**How the spatial path works** (`layout.py`):
1. Cluster tokens into rows by vertical centre, with tolerance proportional to
   median token height, so it scales from ~200 px crops to large phone photos
   without retuning.
2. Find column x-ranges from a header row (≥2 recognized column keywords), or
   fall back to clustering numeric token x-centres across data rows.
3. Read each cell by which x-band its token falls in — robust to mangled
   separators, because a value stays under its own column regardless.

Label/value association works the same way: `Grand Total` at x=500 and
`1121.00` at x=700 belong together because they share a row, even if OCR emits
them in different text lines. Only numerics *right of* the label count.

**Arbitration.** `_item_set_consistency()` scores each candidate set on whether
`quantity × unit_price ≈ amount` holds, with completeness as a tiebreak. This
is a correctness proxy, not a heuristic preference for one path.

**Phantom-row guard.** A row with only a description and one amount is
ambiguous — it matches both a genuine single-price item and a summary line
whose label OCR destroyed. Measured case: `Discount 10.00` was read as
`Diseamtt 10.00` and became a **fabricated line item carrying real money**.
When the receipt clearly has a structured table, lone single-amount rows are
dropped; when it has no table at all, they are kept as the only item evidence.

---

## 6. Multi-variant OCR: implemented, measured, and left off by default

**Motivation (real).** The preprocessing pipeline picks one final image, and
that choice is sometimes the worst available. On `batch2_invoice_087`:

| variant | words | OCR confidence |
|---|---|---|
| `final` (shadow-corrected) | 3 | **87.54** |
| `grayscale` (discarded) | 21 | 34.92 |
| `thresholded` (discarded) | 39 | 28.20 |

The chosen variant recovered three words; a discarded one recovered
thirty-nine. Note the worst variant carried the *highest* confidence.

**Design.** `variants.py` gates which variants are worth OCR-ing (clean images
select only `final`, so they pay nothing), scores each resulting extraction on
arithmetic self-consistency + field coverage + item structure + text coverage,
and caps OCR confidence at ~2 of ~100 points so it can only break exact ties.
Text coverage saturates at 40 words so a garbage-heavy variant cannot win on
bulk.

**Critical subtlety: variants collapse per engine.** Two variants of the *same*
engine agreeing is not independent corroboration — it is one model with one set
of failure modes reading two versions of one image. Feeding both into
reconciliation would manufacture false agreement and inflate confidence. So
each engine contributes exactly one winner, and only then does cross-engine
reconciliation run.

**Measured result: it did not work.** Over 11 receipts, unguarded selection made
things *worse*: financial accuracy 40.8% → 39.8%, and wrong non-null values
**doubled from 1 to 2**.

**Root cause — structural, not a tuning miss.** The `field_coverage` term
rewards a value being *present*, and a present-but-wrong value scores the same
as a present-and-right one. On a sparse receipt (single `Total`, no
subtotal/tax/quantity columns) *no* arithmetic check is applicable, so coverage
alone decided the winner — and it promoted a binarized variant that read the
total as **352** when the receipt says **850**, replacing a correct `null` with
a plausible wrong number. Coverage rewards hallucination precisely where
evidence is weakest.

**Fix.** A non-default variant may only displace `final` when it carries
*positive arithmetic corroboration* (at least one real cross-check passed). This
removed the harm exactly: back to 78/191 and 1 wrong value, identical to
baseline.

**Conclusion.** With the guard, the feature is safe but **never fires
productively** — because the images where variants would help most are exactly
the images with no arithmetic to verify against. It costs ~65% more runtime for
zero measured gain, so `use_variants` defaults to `False`. The code and the
negative result are kept rather than deleted, so the finding is not rediscovered
from scratch and so a larger corpus can revisit it.

---

## 7. Reconciliation: evidence ordering, never confidence

**Decision.** Merge per-engine extractions field by field, in this order of
evidence strength:

1. **Agreement** — engines produced the same value → high confidence.
2. **Arithmetic consistency** — engines disagree, but exactly one candidate
   makes `subtotal − discount + tax ≈ total` (or the discount/tax-adjusted item
   sum) hold → that candidate wins, `source="arithmetic"`.
3. **Single-engine evidence** — only one engine produced a value → use it at
   reduced confidence.
4. **Unresolved disagreement** — → `value = null`, both candidates preserved in
   `field_decisions.candidates`.

**Why confidence is banned as a tiebreak.** Measured: the dataset's
highest-confidence Tesseract result recognised three words. A rule of "90
confidence with 3 words beats 65 confidence with 60 useful words" is exactly
backwards.

**Text fields have no arithmetic escape hatch.** For `vendor_name` there is no
way to check which engine is right, so disagreement means `null`. This is a
deliberate accuracy sacrifice: on a held-out receipt Tesseract read the vendor
as "Cash Meme" (the document header) while EasyOCR correctly read "Patel
Medicals", and the pipeline returned `null`. That looks like a regression
against a single-engine score, and it is the correct behaviour.

Text agreement tolerates word-boundary differences: Tesseract's "New Star
Electricals" and EasyOCR's "NewStar Electricals" are the same vendor, so
comparison falls back to a whitespace-stripped match.

### Two bugs found here by measurement, not by inspection

**Item-sum compared against the wrong figure.** The arithmetic fallback
compared the line-item sum directly to `total` candidates. But an item sum
approximates *subtotal*, not total. On a receipt with subtotal 430, discount 20,
true total 410, one engine misread the total as 430 — which coincidentally
matched the unadjusted item sum, "confirming" the wrong value, creating an
ambiguous tie, and forcing a `null` where 410 was in fact resolvable. Fixed by
applying the same discount/tax adjustment to both arithmetic checks.

**Position drift broke item merging.** Cross-engine item matching used a loose
similarity threshold only at *exact* index equality. When one engine drops an
early row, every later row shifts by one, so all of them fell back to a strict
0.85 text threshold — too strict for real variants like "Sugac"/"Sugac kg"
(0.77). Result: unmerged duplicate rows, with reconciled item accuracy *below*
the best single engine (4/15 vs 7/15). Fixed with a containment check
(one description is a substring of the other) for small index drift.
Containment is safe where a similarity ratio is not: "Widget A" vs "Widget B"
scores 0.875 by ratio — high enough to be wrongly merged by a ratio-based fix —
but satisfies no containment relationship, so genuinely different items stay
separate.

---

## 8. A rejected fix worth recording

EasyOCR read a receipt's `Total` label as `Totr`, which scores 0.667 similarity
— below the 0.8 fuzzy-keyword threshold — so a fully legible `850` was dropped
to `null`.

The tempting fix is a `"tot"`-prefix match. It was implemented, then
**rejected** before shipping. Writing the negative test revealed that ordinary
English words ("tote", "tots", "toto") score identically to the corruption, and
the shared matcher is also used by `_is_summary_row()`, which decides whether a
table row is a line item or a summary line. A false positive there could
misclassify a real item (e.g. "Toto Snacks 50.00") as a total — silent financial
corruption, the worst outcome available.

Recovering this pattern safely needs either hardcoded corrupted spellings
(forbidden) or a dictionary (not justified for one case). So it remains a
documented limitation: `total = null` with raw OCR preserved is the correct
outcome. Lowering a threshold to win one case is not worth a new corruption
channel.

---

## 9. Validation and the four confidence signals

Validators **only flag**. A validator that silently rescaled a suspicious
number would reintroduce the exact risk the whole design avoids, and without a
second independent source of truth there is no safe basis for a correction.

Checks: per-item `quantity × unit_price ≈ amount`; `sum(items) ≈ subtotal`;
`subtotal − discount + tax ≈ total`; date sanity; magnitude sanity. Tolerances
are intentionally loose (≈2% or 1 unit) because every input already passed
through OCR — a tight tolerance would mostly flag rounding noise.

**Digit-pattern diagnostics.** When engines disagree numerically, the
disagreement is classified by shape: `trailing_digit_lost` (1550→155),
`leading_digit_lost` (1121→121), `decimal_place_shift`, `digit_transposition`,
`single_digit_substitution`. This is pattern-based over digit strings, so it
hardcodes no amount and generalizes to any receipt. It turns "the engines
disagree" into an actionable review reason. It changes no value.

**Why four confidence numbers instead of one.** They measure different things
and genuinely diverge:

| Signal | Answers |
|---|---|
| `ocr_confidence` | How sure was the engine about its characters? |
| `extraction_confidence` | How much structure did we recover? |
| `validation_confidence` | What share of applicable arithmetic checks passed? |
| `overall_confidence` | Conservative combination |

`overall_confidence` uses the **minimum** of extraction and validation, not an
average, so a receipt that parsed a lot of structure but failed its arithmetic
cannot score highly — for a financial consumer the arithmetic failure is the
more important fact. When no arithmetic was checkable, `validation_confidence`
is `None` (distinct from `0.0`) and extraction confidence is damped rather than
trusted.

`needs_review` is deliberately biased toward flagging.

---

## 10. Backward compatibility

The downstream team needs a predictable contract, so:

- `process_receipt` / `process_receipts` only ever gained **optional**
  parameters (`ocr_engines`, `use_variants`). `ocr_engine=` (singular) still
  behaves exactly as before.
- `to_dict()` stayed flat and unchanged. The nested contract was added as a
  **separate** `to_grouped_dict()` rather than replacing it.
- New result fields (`engines_used`, `field_decisions`, `raw_ocr_by_engine`, …)
  are additive.
- The preprocessing handoff record is byte-identical unless `variant_stages` is
  explicitly requested — verified by a test asserting the exact key set.

---

## 11. Testing strategy

228 tests, all deterministic: no network, no model download, no real OCR call
in the unit suite. Engines are faked so reconciliation logic is exercised in
isolation; real-engine behaviour is measured by the benchmark scripts instead.

Every bug described above has a regression test that encodes *why* the case
matters, not just the assertion.

**Ground truth is hand-transcribed by reading images.** Using OCR output as
ground truth would make measurement circular and meaningless. Conventions: a
field absent from the receipt is `null`; a field a human *cannot confidently
read* is **omitted entirely** so it is excluded from scoring rather than counted
as wrong.

**Development vs held-out sets are reported separately.** The 11 development
receipts informed the fixes being measured, so their scores are optimistic by
construction. The 3 held-out receipts were transcribed after the implementation
was finished and never used to tune anything — those are the honest
generalization numbers.

### Ground truth is a failure mode too

Two transcription errors were caught during this work, both by noticing that
results were *impossible* rather than merely bad:

1. `batch2_invoice_087.json` described "Sudha Tailors" while the image at that
   path is "Ganesh Provision Store" — invalidating part of an earlier reported
   benchmark.
2. Three held-out files had their images **rotated** relative to their content.
   The tell was that the pipeline reported one receipt's total for another,
   which looked like state leakage between images. Verifying each image
   individually showed **the pipeline was right and the transcriptions were
   wrong**. Uncorrected, this would have been reported as a fabricated
   "14.6% accuracy, 6 wrong values" failure.

Both are now documented in-file, and images are verified individually rather
than reviewed in batches.

---

## 12. Anti-overfitting rules

Enforced throughout, and audited by grep:

- No receipt filename, vendor name, expected total, or date appears in any code
  path.
- Thresholds live in `config.py`, are relative to image properties (token
  height, median width) rather than absolute pixels where possible, and are
  annotated where uncalibrated.
- A fix must generalize by construction. The "Total → Discount → Grand Total"
  ordering rule, for example, is expressed as a structural rule about line
  order, not as a rule about the receipt that motivated it.
- A change is kept only if it measurably improves accuracy **without**
  increasing wrong non-null values. Multi-variant OCR (§6) failed that test and
  was left off.

---

## 13. What is deliberately not here

- **Azure / any cloud OCR** — the local pipeline was to be verified first. The
  `OcrEngine` protocol and the `ocr_engines` list parameter already accommodate
  it with no redesign.
- **UI, database, analytics, recommendations, natural-language queries** — owned
  by other team members.
- **Model training or fine-tuning** — out of scope for this component.

---

## 14. Highest-value future work, in order

1. **Line-item extraction** (23–29%) is the weakest area and the largest share
   of financial fields. Likely the biggest single win available.
2. **A skew fallback** for images where no document boundary is detectable
   (Hough transform over table rules), which would address the uniformly-failing
   skewed receipts.
3. **Per-token confidence is captured but unused.** `layout.value_in_column()`
   currently picks the *widest* token when several land in one band; token
   confidence is an available, free signal that nothing consumes yet.
4. **A handwriting-capable OCR engine**, benchmarked as a third independent
   voice before replacing anything. More independent voices strengthen the
   agreement signal, which is the pipeline's most reliable evidence.
5. **A larger held-out set.** Three receipts is enough to catch gross problems,
   not to distinguish a 3% improvement from noise.
