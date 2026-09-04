# Ground Truth (hand-verified)

Each `*.json` here was transcribed by a human **reading the source image
directly**. OCR output was never used to produce these files — that would
make any accuracy measurement circular and meaningless.

Conventions:

- A field present on the receipt is recorded with its exact printed value.
- A field genuinely **absent** from the receipt is recorded as `null`, so
  "correctly returned null" can be distinguished from "missed a value that
  was there".
- A field that a human **cannot confidently read** from the image is
  **omitted entirely** (not guessed, not set to null) so it is excluded
  from scoring rather than counted as a wrong answer.
- Money values are recorded as numbers exactly as printed on the receipt,
  including where the receipt's own arithmetic is internally inconsistent
  (real receipts sometimes contain human errors; the benchmark measures
  whether OCR read the *printed* value, not whether the receipt is
  correct).

`category` is used for per-category reporting in the benchmark.
