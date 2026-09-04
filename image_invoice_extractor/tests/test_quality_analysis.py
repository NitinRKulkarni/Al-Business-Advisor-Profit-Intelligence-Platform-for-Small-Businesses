"""
Tests for the individual-crop quality analysis improvements.

Scope: these tests target the four fixes made on top of the baseline run
against `data/samples/batch2/individual/` (see the report in
data/output/): low_resolution, high_noise, document_boundary semantics,
and low_contrast, plus a check that skew estimation's warning scoping
changed correctly without altering the underlying estimate.

All images are synthetic and built in-memory with OpenCV/NumPy rather than
loaded from `data/samples/`, so these tests do not depend on, and cannot
accidentally modify, the real sample images. Each test constructs the
smallest image that isolates the behavior under test.
"""

from __future__ import annotations

import dataclasses

import cv2
import numpy as np
import pytest

from image_processing.config import DEFAULT_CONFIG
from image_processing.quality_analysis import (
    _classify_document_boundary,
    _compute_ink_paper_contrast,
    _compute_noise_level,
    _estimate_stroke_width_px,
    _find_document_contour,
    _ink_foreground_mask,
    analyze_image_quality,
)

CONFIG = DEFAULT_CONFIG


def _write_bgr(path, gray_or_bgr: np.ndarray) -> None:
    cv2.imwrite(str(path), gray_or_bgr)


def _text_crop(
    width: int = 300,
    height: int = 220,
    text_scale: float = 0.8,
    thickness: int = 1,
    paper_value: int = 245,
    ink_value: int = 20,
    n_lines: int = 5,
) -> np.ndarray:
    """
    Build a synthetic "document crop": a plain paper-colored background
    with several lines of dark, thin, text-like strokes, similar in
    spirit to a real invoice crop (mostly blank margin, sparse dark ink).
    """
    img = np.full((height, width), paper_value, dtype=np.uint8)
    for i in range(n_lines):
        y = 30 + i * (height - 60) // max(1, n_lines - 1)
        cv2.putText(
            img, "Rice Sona Masoori 60.00", (15, y),
            cv2.FONT_HERSHEY_SIMPLEX, text_scale, ink_value, thickness, cv2.LINE_AA,
        )
    return img


def _blank_paper(width: int = 300, height: int = 220, value: int = 245) -> np.ndarray:
    return np.full((height, width), value, dtype=np.uint8)


def _add_speckle_noise(gray: np.ndarray, sigma: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, gray.shape)
    noisy = gray.astype(np.float64) + noise
    return np.clip(noisy, 0, 255).astype(np.uint8)


def _with_margin(inner: np.ndarray, margin_px: int, margin_value: int = 245) -> np.ndarray:
    """
    Pad `inner` with a solid border, simulating a visible background
    margin. `margin_value` defaults to a paper-bright value (not a
    mid-tone) so Otsu's ink/paper split classifies the margin as
    background rather than accidentally lumping it in with the ink.
    """
    return cv2.copyMakeBorder(
        inner, margin_px, margin_px, margin_px, margin_px,
        cv2.BORDER_CONSTANT, value=margin_value,
    )


def _sparse_ink_crop(
    width: int = 300,
    height: int = 220,
    paper_value: int = 200,
    ink_value: int = 30,
    n_lines: int = 3,
) -> np.ndarray:
    """
    Build a crop with a LOW global std (mostly blank bright paper, a
    small amount of sharply dark ink, no anti-aliasing) that still has a
    large ink-vs-paper intensity gap — i.e. the exact shape of the
    baseline's invoice_03 complaint (bright paper ~195-208, global std
    ~20-29, but clearly legible dark ink). `cv2.LINE_8` (no
    anti-aliasing) keeps every pixel at exactly `paper_value` or
    `ink_value`, so the resulting global std is easy to reason about.
    """
    img = np.full((height, width), paper_value, dtype=np.uint8)
    for i in range(n_lines):
        y = height // (n_lines + 1) * (i + 1)
        cv2.line(img, (20, y), (width - 20, y), ink_value, thickness=1, lineType=cv2.LINE_8)
    return img


def _rotated_document(
    width: int = 300,
    height: int = 220,
    angle_deg: float = 10.0,
    canvas_size: int = 400,
    background_value: int = 30,
    paper_value: int = 235,
) -> np.ndarray:
    """
    Build a synthetic photo of a rotated rectangular document: a bright
    axis-unaligned rectangle on a uniform dark background, so
    `_find_document_contour` finds a genuine quadrilateral contour whose
    `cv2.minAreaRect` angle is a real, non-zero value (rather than a
    contrived shape). Used to isolate the "boundary detected but angle
    discarded" path deterministically via a config with a very low
    `max_correction_angle_deg`.
    """
    canvas = np.full((canvas_size, canvas_size), background_value, dtype=np.uint8)
    center = (canvas_size / 2.0, canvas_size / 2.0)
    rect = (center, (float(width), float(height)), angle_deg)
    box = cv2.boxPoints(rect)
    cv2.fillConvexPoly(canvas, box.astype(np.int32), paper_value)
    return canvas


def _fills_frame_image(
    width: int = 300,
    height: int = 220,
    ink_value: int = 40,
    gap_value: int = 220,
    gap_margin_x: int = 120,
    gap_margin_y: int = 90,
) -> np.ndarray:
    """
    Build a synthetic crop whose content runs edge-to-edge on all four
    sides: a dark, ink-like fill covering the whole frame (including the
    border) with a single small, bright gap well inside — deliberately
    kept under `min_document_area_fraction` of the frame so
    `_find_document_contour` does not mistake the gap's edge for a
    document boundary. This is the "fills_frame" shape: no background
    margin exists anywhere on the border for a boundary to be found in.
    """
    img = np.full((height, width), ink_value, dtype=np.uint8)
    img[gap_margin_y:height - gap_margin_y, gap_margin_x:width - gap_margin_x] = gap_value
    return img


# ---------------------------------------------------------------------------
# 1. low_resolution
# ---------------------------------------------------------------------------


class TestLowResolution:
    def test_small_but_sharp_text_crop_is_not_flagged(self, tmp_path):
        """
        A small (below the old 800px full-page floor) but sharp,
        legible-stroke crop — representative of this project's real
        individual crops (243-453px wide) — should NOT be flagged
        low_resolution purely for being small.
        """
        gray = _text_crop(width=300, height=220)
        path = tmp_path / "small_sharp.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert "low_resolution" not in result.warnings

    def test_tiny_crop_below_ocr_floor_is_flagged(self, tmp_path):
        """A crop smaller than `min_dimension_for_ocr_px` on its longer
        side cannot plausibly hold legible text and should be flagged
        regardless of sharpness."""
        gray = _text_crop(width=90, height=70, text_scale=0.3)
        path = tmp_path / "tiny.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert max(result.width, result.height) < CONFIG.quality.min_dimension_for_ocr_px
        assert "low_resolution" in result.warnings

    def test_heavily_blurred_crop_is_flagged_via_stroke_width(self, tmp_path):
        """A crop above the size floor but so blurred that strokes have
        bloomed together should be flagged via the stroke-width signal."""
        gray = _text_crop(width=300, height=220)
        blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=6.0)
        path = tmp_path / "blurred.png"
        _write_bgr(path, blurred)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert max(result.width, result.height) >= CONFIG.quality.min_dimension_for_ocr_px
        assert result.stroke_width_px is not None
        assert result.stroke_width_px > CONFIG.quality.max_stroke_width_px
        assert "low_resolution" in result.warnings

    def test_frame_spanning_dark_border_does_not_inflate_stroke_width(self, tmp_path):
        """
        Regression test for a real finding on the sample set: a crop
        photographed inside a dark notebook/binder cover has a dark ring
        running the full width and height of the frame, which Otsu
        thresholding classifies as ink. That structural ring must be
        excluded from the stroke-width estimate — otherwise a document
        with genuinely thin, normal pen strokes gets a wildly inflated
        estimate (15-17px was observed on real samples) purely because of
        the frame-spanning border, not the actual handwriting.
        """
        gray = _text_crop(width=380, height=372, paper_value=235, ink_value=30, thickness=1)
        border_thickness = 12
        cv2.rectangle(
            gray, (0, 0), (gray.shape[1] - 1, gray.shape[0] - 1),
            60, thickness=border_thickness,
        )
        path = tmp_path / "notebook_cover_border.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.stroke_width_px is not None
        # The genuine text strokes are thin; the estimate must reflect
        # that, not the thick structural border.
        assert result.stroke_width_px <= CONFIG.quality.max_stroke_width_px

    def test_blank_crop_skips_stroke_width_signal_gracefully(self, tmp_path):
        """A near-blank crop has no foreground to measure stroke width
        from; this must not raise and must not fabricate a warning from
        the stroke-width signal (only the size floor can still apply)."""
        gray = _blank_paper(width=300, height=220)
        path = tmp_path / "blank.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.stroke_width_px is None


# ---------------------------------------------------------------------------
# 2. high_noise
# ---------------------------------------------------------------------------


class TestNoiseEstimation:
    def test_sharp_clean_text_crop_is_not_flagged_high_noise(self, tmp_path):
        """
        A sharp, clean synthetic text crop should not be flagged as
        noisy. This is the direct regression test for the baseline
        finding that the old whole-image residual metric fired on
        145/156 real crops because it was measuring text-edge detail,
        not grain (it correlated with blur_score at r=0.956).
        """
        gray = _text_crop(width=300, height=220)
        path = tmp_path / "clean_text.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert "high_noise" not in result.warnings

    def test_genuinely_grainy_background_is_flagged_high_noise(self, tmp_path):
        """Real speckle/grain added to the paper background (not the
        text) should still be detected as noise."""
        gray = _text_crop(width=300, height=220)
        noisy = _add_speckle_noise(gray, sigma=25.0)
        path = tmp_path / "grainy.png"
        _write_bgr(path, noisy)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.noise_level is not None
        assert "high_noise" in result.warnings

    def test_noise_metric_excludes_text_edges_not_just_lowers_value(self, tmp_path):
        """
        Directly check the mechanism, not just the warning: measuring
        noise on a clean text crop via the OLD whole-image approach
        would give a much higher value than the new background-only
        approach, because the old approach counts text edges as noise.
        """
        gray = _text_crop(width=300, height=220)
        foreground_mask, foreground_fraction = _ink_foreground_mask(gray)
        assert foreground_fraction > 0.0  # sanity: text was actually detected as foreground

        new_noise = _compute_noise_level(gray, foreground_mask, CONFIG)

        median_filtered = cv2.medianBlur(gray, ksize=3)
        old_style_whole_image_noise = float(
            (gray.astype(np.int16) - median_filtered.astype(np.int16)).std()
        )

        assert new_noise is not None
        assert new_noise < old_style_whole_image_noise

    def test_text_dense_crop_with_little_background_returns_none(self, tmp_path):
        """If excluding foreground leaves too little background to
        measure, the metric should report None rather than guess."""
        # Fill almost the whole frame with "ink" (foreground), leaving
        # only a thin margin as background.
        height, width = 220, 300
        gray = np.full((height, width), 20, dtype=np.uint8)
        gray[:6, :] = 245
        gray[-6:, :] = 245
        gray[:, :6] = 245
        gray[:, -6:] = 245

        foreground_mask, foreground_fraction = _ink_foreground_mask(gray)
        noise = _compute_noise_level(gray, foreground_mask, CONFIG)

        assert foreground_fraction > 0.9
        assert noise is None


# ---------------------------------------------------------------------------
# 3. document_boundary semantics
# ---------------------------------------------------------------------------


class TestDocumentBoundarySemantics:
    def test_crop_filling_the_frame_is_not_warned(self, tmp_path):
        """
        A crop whose content runs edge-to-edge (typical of this
        project's real individual crops, which are tightly cropped to
        the document) has no background margin for a boundary to appear
        in. Missing a contour there must be classified "fills_frame" and
        must NOT raise document_boundary_not_found.
        """
        gray = _fills_frame_image()
        path = tmp_path / "fills_frame.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.document_boundary_status == "fills_frame"
        assert "document_boundary_not_found" not in result.warnings

    def test_crop_with_real_margin_and_no_boundary_is_warned(self, tmp_path):
        """
        A crop with a genuine, uniform background margin on its border,
        where contour detection still fails to find a boundary (forced
        here via an unreachable area-fraction threshold), should be
        classified "not_found" and SHOULD raise the warning — that is a
        real detection gap, not an expected consequence of the crop
        having no margin.
        """
        inner = _text_crop(width=200, height=140)
        gray = _with_margin(inner, margin_px=40)
        path = tmp_path / "has_margin.png"
        _write_bgr(path, gray)

        impossible_config = dataclasses.replace(
            CONFIG,
            quality=dataclasses.replace(CONFIG.quality, min_document_area_fraction=2.0),
        )
        result = analyze_image_quality(path, config=impossible_config)

        assert result.success
        assert result.document_boundary_status == "not_found"
        assert "document_boundary_not_found" in result.warnings

    def test_detected_boundary_is_classified_detected(self, tmp_path):
        """A crop with a clean quadrilateral boundary against a
        contrasting background should classify as "detected"."""
        inner = np.full((160, 220), 235, dtype=np.uint8)
        gray = _with_margin(inner, margin_px=30, margin_value=40)
        path = tmp_path / "clean_boundary.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.document_boundary_status == "detected"
        assert result.document_detected is True

    def test_classify_function_directly_on_synthetic_masks(self):
        """Unit-level check of `_classify_document_boundary` independent
        of contour detection, to pin down the ring-based decision rule
        itself."""
        # Border almost entirely background -> not_found (no contour).
        mask_with_margin = np.zeros((100, 100), dtype=bool)
        mask_with_margin[20:80, 20:80] = True  # ink block well inside the frame
        status = _classify_document_boundary(None, mask_with_margin, CONFIG)
        assert status == "not_found"

        # Border almost entirely ink -> fills_frame.
        mask_fills_frame = np.ones((100, 100), dtype=bool)
        mask_fills_frame[40:60, 40:60] = False  # small gap in the middle, irrelevant
        status = _classify_document_boundary(None, mask_fills_frame, CONFIG)
        assert status == "fills_frame"

        # A contour was found -> detected, regardless of the mask.
        fake_contour = np.array([[[0, 0]], [[10, 0]], [[10, 10]], [[0, 10]]])
        status = _classify_document_boundary(fake_contour, mask_fills_frame, CONFIG)
        assert status == "detected"


# ---------------------------------------------------------------------------
# 4. low_contrast (ink-vs-paper contrast, not global std)
# ---------------------------------------------------------------------------


class TestInkPaperContrast:
    def test_sparse_dark_ink_on_bright_paper_is_not_flagged(self, tmp_path):
        """
        Direct regression test for the baseline finding: all 16
        invoice_03 crops (bright paper ~195-208, global std ~20-29) were
        flagged low_contrast despite being legible, dark-ink-on-white
        documents. A synthetic crop with the same shape — bright paper,
        thin dark text, mostly blank margin — should NOT be flagged now.
        """
        gray = _sparse_ink_crop(width=300, height=220, paper_value=200, ink_value=30)
        path = tmp_path / "sparse_ink.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        # Confirm this crop really does look like the baseline complaint:
        # bright paper with a low GLOBAL std, to prove the new metric is
        # doing something different from the old one on the same image.
        assert result.brightness > 150
        assert result.contrast < CONFIG.quality.low_contrast_std_threshold
        assert "low_contrast" not in result.warnings
        assert result.ink_paper_contrast is not None
        assert result.ink_paper_contrast >= CONFIG.quality.min_ink_paper_contrast

    def test_washed_out_faint_ink_is_flagged(self, tmp_path):
        """Ink that is only faintly darker than its paper (e.g. worn
        pencil, a badly faded printout) should still be flagged: the
        fix targets the METRIC, not the ability to detect genuine low
        contrast."""
        gray = _text_crop(width=300, height=220, paper_value=200, ink_value=175, thickness=1)
        path = tmp_path / "faint_ink.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.ink_paper_contrast is not None
        assert result.ink_paper_contrast < CONFIG.quality.min_ink_paper_contrast
        assert "low_contrast" in result.warnings

    def test_blank_page_skips_contrast_check_rather_than_guessing(self, tmp_path):
        """A near-blank page has no foreground to compute a meaningful
        ink-vs-paper gap from; the check must be skipped (None), not
        guessed, and must not raise low_contrast."""
        gray = _blank_paper(width=300, height=220)
        path = tmp_path / "blank_page.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.ink_paper_contrast is None
        assert "low_contrast" not in result.warnings

    def test_compute_ink_paper_contrast_matches_expected_gap(self):
        """Unit-level check with an exact, known ink/paper split."""
        gray = np.full((100, 100), 200, dtype=np.uint8)
        gray[40:60, 40:60] = 20  # a solid ink block, unambiguous under Otsu
        mask, fraction = _ink_foreground_mask(gray)

        contrast = _compute_ink_paper_contrast(gray, mask, fraction, CONFIG)

        assert contrast is not None
        assert contrast == pytest.approx(180.0, abs=2.0)

    def test_global_std_field_is_still_reported_unchanged(self, tmp_path):
        """The old global-std metric must still be reported (as `contrast`)
        for backward compatibility / raw-statistic purposes — only the
        WARNING derivation changed, not the field itself."""
        gray = _text_crop(width=300, height=220, paper_value=200, ink_value=30)
        path = tmp_path / "reported_contrast.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        expected_std = float(gray.std())
        assert result.contrast == pytest.approx(expected_std, abs=0.5)


# ---------------------------------------------------------------------------
# 5. skew: unchanged estimation, corrected warning scoping
# ---------------------------------------------------------------------------


class TestSkewWarningScoping:
    def test_no_boundary_crop_gets_no_skew_and_no_redundant_warning(self, tmp_path):
        """
        A crop that fills the frame (no boundary to measure skew from at
        all) should report skew_angle=None WITHOUT also raising
        "skew_not_estimable" — that would be a redundant second warning
        for the same underlying fact already covered by
        document_boundary_not_found (which itself is correctly absent
        here, since fills_frame is not a detection failure).
        """
        gray = _fills_frame_image()
        path = tmp_path / "no_boundary.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.document_boundary_status == "fills_frame"
        assert result.skew_angle is None
        assert "skew_not_estimable" not in result.warnings
        assert "document_boundary_not_found" not in result.warnings

    def test_boundary_found_but_angle_discarded_still_warns(self, tmp_path):
        """
        When a boundary IS found (document_boundary_status == "detected")
        but the angle itself could not be trusted/estimated, the
        "skew_not_estimable" warning must still fire — that is the one
        case it is meant to cover post-fix.
        """
        # A genuinely rotated rectangular "document" against a plain dark
        # background gives a real quadrilateral contour with a real,
        # non-zero minAreaRect angle. Capping max_correction_angle_deg
        # below that angle forces the angle to be discarded as unreliable
        # while the boundary itself is still cleanly "detected".
        gray = _rotated_document(width=300, height=220, angle_deg=15.0)
        path = tmp_path / "discarded_angle.png"
        _write_bgr(path, gray)

        low_max_angle_config = dataclasses.replace(
            CONFIG,
            skew=dataclasses.replace(CONFIG.skew, max_correction_angle_deg=5.0),
        )
        result = analyze_image_quality(path, config=low_max_angle_config)

        assert result.success
        assert result.document_boundary_status == "detected"
        assert result.skew_angle is None
        assert "skew_not_estimable" in result.warnings

    def test_straight_detected_boundary_reports_zero_not_none(self, tmp_path):
        """A cleanly detected, essentially unrotated boundary should
        report skew_angle == 0.0 (not None), matching the pre-existing
        `_estimate_skew` behavior, which this change does not touch."""
        inner = np.full((160, 220), 235, dtype=np.uint8)
        gray = _with_margin(inner, margin_px=30, margin_value=40)
        path = tmp_path / "straight.png"
        _write_bgr(path, gray)

        result = analyze_image_quality(path, config=CONFIG)

        assert result.success
        assert result.document_boundary_status == "detected"
        assert result.skew_angle == pytest.approx(0.0, abs=0.01)
        assert "skew_not_estimable" not in result.warnings


# ---------------------------------------------------------------------------
# Cross-cutting: never modifies the input file
# ---------------------------------------------------------------------------


class TestReadOnlyBehavior:
    def test_analysis_does_not_modify_the_image_file(self, tmp_path):
        """Quality analysis must be read-only: running it must not change
        the file's bytes on disk."""
        gray = _text_crop(width=300, height=220)
        path = tmp_path / "untouched.png"
        _write_bgr(path, gray)
        before = path.read_bytes()

        analyze_image_quality(path, config=CONFIG)

        after = path.read_bytes()
        assert before == after
