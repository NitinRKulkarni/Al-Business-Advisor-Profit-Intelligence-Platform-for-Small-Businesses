# Receipt Image Processing & Structured Extraction

Local (no cloud) pipeline that turns a photographed receipt or invoice into
structured, validated JSON:

```
image → preprocessing → OCR (Tesseract + EasyOCR) → reconciliation
      → structured extraction → validation → confidence/review → JSON
```

This repository is **one component** of a larger team project (an AI business
advisor / profit-intelligence platform). Its only responsibility is producing
trustworthy structured receipt data. UI, database, analytics, and
recommendations are owned by other team members and are deliberately **not**
implemented here.

See [`DESIGN.md`](DESIGN.md) for architecture and the reasoning behind the
design decisions.

---

## Core principle: wrong data is worse than missing data

A wrong rupee amount silently corrupts every downstream calculation. A `null`
does not. So when a value cannot be established reliably, this pipeline
returns `null`, records a warning, lowers the relevant confidence score, and
sets `needs_review` — it never guesses to fill a field.

Concretely: if the two OCR engines disagree on the total and no arithmetic
check can settle which is right, `total` comes back `null` with both candidate
values preserved in `field_decisions` for a human to resolve.

---

## Requirements

- **Python 3.14** (developed and tested on 3.14.3)
- **Tesseract OCR** installed at system level — the `pytesseract` package is
  only a wrapper.
  Windows: `winget install --id UB-Mannheim.TesseractOCR`
- Python packages: `pip install -r requirements.txt`

EasyOCR pulls torch/torchvision (~250 MB of wheels) and downloads ~100 MB of
model weights on first use. CPU-only is fine; no GPU is required.

---

## Quick start

Run everything from the repository root.

**Extract from one receipt (both engines, with reconciliation):**

```powershell
.venv\Scripts\python.exe scripts/test_receipt_cli.py test/2.png --engines tesseract,easyocr
```

**Your own image** (`.jpg`, `.jpeg`, `.png`; quote paths containing spaces):

```powershell
.venv\Scripts\python.exe scripts/test_receipt_cli.py "C:\path\to\receipt.jpg" --engines tesseract,easyocr
```

**Single engine** (faster — skips the EasyOCR model load, but no cross-engine
reconciliation, so disagreement can no longer be detected):

```powershell
.venv\Scripts\python.exe scripts/test_receipt_cli.py test/2.png
```

The CLI prints the full JSON, then a readable summary of vendor, receipt/invoice
number, date, line items, subtotal, discount, tax, total, confidences, and
validation warnings.

Source images are never modified. The preprocessed copy is written to
`data/output/cli_test_runs/`.

### Multiple receipts at once

Use `batch_receipts_cli.py` for batches. All images go through a single
`process_receipts()` call, so the OCR engines are constructed once and reused
(important — EasyOCR loads ~100 MB of weights on construction).

```powershell
# every image in a folder
.venv\Scripts\python.exe scripts/batch_receipts_cli.py --dir test --engines tesseract,easyocr

# specific files
.venv\Scripts\python.exe scripts/batch_receipts_cli.py a.jpg b.png c.jpeg

# summary table only, and save the structured output for the DB team
.venv\Scripts\python.exe scripts/batch_receipts_cli.py --dir test --engines tesseract,easyocr --quiet --json-out results.json
```

Useful flags: `--quiet` (suppress per-image JSON, print only the summary),
`--json-out FILE` (write the combined results array), `--grouped` (emit the
nested `to_grouped_dict()` contract instead of the flat one), `--output-dir`.

Example summary output:

```
source                         ok        total    subtot      tax     disc  items  review   conf
1.png                          yes           -         -        -        -      1     YES  13.26
2.png                          yes         685       700        -       15      4     YES  58.84
images processed      : 2
pipeline succeeded    : 2/2
total extracted       : 1/2
flagged needs_review  : 2/2
```

Each image gets its own independent result — one unreadable or corrupt file
never aborts the batch. The exit code is `0` if at least one image succeeded and
`2` only if every image failed, since per-image status is already in the JSON.

---

## Using it from Python (for the downstream team)

```python
from ocr import TesseractOcrEngine, EasyOcrEngine
from receipt_extraction import process_receipt, process_receipts

# One image
result = process_receipt(
    "path/to/receipt.jpg",
    "data/output/my_run",                       # processed images go here
    ocr_engines=[TesseractOcrEngine(), EasyOcrEngine()],
)

payload = result.to_dict()          # flat contract (below)
nested  = result.to_grouped_dict()  # grouped contract, for DB handoff

# Many images — each returns its own result; one bad image never
# aborts the batch.
results = process_receipts([img1, img2, img3], "data/output/my_run",
                           ocr_engines=[TesseractOcrEngine(), EasyOcrEngine()])
```

Both functions are backward compatible. `ocr_engine=` (singular) still works
for single-engine use, and omitting both defaults to Tesseract only.

### Adding another OCR engine later (e.g. Azure)

Implement the `OcrEngine` protocol — a `name` property and
`recognize(image_path) -> OcrResult` — and pass it in the `ocr_engines` list.
No extraction, reconciliation, or validation code needs to change. Azure is
**not** implemented here yet, by design.

---

## Output contract

`to_dict()` returns a flat, JSON-serializable dict. Any field may be `null`.

| Field | Meaning |
|---|---|
| `source`, `success`, `error` | Input filename and pipeline status |
| `document_type` | e.g. `cash_memo`, `invoice`, `delivery_challan` |
| `vendor_name`, `customer_name` | Parties |
| `invoice_number`, `receipt_number` | Identifiers (always contain a digit) |
| `date`, `time` | `date` is ISO `YYYY-MM-DD` when confidently parsed |
| `currency` | `INR` when a ₹/Rs./INR marker is present |
| `subtotal`, `discount`, `tax`, `total` | Financial fields |
| `items[]` | `description`, `quantity`, `unit_price`, `amount`, `confidence`, `warnings` |
| `payment_method` | When stated |
| `raw_text` | OCR text, always preserved for debugging |
| `ocr_engine`, `engines_used` | Which engines ran |
| `ocr_confidence` | Engine's own token score — **not** a correctness measure |
| `extraction_confidence` | How much structure was recovered |
| `validation_confidence` | Share of applicable arithmetic checks that passed |
| `overall_confidence` | Conservative combination of the above |
| `needs_review`, `review_reasons` | Review signal and machine-readable causes |
| `operations_applied` | Preprocessing steps actually used |
| `warnings` | Everything noteworthy, including per-engine notes |
| `reconciliation_performed` | Whether engines were cross-checked |
| `raw_ocr_by_engine` | Per-engine raw text |
| `field_decisions` | Per-field evidence trail: value, confidence, agreement, source, candidates, reason |

`to_grouped_dict()` returns the same information nested under `document`,
`financials`, `items`, `payment`, `quality`, `validation`, `provenance`,
`raw_ocr`, plus `field_decisions` and `needs_review`.

### Reading `field_decisions`

This is how you tell "genuinely absent" from "could not be resolved":

```json
"total": {
  "value": null,
  "agreement": false,
  "source": "disagreement",
  "candidates": [
    {"engine": "tesseract-5.4.0.20240606", "value": 430.0},
    {"engine": "easyocr-1.7.2", "value": 410.0}
  ],
  "reason": "engines_disagree_on_total_and_arithmetic_evidence_did_not_resolve_it:suspicious_pattern=single_digit_substitution"
}
```

`source` values: `engines_agree` (strongest), `arithmetic` (resolved by
arithmetic evidence), a single engine name (only one engine produced a value),
`disagreement` (unresolved → `null`), `none` (nothing found).

---

## Confidence: four separate numbers, deliberately

OCR confidence is **not** correctness. Measured on this dataset: one image
scored the highest Tesseract confidence in the whole set (87.5) while
recognising only three words. So confidence is never used to choose between
candidate values, and four independent signals are reported instead —
`ocr_confidence`, `extraction_confidence`, `validation_confidence`, and
`overall_confidence`. A receipt can legitimately have high OCR confidence and
low extraction confidence.

For an automated consumer, the practical rule is: gate on `needs_review` and
`validation_confidence`, not on `ocr_confidence`.

---

## Validation

All checks **flag**; none silently correct a value.

- `quantity × unit_price ≈ amount` per line item
- `sum(item amounts) ≈ subtotal`
- `subtotal − discount + tax ≈ total`
- Date sanity (malformed, future, implausibly old)
- Magnitude sanity (negative, absurdly large, zero-with-items)
- Cross-engine numeric disagreements, classified by digit pattern:
  `trailing_digit_lost` (1550→155), `leading_digit_lost` (1121→121),
  `decimal_place_shift`, `digit_transposition`, `single_digit_substitution`

---

## Running tests and benchmarks

```powershell
# Full suite — 243 tests, deterministic (no network, no model download)
.venv\Scripts\python.exe -m pytest -q

# Held-out verification: receipts never used to build or tune anything
.venv\Scripts\python.exe scripts/verify_heldout.py

# Development-set benchmark: Tesseract vs EasyOCR vs reconciled
.venv\Scripts\python.exe scripts/benchmark_extraction.py

# Multi-variant OCR: baseline vs variants
.venv\Scripts\python.exe scripts/benchmark_variants.py
```

Benchmarks take 1–3 minutes each (EasyOCR model load plus per-image
inference). Reports are written to `data/output/heldout_verification/`,
`data/output/ocr_benchmark/`, and `data/output/variant_benchmark/`.

---

## Measured accuracy (no rounding up, no claims of 100%)

Ground truth is hand-transcribed by reading each image; OCR output is never
used as ground truth, which would make measurement circular. See
`ground_truth/README.md` for the transcription conventions.

**Held-out set** — 3 receipts transcribed *after* the implementation was
finished and never used to tune any threshold, regex, weight, or gate. This is
the honest estimate for an arbitrary new upload:

| Metric | Result |
|---|---|
| Financial-field accuracy | 10/48 (20.8%) |
| **Wrong non-null values** | **0** |
| Correct nulls (field genuinely absent) | 10 |
| Missed values (present, returned null) | 8 |
| Flagged `needs_review` | 3/3 |

`total` was correct on 2 of 3, including a receipt whose final line is labelled
**"Net Total"** — a label absent from the development set, so that is real
generalization rather than memorization.

**Development set** — 11 receipts used while building the fixes, so these
numbers are optimistic by construction:

| Variant | Financial-field accuracy |
|---|---|
| Tesseract only | 73/191 (38.2%) |
| EasyOCR only | 54/191 (28.3%) |
| **Reconciled (both)** | **78/191 (40.8%)** |

Reconciliation beats either engine alone. Combined across all 14 ground-truth
receipts: 88/239 (36.8%).

Read these numbers with the null policy in mind: the pipeline is tuned to
*decline* rather than guess, so a large share of the gap is `null`s that are
flagged for review — not wrong values shipped to the database.

---

## Known limitations

- **Line-item numeric fields are weakest** (23–29%). Multi-column handwritten
  tables are the hardest part of the problem.
- **Severely degraded images stay unreliable**: heavy skew/perspective, very
  dark, or faded-low-contrast receipts fail similarly on *both* engines, so
  reconciliation cannot rescue them.
- **Vendor names sometimes come back partial** (e.g. missing a leading "SRI").
- **India-centric assumptions**: DD/MM date order is preferred, currency
  detection recognises only ₹/Rs./INR, and financial keywords are English.
- **Multi-variant OCR (`use_variants=True`) is off by default** because it
  measured neutral: identical accuracy for ~65% more runtime. See `DESIGN.md`.
- **A scoring caveat**: `benchmark_extraction.py` matches vendor names by
  substring in either direction, so an empty string technically matches
  anything. `verify_heldout.py` guards against this; the older script does not.
- Accuracy is measured only on the 14 hand-verified receipts. It is **not** a
  claim about all 156 dataset images, which have no ground truth.

---

## Repository layout

```
image_processing/     preprocessing + quality analysis
  config.py           all tunable thresholds, centralized
  quality_analysis.py blur/contrast/noise/skew/exposure metrics → warnings
  preprocessing.py    adaptive, quality-gated transformations
  receipt_pipeline.py handoff wrapper: writes OCR-ready images
ocr/                  OCR engine abstraction
  engine.py           OcrEngine protocol, OcrResult, OcrToken (bbox + confidence)
  tesseract_engine.py / easyocr_engine.py
receipt_extraction/   structured extraction
  extractor.py        orchestration + text-based field extraction
  layout.py           spatial/bounding-box table reconstruction
  reconciliation.py   cross-engine field-level merge, digit-pattern diagnostics
  variants.py         multi-variant OCR gating and evidence-based selection
  validators.py       arithmetic/sanity checks (flag only, never correct)
  confidence.py       four confidence signals + needs_review
  models.py           ReceiptData, LineItem, ExtractionResult, FieldDecision
ground_truth/         hand-transcribed JSON, one per benchmarked receipt
scripts/              CLIs, benchmarks, verification tools
  test_receipt_cli.py     one image, full JSON + readable summary
  batch_receipts_cli.py   many images, summary table + combined JSON
  benchmark_extraction.py / benchmark_variants.py / verify_heldout.py
tests/                243 deterministic tests
```

---

## Guarantees

- Source images are never modified, moved, or overwritten.
- No cloud/API calls; fully local.
- No value is ever invented to fill a field.
- Raw OCR text is always preserved for debugging.
- Validators only flag; they never rewrite a financial value.
