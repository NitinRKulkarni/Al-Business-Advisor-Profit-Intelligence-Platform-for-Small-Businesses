"""
Focused tests for `scripts/test_receipt_cli.py`.

Scope: only the CLI's own responsibilities (argument handling, path
validation, exit codes) -- the pipeline itself is already covered by
`tests/test_receipt_extraction.py` and is not re-tested here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import test_receipt_cli as cli  # noqa: E402


class TestCliArgumentHandling:
    def test_missing_file_path_is_rejected(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["test_receipt_cli.py", str(tmp_path / "missing.jpg")])

        exit_code = cli.main()

        assert exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_unsupported_extension_is_rejected(self, tmp_path, monkeypatch, capsys):
        bogus = tmp_path / "receipt.txt"
        bogus.write_text("not an image")
        monkeypatch.setattr(sys, "argv", ["test_receipt_cli.py", str(bogus)])

        exit_code = cli.main()

        assert exit_code == 1
        assert "unsupported file type" in capsys.readouterr().err.lower()

    def test_directory_path_is_rejected(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["test_receipt_cli.py", str(tmp_path)])

        exit_code = cli.main()

        assert exit_code == 1
        assert "not a file" in capsys.readouterr().err

    def test_unknown_engine_name_is_rejected(self, tmp_path, monkeypatch, capsys):
        image = tmp_path / "receipt.jpg"
        image.write_bytes(b"fake image bytes")
        monkeypatch.setattr(
            sys, "argv", ["test_receipt_cli.py", str(image), "--engines", "tesseract,not_a_real_engine"]
        )

        exit_code = cli.main()

        err = capsys.readouterr().err
        assert exit_code == 1
        assert "unknown engine" in err.lower()
        assert "not_a_real_engine" in err


class TestCliEngineSelection:
    """Verify --engines wiring picks the right process_receipt call shape,
    without exercising the real (slow) OCR engines."""

    def _fake_result(self):
        class _FakeResult:
            def to_dict(self):
                return {
                    "success": True,
                    "vendor_name": None,
                    "invoice_number": None,
                    "receipt_number": None,
                    "date": None,
                    "subtotal": None,
                    "discount": None,
                    "tax": None,
                    "total": None,
                    "ocr_confidence": None,
                    "extraction_confidence": None,
                    "items": [],
                    "warnings": [],
                    "error": None,
                }

        return _FakeResult()

    def test_single_engine_uses_ocr_engine_param(self, tmp_path, monkeypatch, capsys):
        image = tmp_path / "receipt.jpg"
        image.write_bytes(b"fake image bytes")
        monkeypatch.setattr(sys, "argv", ["test_receipt_cli.py", str(image), "--engines", "tesseract"])
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "tesseract-engine-stub")

        captured = {}

        def fake_process_receipt(path, output_dir, **kwargs):
            captured.update(kwargs)
            return self._fake_result()

        monkeypatch.setattr(cli, "process_receipt", fake_process_receipt)

        exit_code = cli.main()

        assert exit_code == 0
        assert captured.get("ocr_engine") == "tesseract-engine-stub"
        assert "ocr_engines" not in captured

    def test_multi_engine_uses_ocr_engines_param(self, tmp_path, monkeypatch, capsys):
        image = tmp_path / "receipt.jpg"
        image.write_bytes(b"fake image bytes")
        monkeypatch.setattr(
            sys, "argv", ["test_receipt_cli.py", str(image), "--engines", "tesseract,easyocr"]
        )
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "tesseract", lambda: "tesseract-engine-stub")
        monkeypatch.setitem(cli._ENGINE_FACTORIES, "easyocr", lambda: "easyocr-engine-stub")

        captured = {}

        def fake_process_receipt(path, output_dir, **kwargs):
            captured.update(kwargs)
            return self._fake_result()

        monkeypatch.setattr(cli, "process_receipt", fake_process_receipt)

        exit_code = cli.main()

        assert exit_code == 0
        assert captured.get("ocr_engines") == ["tesseract-engine-stub", "easyocr-engine-stub"]
        assert "ocr_engine" not in captured
