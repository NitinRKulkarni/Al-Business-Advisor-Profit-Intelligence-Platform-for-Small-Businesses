"""
preprocessing
==============

Adaptive image preprocessing for handwritten invoice images.

Why this module exists
-----------------------
`quality_analysis.py` only diagnoses an image (read-only). This module is
where corrective action actually happens: turning a raw photo/scan into a
"recognition-ready" image while preserving handwriting. The two are kept
separate on purpose — preprocessing decisions here are driven by the
warnings that quality analysis already produced, rather than duplicating
diagnostic logic.

Architecture: small stage functions + one orchestrator
---------------------------------------------------------
Each correction is its own small function with the signature
`(image, config) -> (result_image, applied: bool, note: str)`. None of
them decide *whether* they should run — that decision belongs to
`preprocess_image()`, which reads the relevant warning from the quality
analysis result and only calls a stage if that warning is present. This
keeps each stage simple/testable and keeps the "when do we apply this"
policy in one readable place.

Pipeline order and reasoning
------------------------------
1. resize (adaptive UPSCALE only — see below) — enlarge only if quality
   analysis flagged "low_resolution". A hard downscale safety rail (very
   large input, unrelated to OCR adequacy) still runs unconditionally.
2. geometry correction (adaptive: perspective correction OR deskew, never
   both) — see "Document boundary and skew" below. Runs ONLY when quality
   analysis already classified this image's `document_boundary_status`
   as "detected"; skipped entirely (no contour re-detection at all) for
   "fills_frame" or "not_found".
3. grayscale conversion (always) — foundation for every step after.
4. exposure normalization (adaptive, only if quality analysis flagged
   "underexposed" or "overexposed") — a global percentile-based contrast
   stretch, run before shadow/noise/contrast correction since a genuinely
   mis-exposed image would otherwise skew all three of those measurements
   and corrections.
5. shadow/lighting correction (adaptive, only if quality analysis flagged
   uneven lighting) — normalizes illumination before we measure/alter
   noise or contrast, since a shadow gradient would otherwise skew both.
6. denoising (adaptive, only if quality analysis flagged high noise) —
   conservative bilateral filtering, done before contrast enhancement so
   we are not asking CLAHE to amplify grain along with real detail.
7. contrast enhancement (adaptive, only if quality analysis flagged low
   contrast) — CLAHE, gated by a measured-improvement check (see below).
8. sharpening (adaptive, only if quality analysis flagged blur AND noise
   is not also high — sharpening a noisy image amplifies noise, not
   detail) — mild unsharp masking, also gated by a measured-improvement
   check.
9. binarization (always computed, never selected as the final output) —
   an optional side-branch purely for visual comparison during testing.
   Morphological cleanup (opening) is applied to THIS branch only, and
   only when the branch is measurably speckled — see `MorphologyConfig`.

The **final** output is always the enhanced grayscale image after
whichever of steps 4-8 actually ran (possibly none of them, if the image
needed no correction at all — that is a legitimate outcome, not a bug).

Adaptive resize (step 1) — why this changed
----------------------------------------------
The original implementation upscaled whenever the image was smaller than
`IOConfig.min_dimension_px` (800px) — a full-page-scan threshold. Every
individual document crop this pipeline actually receives (from
`collage_split.py`) is smaller than that by design (~243-453px wide), so
that wiring upscaled literally every crop regardless of whether quality
analysis had anything to say about its resolution. Upscaling is now gated
on the "low_resolution" warning itself (which — per the quality-analysis
fix — accounts for both raw size and estimated stroke width, not a blind
pixel-count floor), and the target/cap come from `ResizeConfig`, separate
from the hard downscale safety rail in `IOConfig`.

Document boundary and skew (step 2, reusing quality_analysis's classification)
--------------------------------------------------------------------------------
This module reuses the document-boundary classification quality analysis
already computed (`QualityAnalysisResult.document_boundary_status`)
rather than re-deriving it. Contour detection
(`quality_analysis._find_document_contour`) is only invoked when that
status is "detected" — for "fills_frame" (a crop with no background
margin at all, the common case in this sample set) or "not_found", no
contour search runs at all, which both avoids wasted computation and
guarantees a `fills_frame` crop is never perspective-warped against a
spurious internal contour (a table border, a boxed total, a signature
block) that happened to pass the quadrilateral check.

Three outcomes are possible once a large-enough contour is found:

- It simplifies to exactly 4 corners (`cv2.approxPolyDP`): treated as a
  clean page boundary. We perspective-warp + crop to it in one step
  (`cv2.getPerspectiveTransform` + `cv2.warpPerspective`). This corrects
  rotation too, so no separate deskew is needed. Saved as stage
  "perspective_corrected".

- It simplifies to 5-6 corners (still "quadrilateral-like enough" per
  `_is_quadrilateral_like`, but not clean enough to safely crop/warp): we
  do NOT attempt a perspective warp against corner points we don't fully
  trust. Instead we only rotate (deskew) using the angle from
  `cv2.minAreaRect`, without cropping. Saved as stage "deskewed".

- No large-enough or quadrilateral-like contour at all: per project
  requirement, we do NOT invent a boundary or a rotation angle. The image
  is left exactly as-is (no stage produced for this step). This is the
  expected/common outcome on the current sample set, which consists of
  scans tightly cropped to the page (no visible background/edge margin
  for contour detection to find).

Explainable "did this actually help" checks (contrast + sharpen)
---------------------------------------------------------------------
Per the project requirement to not assume the last operation is
automatically the best result, both CLAHE and unsharp-mask sharpening are
measured before/after using the same metrics `quality_analysis.py` already
defines as meaningful (contrast = intensity std-dev; blur_score = Laplacian
variance). If the measured improvement does not clear a configured
minimum (see `ContrastConfig.min_contrast_improvement` and
`SharpenConfig.min_blur_score_improvement` in config.py), the candidate
result is discarded and the pre-stage image is kept instead. This is
deliberately simple and explainable rather than a combined/abstract
"quality score": each operation is checked against the one metric it is
actually supposed to improve.

Binarization is not run through this kind of gate because it is never a
candidate for the final image in the first place — it exists purely as a
side-branch for visual comparison during testing (per project decision:
enhanced grayscale is the default output; binarization can destroy thin
strokes, decimal points, and small characters).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .config import DEFAULT_CONFIG, PipelineConfig
from .io_utils import ImageLoadError, load_image
from .quality_analysis import (
    _compute_blur_score,
    _find_document_contour,
    _is_quadrilateral_like,
    analyze_image_quality,
)
from .result import PreprocessingResult, QualityAnalysisResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage: resize
# ---------------------------------------------------------------------------


def resize_adaptive(
    image: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
    low_resolution_flagged: bool = False,
) -> tuple[np.ndarray, bool, str]:
    """
    Downscale `image` if it exceeds the hard safety-rail size, or upscale
    it ONLY when `low_resolution_flagged` is True (i.e. quality analysis
    raised the "low_resolution" warning for this specific image).

    Downscaling (`IOConfig.max_dimension_px`) is an unconditional runtime
    safety rail, not an OCR-adequacy decision — it still runs regardless
    of `low_resolution_flagged`, since an oversized image is a performance
    concern independent of whether quality analysis flagged anything.

    Upscaling is gated on `low_resolution_flagged` and sized/capped via
    `ResizeConfig` rather than `IOConfig.min_dimension_px` (see the module
    docstring for why: that field is a full-page threshold that would
    otherwise upscale every individual crop unconditionally). Uses
    `cv2.INTER_CUBIC` (configurable via `ResizeConfig.upscale_interpolation`),
    which produces smoother edges than simple bilinear/nearest
    interpolation — helpful when thin strokes need to survive enlargement.

    Returns (result_image, applied, note).
    """
    height, width = image.shape[:2]
    longest_side = max(height, width)
    io_cfg = config.io
    resize_cfg = config.resize

    if longest_side > io_cfg.max_dimension_px:
        scale = io_cfg.max_dimension_px / float(longest_side)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resized = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
        return resized, True, f"downscaled_to_{new_size[0]}x{new_size[1]}"

    if low_resolution_flagged and longest_side < resize_cfg.upscale_target_px:
        scale = resize_cfg.upscale_target_px / float(longest_side)
        scale = min(scale, resize_cfg.max_upscale_factor)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resized = cv2.resize(image, new_size, interpolation=resize_cfg.upscale_interpolation)
        return resized, True, f"upscaled_to_{new_size[0]}x{new_size[1]}"

    return image, False, "resize_not_needed"


# ---------------------------------------------------------------------------
# Stage: geometry correction (perspective correction OR deskew)
# ---------------------------------------------------------------------------


def _order_quad_points(points: np.ndarray) -> np.ndarray:
    """
    Order 4 corner points as (top-left, top-right, bottom-right,
    bottom-left), which is the order `cv2.getPerspectiveTransform` expects
    for both the source and destination point arrays.

    The top-left corner has the smallest (x + y); the bottom-right has the
    largest. The top-right has the smallest (y - x); the bottom-left has
    the largest. This works regardless of the order `approxPolyDP`
    happened to return the points in.
    """
    pts = points.reshape(4, 2).astype(np.float32)
    sums = pts.sum(axis=1)
    diffs = (pts[:, 1] - pts[:, 0])

    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(sums)]
    ordered[2] = pts[np.argmax(sums)]
    ordered[1] = pts[np.argmin(diffs)]
    ordered[3] = pts[np.argmax(diffs)]
    return ordered


def _warp_perspective_to_quad(image: np.ndarray, quad: np.ndarray) -> np.ndarray | None:
    """
    Perspective-warp `image` so the given quadrilateral becomes a flat,
    axis-aligned rectangle, cropped to that rectangle's size.

    The output size is estimated from the quad's own side lengths (the
    longer of the two width estimates and the longer of the two height
    estimates), so we don't distort the document's proportions. Returns
    None if the resulting size would be degenerate (too small to be a
    real document).
    """
    top_left, top_right, bottom_right, bottom_left = quad

    width_top = np.linalg.norm(top_right - top_left)
    width_bottom = np.linalg.norm(bottom_right - bottom_left)
    target_width = int(max(width_top, width_bottom))

    height_left = np.linalg.norm(bottom_left - top_left)
    height_right = np.linalg.norm(bottom_right - top_right)
    target_height = int(max(height_left, height_right))

    if target_width < 10 or target_height < 10:
        return None

    destination = np.array(
        [[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(quad, destination)
    return cv2.warpPerspective(image, matrix, (target_width, target_height))


def _rotate_image(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    """
    Rotate `image` by `angle_degrees` around its center, expanding the
    output canvas so no content is cropped off by the rotation (unlike a
    naive `warpAffine` at the original size, which clips corners).

    Uses `cv2.BORDER_REPLICATE` for the newly exposed corners so they
    extend the nearest edge pixels (typically background/paper color)
    rather than introducing hard black triangles.
    """
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)

    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_width = int(height * sin + width * cos)
    new_height = int(height * cos + width * sin)

    matrix[0, 2] += (new_width / 2.0) - center[0]
    matrix[1, 2] += (new_height / 2.0) - center[1]

    return cv2.warpAffine(
        image, matrix, (new_width, new_height), borderMode=cv2.BORDER_REPLICATE
    )


def correct_geometry(
    image: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
    document_boundary_status: str = "not_found",
) -> tuple[np.ndarray, bool, str]:
    """
    Attempt perspective correction or deskew, but ONLY when
    `document_boundary_status` (as already classified by quality analysis
    — see `QualityAnalysisResult.document_boundary_status`) is "detected".

    For "fills_frame" or "not_found", contour detection is not even
    attempted here: it was already run once during quality analysis, and
    re-running it would (a) waste computation and (b) risk perspective-
    warping a "fills_frame" crop against a spurious internal contour (a
    table border, a boxed total, a signature block) that happens to look
    quadrilateral-like without being the actual page edge — exactly the
    case "fills_frame" exists to flag as having no real boundary to warp
    against. Per project requirement, we never invent a boundary or
    rotation angle.

    Returns (result_image, applied, note). `note` is one of:
    "perspective_correction_applied", "deskew_applied", or a reason the
    step was skipped (used by the caller only for logging).
    """
    if document_boundary_status != "detected":
        return image, False, "document_boundary_status_not_detected"

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    contour = _find_document_contour(gray, config)

    if contour is None:
        return image, False, "no_document_boundary_detected"
    if not _is_quadrilateral_like(contour):
        return image, False, "boundary_not_quadrilateral_like"

    perimeter = cv2.arcLength(contour, closed=True)
    epsilon = 0.02 * perimeter
    approx = cv2.approxPolyDP(contour, epsilon, closed=True)

    if len(approx) == 4:
        quad = _order_quad_points(approx)
        warped = _warp_perspective_to_quad(image, quad)
        if warped is not None:
            return warped, True, "perspective_correction_applied"
        # Degenerate size estimate; fall through to try rotation-only.
        logger.debug("Perspective warp produced a degenerate size; falling back to deskew")

    # Either not exactly 4 corners, or the perspective warp size was
    # degenerate. The contour is still "quadrilateral-like enough" (per
    # the check above) to trust for a rotation angle, just not clean
    # enough to safely crop/warp.
    rect = cv2.minAreaRect(contour)
    angle = rect[-1]
    if angle < -45:
        angle += 90
    elif angle > 45:
        angle -= 90

    if abs(angle) < config.skew.min_correction_angle_deg:
        return image, False, "angle_within_straight_tolerance"
    if abs(angle) > config.skew.max_correction_angle_deg:
        return image, False, "angle_outside_reliable_range"

    rotated = _rotate_image(image, angle)
    return rotated, True, "deskew_applied"


# ---------------------------------------------------------------------------
# Stage: exposure normalization (underexposed / overexposed only)
# ---------------------------------------------------------------------------


def normalize_exposure(
    gray: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Apply a global percentile-based contrast stretch to correct overall
    under/overexposure.

    Unlike CLAHE (local/tile-based, driven by ink-vs-paper contrast), this
    is a single global remap: the intensities at
    `NormalizationConfig.stretch_low_percentile` /
    `stretch_high_percentile` become the new black/white points, and
    everything in between is linearly rescaled to fill 0-255. Percentiles
    rather than true min/max are used so a handful of extreme outlier
    pixels (a stray dark shadow corner, a small hard-clipped highlight)
    cannot single-handedly determine the whole remap.

    Note: this function does not decide whether the result is actually
    better; see `preprocess_image()` for the before/after gating check.
    """
    n = config.normalization
    low = float(np.percentile(gray, n.stretch_low_percentile))
    high = float(np.percentile(gray, n.stretch_high_percentile))

    if high <= low:
        # Degenerate (near-uniform image): nothing meaningful to stretch.
        return gray

    stretched = (gray.astype(np.float32) - low) * (255.0 / (high - low))
    return np.clip(stretched, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Stage: shadow / uneven-lighting correction
# ---------------------------------------------------------------------------


def correct_shadow(
    gray: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Normalize uneven illumination by estimating a smooth background map
    and dividing it out.

    A large Gaussian blur estimates the slowly-varying background
    (illumination) while averaging away fine detail like handwriting
    strokes, since strokes are thin relative to the blur kernel. Dividing
    the original image by this background map cancels out the
    illumination gradient (a shadow) while leaving relative detail
    (ink vs. paper contrast) intact. The result is rescaled so the overall
    brightness matches the original background's average, then clipped to
    the valid 0-255 range.
    """
    kernel_size = config.shadow.background_kernel_size
    if kernel_size % 2 == 0:
        kernel_size += 1

    background = cv2.GaussianBlur(gray, (kernel_size, kernel_size), 0)
    background_safe = np.where(background == 0, 1, background).astype(np.float32)

    normalized = (gray.astype(np.float32) / background_safe) * float(background.mean())
    return np.clip(normalized, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Stage: denoising
# ---------------------------------------------------------------------------


def denoise_conservative(
    gray: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Apply a mild bilateral filter to reduce grain/speckle noise.

    A bilateral filter smooths pixels based on both spatial distance and
    intensity similarity, which means it blurs flat, low-contrast regions
    (like paper texture) while leaving strong edges (like a pen stroke's
    boundary) largely alone. This makes it much safer for handwriting than
    a plain Gaussian blur, which would soften strokes just as much as
    noise. Parameters are intentionally mild (see `DenoiseConfig`).
    """
    d = config.denoise
    return cv2.bilateralFilter(gray, d.bilateral_diameter, d.bilateral_sigma_color, d.bilateral_sigma_space)


# ---------------------------------------------------------------------------
# Stage: contrast enhancement
# ---------------------------------------------------------------------------


def enhance_contrast(
    gray: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Apply CLAHE (Contrast Limited Adaptive Histogram Equalization).

    Regular histogram equalization redistributes intensities globally,
    which can badly over-amplify noise in a document image. CLAHE instead
    equalizes within small tiles (`clahe_tile_grid_size`) and caps how much
    any tile can be stretched (`clahe_clip_limit`), which is what makes it
    safe to use conservatively on scanned documents — it improves local
    contrast (e.g. faint pencil marks against paper) without blowing out
    noise the way global equalization would.

    Note: this function does not decide whether the result is actually
    better; see `preprocess_image()` for the before/after gating check.
    """
    c = config.contrast
    clahe = cv2.createCLAHE(clipLimit=c.clahe_clip_limit, tileGridSize=c.clahe_tile_grid_size)
    return clahe.apply(gray)


# ---------------------------------------------------------------------------
# Stage: sharpening
# ---------------------------------------------------------------------------


def sharpen_image(
    gray: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Apply a mild unsharp mask: output = image + amount * (image - blurred).

    Subtracting a blurred version of the image from itself isolates the
    high-frequency detail (edges, fine strokes); adding a scaled copy of
    that back onto the original accentuates those edges without touching
    broad, flat areas. `unsharp_sigma` controls how "fine" the boosted
    detail is (kept small so only thin strokes are affected, not the
    overall page); `unsharp_amount` controls how strong the boost is.

    Note: this function does not decide whether the result is actually
    better; see `preprocess_image()` for the before/after gating check.
    """
    s = config.sharpen
    blurred = cv2.GaussianBlur(gray, (0, 0), s.unsharp_sigma)
    sharpened = cv2.addWeighted(gray, 1.0 + s.unsharp_amount, blurred, -s.unsharp_amount, 0)
    return sharpened


# ---------------------------------------------------------------------------
# Optional side-branch: binarization (never selected as the final image)
# ---------------------------------------------------------------------------


def binarize_adaptive(
    gray: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Produce a black/white version via adaptive Gaussian thresholding, for
    visual comparison only.

    Unlike a single global threshold, adaptive thresholding computes a
    local threshold per pixel neighborhood (`adaptive_block_size`), which
    handles pages with some remaining lighting variation better than a
    single global cutoff. This is deliberately NOT used as the pipeline's
    final output: aggressive thresholding can erase thin pen strokes,
    decimal points, and small characters entirely, which is unacceptable
    for handwriting preservation. It exists purely so a human reviewer can
    visually compare it against the enhanced-grayscale final output.
    """
    b = config.binarization
    block_size = b.adaptive_block_size
    if block_size % 2 == 0:
        block_size += 1
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, b.adaptive_c
    )


def denoise_binarized_if_speckled(
    binary: np.ndarray,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> tuple[np.ndarray, bool]:
    """
    Apply morphological opening (erosion then dilation) to the binarized
    side-branch image, but ONLY if it is measurably speckled — diagnostic
    branch only; this never touches the grayscale final output.

    "Speckled" is measured as the fraction of foreground (ink) pixels that
    are isolated 1-2px specks (found via `cv2.connectedComponentsWithStats`
    on the foreground mask; a component with a tiny bounding box is a
    speck rather than part of a real stroke). If that fraction is below
    `MorphologyConfig.speckle_fraction_threshold`, the branch is already
    clean and morphology is skipped — even on a diagnostic-only branch,
    there is no reason to risk eroding real stroke shapes for no
    measurable benefit. See `MorphologyConfig` in config.py.

    Returns (result, applied).
    """
    m = config.morphology
    if not m.enabled_by_default:
        return binary, False

    foreground = binary == 0  # adaptiveThreshold's ink is the dark (0) pixels
    total_foreground = int(np.count_nonzero(foreground))
    if total_foreground == 0:
        return binary, False

    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground.astype(np.uint8), connectivity=8
    )
    speck_pixels = sum(
        stats[i, cv2.CC_STAT_AREA]
        for i in range(1, n)
        if stats[i, cv2.CC_STAT_WIDTH] <= 2 and stats[i, cv2.CC_STAT_HEIGHT] <= 2
    )
    speckle_fraction = speck_pixels / total_foreground

    if speckle_fraction < m.speckle_fraction_threshold:
        return binary, False

    kernel_size = m.kernel_size
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return opened, True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def preprocess_image(
    image_path: str | Path,
    config: PipelineConfig = DEFAULT_CONFIG,
    quality_result: QualityAnalysisResult | None = None,
) -> tuple[PreprocessingResult, dict[str, np.ndarray]]:
    """
    Run the adaptive preprocessing pipeline on a single image.

    Which correction stages run is driven by `quality_result.warnings`
    (computed via `analyze_image_quality` if not already provided by the
    caller). Only stages that actually ran produce an entry in the
    returned stages dict — there are no placeholder/fake stages for
    corrections that were skipped.

    Parameters
    ----------
    image_path:
        Path to the image file to preprocess.
    config:
        Pipeline configuration.
    quality_result:
        Optionally, a `QualityAnalysisResult` already computed for this
        image (e.g. by a caller that also wants to report quality
        metrics). If omitted, quality analysis is run internally.

    Returns
    -------
    (PreprocessingResult, stages)
        `stages` maps stage name -> image array for every stage that was
        actually produced (including "original" and "final", which are
        always present on success). On failure, `stages` is empty and
        `PreprocessingResult.success` is False.
    """
    path = Path(image_path)

    try:
        original = load_image(path, config=config)
    except ImageLoadError as exc:
        logger.warning("Preprocessing failed to load %s: %s", path.name, exc)
        return PreprocessingResult(filename=path.name, success=False, error=str(exc)), {}

    if quality_result is None:
        quality_result = analyze_image_quality(path, config=config)

    start_time = time.perf_counter()
    stages: dict[str, np.ndarray] = {"original": original}
    operations: list[str] = []
    warnings = list(quality_result.warnings)

    working = original

    resized, applied, note = resize_adaptive(
        working, config, low_resolution_flagged="low_resolution" in quality_result.warnings
    )
    if applied:
        working = resized
        stages["resized"] = working
        operations.append("resize")
        logger.debug("%s: resize applied (%s)", path.name, note)

    geo_result, applied, note = correct_geometry(
        working, config, document_boundary_status=quality_result.document_boundary_status
    )
    if applied:
        working = geo_result
        stage_name = "perspective_corrected" if note == "perspective_correction_applied" else "deskewed"
        stages[stage_name] = working
        operations.append(stage_name)
        logger.debug("%s: geometry correction applied (%s)", path.name, note)
    else:
        logger.debug("%s: geometry correction skipped (%s)", path.name, note)

    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    stages["grayscale"] = gray
    operations.append("grayscale_conversion")
    working_gray = gray

    if "underexposed" in quality_result.warnings or "overexposed" in quality_result.warnings:
        before_brightness = float(working_gray.mean())
        candidate = normalize_exposure(working_gray, config)
        after_brightness = float(candidate.mean())
        # "Improved" means brightness moved back toward the acceptable
        # band rather than away from it — checked directionally, since
        # underexposed needs brightness to rise and overexposed needs it
        # to fall.
        if "underexposed" in quality_result.warnings:
            improvement = after_brightness - before_brightness
        else:
            improvement = before_brightness - after_brightness
        if improvement >= config.normalization.min_brightness_improvement:
            working_gray = candidate
            stages["normalized"] = working_gray
            operations.append("exposure_normalization")
        else:
            warnings.append("exposure_normalization_skipped_no_improvement")
            logger.debug(
                "%s: exposure normalization discarded (improvement=%.2f below threshold)",
                path.name, improvement,
            )

    if "uneven_lighting_or_shadow" in quality_result.warnings:
        working_gray = correct_shadow(working_gray, config)
        stages["shadow_corrected"] = working_gray
        operations.append("shadow_correction")

    if "high_noise" in quality_result.warnings:
        working_gray = denoise_conservative(working_gray, config)
        stages["denoised"] = working_gray
        operations.append("denoise")

    if "low_contrast" in quality_result.warnings:
        before_contrast = float(working_gray.std())
        candidate = enhance_contrast(working_gray, config)
        after_contrast = float(candidate.std())
        improvement = after_contrast - before_contrast
        if improvement >= config.contrast.min_contrast_improvement:
            working_gray = candidate
            stages["contrast"] = working_gray
            operations.append("contrast_enhancement")
        else:
            warnings.append("contrast_enhancement_skipped_no_improvement")
            logger.debug(
                "%s: CLAHE discarded (improvement=%.2f below threshold)",
                path.name, improvement,
            )

    # Sharpening amplifies whatever detail is present, including noise, so
    # we skip it if the image was already flagged as noisy — even after
    # denoising, we don't want to compound the two adaptive corrections
    # in a way that risks manufacturing false stroke-like edges.
    if "image_may_be_blurry" in quality_result.warnings and "high_noise" not in quality_result.warnings:
        before_blur = _compute_blur_score(working_gray)
        candidate = sharpen_image(working_gray, config)
        after_blur = _compute_blur_score(candidate)
        improvement = after_blur - before_blur
        if improvement >= config.sharpen.min_blur_score_improvement:
            working_gray = candidate
            stages["sharpened"] = working_gray
            operations.append("sharpen")
        else:
            warnings.append("sharpen_skipped_no_improvement")
            logger.debug(
                "%s: sharpening discarded (improvement=%.2f below threshold)",
                path.name, improvement,
            )

    # Side-branch: always computed for comparison, never used as `final`.
    # Morphology (if enabled and the branch is measurably speckled) is
    # applied only here, never to `working_gray`/the final output — see
    # `denoise_binarized_if_speckled` / `MorphologyConfig`.
    thresholded = binarize_adaptive(working_gray, config)
    thresholded, morphology_applied = denoise_binarized_if_speckled(thresholded, config)
    stages["thresholded"] = thresholded
    if morphology_applied:
        operations.append("morphology_on_binarized_branch")

    stages["final"] = working_gray
    elapsed = time.perf_counter() - start_time

    result = PreprocessingResult(
        filename=path.name,
        success=True,
        original_width=original.shape[1],
        original_height=original.shape[0],
        final_width=working_gray.shape[1],
        final_height=working_gray.shape[0],
        operations_applied=operations,
        processing_time_seconds=round(elapsed, 4),
        warnings=warnings,
    )

    logger.info(
        "Preprocessed %s: operations=%s final_size=%dx%d time=%.3fs",
        path.name, operations, result.final_width, result.final_height, elapsed,
    )

    return result, stages
