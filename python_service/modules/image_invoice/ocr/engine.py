"""
engine
=======

The engine-agnostic contract for the OCR stage: `OcrResult` (what every
engine returns) and `OcrEngine` (what every engine must implement).

Why a protocol rather than just calling pytesseract
-----------------------------------------------------
Tesseract is a baseline here, not a commitment. This dataset is mostly
*handwritten* invoices, which is precisely where Tesseract's legacy
character-based recognition is weakest, so there is a realistic chance the
engine gets replaced by a deep-learning alternative (EasyOCR, TrOCR, or a
cloud handwriting API) after the baseline is measured.

Using `typing.Protocol` means that swap requires no changes to any caller:
a new engine just needs a `name` property and a `recognize()` method with
a matching signature. There is no base class to inherit from and no
registration step — structural typing is enough. Type checkers will verify
that a candidate class actually satisfies the contract.

`OcrResult` mirrors the design decisions already made in
`image_processing/result.py`:
- failure is represented as *data* (`success` / `error`), not exceptions,
  so a batch runner can process a whole folder without one bad image
  aborting the run;
- no image arrays are carried, so the result stays cheap to log, put in a
  CSV row, or serialize to JSON;
- fields that an engine genuinely cannot supply are `None` rather than a
  fabricated number (same "don't invent a misleading value" policy as
  `skew_angle` / `noise_level` in the quality stage).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class OcrToken:
    """
    One recognized word/region with its position on the page.

    Why this exists
    -----------------
    Both installed engines already compute per-word bounding boxes
    (Tesseract exposes left/top/width/height in its TSV output; EasyOCR
    returns four corner points), but the original `OcrResult` discarded
    them and kept only flattened text. That forced the extraction layer to
    infer table columns by splitting whitespace inside an already-garbled
    text line -- the direct cause of quantity/rate/amount values being
    associated with the wrong column when OCR mangles the separators.

    Coordinates are in pixels of the image that was actually OCR'd, with
    origin at top-left. `confidence` is on the same 0-100 scale as
    `OcrResult.mean_confidence` so the two are directly comparable.
    """

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OcrResult:
    """Result of running OCR on a single (already preprocessed) image."""

    # Name of the image file OCR was run against (not the full path).
    filename: str

    # False if OCR could not be performed at all (missing file, engine
    # binary not found, engine crashed). When False, `text` is empty and
    # `error` explains why.
    success: bool

    # Which engine produced this result, e.g. "tesseract-5.5.3". Recorded
    # per-result rather than assumed globally so a report containing rows
    # from several engines stays unambiguous.
    engine: str = "unknown"

    # Full recognized text, newlines preserved as the engine emitted them.
    text: str = ""

    # Mean confidence (0-100) over recognized words, or None if the engine
    # does not expose confidence. Words the engine itself marked as
    # unrecognized (Tesseract reports -1) are excluded from the mean
    # rather than dragging it down as if they were low-confidence
    # readings.
    mean_confidence: float | None = None

    # Number of non-whitespace tokens the engine actually returned with a
    # usable confidence value. Useful sanity signal: high mean confidence
    # over 3 words is very different from the same figure over 80 words.
    word_count: int = 0

    # Per-word confidences (0-100), same order as they appear in `text`.
    # Kept so a later step can threshold/inspect weak words without
    # re-running OCR; excluded from `to_dict_summary()` because it is too
    # verbose for a CSV row.
    word_confidences: list[float] = field(default_factory=list)

    # Positioned tokens (see `OcrToken`). Populated by engines that can
    # report geometry; an engine that cannot simply leaves this empty, and
    # spatial extraction then degrades gracefully to text-only parsing
    # rather than failing. Excluded from `to_dict_summary()` (too verbose
    # for a CSV row) but included in `to_dict()`.
    tokens: list[OcrToken] = field(default_factory=list)

    # Wall-clock seconds spent inside the engine call itself (excludes
    # reading the file from disk and writing outputs).
    processing_time_seconds: float = 0.0

    # Present only when success is False.
    error: str | None = None

    def to_dict(self) -> dict:
        """Full, JSON-serializable dict including per-word confidences."""
        return asdict(self)

    def to_dict_summary(self) -> dict:
        """
        Flat dict suitable for a CSV row: everything except the verbose
        `word_confidences` list and the raw `text` (which contains
        newlines and is saved to its own .txt file instead).
        """
        data = asdict(self)
        data.pop("word_confidences", None)
        data.pop("tokens", None)
        data.pop("text", None)
        return data


@runtime_checkable
class OcrEngine(Protocol):
    """
    Structural contract every OCR engine must satisfy.

    Implementations must not raise for per-image problems: a missing file,
    an undecodable image, or an engine-level failure should come back as
    `OcrResult(success=False, error=...)`. Raising is reserved for
    programmer error and for engine *setup* problems that make every
    subsequent call pointless (e.g. the Tesseract binary is not
    installed), which is better surfaced loudly at construction time than
    silently repeated 156 times.
    """

    @property
    def name(self) -> str:
        """Engine identifier recorded in `OcrResult.engine`."""
        ...

    def recognize(self, image_path: str | Path) -> OcrResult:
        """Run OCR on one image and return an `OcrResult`."""
        ...
