"""
tesseract_engine
=================

`OcrEngine` implementation backed by Tesseract via the `pytesseract`
wrapper.

Why Tesseract first
--------------------
It is the cheap baseline: a ~48MB system binary plus a tiny pure-Python
wrapper, no GPU, no ML framework, and no Python-version compatibility risk
(this project's venv runs Python 3.14, where PyTorch — required by
EasyOCR/TrOCR — is still only preview-supported). It also exposes
per-word confidence natively via TSV output, which the evaluation needs.
Its known weakness is exactly this dataset's hard case (handwriting), so
it is wired up to *measure* that weakness, not on the assumption it will
win.

Windows binary discovery
-------------------------
`pytesseract` shells out to a `tesseract` executable and by default expects
it on PATH. The standard Windows installer (UB-Mannheim) installs to
`C:\\Program Files\\Tesseract-OCR\\` but does not always add that to the
PATH of an already-running shell/process. Rather than depend on PATH being
correct, `_resolve_tesseract_cmd()` checks PATH first and then falls back
to the known install locations, so the engine works without requiring the
user to fix their environment or restart their terminal.
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
import time
from pathlib import Path

import pytesseract
from PIL import Image

from .engine import OcrResult, OcrToken

logger = logging.getLogger(__name__)

# Locations the standard Windows Tesseract installers use, checked only if
# `tesseract` is not already resolvable on PATH.
_WINDOWS_FALLBACK_PATHS = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


class TesseractNotAvailableError(RuntimeError):
    """Raised at construction time when no Tesseract binary can be found."""


def _resolve_tesseract_cmd() -> str:
    """
    Return a usable path to the Tesseract executable.

    Checks PATH first (so a properly configured environment or a
    non-standard install location wins), then the known Windows installer
    directories.
    """
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    for candidate in _WINDOWS_FALLBACK_PATHS:
        if candidate.is_file():
            return str(candidate)

    raise TesseractNotAvailableError(
        "Could not find a Tesseract executable. Looked on PATH and in: "
        + ", ".join(str(p) for p in _WINDOWS_FALLBACK_PATHS)
    )


class TesseractOcrEngine:
    """
    Tesseract-backed OCR engine.

    Parameters
    ----------
    language:
        Tesseract language code(s), e.g. "eng". Only the English model is
        installed by default with the standard Windows package.
    psm:
        Tesseract page segmentation mode. 6 ("assume a single uniform
        block of text") is a reasonable default for a cropped invoice: the
        default mode 3 includes automatic orientation/script detection
        that tends to be unhelpful on small single-document crops that
        have already been deskewed by our own preprocessing stage.
    oem:
        OCR engine mode. 3 = "default", which lets Tesseract use its LSTM
        neural engine when available (better on cursive-ish text than the
        legacy character matcher).
    """

    def __init__(self, language: str = "eng", psm: int = 6, oem: int = 3) -> None:
        # Resolved once, at construction: if Tesseract is missing, fail
        # loudly here rather than returning 156 identical failed results.
        self._cmd = _resolve_tesseract_cmd()
        pytesseract.pytesseract.tesseract_cmd = self._cmd

        self.language = language
        self.psm = psm
        self.oem = oem

        try:
            self._version = str(pytesseract.get_tesseract_version()).strip()
        except Exception as exc:  # noqa: BLE001 - surfaced as a setup error
            raise TesseractNotAvailableError(
                f"Found Tesseract at {self._cmd} but could not query its "
                f"version ({exc})"
            ) from exc

        logger.info("Tesseract engine ready: %s (v%s)", self._cmd, self._version)

    @property
    def name(self) -> str:
        return f"tesseract-{self._version}"

    @property
    def config(self) -> str:
        """The Tesseract CLI config string derived from psm/oem."""
        return f"--oem {self.oem} --psm {self.psm}"

    def recognize(self, image_path: str | Path) -> OcrResult:
        """
        Run Tesseract on one image.

        Uses TSV output (`image_to_data`) rather than plain text so that
        per-word confidence comes back alongside the words themselves, and
        reconstructs the text from that same TSV. Reconstructing (rather
        than making a second `image_to_string` call) keeps text and
        confidences guaranteed consistent with each other and halves the
        OCR work per image.
        """
        path = Path(image_path)

        if not path.is_file():
            return OcrResult(
                filename=path.name,
                success=False,
                engine=self.name,
                error=f"File not found: {path}",
            )

        try:
            with Image.open(path) as image:
                image.load()
                start = time.perf_counter()
                tsv = pytesseract.image_to_data(
                    image,
                    lang=self.language,
                    config=self.config,
                )
                elapsed = time.perf_counter() - start
        except Exception as exc:  # noqa: BLE001 - reported as data, per contract
            logger.warning("OCR failed on %s: %s", path.name, exc)
            return OcrResult(
                filename=path.name,
                success=False,
                engine=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        text, confidences, tokens = self._parse_tsv(tsv)
        mean_conf = sum(confidences) / len(confidences) if confidences else None

        return OcrResult(
            filename=path.name,
            success=True,
            engine=self.name,
            text=text,
            mean_confidence=round(mean_conf, 2) if mean_conf is not None else None,
            word_count=len(confidences),
            word_confidences=confidences,
            tokens=tokens,
            processing_time_seconds=round(elapsed, 4),
        )

    @staticmethod
    def _parse_tsv(tsv: str) -> tuple[str, list[float], list[OcrToken]]:
        """
        Turn Tesseract's TSV output into (text, per-word confidences,
        positioned tokens).

        Tesseract emits one row per detected block/para/line/word. Only
        word-level rows carry text. A confidence of -1 marks a row
        Tesseract did not actually recognize as a word (structural rows,
        or discarded candidates); those are skipped entirely rather than
        being averaged in as "0% confident", which would understate the
        quality of what genuinely was read.

        Line structure is rebuilt from the block/paragraph/line index
        columns so the returned text keeps its original layout — important
        for an invoice, where a number's row position is what associates it
        with a line item.

        The TSV also carries left/top/width/height per word, which is
        emitted as `OcrToken`s so the extraction layer can reason about
        table columns geometrically instead of inferring them from
        whitespace in a possibly-garbled text line.
        """
        reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)

        lines: dict[tuple[str, str, str], list[str]] = {}
        confidences: list[float] = []
        tokens: list[OcrToken] = []

        for row in reader:
            word = (row.get("text") or "").strip()
            if not word:
                continue
            try:
                conf = float(row.get("conf", -1))
            except (TypeError, ValueError):
                continue
            if conf < 0:
                continue

            key = (row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""))
            lines.setdefault(key, []).append(word)
            confidences.append(conf)

            try:
                tokens.append(OcrToken(
                    text=word,
                    confidence=conf,
                    left=int(float(row.get("left", 0))),
                    top=int(float(row.get("top", 0))),
                    width=int(float(row.get("width", 0))),
                    height=int(float(row.get("height", 0))),
                ))
            except (TypeError, ValueError):
                # Geometry missing/unparseable for this row: keep the word
                # in the text output but skip the token rather than
                # inventing a position.
                continue

        text = "\n".join(" ".join(words) for words in lines.values())
        return text, confidences, tokens
