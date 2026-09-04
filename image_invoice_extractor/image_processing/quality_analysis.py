"""
quality_analysis
==================

Image quality analysis for handwritten invoice images.

Why this module exists
-----------------------
Before we do any preprocessing or recognition, we need to know what we're
actually dealing with: is the photo blurry, too dark, tilted, noisy, is
there even a document boundary visible? This module inspects a single
image and produces a `QualityAnalysisResult` describing it, without
modifying the image in any way. That separation matters: quality analysis
is a *read-only diagnostic* step; preprocessing (Step 4, not built yet) is
where corrective action actually happens. Keeping them separate means we
can log/report quality metrics even for images we decide not to alter.

What each metric measures and why (OpenCV concepts)
-----------------------------------------------------
- brightness / contrast: mean and standard deviation of pixel intensity on
  the grayscale image. Mean tells us how light/dark the image is overall;
  std tells us how much tonal variation there is (a washed-out, flat scan
  has low std even if its mean brightness looks "normal"). Both are always
  reported in the result regardless of whether any exposure warning fires.

- overexposure (clipping + foreground check, NOT mean brightness alone):
  early testing on real scanned invoices showed that judging overexposure
  from mean brightness alone produced false positives — a mostly-blank
  invoice page is legitimately bright (lots of plain white paper) without
  any actual exposure problem. Real overexposure means detail is being
  lost to blown-out highlights, which mean brightness cannot distinguish
  from "the page is just white". Instead we check two things together:
  (1) what fraction of pixels are clipped near pure white (potential
  highlight clipping), and (2) whether the ink/content itself (found via
  an Otsu threshold, the same technique used for the noise/content masks
  elsewhere in this module) is also washed toward white. Only when *both*
  are true do we call it "overexposed" — a bright background alone is not
  enough, and a small amount of clipping alongside dark, legible ink is
  not enough either. See `QualityAnalysisConfig` for the (starting-value)
  thresholds involved.

- blur_score (variance of Laplacian): the Laplacian operator
  (`cv2.Laplacian`) approximates the second derivative of the image i.e.
  it responds strongly at edges and texture, and near-zero on flat regions.
  A sharp image has many strong, varied edge responses -> high variance.
  A blurry image has smoothed-out edges -> low variance. This is a widely
  used, cheap blur heuristic; it is not a perfect measure (busy/textured
  images naturally score higher than plain ones), which is one reason the
  threshold in config.py is explicitly marked as a starting value.

- noise_level (residual std after median blur): `cv2.medianBlur` replaces
  each pixel with the median of its neighborhood, which suppresses small
  speckle noise while preserving strong edges. Subtracting the median-
  blurred image from the original leaves mostly what the median blur
  removed: fine-grained noise (plus a little texture/edge "leakage" near
  hard edges). The standard deviation of that residual is our noise proxy.
  It is deliberately simple; a rigorous noise estimator is out of scope
  for this milestone.

- document boundary + skew: `cv2.Canny` finds edges, `cv2.findContours`
  groups connected edge pixels into contours, and we keep the largest
  contour if it's big enough relative to the frame (area fraction is
  configurable — see `config.quality.min_document_area_fraction` — and is
  explicitly a starting value pending calibration). That "big enough"
  contour is what `document_detected` reports.

  For `skew_angle` specifically, we apply one more check before trusting
  the contour: `cv2.approxPolyDP` simplifies the contour to its dominant
  corners, and we only treat it as a reliable page boundary if that
  simplification is quadrilateral-like (~4 corners). This matters for
  handwritten invoices: a large contour can appear for reasons that have
  nothing to do with the page edge (e.g. a strong shadow line, a table
  edge, or a cluster of handwriting merging into one blob after
  dilation), and such a contour is not quadrilateral. Fitting a
  `cv2.minAreaRect` around a non-quadrilateral blob and reporting its
  angle as "skew" would describe the shape of that blob, not the
  rotation of the page.

  If no reliable (large + quadrilateral-like) document boundary is found,
  we deliberately do NOT fall back to estimating skew from the overall
  handwriting/content distribution. Handwriting on an invoice is
  scattered and unevenly distributed (a signature block, a table, a few
  scribbled totals) — a bounding rectangle around all dark pixels mostly
  reflects where the handwriting happens to be, not how the page is
  rotated. Rather than report a number that looks precise but may be
  measuring the wrong thing, `skew_angle` is `None` whenever we can't
  ground the estimate in an actual page edge. This keeps the module
  honest: no ML/DNN model, just declining to guess when the simple
  geometric method (contour + approxPolyDP) isn't applicable.

- shadow/uneven lighting: we split the grayscale image into a coarse grid
  and compute the variance of each cell's mean brightness. Real shadows or
  uneven lighting show up as some regions being noticeably brighter/darker
  than others, which this captures without needing a full background
  model (that belongs in preprocessing, not analysis).

All thresholds referenced here live in `config.py` (`QualityAnalysisConfig`
and `SkewCorrectionConfig`) and are explicitly marked there as starting
values pending calibration against real sample images.

Individual-crop revision: foreground/background-aware metrics
------------------------------------------------------------------
The metrics above were designed and validated against full-page collage
images. Running the same logic against the individual per-document crops
produced by `collage_split.py` exposed a shared root cause behind four
misleading warnings, documented in detail in `config.py` next to each
affected threshold:

    warning                        | problem on a cropped document
    --------------------------------+------------------------------------
    low_resolution                 | fires on every crop, because the
                                    | threshold (800px) describes a full
                                    | page, not a deliberately small crop
    high_noise                     | measures text-edge/ruling detail as
                                    | noise (correlated with blur_score
                                    | at r=0.956 on the baseline), because
                                    | it does not distinguish ink from
                                    | background
    document_boundary_not_found    | fires even when a crop fills the
                                    | frame edge-to-edge and simply has no
                                    | margin for a boundary to appear in
    low_contrast                   | fires on legible ink-on-white
                                    | documents that happen to have a lot
                                    | of blank margin, because global std
                                    | is diluted by that margin

The common fix is the same pattern this module already uses for
overexposure detection (see `_is_overexposed`): separate ink/foreground
pixels from paper/background pixels via Otsu thresholding, then measure
the thing that actually matters on the *correct* population instead of
the whole frame. `_ink_foreground_mask` computes this mask once per image
so every check below (contrast, noise, resolution, overexposure) shares
it rather than re-running Otsu four times.

Each fix and its exact behavior is documented at its own function below;
skew estimation (`_estimate_skew`) is UNCHANGED — only the warning that
accompanies it (`skew_not_estimable`) is now scoped so it does not fire on
a crop that never had a boundary to measure skew from in the first place.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .config import DEFAULT_CONFIG, PipelineConfig
from .io_utils import ImageLoadError, load_image
from .result import QualityAnalysisResult

logger = logging.getLogger(__name__)

# Grid size used to sample local brightness for shadow/uneven-lighting
# detection. 4x4 is coarse enough to be robust to handwriting/text texture
# but fine enough to catch a shadow across half the page.
_SHADOW_GRID_ROWS = 4
_SHADOW_GRID_COLS = 4

# Number of corners a simplified contour (via cv2.approxPolyDP) must have,
# within this tolerance, to be considered "quadrilateral-like" and
# therefore trustworthy as a page boundary for skew estimation. A page
# photographed or scanned is a quadrilateral (a rectangle, or a
# perspective-distorted rectangle); a contour that simplifies to a very
# different number of corners is more likely a shadow edge, a table line,
# or a cluster of handwriting rather than the actual page edge.
# Not a threshold that needs per-image tuning (it follows from the
# geometry of "a page has 4 corners"), so it is kept as a module constant
# rather than moved into config.py.
_QUADRILATERAL_CORNER_RANGE = (4, 6)


def _ink_foreground_mask(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Return (foreground_mask, foreground_fraction) separating presumed
    ink/content pixels from paper/background pixels.

    Otsu's method picks the single global threshold that best separates
    an image's intensities into two populations; inverting makes the
    darker population (ink, on a document) the foreground/True region.
    This is the exact technique `_is_overexposed` already used —
    factored out here so every foreground/background-aware check in this
    module (contrast, noise, resolution, overexposure) shares one mask
    instead of re-running Otsu per check.
    """
    total_pixels = gray.size
    if total_pixels == 0:
        return np.zeros_like(gray, dtype=bool), 0.0

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = binary == 255
    fraction = float(np.count_nonzero(mask)) / total_pixels
    return mask, fraction


def _compute_brightness_contrast(gray: np.ndarray) -> tuple[float, float]:
    """Return (mean intensity, std intensity) of a grayscale image."""
    mean_val, std_val = cv2.meanStdDev(gray)
    return float(mean_val[0][0]), float(std_val[0][0])


def _compute_blur_score(gray: np.ndarray) -> float:
    """Return the variance of the Laplacian (higher = sharper)."""
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return float(laplacian.var())


def _compute_ink_paper_contrast(
    gray: np.ndarray,
    foreground_mask: np.ndarray,
    foreground_fraction: float,
    config: PipelineConfig,
) -> float | None:
    """
    Return the gap (0-255) between paper/background mean intensity and
    ink/foreground mean intensity, or None if there isn't enough detected
    foreground to judge reliably.

    This replaces global intensity std as the driver of the
    "low_contrast" warning. Global std answers "how much does intensity
    vary across the whole frame", which on a document crop is mostly a
    function of how much blank paper margin surrounds the ink — NOT
    whether the ink itself is legible. This metric answers the question
    that actually matters: is there a real brightness gap between ink and
    the paper it sits on. See `min_ink_paper_contrast` in config.py.
    """
    q = config.quality
    if foreground_fraction < q.min_foreground_fraction_for_contrast_check:
        return None

    background_mean = float(gray[~foreground_mask].mean()) if np.any(~foreground_mask) else float(gray.mean())
    foreground_mean = float(gray[foreground_mask].mean())
    return background_mean - foreground_mean


def _compute_noise_level(
    gray: np.ndarray,
    foreground_mask: np.ndarray,
    config: PipelineConfig,
) -> float | None:
    """
    Return std of (gray - median_blur(gray)), measured ONLY over
    background/paper pixels, or None if too little background remains to
    measure reliably.

    The original version of this metric measured the residual over the
    WHOLE image. `cv2.medianBlur` suppresses small speckle but is defeated
    by real edges — including text strokes and ruling lines — which show
    up in the "removed" residual just as strongly as actual grain does.
    On the individual-crop baseline this made the metric track
    blur_score/sharpness almost perfectly (Pearson r=0.956 across all 156
    images) rather than tracking noise: a sharp, well-lit, text-dense
    crop scored as "noisy" purely because it had a lot of crisp edges, and
    145/156 images were flagged. Excluding ink/foreground pixels (dilated
    by `noise_mask_dilation_px` to also clear the halo of strong residual
    immediately around a stroke's edge) leaves only blank paper, where a
    genuine grain/speckle proxy is actually meaningful.
    """
    q = config.quality
    median_filtered = cv2.medianBlur(gray, ksize=3)
    residual = gray.astype(np.int16) - median_filtered.astype(np.int16)

    dilation_px = max(0, q.noise_mask_dilation_px)
    if dilation_px > 0 and np.any(foreground_mask):
        kernel = np.ones((dilation_px * 2 + 1, dilation_px * 2 + 1), np.uint8)
        excluded = cv2.dilate(foreground_mask.astype(np.uint8), kernel, iterations=1) > 0
    else:
        excluded = foreground_mask

    background_pixels = residual[~excluded]
    background_fraction = background_pixels.size / residual.size if residual.size else 0.0
    if background_fraction < q.min_background_fraction_for_noise_check:
        return None

    return float(background_pixels.std())


def _compute_shadow_variance(gray: np.ndarray) -> float:
    """
    Return the variance of mean brightness across a coarse grid of cells.

    High values indicate uneven lighting (e.g. a shadow across part of
    the page) rather than a uniformly lit document.
    """
    height, width = gray.shape
    row_edges = np.linspace(0, height, _SHADOW_GRID_ROWS + 1, dtype=int)
    col_edges = np.linspace(0, width, _SHADOW_GRID_COLS + 1, dtype=int)

    cell_means = []
    for r in range(_SHADOW_GRID_ROWS):
        for c in range(_SHADOW_GRID_COLS):
            cell = gray[row_edges[r]:row_edges[r + 1], col_edges[c]:col_edges[c + 1]]
            if cell.size > 0:
                cell_means.append(float(cell.mean()))

    if len(cell_means) < 2:
        return 0.0
    return float(np.var(cell_means))


def _is_overexposed(
    gray: np.ndarray,
    foreground_mask: np.ndarray,
    foreground_fraction: float,
    config: PipelineConfig,
) -> bool:
    """
    Determine whether an image shows genuine overexposure (highlight
    clipping that is also washing out the actual content), rather than
    simply having a bright white-paper background.

    Two conditions must both hold:

    1. A high fraction of pixels are clipped near-white (see
       `overexposed_clip_intensity` / `overexposed_clip_fraction_threshold`
       in config.py). This is necessary but NOT sufficient — a normal
       bright scan of a mostly-blank page will also clip heavily.

    2. The foreground/ink region (found via `_ink_foreground_mask`, the
       same "presumed ink" mask shared by every check in this module) has
       a mean intensity at or above `overexposed_foreground_intensity_threshold`.
       If the ink itself still reads dark, the page is just bright, not
       overexposed — legible content is not actually being lost. If there
       isn't enough detected foreground to judge (a near-blank page), this
       check is skipped and we do not report overexposure, since we would
       otherwise be guessing from too little content.

    This intentionally does not use mean brightness of the whole image,
    which was found (via real sample testing) to falsely flag normal
    bright-paper invoice scans as "overexposed".
    """
    q = config.quality
    total_pixels = gray.size
    if total_pixels == 0:
        return False

    clip_fraction = float(np.count_nonzero(gray >= q.overexposed_clip_intensity)) / total_pixels
    if clip_fraction < q.overexposed_clip_fraction_threshold:
        return False

    if foreground_fraction < q.min_foreground_fraction_for_exposure_check:
        # Too little detected content (near-blank page) to judge whether
        # ink is washed out; avoid guessing.
        return False

    foreground_mean_intensity = float(gray[foreground_mask].mean())
    return foreground_mean_intensity >= q.overexposed_foreground_intensity_threshold


def _find_document_contour(
    gray: np.ndarray,
    config: PipelineConfig,
) -> np.ndarray | None:
    """
    Attempt to find a large, document-like contour in the image.

    Returns the largest contour if its area is at least
    `config.quality.min_document_area_fraction` of the total frame area,
    otherwise None. That fraction is a STARTING VALUE (see config.py) and
    will need calibration against real handwritten invoice photos.
    """
    frame_area = gray.shape[0] * gray.shape[1]

    # Blur slightly before edge detection to suppress noise that would
    # otherwise fragment the page boundary into many small edges.
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, threshold1=50, threshold2=150)

    # Dilate to close small gaps in the boundary so findContours sees one
    # continuous outline rather than several broken segments.
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < config.quality.min_document_area_fraction * frame_area:
        return None

    return largest


def _classify_document_boundary(
    document_contour: np.ndarray | None,
    foreground_mask: np.ndarray,
    config: PipelineConfig,
) -> str:
    """
    Return one of "detected", "fills_frame", "not_found" — see
    `QualityAnalysisResult.document_boundary_status` for the meaning of
    each. Only "not_found" raises the "document_boundary_not_found"
    warning.

    The distinction between "fills_frame" and "not_found" is made by
    sampling a thin ring around the crop's outer border and checking what
    fraction of it is background/paper rather than ink (using the same
    foreground mask every other check in this module shares). A crop that
    was tightly cropped to the document has ink/content running right up
    to its edge on most sides — there was never a background margin for
    `_find_document_contour` to find a boundary within, so a miss there
    is expected, not a defect. A crop with a real paper margin visible on
    its border plausibly does have a boundary to find, so a miss there is
    a genuine detection gap.
    """
    if document_contour is not None:
        return "detected"

    q = config.quality
    height, width = foreground_mask.shape
    ring = max(1, q.boundary_ring_width_px)
    if ring * 2 >= min(height, width):
        # Degenerate: the "ring" would cover the whole crop. Fall back to
        # treating the full frame as the border sample.
        border_background_fraction = float(np.count_nonzero(~foreground_mask)) / foreground_mask.size
    else:
        border_mask = np.zeros_like(foreground_mask, dtype=bool)
        border_mask[:ring, :] = True
        border_mask[-ring:, :] = True
        border_mask[:, :ring] = True
        border_mask[:, -ring:] = True
        border_background = np.count_nonzero(border_mask & ~foreground_mask)
        border_total = np.count_nonzero(border_mask)
        border_background_fraction = border_background / border_total if border_total else 0.0

    if border_background_fraction >= q.boundary_ring_background_fraction:
        return "not_found"
    return "fills_frame"


def _estimate_stroke_width_px(
    foreground_mask: np.ndarray,
    foreground_fraction: float,
    config: PipelineConfig,
) -> float | None:
    """
    Return an estimate of typical ink stroke width in pixels, or None if
    there isn't enough detected foreground to judge.

    Uses `cv2.distanceTransform` on the foreground/ink mask: for every ink
    pixel, this gives the distance to the nearest background pixel, which
    is roughly half the local stroke width at that point (a pixel in the
    middle of a stroke is far from the edge; a pixel near the stroke's
    boundary is close). Doubling the MEDIAN (not mean) of those distances
    gives a robust typical-stroke-width estimate; median rather than mean
    because a small number of large filled regions (a ruled table border,
    a filled cell, a stamp) can otherwise dominate the average even
    though most ink pixels genuinely sit on thin strokes.

    Before measuring, any connected component of the mask that spans
    almost the entire frame in both dimensions is excluded — see
    `stroke_width_ignore_frame_spanning_fraction` in config.py. This was
    necessary, not just a refinement: checking against real sample crops
    (several invoice_02 documents, photographed inside a dark notebook
    cover) showed Otsu classifying the cover's dark edge — a ring running
    the full width and height of the frame — as "ink", which by itself
    held ~75% of all foreground pixels and pushed the raw median-based
    estimate to 15-17px on documents with genuinely normal, thin pen
    strokes. No real character spans the whole crop in both directions,
    so a component that does is structural, not text, regardless of why
    Otsu called it foreground.
    """
    q = config.quality
    if foreground_fraction < q.min_foreground_fraction_for_resolution_check:
        return None

    height, width = foreground_mask.shape
    span_fraction = q.stroke_width_ignore_frame_spanning_fraction
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground_mask.astype(np.uint8), connectivity=8
    )
    text_mask = foreground_mask.copy()
    for i in range(1, n):
        comp_w, comp_h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if comp_w >= span_fraction * width and comp_h >= span_fraction * height:
            text_mask[labels == i] = False

    if not np.any(text_mask):
        # Every foreground pixel belonged to frame-spanning structure;
        # nothing text-like remains to measure.
        return None

    distances = cv2.distanceTransform(text_mask.astype(np.uint8), cv2.DIST_L2, 3)
    ink_distances = distances[text_mask]
    if ink_distances.size == 0:
        return None
    return float(np.median(ink_distances) * 2.0)


def _is_quadrilateral_like(contour: np.ndarray) -> bool:
    """
    Return True if a contour simplifies to roughly 4 corners.

    Uses `cv2.approxPolyDP` to reduce the contour to its dominant corner
    points, using an epsilon (approximation tolerance) proportional to the
    contour's perimeter so it scales sensibly with image resolution. A
    real page boundary — even with mild perspective distortion — should
    simplify to about 4 corners. A shadow edge, a table line, or a
    handwriting cluster typically will not, which is what lets us
    distinguish "this is the page" from "this is just a large contour"
    without any ML model.
    """
    perimeter = cv2.arcLength(contour, closed=True)
    if perimeter <= 0:
        return False
    epsilon = 0.02 * perimeter
    approx = cv2.approxPolyDP(contour, epsilon, closed=True)
    min_corners, max_corners = _QUADRILATERAL_CORNER_RANGE
    return min_corners <= len(approx) <= max_corners


def _angle_from_contour(contour: np.ndarray) -> float:
    """
    Return the rotation angle (degrees) of the minimum-area bounding
    rectangle around a contour, normalized to the range (-45, 45].

    `cv2.minAreaRect` returns angles in a convention where the value can
    describe either the "short side" or "long side" tilt depending on the
    rectangle's shape. Normalizing keeps skew_angle meaningful regardless
    of whether the document is closer to portrait or landscape.
    """
    rect = cv2.minAreaRect(contour)
    angle = rect[-1]
    if angle < -45:
        angle += 90
    elif angle > 45:
        angle -= 90
    return float(angle)


def _estimate_skew(
    document_contour: np.ndarray | None,
    config: PipelineConfig,
) -> float | None:
    """
    Estimate page rotation in degrees from the document boundary, or
    return None if it cannot be estimated reliably.

    Deliberate design choice for handwritten invoices: skew is ONLY
    estimated from a detected document boundary that also passes the
    `_is_quadrilateral_like` check. There is intentionally no fallback
    that estimates skew from the overall handwriting/content distribution
    (e.g. a bounding rectangle around all dark pixels). Handwriting on an
    invoice is scattered — near a signature line, inside a table, next to
    a total — so a rectangle fit around all of it mostly reflects where
    the writing happens to be, not how the page is rotated. Reporting an
    angle in that case would look precise while actually being
    misleading, which is worse than reporting nothing. If neither
    condition is met, we return None rather than guess.

    UNCHANGED behavior from the original implementation. What changed
    (see `analyze_image_quality`) is only which case is treated as
    noteworthy: a crop that never had a boundary to measure from at all
    (`document_boundary_status in {"fills_frame", "not_found"}`) no
    longer raises "skew_not_estimable" merely for lacking that boundary —
    that is already covered, when it matters, by
    "document_boundary_not_found". "skew_not_estimable" is now reserved
    for the case a boundary WAS found but the angle estimate itself had to
    be discarded (not quadrilateral enough, or outside the reliable
    range) — a genuine estimation failure rather than an expected
    consequence of the crop having no margin.

    No fallback skew estimator is implemented for the no-boundary case
    (e.g. Hough-line detection against ruled table borders, which several
    of these invoices have). That is a plausible future option, deferred
    rather than built here because it would need its own validation
    against real samples before being trusted — table rules are not
    guaranteed parallel to the page edge, and a wrong skew estimate is
    worse than none per this module's existing design philosophy.
    """
    if document_contour is None or not _is_quadrilateral_like(document_contour):
        logger.debug(
            "No reliable quadrilateral document boundary; skew_angle will be None"
        )
        return None

    angle = _angle_from_contour(document_contour)

    if abs(angle) < config.skew.min_correction_angle_deg:
        # Effectively straight; report as 0.0 rather than a noisy
        # near-zero value.
        return 0.0
    if abs(angle) > config.skew.max_correction_angle_deg:
        logger.debug("Discarding unreliable skew estimate: %.2f degrees", angle)
        return None
    return angle


def analyze_image_quality(
    image_path: str | Path,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> QualityAnalysisResult:
    """
    Analyze a single image and return a `QualityAnalysisResult`.

    This function never raises for image-loading problems: any
    `ImageLoadError` (missing file, corrupted image, unsupported format,
    etc.) is caught and reported as a failed result with `success=False`
    and a descriptive `error`, so callers (including batch tools built in
    later steps) can process a whole folder without one bad file stopping
    everything.

    Parameters
    ----------
    image_path:
        Path to the image file to analyze.
    config:
        Pipeline configuration providing quality/skew thresholds.

    Returns
    -------
    QualityAnalysisResult
    """
    path = Path(image_path)

    try:
        image = load_image(path, config=config)
    except ImageLoadError as exc:
        logger.warning("Quality analysis failed to load %s: %s", path.name, exc)
        return QualityAnalysisResult(filename=path.name, success=False, error=str(exc))

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    q = config.quality

    brightness, contrast = _compute_brightness_contrast(gray)
    blur_score = _compute_blur_score(gray)
    shadow_variance = _compute_shadow_variance(gray)

    # Computed once, shared by every foreground/background-aware check
    # below (contrast, noise, resolution, overexposure) — see the module
    # docstring and `_ink_foreground_mask`.
    foreground_mask, foreground_fraction = _ink_foreground_mask(gray)

    ink_paper_contrast = _compute_ink_paper_contrast(gray, foreground_mask, foreground_fraction, config)
    noise_level = _compute_noise_level(gray, foreground_mask, config)
    stroke_width_px = _estimate_stroke_width_px(foreground_mask, foreground_fraction, config)

    document_contour = _find_document_contour(gray, config)
    document_detected = document_contour is not None
    boundary_status = _classify_document_boundary(document_contour, foreground_mask, config)
    skew_angle = _estimate_skew(document_contour, config)

    warnings: list[str] = []

    if blur_score < q.blur_variance_threshold:
        warnings.append("image_may_be_blurry")

    # low_contrast: driven by ink-vs-paper contrast, not global std (see
    # `_compute_ink_paper_contrast`). If there wasn't enough foreground to
    # judge, we do not guess — no warning either way.
    if ink_paper_contrast is not None and ink_paper_contrast < q.min_ink_paper_contrast:
        warnings.append("low_contrast")

    if _is_overexposed(gray, foreground_mask, foreground_fraction, config):
        warnings.append("overexposed")
    if brightness < q.underexposed_mean_threshold:
        warnings.append("underexposed")

    # high_noise: driven by background-only residual std (see
    # `_compute_noise_level`). If too little background remained to
    # measure, we do not guess — no warning either way.
    if noise_level is not None and noise_level > q.noise_level_threshold:
        warnings.append("high_noise")

    if shadow_variance > q.shadow_variance_threshold:
        warnings.append("uneven_lighting_or_shadow")

    # document_boundary_not_found: only raised for the genuine detection
    # gap ("not_found"), not for a crop that simply has no margin to find
    # a boundary within ("fills_frame") — see `_classify_document_boundary`.
    if boundary_status == "not_found":
        warnings.append("document_boundary_not_found")

    if skew_angle is None:
        # Only noteworthy if a boundary WAS found but the angle had to be
        # discarded as unreliable. A crop with no boundary at all
        # ("fills_frame"/"not_found") never had skew to estimate in the
        # first place; that absence is already covered (when it matters)
        # by document_boundary_not_found above, so it is not repeated
        # here as a second, redundant warning.
        if boundary_status == "detected":
            warnings.append("skew_not_estimable")
    elif abs(skew_angle) >= config.skew.min_correction_angle_deg:
        warnings.append("possible_skew")

    # low_resolution: an OCR-relevant floor for a per-document crop, not
    # the full-page 800px threshold (see config.py). Two independent
    # signals, either of which is sufficient on its own:
    #   (a) the crop is small enough on its longer side that it could not
    #       plausibly hold legible text regardless of sharpness;
    #   (b) estimated ink stroke width suggests strokes have blurred/
    #       bloomed together (thick relative to a normal pen/print stroke)
    #       rather than being genuinely thick handwriting.
    # If there was too little foreground to estimate stroke width, only
    # signal (a) is checked — we do not guess about stroke quality from
    # too little ink.
    too_small = max(width, height) < q.min_dimension_for_ocr_px
    strokes_too_thick = stroke_width_px is not None and stroke_width_px > q.max_stroke_width_px
    if too_small or strokes_too_thick:
        warnings.append("low_resolution")

    logger.info(
        "Analyzed %s: %dx%d brightness=%.1f contrast(global_std)=%.1f "
        "ink_paper_contrast=%s blur=%.1f noise=%s stroke_width=%s skew=%s "
        "boundary=%s warnings=%s",
        path.name, width, height, brightness, contrast,
        f"{ink_paper_contrast:.1f}" if ink_paper_contrast is not None else "None",
        blur_score,
        f"{noise_level:.1f}" if noise_level is not None else "None",
        f"{stroke_width_px:.1f}" if stroke_width_px is not None else "None",
        skew_angle, boundary_status, warnings,
    )

    return QualityAnalysisResult(
        filename=path.name,
        success=True,
        width=width,
        height=height,
        brightness=round(brightness, 2),
        contrast=round(contrast, 2),
        blur_score=round(blur_score, 2),
        noise_level=round(noise_level, 2) if noise_level is not None else None,
        ink_paper_contrast=round(ink_paper_contrast, 2) if ink_paper_contrast is not None else None,
        stroke_width_px=round(stroke_width_px, 2) if stroke_width_px is not None else None,
        skew_angle=round(skew_angle, 2) if skew_angle is not None else None,
        document_detected=document_detected,
        document_boundary_status=boundary_status,
        warnings=warnings,
    )
