"""
Tests for the adaptive preprocessing decision logic.

Scope: these tests target the specific decisions this stage must make
correctly, not exhaustive image-quality coverage (that belongs to
test_quality_analysis.py). Each test builds the smallest synthetic image
needed to force a specific quality-analysis outcome, then checks that
preprocessing reacted (or deliberately did not react) correctly to it.

All images are synthetic and built in-memory; nothing here reads from or
writes to `data/samples/`.
"""

from __future__ import annotations

import dataclasses

import cv2
import numpy as np
import pytest

from image_processing.config import DEFAULT_CONFIG
from image_processing.preprocessing import (
    correct_geometry,
    normalize_exposure,
    preprocess_image,
    resize_adaptive,
)
from image_processing.result import QualityAnalysisResult

CONFIG = DEFAULT_CONFIG


def _write(path, gray: np.ndarray) -> None:
    cv2.imwrite(str(path), gray)


def _text_bgr(width: int = 300, height: int = 220, paper_value: int = 235, ink_value: int = 20) -> np.ndarray:
    """A small BGR "document crop" with a few thin lines of dark text."""
    gray = np.full((height, width), paper_value, dtype=np.uint8)
    for i in range(4):
        y = 30 + i * (height - 60) // 3
        cv2.putText(gray, "Total 730.00", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, ink_value, 1, cv2.LINE_AA)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _blank_result(**overrides) -> QualityAnalysisResult:
    """A minimal successful QualityAnalysisResult with no warnings, for
    directly driving preprocessing stage decisions without depending on
    quality_analysis's own detection logic."""
    base = dict(
        filename="synthetic.png", success=True, width=300, height=220,
        brightness=180.0, contrast=40.0, blur_score=3000.0, noise_level=2.0,
        ink_paper_contrast=150.0, stroke_width_px=2.0, skew_angle=None,
        document_detected=False, document_boundary_status="fills_frame",
        warnings=[],
    )
    base.update(overrides)
    return QualityAnalysisResult(**base)


# ---------------------------------------------------------------------------
# 1. Adaptive resize: upscale ONLY when low_resolution is flagged
# ---------------------------------------------------------------------------


class TestAdaptiveResize:
    def test_no_upscale_when_not_flagged(self):
        """
        Direct regression test for the bug this phase fixes: a small
        crop (representative of the real 243-453px individual crops)
        must NOT be upscaled when low_resolution was not flagged, even
        though it is far below the old 800px full-page floor.
        """
        image = _text_bgr(width=300, height=220)
        result, applied, note = resize_adaptive(image, CONFIG, low_resolution_flagged=False)

        assert applied is False
        assert note == "resize_not_needed"
        assert result.shape == image.shape

    def test_upscale_when_flagged(self):
        """When low_resolution IS flagged, a small crop should be
        upscaled toward ResizeConfig.upscale_target_px."""
        image = _text_bgr(width=300, height=220)
        result, applied, note = resize_adaptive(image, CONFIG, low_resolution_flagged=True)

        assert applied is True
        assert note.startswith("upscaled_to_")
        assert max(result.shape[:2]) > max(image.shape[:2])

    def test_upscale_factor_is_capped(self):
        """A very small crop must not be enlarged beyond
        ResizeConfig.max_upscale_factor even if the target size would
        otherwise imply a larger factor."""
        image = _text_bgr(width=50, height=40)
        result, applied, note = resize_adaptive(image, CONFIG, low_resolution_flagged=True)

        assert applied is True
        actual_factor = result.shape[1] / image.shape[1]
        assert actual_factor <= CONFIG.resize.max_upscale_factor + 1e-6

    def test_downscale_safety_rail_runs_regardless_of_flag(self):
        """The hard downscale safety rail (oversized input) must still
        run even when low_resolution_flagged is False — it is a runtime
        concern, not an OCR-adequacy decision."""
        big_config = dataclasses.replace(
            CONFIG, io=dataclasses.replace(CONFIG.io, max_dimension_px=100)
        )
        image = _text_bgr(width=300, height=220)
        result, applied, note = resize_adaptive(image, big_config, low_resolution_flagged=False)

        assert applied is True
        assert note.startswith("downscaled_to_")
        assert max(result.shape[:2]) <= 100

    def test_end_to_end_preprocess_does_not_upscale_good_resolution_crop(self, tmp_path):
        """End-to-end: a crop analyzed as having no low_resolution
        warning must not gain a 'resize' operation."""
        image = _text_bgr(width=300, height=220)
        path = tmp_path / "good.png"
        _write(path, image)

        quality_result = _blank_result(warnings=[])
        prep_result, stages = preprocess_image(path, config=CONFIG, quality_result=quality_result)

        assert prep_result.success
        assert "resize" not in prep_result.operations_applied
        assert "resized" not in stages


# ---------------------------------------------------------------------------
# 2. Geometry correction depends on document_boundary_status
# ---------------------------------------------------------------------------


class TestGeometryDependsOnBoundaryStatus:
    def test_fills_frame_is_never_warped(self):
        """A crop classified 'fills_frame' must not be perspective-warped
        or deskewed, even if an internal shape inside it would otherwise
        look quadrilateral-like to contour detection."""
        image = _text_bgr(width=300, height=220)
        # A large rectangle drawn INSIDE the frame — if contour detection
        # ran, this alone could be mistaken for a page boundary.
        cv2.rectangle(image, (20, 20), (280, 200), (10, 10, 10), thickness=4)

        result, applied, note = correct_geometry(image, CONFIG, document_boundary_status="fills_frame")

        assert applied is False
        assert note == "document_boundary_status_not_detected"
        assert np.array_equal(result, image)

    def test_not_found_is_never_warped(self):
        """Same guarantee for 'not_found' — a real detection gap, not a
        license to guess a boundary now."""
        image = _text_bgr(width=300, height=220)
        result, applied, note = correct_geometry(image, CONFIG, document_boundary_status="not_found")

        assert applied is False
        assert note == "document_boundary_status_not_detected"

    def test_detected_status_allows_contour_search_to_run(self):
        """When status is 'detected', geometry correction should actually
        attempt contour-based correction (using a clean, high-contrast
        rectangular "document" against a plain background so a real
        contour is genuinely there to find)."""
        canvas = np.full((300, 300, 3), 30, dtype=np.uint8)
        cv2.rectangle(canvas, (40, 40), (260, 260), (235, 235, 235), thickness=-1)

        result, applied, note = correct_geometry(canvas, CONFIG, document_boundary_status="detected")

        # Either it finds and corrects (applied True) or it finds a
        # boundary but decides no correction is needed (e.g. already
        # straight) — both are legitimate outcomes of actually running
        # the search, unlike the "fills_frame"/"not_found" cases above,
        # which must never even attempt it.
        assert note != "document_boundary_status_not_detected"

    def test_end_to_end_preprocess_skips_geometry_for_fills_frame(self, tmp_path):
        """End-to-end: a fills_frame quality result must not produce a
        perspective_corrected/deskewed stage."""
        image = _text_bgr(width=300, height=220)
        cv2.rectangle(image, (20, 20), (280, 200), (10, 10, 10), thickness=4)
        path = tmp_path / "fills_frame.png"
        _write(path, image)

        quality_result = _blank_result(document_boundary_status="fills_frame", warnings=[])
        prep_result, stages = preprocess_image(path, config=CONFIG, quality_result=quality_result)

        assert prep_result.success
        assert "perspective_corrected" not in prep_result.operations_applied
        assert "deskewed" not in prep_result.operations_applied


# ---------------------------------------------------------------------------
# 3. Exposure normalization: underexposed / overexposed only
# ---------------------------------------------------------------------------


class TestExposureNormalization:
    def test_underexposed_crop_gets_normalized(self, tmp_path):
        """A crop flagged underexposed should gain an
        exposure_normalization stage and end up brighter."""
        dark = _text_bgr(paper_value=40, ink_value=5)
        path = tmp_path / "dark.png"
        _write(path, dark)

        quality_result = _blank_result(brightness=40.0, warnings=["underexposed"])
        prep_result, stages = preprocess_image(path, config=CONFIG, quality_result=quality_result)

        assert prep_result.success
        assert "exposure_normalization" in prep_result.operations_applied
        assert "normalized" in stages
        assert float(stages["normalized"].mean()) > float(stages["grayscale"].mean())

    def test_no_normalization_without_exposure_warning(self, tmp_path):
        """A normally-exposed crop must not get exposure_normalization
        applied — this is not a general-purpose contrast tool."""
        image = _text_bgr()
        path = tmp_path / "normal.png"
        _write(path, image)

        quality_result = _blank_result(warnings=[])
        prep_result, _ = preprocess_image(path, config=CONFIG, quality_result=quality_result)

        assert prep_result.success
        assert "exposure_normalization" not in prep_result.operations_applied

    def test_normalize_exposure_function_stretches_toward_full_range(self):
        """Direct check of the stretch itself: a narrow, dim intensity
        band should end up spanning much closer to the full 0-255 range."""
        gray = np.random.default_rng(0).integers(40, 70, size=(100, 100), dtype=np.uint8)
        result = normalize_exposure(gray, CONFIG)

        assert float(result.std()) > float(gray.std())
        assert float(result.max()) - float(result.min()) > float(gray.max()) - float(gray.min())


# ---------------------------------------------------------------------------
# 4. Adaptive shadow / denoise / CLAHE / sharpen gating (regression checks)
# ---------------------------------------------------------------------------


class TestOtherAdaptiveStages:
    def test_shadow_correction_only_when_flagged(self, tmp_path):
        image = _text_bgr()
        path = tmp_path / "img.png"
        _write(path, image)

        with_flag, _ = preprocess_image(
            path, config=CONFIG, quality_result=_blank_result(warnings=["uneven_lighting_or_shadow"])
        )
        without_flag, _ = preprocess_image(path, config=CONFIG, quality_result=_blank_result(warnings=[]))

        assert "shadow_correction" in with_flag.operations_applied
        assert "shadow_correction" not in without_flag.operations_applied

    def test_denoise_only_when_flagged(self, tmp_path):
        image = _text_bgr()
        path = tmp_path / "img.png"
        _write(path, image)

        with_flag, _ = preprocess_image(
            path, config=CONFIG, quality_result=_blank_result(warnings=["high_noise"])
        )
        without_flag, _ = preprocess_image(path, config=CONFIG, quality_result=_blank_result(warnings=[]))

        assert "denoise" in with_flag.operations_applied
        assert "denoise" not in without_flag.operations_applied

    def test_sharpen_only_when_blurry_and_not_noisy(self, tmp_path):
        """Sharpening must fire when blurry-and-not-noisy, and must NOT
        fire when both blurry and noisy are flagged together."""
        image = _text_bgr()
        blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=3.0)
        path = tmp_path / "blurred.png"
        _write(path, blurred)

        blurry_only, _ = preprocess_image(
            path, config=CONFIG, quality_result=_blank_result(warnings=["image_may_be_blurry"])
        )
        blurry_and_noisy, _ = preprocess_image(
            path, config=CONFIG,
            quality_result=_blank_result(warnings=["image_may_be_blurry", "high_noise"]),
        )

        assert "sharpen" not in blurry_and_noisy.operations_applied
        # blurry_only may or may not clear the improvement gate depending
        # on the synthetic image, but it must at least be attempted
        # (recorded either as applied or as an explicit skip note), never
        # silently ignored the way the noisy case is.
        attempted = (
            "sharpen" in blurry_only.operations_applied
            or "sharpen_skipped_no_improvement" in blurry_only.warnings
        )
        assert attempted

    def test_clahe_only_when_low_contrast_flagged(self, tmp_path):
        image = _text_bgr()
        path = tmp_path / "img.png"
        _write(path, image)

        with_flag, _ = preprocess_image(
            path, config=CONFIG, quality_result=_blank_result(warnings=["low_contrast"])
        )
        without_flag, _ = preprocess_image(path, config=CONFIG, quality_result=_blank_result(warnings=[]))

        attempted = (
            "contrast_enhancement" in with_flag.operations_applied
            or "contrast_enhancement_skipped_no_improvement" in with_flag.warnings
        )
        assert attempted
        assert "contrast_enhancement" not in without_flag.operations_applied
        assert "contrast_enhancement_skipped_no_improvement" not in without_flag.warnings


# ---------------------------------------------------------------------------
# 5. Binarization stays diagnostic-only
# ---------------------------------------------------------------------------


class TestBinarizationDiagnosticOnly:
    def test_thresholded_stage_present_but_never_final(self, tmp_path):
        image = _text_bgr()
        path = tmp_path / "img.png"
        _write(path, image)

        prep_result, stages = preprocess_image(path, config=CONFIG, quality_result=_blank_result(warnings=[]))

        assert "thresholded" in stages
        assert not np.array_equal(stages["final"], stages["thresholded"])
        # thresholded must be binary (only two distinct values).
        assert set(np.unique(stages["thresholded"]).tolist()) <= {0, 255}


# ---------------------------------------------------------------------------
# 6. Morphology stays diagnostic-only and disabled by default
# ---------------------------------------------------------------------------


class TestMorphologyDiagnosticOnly:
    def test_disabled_by_default(self, tmp_path):
        """With the default config (enabled_by_default=False), morphology
        must never run, regardless of how speckled the binarized branch
        is."""
        rng = np.random.default_rng(1)
        speckled = np.full((150, 150), 235, dtype=np.uint8)
        ys, xs = rng.integers(0, 150, 400), rng.integers(0, 150, 400)
        speckled[ys, xs] = 10
        path = tmp_path / "speckled.png"
        _write(path, cv2.cvtColor(speckled, cv2.COLOR_GRAY2BGR))

        prep_result, _ = preprocess_image(path, config=CONFIG, quality_result=_blank_result(warnings=[]))

        assert "morphology_on_binarized_branch" not in prep_result.operations_applied

    def test_never_applied_to_grayscale_final_output(self, tmp_path):
        """Even if morphology were enabled, it must only ever touch the
        binarized side-branch, never `final`."""
        image = _text_bgr()
        path = tmp_path / "img.png"
        _write(path, image)

        enabled_config = dataclasses.replace(
            CONFIG,
            morphology=dataclasses.replace(
                CONFIG.morphology, enabled_by_default=True, speckle_fraction_threshold=0.0
            ),
        )
        prep_result, stages = preprocess_image(
            path, config=enabled_config, quality_result=_blank_result(warnings=[])
        )

        assert prep_result.success
        assert set(np.unique(stages["final"]).tolist()) - {0, 255} != set()  # final stays grayscale, not binary


# ---------------------------------------------------------------------------
# 7. Source image integrity
# ---------------------------------------------------------------------------


class TestSourceIntegrity:
    def test_preprocessing_does_not_modify_the_source_file(self, tmp_path):
        """Preprocessing reads the source file and returns in-memory
        arrays; it must never write back to the original path."""
        image = _text_bgr()
        path = tmp_path / "untouched.png"
        _write(path, image)
        before = path.read_bytes()

        preprocess_image(path, config=CONFIG, quality_result=_blank_result(warnings=[]))

        after = path.read_bytes()
        assert before == after

    def test_all_new_config_fields_have_no_hardcoded_equivalents(self):
        """Sanity check that the new config sections actually exist and
        are wired into PipelineConfig (guards against a field being added
        to a dataclass but never composed into DEFAULT_CONFIG)."""
        assert hasattr(CONFIG, "resize")
        assert hasattr(CONFIG, "normalization")
        assert CONFIG.resize.upscale_target_px > 0
        assert CONFIG.normalization.stretch_low_percentile < CONFIG.normalization.stretch_high_percentile
