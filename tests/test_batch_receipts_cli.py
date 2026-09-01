"""
Focused tests for `scripts/batch_receipts_cli.py`.

Scope: the batch CLI's own responsibilities -- argument handling, image
collection/de-duplication, engine selection, and per-image isolation. The
pipeline itself is already covered elsewhere and is faked here so these
tests stay deterministic (no real OCR, no model download, no network).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import batch_receipts_cli as cli  # noqa: E402


def _write_image(path: Path) -> None:
    arr = np.full((120, 200), 240, dtype=np.uint8)
    arr[40:44, 20:180] = 40
    Image.fromarray(arr, mode="L").save(path)


class _FakeResult:
    """Minimal stand-in for ExtractionResult, enough for the CLI's use."""

    class _Receipt:
        def __init__(self, total):
            self.total = total

    def __init__(self, source: str, success: bool = True, total: float | None = 100.0):
        self.source = source
        self.success = success
        self.needs_review = False
        self.receipt = self._Receipt(total)

    def to_dict(self) -> dict:
        return {
            "source": self.source, "success": self.success, "total": self.receipt.total,
            "subtotal": None, "tax": None, "discount": None, "items": [],
            "needs_review": self.needs_review, "overall_confidence": 80.0,
        }

    def to_grouped_dict(self) -> dict:
        return {"source": self.source, "financials": {"total": self.receipt.total}}


class TestImageCollection:
    def test_directory_images_are_collected_in_sorted_order(self, tmp_path: Path):
        for name in ("c.png", "a.png", "b.jpg"):
            _write_image(tmp_path / name)

        images, problems = cli.collect_images([], str(tmp_path))

        assert [p.name for p in images] == ["a.png", "b.jpg", "c.png"]
        assert problems == []

    def test_unsupported_and_missing_files_are_reported_not_raised(self, tmp_path: Path):
        good = tmp_path / "ok.png"
        _write_image(good)
        bad = tmp_path / "notes.txt"
        bad.write_text("not an image")

        images, problems = cli.collect_images(
            [str(good), str(bad), str(tmp_path / "ghost.png")], None,
        )

        assert [p.name for p in images] == ["ok.png"]
        assert any("unsupported file type" in p for p in problems)
        assert any("not found" in p for p in problems)

    def test_duplicate_paths_are_processed_once(self, tmp_path: Path):
        image = tmp_path / "dup.png"
        _write_image(image)

        # Same file supplied explicitly AND via --dir.
        images, _ = cli.collect_images([str(image)], str(tmp_path))

        assert len(images) == 1

    def test_missing_directory_is_reported(self, tmp_path: Path):
        images, problems = cli.collect_images([], str(tmp_path / "nope"))

        assert images == []
        assert any("not a directory" in p for p in problems)

    def test_empty_directory_is_reported(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()

        images, problems = cli.collect_images([], str(empty))

        assert images == []
        assert any("no " in p for p in problems)


class TestArgumentHandling:
    def test_no_arguments_is_rejected(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["batch_receipts_cli.py"])

        assert cli.main() == 1
        assert "provide image paths" in capsys.readouterr().err

    def test_unknown_engine_is_rejected(self, tmp_path: Path, monkeypatch, capsys):
        image = tmp_path / "r.png"
        _write_image(image)
        monkeypatch.setattr(
            sys, "argv",
            ["batch_receipts_cli.py", str(image), "--engines", "tesseract,bogus"],
        )

        assert cli.main() == 1
        assert "unknown engine" in capsys.readouterr().err.lower()

    def test_all_inputs_unusable_exits_nonzero(self, tmp_path: Path, monkeypatch, capsys):
        bad = tmp_path / "x.txt"
        bad.write_text("nope")
        monkeypatch.setattr(sys, "argv", ["batch_receipts_cli.py", str(bad)])

        assert cli.main() == 1
        assert "no usable images" in capsys.readouterr().err


class TestBatchExecution:
    def _patch_pipeline(self, monkeypatch, results, captured: dict):
        def fake_process_receipts(images, output_dir, **kwargs):
            captured["images"] = list(images)
            captured["kwargs"] = kwargs
            return results
        monkeypatch.setattr(cli, "process_receipts", fake_process_receipts)

    def test_multiple_images_are_passed_in_one_call(self, tmp_path: Path, monkeypatch, capsys):
        for name in ("a.png", "b.png"):
            _write_image(tmp_path / name)
        captured: dict = {}
        self._patch_pipeline(
            monkeypatch, [_FakeResult("a.png"), _FakeResult("b.png")], captured,
        )
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "stub")
        monkeypatch.setattr(
            sys, "argv", ["batch_receipts_cli.py", "--dir", str(tmp_path), "--quiet"],
        )

        exit_code = cli.main()

        assert exit_code == 0
        # A single batch call, not one call per image -- engines are
        # expensive to construct and reload.
        assert len(captured["images"]) == 2

    def test_multi_engine_uses_ocr_engines_param(self, tmp_path: Path, monkeypatch, capsys):
        _write_image(tmp_path / "a.png")
        captured: dict = {}
        self._patch_pipeline(monkeypatch, [_FakeResult("a.png")], captured)
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "tess-stub")
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "easyocr", lambda: "easy-stub")
        monkeypatch.setattr(
            sys, "argv",
            ["batch_receipts_cli.py", "--dir", str(tmp_path),
             "--engines", "tesseract,easyocr", "--quiet"],
        )

        cli.main()

        assert captured["kwargs"].get("ocr_engines") == ["tess-stub", "easy-stub"]
        assert "ocr_engine" not in captured["kwargs"]

    def test_one_failed_image_does_not_fail_the_batch(self, tmp_path: Path, monkeypatch, capsys):
        for name in ("a.png", "b.png"):
            _write_image(tmp_path / name)
        captured: dict = {}
        self._patch_pipeline(
            monkeypatch,
            [_FakeResult("a.png", success=False, total=None), _FakeResult("b.png")],
            captured,
        )
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "stub")
        monkeypatch.setattr(
            sys, "argv", ["batch_receipts_cli.py", "--dir", str(tmp_path), "--quiet"],
        )

        exit_code = cli.main()

        # Partial success is still success: each result carries its own status.
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "pipeline succeeded    : 1/2" in out

    def test_every_image_failing_exits_two(self, tmp_path: Path, monkeypatch, capsys):
        _write_image(tmp_path / "a.png")
        captured: dict = {}
        self._patch_pipeline(
            monkeypatch, [_FakeResult("a.png", success=False, total=None)], captured,
        )
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "stub")
        monkeypatch.setattr(
            sys, "argv", ["batch_receipts_cli.py", "--dir", str(tmp_path), "--quiet"],
        )

        assert cli.main() == 2

    def test_json_out_writes_one_entry_per_image(self, tmp_path: Path, monkeypatch, capsys):
        for name in ("a.png", "b.png"):
            _write_image(tmp_path / name)
        out_file = tmp_path / "out" / "results.json"
        captured: dict = {}
        self._patch_pipeline(
            monkeypatch, [_FakeResult("a.png"), _FakeResult("b.png")], captured,
        )
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "stub")
        monkeypatch.setattr(
            sys, "argv",
            ["batch_receipts_cli.py", "--dir", str(tmp_path),
             "--json-out", str(out_file), "--quiet"],
        )

        cli.main()

        import json
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert [entry["source"] for entry in payload] == ["a.png", "b.png"]

    def test_grouped_flag_uses_the_nested_contract(self, tmp_path: Path, monkeypatch, capsys):
        _write_image(tmp_path / "a.png")
        out_file = tmp_path / "grouped.json"
        captured: dict = {}
        self._patch_pipeline(monkeypatch, [_FakeResult("a.png")], captured)
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "stub")
        monkeypatch.setattr(
            sys, "argv",
            ["batch_receipts_cli.py", "--dir", str(tmp_path), "--grouped",
             "--json-out", str(out_file), "--quiet"],
        )

        cli.main()

        import json
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert "financials" in payload[0]

    def test_source_images_are_not_modified(self, tmp_path: Path, monkeypatch, capsys):
        image = tmp_path / "a.png"
        _write_image(image)
        before = image.read_bytes()
        captured: dict = {}
        self._patch_pipeline(monkeypatch, [_FakeResult("a.png")], captured)
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "stub")
        monkeypatch.setattr(
            sys, "argv", ["batch_receipts_cli.py", str(image), "--quiet"],
        )

        cli.main()

        assert image.read_bytes() == before
