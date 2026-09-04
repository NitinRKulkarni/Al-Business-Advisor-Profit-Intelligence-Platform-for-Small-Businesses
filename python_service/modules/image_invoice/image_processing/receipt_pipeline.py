"""
receipt_pipeline
==================

Thin handoff wrapper around the existing `preprocess_image()` pipeline.

Why this module exists
-----------------------
`preprocess_image()` already implements the full adaptive pipeline
(validation via `load_image`, document-boundary-gated perspective
correction/deskew, shadow correction, denoise, exposure normalization,
CLAHE contrast enhancement, adaptive resize, conservative sharpening) and
returns a `PreprocessingResult` plus an in-memory `stages` dict of image
arrays. It does not write the final image to disk and only accepts one
image at a time.

This module adds exactly the two things a downstream OCR/extraction
component needs and that do not already exist:

1. Accepting one or more image paths and writing each `final` stage image
   to disk in an isolated output directory (never touching the source
   images), so the next stage has a real file path to read.
2. Returning a small, stable, JSON-serializable dict per image matching
   the agreed handoff contract, instead of the richer internal
   `PreprocessingResult` + raw NumPy stage arrays.

Nothing in `image_processing/preprocessing.py`, `config.py`, or
`quality_analysis.py` is duplicated or reimplemented here.
"""

from __future__ import annotations

from pathlib import Path

import cv2

from .config import DEFAULT_CONFIG, PipelineConfig
from .preprocessing import preprocess_image

# Handoff contract returned per image. Kept intentionally small and
# generic (plain dict, not a dataclass) so any downstream consumer -
# OCR script, notebook, future service - can read it without importing
# this project's types.
HandoffRecord = dict


def process_receipt_images(
    image_paths: list[str | Path],
    output_dir: str | Path,
    config: PipelineConfig = DEFAULT_CONFIG,
    variant_stages: list[str] | None = None,
) -> list[HandoffRecord]:
    """
    Run the existing preprocessing pipeline over one or more receipt/
    invoice images and write each OCR-ready result to `output_dir`.

    Parameters
    ----------
    image_paths:
        Paths to the source images. Never modified or moved.
    output_dir:
        Directory the processed images are written to. Created if it
        does not exist. Must be separate from the source dataset -
        callers are responsible for pointing this at an isolated
        location (e.g. a `data/output/...` subfolder), not
        `data/samples/`.
    config:
        Pipeline configuration, passed straight through to
        `preprocess_image`.
    variant_stages:
        Optional list of ADDITIONAL preprocessing stage names (e.g.
        `["grayscale", "thresholded"]`) to also write to disk, for
        multi-variant OCR. When given, each record gains a
        `variant_image_paths` key mapping stage name -> written path.

        Left as None by default so the returned record shape is
        byte-identical to the original contract -- existing consumers
        (and the handoff contract documented above) are unaffected. Stage
        names this image does not have are silently skipped, and a stage
        whose pixels are identical to `final` is skipped too, so callers
        never pay for OCR on a duplicate image.

    Returns
    -------
    list[dict]
        One record per input image, in the same order, each shaped as:

            {
                "input_path": str,
                "processed_image_path": str | None,   # None on failure
                "processing_success": bool,
                "operations_applied": list[str],
                "warnings": list[str],
                "original_dimensions": (width, height),
                "final_dimensions": (width, height),
                "processing_time": float,              # seconds
                "error": str | None,
                # only present when `variant_stages` was passed:
                "variant_image_paths": dict[str, str],
            }

        This is the full handoff contract for the next (OCR/extraction)
        component; nothing else should be required to consume it.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[HandoffRecord] = []

    for image_path in image_paths:
        path = Path(image_path)
        result, stages = preprocess_image(path, config=config)

        processed_path: str | None = None
        if result.success and "final" in stages:
            processed_path = str(out_dir / f"{path.stem}_processed.png")
            cv2.imwrite(processed_path, stages["final"])

        record: HandoffRecord = {
            "input_path": str(path),
            "processed_image_path": processed_path,
            "processing_success": result.success,
            "operations_applied": list(result.operations_applied),
            "warnings": list(result.warnings),
            "original_dimensions": (result.original_width, result.original_height),
            "final_dimensions": (result.final_width, result.final_height),
            "processing_time": result.processing_time_seconds,
            "error": result.error,
        }

        if variant_stages is not None:
            variant_paths: dict[str, str] = {}
            if result.success:
                final_image = stages.get("final")
                for stage_name in variant_stages:
                    if stage_name == "final" or stage_name not in stages:
                        continue
                    stage_image = stages[stage_name]
                    # Skip a variant that is pixel-identical to `final`
                    # (e.g. `grayscale` when no enhancement ran): OCR-ing
                    # it would cost time and produce a duplicate vote.
                    if final_image is not None and stage_image.shape == final_image.shape:
                        if not (stage_image != final_image).any():
                            continue
                    variant_path = out_dir / f"{path.stem}_variant_{stage_name}.png"
                    cv2.imwrite(str(variant_path), stage_image)
                    variant_paths[stage_name] = str(variant_path)
            record["variant_image_paths"] = variant_paths

        records.append(record)

    return records
