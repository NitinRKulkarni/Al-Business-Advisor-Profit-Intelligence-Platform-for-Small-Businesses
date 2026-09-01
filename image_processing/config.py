"""
config
=======

Central configuration for the image_processing pipeline.

Why this module exists
-----------------------
Every numeric threshold used by the pipeline (blur thresholds, contrast
targets, noise limits, skew-correction angle caps, etc.) lives here instead
of being scattered as "magic numbers" inside processing functions. This
gives us one place to read, tune, and document *why* a value was chosen.

IMPORTANT — calibration status
-------------------------------
Every threshold below is a STARTING VALUE only. None of these numbers have
been calibrated against real handwritten invoice photos/scans yet. They are
reasonable defaults drawn from general document-image-processing practice,
but they WILL need adjustment once we run the pipeline against actual
sample images. Each field's docstring/comment says what symptom to watch
for if the value turns out to be wrong.

How it's structured
--------------------
Settings are grouped into small, focused dataclasses by concern (I/O,
quality analysis, denoising, shadow correction, skew correction,
binarization, morphology). A single top-level `PipelineConfig` dataclass
composes them, and `DEFAULT_CONFIG` is the ready-to-use instance that other
modules import. Using dataclasses (rather than a plain dict or module-level
constants) gives us type-checked, IDE-discoverable fields and makes it easy
to construct a *modified* config for experiments without mutating global
state, e.g. `dataclasses.replace(DEFAULT_CONFIG, quality=my_quality_cfg)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2


@dataclass(frozen=True)
class IOConfig:
    """Settings related to reading and writing image files."""

    # Image file extensions we accept as input. Lowercase, without the dot.
    # Starting value: covers the common formats a phone camera or flatbed
    # scanner would produce. Extend if users submit other formats (e.g. HEIC).
    supported_extensions: tuple[str, ...] = ("jpg", "jpeg", "png", "tif", "tiff", "bmp")

    # Maximum input file size in megabytes before we reject/warn. Starting
    # value: generous enough for a high-res phone photo, but guards against
    # accidentally loading a huge scanned batch/multi-page TIFF.
    max_file_size_mb: float = 25.0

    # If the longer image side exceeds this many pixels, we downscale before
    # heavy processing (keeps runtime bounded on very large scans) while
    # still leaving enough resolution for thin handwriting strokes.
    # Starting value: chosen so a 300dpi A4 scan (~3500px) is untouched.
    max_dimension_px: int = 4000

    # If the longer image side is below this many pixels, preprocessing
    # will upscale before further processing.
    #
    # NO LONGER used as the upscale trigger for individual document crops.
    # This 800px figure is a full-page threshold; every real crop in this
    # project (243-453px wide) is legitimately smaller than that by
    # design, so wiring resize directly to this value meant every one of
    # the 156 crops got unconditionally upscaled regardless of whether it
    # actually needed it — the exact "blindly upscale everything" bug the
    # adaptive-resize stage (see `preprocessing.resize_adaptive` and
    # `ResizeConfig` below) was written to avoid. Preprocessing's upscale
    # decision is now driven by the "low_resolution" warning itself
    # (`QualityAnalysisConfig.min_dimension_for_ocr_px` /
    # `max_stroke_width_px`), not this field. Left here, unused by resize,
    # only as a legacy full-page-scan reference value in case a future
    # caller processes uncropped pages directly.
    min_dimension_px: int = 800

    # JPEG quality used when we must re-encode as JPEG (0-100). Starting
    # value: high, to avoid introducing compression artifacts that look like
    # noise to later denoising/binarization steps.
    jpeg_quality: int = 95


@dataclass(frozen=True)
class QualityAnalysisConfig:
    """Thresholds used to score/diagnose input image quality."""

    # Variance of the Laplacian below this value is treated as "blurry".
    # This is the classic OpenCV blur-detection heuristic. Starting value:
    # a common default seen in practice; if sharp images are flagged as
    # blurry, raise it — if blurry images pass, lower it.
    blur_variance_threshold: float = 100.0

    # Standard deviation of pixel intensity below this is treated as
    # "low contrast" (image looks washed out / flat).
    # Starting value: on a 0-255 scale, a well-exposed document photo
    # usually has std well above this.
    #
    # NO LONGER used to drive the "low_contrast" warning as of the
    # individual-crop baseline (see quality_analysis.py). Global std over
    # the whole frame is dominated by however much blank paper margin
    # happens to be in the crop, so a legible document with sparse ink and
    # a lot of white background (e.g. every invoice_03 crop: brightness
    # ~195-208, std ~20-29, visually fine) reads as "low contrast" even
    # though the actual ink is perfectly dark against the paper. This is
    # the same failure mode the overexposure check below already avoids by
    # judging ink/foreground pixels specifically rather than the whole
    # frame — see `min_ink_paper_contrast`, which replaces this field as
    # the warning driver. Left here (unused by the warning) as a reported
    # raw statistic and in case a future caller wants the plain global
    # figure.
    low_contrast_std_threshold: float = 35.0

    # Minimum acceptable gap (0-255 scale) between the mean intensity of
    # detected paper/background pixels and the mean intensity of detected
    # ink/foreground pixels (both via the same Otsu-based ink mask used for
    # overexposure detection). This is what actually determines whether
    # handwriting/print is legible against its background — unlike global
    # std, it is not diluted by how much blank margin surrounds the ink.
    #
    # STARTING VALUE, reasoned rather than fit to any sample set: dark pen
    # ink against white paper typically reads roughly 0-90 vs 200+, a gap
    # well over 100; 40 is a conservative floor meant to catch genuinely
    # faint/washed-out ink (e.g. worn pencil, a badly faded printout)
    # without flagging normal dark-ink-on-white-paper documents that
    # simply have a lot of blank margin. Needs calibration once OCR
    # accuracy numbers are available to check whether documents below this
    # gap actually read worse.
    min_ink_paper_contrast: float = 40.0

    # If the detected foreground/ink region covers less than this fraction
    # of the frame, there isn't enough content to compute a meaningful
    # ink-vs-paper contrast gap (e.g. a near-blank page) — skip the check
    # rather than guess. Mirrors `min_foreground_fraction_for_exposure_check`
    # below; kept as a separate field so the two checks can be tuned
    # independently later even though they start at the same value.
    min_foreground_fraction_for_contrast_check: float = 0.005

    # Mean pixel intensity below this is treated as "underexposed / too dark".
    underexposed_mean_threshold: float = 45.0

    # --- Overexposure / highlight-clipping detection ---
    #
    # NOTE: overexposure is deliberately NOT judged from mean brightness
    # alone. A mostly-blank invoice page (lots of plain white paper, little
    # ink) can easily have a mean brightness above 240 without any actual
    # exposure problem — the paper is just white. Mean-brightness-only
    # detection produced false "overexposed" warnings on normal bright-paper
    # scans during real-sample testing. Instead we look at two things
    # together: how much of the frame is hard-clipped near pure white
    # (clipping/saturation), AND whether the actual ink/content itself has
    # also been washed toward white (loss of foreground detail). Both
    # thresholds below are STARTING VALUES pending calibration.

    # A pixel is considered "clipped" (blown highlight) if its grayscale
    # value is at or above this. 250 (out of 255) leaves a small margin
    # below true maximum to also catch near-clipped highlights, not just
    # pixels at exactly 255.
    overexposed_clip_intensity: int = 250

    # If at least this fraction of all pixels are clipped (see above), the
    # frame is highlight-heavy. On its own this is NOT sufficient to call
    # an image overexposed (a plain white background naturally clips at a
    # high rate), so this is only the first of two conditions checked.
    overexposed_clip_fraction_threshold: float = 0.90

    # After identifying likely foreground/ink pixels (via Otsu
    # thresholding — see quality_analysis.py), if their mean intensity is
    # at or above this value, the ink itself looks washed toward white
    # rather than genuinely dark. That combination (high clipping AND
    # washed-out ink) is what we call "overexposed". Starting value: 180
    # is comfortably above typical dark-ink readings (roughly 10-80 on the
    # real samples tested) so it should only fire when content detail is
    # genuinely being lost, not just because the page background is white.
    overexposed_foreground_intensity_threshold: float = 180.0

    # If the detected foreground/ink region covers less than this fraction
    # of the frame, there isn't enough content to reliably judge whether
    # ink looks washed out (e.g. a nearly blank page). In that case we
    # skip the foreground-darkness check rather than guess, to avoid
    # false positives on sparse pages.
    min_foreground_fraction_for_exposure_check: float = 0.005

    # Estimated noise level (see quality_analysis for the exact metric)
    # above this triggers denoising in the full pipeline. Starting value:
    # a placeholder until we measure real sample noise levels.
    #
    # As of the individual-crop baseline, the metric this threshold is
    # compared against changed from "residual std over the WHOLE image"
    # to "residual std over paper/background pixels ONLY" (see
    # `_compute_noise_level` in quality_analysis.py) — the whole-image
    # version measured mostly text-edge and ruling-line detail, not grain,
    # which is why it fired on 145/156 baseline crops and correlated
    # almost perfectly (r=0.956) with blur_score/sharpness. This threshold
    # value is UNCHANGED from before that fix; it has not been
    # recalibrated against the new, background-only metric and needs a
    # fresh look once real noisy-vs-clean background samples are
    # available to compare.
    noise_level_threshold: float = 6.0

    # Ink/foreground pixels (see the Otsu-based mask used for overexposure
    # and contrast checks) are dilated by this many pixels before being
    # excluded from the noise measurement. The residual-after-median-blur
    # proxy responds strongly right at a stroke's edge even a couple of
    # pixels outside the ink itself, so measuring noise in a ring
    # immediately around every letter would still be measuring stroke
    # detail, not grain. STARTING VALUE: 3px is enough to clear that edge
    # halo at these crops' resolution (see IOConfig doc — crops here are
    # typically 250-450px wide) without excluding so much background that
    # too few pixels remain to measure on a text-dense document. Needs
    # recalibration if run on much higher-resolution scans, where the same
    # edge halo would cover more pixels.
    noise_mask_dilation_px: int = 3

    # If, after excluding dilated ink/foreground pixels, fewer than this
    # fraction of the frame remains as measurable background, the noise
    # estimate is considered unreliable (too little clean paper to judge)
    # and is skipped rather than guessed — same philosophy as
    # `min_foreground_fraction_for_exposure_check` below, mirrored for the
    # opposite population. STARTING VALUE: a document that is almost
    # entirely ink (dense table, heavy ruling) can legitimately leave very
    # little background; 0.05 is a low bar chosen to still allow a
    # measurement on text-dense invoices while refusing to measure noise
    # on essentially nothing.
    min_background_fraction_for_noise_check: float = 0.05

    # Local brightness variance (used to detect uneven lighting/shadows)
    # above this triggers shadow/lighting correction. Starting value:
    # placeholder pending calibration against real photos with shadows.
    shadow_variance_threshold: float = 400.0

    # Minimum area of the largest detected contour, as a fraction of the
    # total frame area, for it to be trusted as "the document boundary"
    # rather than noise, a partial edge, or an unrelated object in frame.
    #
    # STARTING VALUE — chosen as a reasonable rule of thumb (a document
    # photographed/scanned normally fills at least a quarter of the
    # frame), but this has NOT been calibrated against real handwritten
    # invoice photographs yet. Must be tuned once real samples are
    # available: raise it if non-document objects are mistaken for the
    # page; lower it if genuine document boundaries are being missed
    # (e.g. invoices photographed from farther away, or with a wide
    # background visible).
    min_document_area_fraction: float = 0.25

    # --- Document boundary semantics for already-cropped documents ---
    #
    # `_find_document_contour` returning None used to be reported flatly as
    # the "document_boundary_not_found" warning regardless of context. On
    # the individual invoice crops (as opposed to the original collages),
    # that conflates two very different situations: (1) a crop that fills
    # the frame edge-to-edge, where there is no background margin for a
    # boundary to ever appear in — expected and NOT a defect, vs. (2) a
    # crop that does have visible background but the boundary still wasn't
    # found — a genuine detection gap worth flagging. `document_boundary_status`
    # (see result.py) distinguishes these; only case (2) raises a warning.
    #
    # The distinction is made by sampling a thin ring around the crop's
    # outer edge and checking what fraction of it is background/paper
    # rather than ink — see `_classify_document_boundary` in
    # quality_analysis.py.

    # Width, in pixels, of the border ring sampled to decide whether a crop
    # has any background margin at all. STARTING VALUE: small enough to
    # only look at the very edge (not accidentally sample table borders or
    # header text that happens to sit a bit inward), large enough to not
    # be fooled by a single stray dark pixel from a compression artifact
    # or the collage-splitter seam. Not calibrated against real samples of
    # varying resolution; would need to scale with image size if this
    # pipeline starts receiving much larger or smaller crops.
    boundary_ring_width_px: int = 8

    # If at least this fraction of the outer ring is background/paper
    # (rather than ink, via the same Otsu mask used elsewhere), the crop is
    # considered to have a real margin, so a missing contour counts as a
    # genuine "not_found". Below this fraction, the crop is treated as
    # filling the frame ("fills_frame") and a missing contour is expected,
    # not a warning. STARTING VALUE: chosen so a crop needs a clearly
    # visible margin on most of its border, not just a sliver, before we
    # trust contour detection to have had something to find. Pending
    # calibration against a labeled sample of "has margin" vs "fills
    # frame" crops.
    boundary_ring_background_fraction: float = 0.6

    # --- Resolution adequacy for OCR, as opposed to "is this a full page" ---
    #
    # `IOConfig.min_dimension_px` (800) is a full-page threshold that
    # drives preprocessing's upscale decision; it is intentionally left
    # unchanged; it answers a different question ("should we upscale
    # before heavy processing?") than the one below ("does this crop
    # plausibly have enough detail for OCR to work on?"). Applying the
    # 800px full-page threshold directly to a deliberately small per-
    # document crop (this sample set: 243-453px wide) is what caused
    # "low_resolution" to fire on all 156 individual-crop baseline images
    # — an OCR-relevant floor needs to be much lower and, more importantly,
    # needs to look at stroke width rather than raw pixel count, since a
    # small-but-sharp crop can still OCR fine while a larger-but-mushy one
    # will not.

    # Below this pixel count on the longer side, a crop is deemed too
    # small to plausibly hold legible text no matter how sharp it is, and
    # is flagged regardless of stroke width. STARTING VALUE: well below
    # the full-page 800px floor, reasoned from the sample set's own range
    # (smallest real crop here is 243x224) rather than fit to it — this is
    # a "clearly too small" backstop, not a precision cutoff. Needs
    # revisiting once OCR is actually run and accuracy can be checked
    # against crop size directly.
    min_dimension_for_ocr_px: int = 120

    # Estimated ink stroke width (px, via distance transform on the ink
    # mask — see `_estimate_stroke_width_px`) above which strokes are
    # judged too thick/blurred-together for OCR to reliably separate
    # characters. STARTING VALUE: a normal thin pen stroke or printed
    # character stem is roughly 1-3px wide at this sample set's
    # resolution; a value at/above 5 suggests strokes have bloomed
    # together from blur, heavy ink bleed, or upscaling artifacts rather
    # than representing genuinely thick handwriting. This is a reasoned
    # starting point, not fit to measured OCR failures, and should be
    # revisited once OCR accuracy data exists.
    max_stroke_width_px: float = 5.0

    # If the detected ink/foreground region covers less than this fraction
    # of the frame, there isn't enough content to estimate a stroke width
    # (near-blank crop) — skip the check rather than guess. Mirrors the
    # other min-foreground-fraction fields above.
    min_foreground_fraction_for_resolution_check: float = 0.005

    # Before estimating stroke width, connected components of the ink mask
    # whose bounding box spans at least this fraction of BOTH the frame's
    # width and height are excluded from the measurement.
    #
    # Discovered while checking `_estimate_stroke_width_px` against real
    # sample crops: several invoice_02 crops (printed forms photographed
    # inside a dark notebook/binder cover) had a single connected
    # component running the full width and height of the frame — the
    # cover's dark edge forms a ring around the paper that Otsu
    # thresholding classifies as ink, since it is darker than the paper.
    # That one blob held ~75% of all "foreground" pixels on those crops
    # and included corner regions dozens of pixels thick, which is what
    # was pushing stroke_width_px to 15-17px on documents with genuinely
    # normal, thin pen strokes. No real character or handwriting stroke
    # spans the entire crop in both directions, so a component that does
    # is structural (a frame, a cover edge, a table border) rather than
    # text, regardless of what threshold made it "foreground" in the
    # first place. STARTING VALUE: 0.9 is deliberately close to 1.0 so
    # only a component that is essentially frame-sized gets excluded, not
    # merely a long table rule or a wide header underline.
    stroke_width_ignore_frame_spanning_fraction: float = 0.9


@dataclass(frozen=True)
class ResizeConfig:
    """
    Parameters for the adaptive upscale applied ONLY when quality analysis
    reports "low_resolution" — distinct from `IOConfig.max_dimension_px` /
    `min_dimension_px`, which are hard safety rails for full-page input
    (bound runtime on a huge scan; avoid feeding heavy processing an
    extremely tiny image) rather than an OCR-adequacy decision. Conflating
    the two was the bug: every 243-453px individual crop is legitimately
    below the 800px full-page floor, so upscaling on that alone upscaled
    every single crop regardless of whether it needed it.
    """

    # Target size, in pixels on the longer side, to upscale toward when
    # "low_resolution" fires. STARTING VALUE: chosen so a crop just above
    # `QualityAnalysisConfig.min_dimension_for_ocr_px` (120) but still
    # flagged (e.g. via thick/blurred strokes) gets a meaningful resolution
    # boost without being blown up to an unreasonable size relative to its
    # actual detail content. Not calibrated against OCR accuracy yet.
    upscale_target_px: int = 600

    # Upscaling beyond this factor is refused even if `upscale_target_px`
    # would imply more — magnifying a very small crop by a large factor
    # mostly enlarges blur/artifacts rather than recovering real detail,
    # which risks doing more harm than good to thin strokes. STARTING
    # VALUE: a conservative cap; revisit once OCR accuracy data exists to
    # check whether aggressive upscaling of the smallest crops helps or
    # hurts.
    max_upscale_factor: float = 3.0

    # Interpolation for the adaptive upscale. `cv2.INTER_CUBIC` produces
    # smoother edges than nearest/bilinear, which helps thin strokes
    # survive enlargement. Kept as a config field (rather than a hardcoded
    # cv2 constant in preprocessing.py) so it is visible/tunable here.
    upscale_interpolation: int = cv2.INTER_CUBIC


@dataclass(frozen=True)
class NormalizationConfig:
    """
    Parameters for conservative global brightness normalization, applied
    only when quality analysis reports "underexposed" or "overexposed".

    Distinct from CLAHE (`ContrastConfig`), which is local/adaptive and
    driven by ink-vs-paper contrast: this stage corrects the image's
    overall exposure level via a simple global intensity remap
    (percentile-based contrast stretch), rather than adapting per-tile.
    Applying CLAHE to an underexposed/overexposed image without first
    fixing overall exposure risks amplifying noise in regions that are
    dark/bright for the wrong reason (bad exposure) rather than genuine
    low local contrast.
    """

    # Whether normalization runs at all is decided by quality_analysis's
    # warnings at runtime (only when "underexposed" or "overexposed" is
    # present); this flag lets us force it on/off for testing.
    enabled_by_default: bool = False

    # Low/high percentile (0-100) of the intensity histogram used as the
    # black/white points for the contrast stretch, via
    # `np.percentile`+linear rescale to the full 0-255 range. STARTING
    # VALUES: 2/98 rather than the true min/max (0/100) so a handful of
    # extreme outlier pixels (a stray very dark shadow corner, a small
    # hard-clipped highlight) cannot single-handedly determine the whole
    # remap — a risk with a plain min-max stretch. Not calibrated against
    # real underexposed/overexposed samples (none occurred in the current
    # 156-image set); revisit once such samples are available.
    stretch_low_percentile: float = 2.0
    stretch_high_percentile: float = 98.0

    # After stretching, we only keep the result if measured brightness
    # moved back toward the "acceptable" band (between
    # `QualityAnalysisConfig.underexposed_mean_threshold` and
    # `QualityAnalysisConfig.overexposed_foreground_intensity_threshold`)
    # rather than overshooting past it or barely moving — mirrors the
    # existing "don't assume the operation helped" gating pattern used by
    # CLAHE (`min_contrast_improvement`) and sharpening
    # (`min_blur_score_improvement`). STARTING VALUE: a small non-trivial
    # margin, not calibrated against real samples.
    min_brightness_improvement: float = 5.0


@dataclass(frozen=True)
class DenoiseConfig:
    """Parameters for conservative, stroke-preserving denoising."""

    # Whether denoising runs at all is decided by quality_analysis at
    # runtime (only when noise_level_threshold is exceeded); this flag lets
    # us force it on/off for testing.
    enabled_by_default: bool = False

    # Bilateral filter parameters (edge-preserving smoothing). Chosen to be
    # mild: bilateral filtering is safer than Gaussian blur for handwriting
    # because it smooths flat regions while preserving strong edges (like
    # thin pen strokes). Starting values — likely to need tuning per
    # scanner/camera source.
    bilateral_diameter: int = 5
    bilateral_sigma_color: float = 25.0
    bilateral_sigma_space: float = 25.0

    # fastNlMeansDenoising strength parameter ("h"). Higher = more
    # smoothing = more risk of erasing thin strokes. Starting value is
    # deliberately conservative.
    nlm_h: float = 7.0


@dataclass(frozen=True)
class ShadowCorrectionConfig:
    """Parameters for background/illumination normalization."""

    # Whether shadow correction runs at all is decided by quality_analysis
    # at runtime (only when shadow_variance_threshold is exceeded).
    enabled_by_default: bool = False

    # Kernel size (odd, pixels) for the large-kernel blur/morphological
    # closing used to estimate the background illumination map. Must be
    # large relative to text stroke width so strokes don't bleed into the
    # estimated background. Starting value: scaled for a ~2000-3000px wide
    # document image; may need to scale with image size in the actual
    # implementation rather than being a fixed constant.
    background_kernel_size: int = 51


@dataclass(frozen=True)
class SkewCorrectionConfig:
    """Parameters bounding automatic rotation correction."""

    # Below this angle (degrees) we treat the page as already straight and
    # skip rotation, since tiny corrections risk introducing resampling
    # blur for no visible benefit.
    min_correction_angle_deg: float = 1.5

    # Above this angle we treat the estimate as unreliable (likely a
    # detection error rather than real skew) and skip correction rather
    # than risk rotating the image the wrong way.
    max_correction_angle_deg: float = 20.0


@dataclass(frozen=True)
class ContrastConfig:
    """Parameters for conservative contrast enhancement (CLAHE)."""

    # Whether contrast enhancement runs at all is decided by the
    # preprocessing pipeline at runtime (only when quality analysis
    # reports "low_contrast"); this flag lets us force it on/off for
    # testing/experiments.
    enabled_by_default: bool = False

    # CLAHE (Contrast Limited Adaptive Histogram Equalization) clip limit:
    # caps how much any local histogram bin can be stretched, which is
    # what keeps CLAHE from over-amplifying noise/grain the way plain
    # histogram equalization would. Starting value: a mild, commonly used
    # default (OpenCV's own default is 40, but that is far too aggressive
    # for handwriting; 2.0 is a conservative starting point).
    clahe_clip_limit: float = 2.0

    # CLAHE tile grid size (tiles_x, tiles_y): the image is split into a
    # grid and equalized per-tile, which is what makes it "adaptive"
    # (responds to local contrast, e.g. one shadowed corner) rather than
    # global. Starting value: a moderate grid; smaller tiles adapt more
    # locally but risk exaggerating small-scale noise.
    clahe_tile_grid_size: tuple[int, int] = (8, 8)

    # After applying CLAHE, we only keep the result if measured contrast
    # (std of pixel intensity) improved by at least this many points
    # relative to before. If CLAHE does not meaningfully help (or the
    # image already had reasonable local contrast in most tiles), we
    # discard the CLAHE result and keep the untouched grayscale instead —
    # this is the "don't assume the operation helped" check requested for
    # final-image selection, applied specifically to this stage since
    # CLAHE is the operation most likely to amplify noise without
    # visibly helping. Starting value: a small but non-trivial margin.
    min_contrast_improvement: float = 3.0


@dataclass(frozen=True)
class SharpenConfig:
    """Parameters for conservative unsharp-mask sharpening."""

    # Whether sharpening runs at all is decided by the preprocessing
    # pipeline at runtime (only when quality analysis reports
    # "image_may_be_blurry" AND noise is not already high, since
    # sharpening amplifies noise as much as detail). This flag lets us
    # force it on/off for testing.
    enabled_by_default: bool = False

    # Unsharp mask strength: output = image + amount * (image - blurred).
    # Starting value: mild. Sharpening thin handwriting strokes too
    # aggressively can create ringing artifacts right at stroke edges,
    # which risks looking like extra ink to a later recognition step.
    unsharp_amount: float = 0.5

    # Gaussian blur sigma used to build the "blurred" reference for the
    # unsharp mask. Starting value: small, so only fine detail (like thin
    # strokes) is affected rather than broad shapes.
    unsharp_sigma: float = 1.0

    # After sharpening, we only keep the result if the blur score
    # (variance of Laplacian, see quality_analysis.py) improved by at
    # least this many points. If it did not help, we discard the
    # sharpened result and keep the pre-sharpen image instead.
    min_blur_score_improvement: float = 50.0


@dataclass(frozen=True)
class BinarizationConfig:
    """Parameters for the optional binarization side-branch (not the default output)."""

    # Adaptive threshold block size (odd, pixels). Starting value: a
    # generic mid-size window; too small -> speckle noise, too large ->
    # loses local contrast adaptation near shadows/creases.
    adaptive_block_size: int = 35

    # Constant subtracted from the adaptive threshold mean. Starting value:
    # slightly biases toward keeping faint strokes as foreground.
    adaptive_c: float = 10.0


@dataclass(frozen=True)
class MorphologyConfig:
    """
    Parameters for optional morphological cleanup. Diagnostic-only: applied
    solely to the binarization side-branch image (see
    `BinarizationConfig`/`preprocessing.binarize_adaptive`), never to the
    grayscale final output, and never selected as the pipeline's final
    image. Morphological opening/closing risks eroding thin handwriting
    strokes, which is unacceptable for the final output but is an
    acceptable risk on a branch that already exists purely for visual
    comparison, not for OCR input.
    """

    # Disabled by default per project decision: morphological opening/
    # closing risks eroding thin handwriting strokes. Only enable after
    # testing shows recurring speckle noise that other steps don't handle.
    enabled_by_default: bool = False

    # Kernel size (odd, pixels) if/when morphology is enabled. Starting
    # value: intentionally small (1px erosion radius) to minimize stroke damage.
    kernel_size: int = 3

    # Morphological opening (erosion then dilation) on the binarized
    # side-branch is only applied if the fraction of foreground (ink)
    # pixels that are isolated single-pixel/tiny specks — rather than part
    # of a larger stroke/character shape — is at least this fraction of
    # all foreground pixels. Below this fraction, the binarized image is
    # judged clean enough that morphology would only risk eroding real
    # strokes for no measurable benefit, so it is skipped even though the
    # side-branch is otherwise diagnostic-only (no reason to blur a clean
    # comparison image either). STARTING VALUE: a conservative bar so
    # morphology only engages on genuinely speckled output; not
    # calibrated against real speckle-vs-clean samples.
    speckle_fraction_threshold: float = 0.02


@dataclass(frozen=True)
class PipelineConfig:
    """Top-level configuration composing all pipeline stage settings."""

    io: IOConfig = field(default_factory=IOConfig)
    quality: QualityAnalysisConfig = field(default_factory=QualityAnalysisConfig)
    resize: ResizeConfig = field(default_factory=ResizeConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    denoise: DenoiseConfig = field(default_factory=DenoiseConfig)
    shadow: ShadowCorrectionConfig = field(default_factory=ShadowCorrectionConfig)
    skew: SkewCorrectionConfig = field(default_factory=SkewCorrectionConfig)
    contrast: ContrastConfig = field(default_factory=ContrastConfig)
    sharpen: SharpenConfig = field(default_factory=SharpenConfig)
    binarization: BinarizationConfig = field(default_factory=BinarizationConfig)
    morphology: MorphologyConfig = field(default_factory=MorphologyConfig)


# Ready-to-use default configuration. Other modules should import this
# unless a test/experiment needs an overridden variant, in which case use
# `dataclasses.replace(DEFAULT_CONFIG, ...)` to derive a modified copy
# rather than mutating this shared instance (it's frozen, so mutation
# would raise anyway).
DEFAULT_CONFIG = PipelineConfig()
