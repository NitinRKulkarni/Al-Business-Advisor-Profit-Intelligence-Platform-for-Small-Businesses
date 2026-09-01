"""
Tests for the receipt-pipeline handoff wrapper
(`image_processing/receipt_pipeline.py`).

Scope: only the two things this module adds beyond `preprocess_image()` --
writing the final image to an isolated output directory and shaping the
handoff dict. The underlying preprocessing logic is already covered by
`tests/test_preprocessing.py` and is not re-tested here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from image_processing.receipt_pipeline import process_receipt_images


def _make_receipt_image(path: Path, size=(300, 400)) -> None:
    img = Image.new("L", size, color=250)
    arr = np.array(img)
    arr[20:24, 20:200] = 20  # a dark line, so it's not a blank frame
    Image.fromarray(arr).convert("RGB").save(path)


class TestProcessReceiptImages:
    def test_writes_processed_image_and_returns_expected_keys(self, tmp_path: Path):
        src = tmp_path / "receipt.png"
        _make_receipt_image(src)
        out_dir = tmp_path / "out"

        [record] = process_receipt_images([src], out_dir)

        assert record["processing_success"] is True
        assert record["processed_image_path"] is not None
        assert Path(record["processed_image_path"]).is_file()
        assert set(record) == {
            "input_path", "processed_image_path", "processing_success",
            "operations_applied", "warnings", "original_dimensions",
            "final_dimensions", "processing_time", "error",
        }

    def test_does_not_modify_or_move_the_source_image(self, tmp_path: Path):
        src = tmp_path / "receipt.png"
        _make_receipt_image(src)
        original_bytes = src.read_bytes()

        process_receipt_images([src], tmp_path / "out")

        assert src.read_bytes() == original_bytes
        assert src.is_file()

    def test_output_directory_is_created_if_missing(self, tmp_path: Path):
        src = tmp_path / "receipt.png"
        _make_receipt_image(src)
        out_dir = tmp_path / "does" / "not" / "exist"

        process_receipt_images([src], out_dir)

        assert out_dir.is_dir()

    def test_multiple_images_return_one_record_each_in_order(self, tmp_path: Path):
        src1 = tmp_path / "a.png"
        src2 = tmp_path / "b.png"
        _make_receipt_image(src1)
        _make_receipt_image(src2, size=(320, 420))

        records = process_receipt_images([src1, src2], tmp_path / "out")

        assert [r["input_path"] for r in records] == [str(src1), str(src2)]

    def test_missing_input_image_reports_failure_without_raising(self, tmp_path: Path):
        [record] = process_receipt_images([tmp_path / "missing.png"], tmp_path / "out")

        assert record["processing_success"] is False
        assert record["processed_image_path"] is None
        assert record["error"] is not None
