"""
result
=======

Typed result object returned by the image quality analysis stage.

Why this module exists
-----------------------
Rather than returning a plain dict from `quality_analysis.analyze_image_quality`,
we return a `QualityAnalysisResult` dataclass. This gives:

- IDE autocomplete and type checking on every field (typos in dict keys are
  a common, silent source of bugs).
- A single documented "shape" that later stages (batch testing/reporting in
  Step 5, and eventually preprocessing) can rely on without guessing what
  keys might be present.
- A clean way to represent *failure* (corrupted/unreadable image) as data
  — via `success` and `error` — instead of forcing every caller to wrap
  every call in its own try/except.

How it's used
--------------
`analyze_image_quality()` always returns an instance of this class, whether
the image loaded successfully or not. Callers should check `.success`
before trusting the numeric fields. `.to_dict()` produces a plain,
JSON-serializable dict matching the example output shape from the project
brief (width/height/brightness/contrast/blur_score/skew_angle/
document_detected/warnings), plus a couple of extra fields (filename,
noise_level, success, error) that are useful for automation and debugging.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class QualityAnalysisResult:
    """Result of running quality analysis on a single image."""

    # Name of the file that was analyzed (not the full path), useful when
    # this result ends up in a batch report (Step 5) alongside many others.
    filename: str

    # False if the image could not be loaded/decoded at all. When False,
    # every numeric field below is left at its default (0 / None / empty)
    # and `error` explains what went wrong.
    success: bool

    width: int = 0
    height: int = 0

    # Mean pixel intensity of the grayscale image, 0-255. Higher = brighter.
    brightness: float = 0.0

    # Standard deviation of pixel intensity over the WHOLE frame, 0-255.
    # Reported as a raw statistic, but — as of the individual-crop
    # baseline — no longer used to drive the "low_contrast" warning. On a
    # document crop with a lot of blank paper margin, this number is
    # dominated by how much margin there is, not by whether the actual
    # ink is legible against its background; see `ink_paper_contrast`
    # below for the metric that now drives the warning, and
    # `QualityAnalysisConfig.low_contrast_std_threshold` in config.py for
    # the fuller explanation.
    contrast: float = 0.0

    # Variance of the Laplacian of the grayscale image. Higher = sharper.
    # See quality_analysis.py for why this measures blur.
    blur_score: float = 0.0

    # Standard deviation of (image - median_blurred_image), measured ONLY
    # over pixels judged to be paper/background (ink/foreground pixels,
    # plus a small margin around them, are excluded) — a proxy for
    # grain/speckle noise in the background rather than text-edge detail.
    # None means there wasn't enough background left to measure once
    # foreground was excluded (e.g. an ink-dense, nearly all-text crop);
    # in that case we deliberately do not guess, matching the project's
    # existing "skew_angle: None rather than a misleading number" policy.
    noise_level: float | None = None

    # Gap (0-255 scale) between the mean intensity of detected
    # paper/background pixels and the mean intensity of detected
    # ink/foreground pixels. This is what actually drives the
    # "low_contrast" warning: it measures whether the ink itself is
    # legible against its background, independent of how much blank
    # margin surrounds it. None means there wasn't enough detected
    # foreground to judge (e.g. a near-blank crop).
    ink_paper_contrast: float | None = None

    # Estimated typical ink stroke width in pixels (see
    # `_estimate_stroke_width_px` in quality_analysis.py), used as one of
    # the two signals behind the "low_resolution" warning: OCR cares about
    # whether strokes are thin/distinct enough to read, not just raw pixel
    # count. None means there wasn't enough detected foreground to judge.
    stroke_width_px: float | None = None

    # Estimated rotation of the page/content in degrees. None means we
    # either couldn't estimate it, or the estimate exceeded the configured
    # "reliable" range and was discarded rather than reported as fact.
    # Only ever populated when `document_boundary_status == "detected"`;
    # see that field and `_estimate_skew` for why no fallback estimate is
    # produced when a crop has no boundary to measure from at all.
    skew_angle: float | None = None

    # Whether a document-like boundary (a large, roughly rectangular
    # contour) was found in the frame. False just means no such contour
    # was found — see `document_boundary_status` for why that is not
    # automatically a defect on an already-cropped document.
    document_detected: bool = False

    # One of:
    #   "detected"    - a large, roughly rectangular contour was found.
    #   "fills_frame" - no contour was found, but the crop's own outer
    #                   border is mostly ink/content rather than paper
    #                   margin, so there was no background gap for a
    #                   boundary to appear in. Expected on a tightly
    #                   cropped document; NOT a warning.
    #   "not_found"   - no contour was found AND the crop's border shows
    #                   a real paper margin, meaning a boundary plausibly
    #                   existed to detect and detection missed it. This
    #                   is the only case that raises
    #                   "document_boundary_not_found".
    # See `_classify_document_boundary` in quality_analysis.py.
    document_boundary_status: str = "not_found"

    # Human-readable, machine-checkable warning codes, e.g. "low_contrast",
    # "image_may_be_blurry". See quality_analysis.py for the full list and
    # the thresholds (from config.py) that trigger each one.
    warnings: list[str] = field(default_factory=list)

    # Present only when success is False: a short description of why the
    # image could not be analyzed (e.g. "file not found", "corrupted").
    error: str | None = None

    def to_dict(self) -> dict:
        """Return a plain, JSON-serializable dict representation."""
        return asdict(self)


@dataclass
class PreprocessingResult:
    """
    Result of running the adaptive preprocessing pipeline on a single image.

    Why this exists
    -----------------
    Mirrors `QualityAnalysisResult`'s role for the preprocessing stage: a
    single typed object that batch tooling (Step 5's test script) and any
    future caller can rely on, instead of passing around loose tuples or
    dicts with ad-hoc keys. It deliberately does NOT carry the actual
    image arrays — see `PreprocessingOutput` below for that — because this
    result is meant to be cheap to log, put in a CSV row, or serialize to
    JSON, none of which should have to deal with NumPy arrays.
    """

    filename: str
    success: bool

    original_width: int = 0
    original_height: int = 0
    final_width: int = 0
    final_height: int = 0

    # Ordered list of stage names that were actually applied to this
    # image, e.g. ["resize", "perspective_correction", "denoise"]. A stage
    # being adaptive and skipped (e.g. denoise not needed) means its name
    # is simply absent here — there is no "skipped" placeholder entry,
    # per the project requirement not to invent fake stages.
    operations_applied: list[str] = field(default_factory=list)

    # Wall-clock seconds spent in the preprocessing pipeline for this
    # image (excludes quality analysis and I/O of saving debug stages).
    processing_time_seconds: float = 0.0

    # Warnings carried over from quality analysis plus any preprocessing-
    # specific notes (e.g. "clahe_result_discarded_no_improvement").
    warnings: list[str] = field(default_factory=list)

    error: str | None = None

    def to_dict(self) -> dict:
        """Return a plain, JSON-serializable dict representation."""
        return asdict(self)
