"""
easyocr_engine
===============

`OcrEngine` implementation backed by EasyOCR (CRAFT text detection +
CRNN recognition, on PyTorch).

Why EasyOCR as the stronger candidate
---------------------------------------
Tesseract's baseline on this dataset held up only on neatly hand-printed
invoices and collapsed on the dark/low-contrast/noisy majority, with
numeric fields corrupting (quantities misread, digits dropped). The two
serious *local* alternatives were EasyOCR and TrOCR; EasyOCR was chosen
because:

- TrOCR (`trocr-base-handwritten`) has an autoregressive language-model
  decoder trained on IAM handwritten *sentences*. On isolated numbers it
  is prone to emitting fluent-but-wrong tokens, and a silently wrong total
  is a worse outcome for this project than a missing one.
- TrOCR performs recognition only — it has no text detector, so it needs a
  segmentation stage built in front of it. Worse, on a table a "line"
  spans columns, so item descriptions and their amounts would be merged
  into one string, destroying the column association that later field
  extraction depends on.
- EasyOCR detects and recognizes *word/phrase regions* with a confidence
  each, which maps directly onto the existing `OcrResult` contract
  (`mean_confidence` / `word_count` / `word_confidences`) with no change
  to the protocol or to any caller.

Known limitation, stated plainly: EasyOCR's recognizer is scene-text
oriented, not a dedicated handwriting model. It is expected to improve on
Tesseract for these camera photos but is not guaranteed to solve
handwriting. Measuring that gap is the point of the comparison experiment.

Determinism / reproducibility
------------------------------
`Reader` construction downloads model weights on first use (~100MB) and is
expensive (seconds), so it is built once per engine instance and reused
across images — the experiment runner constructs the engine once and calls
`recognize()` per image, so model load cost is not charged to any single
image's `processing_time_seconds`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from .engine import OcrResult, OcrToken

logger = logging.getLogger(__name__)


class EasyOcrNotAvailableError(RuntimeError):
    """Raised at construction time when EasyOCR cannot be initialised."""


class EasyOcrEngine:
    """
    EasyOCR-backed OCR engine.

    Parameters
    ----------
    languages:
        EasyOCR language codes. English only here; the invoices are
        English/Tamil-region but the recognizable text is Latin-script.
    gpu:
        Whether to use CUDA. Defaults to False: the installed torch build
        is the CPU wheel, and forcing GPU on a CPU-only install makes
        EasyOCR emit a warning and silently fall back anyway.
    paragraph:
        When False (the default here), EasyOCR returns one entry per
        detected text region rather than merging regions into paragraphs.
        Kept unmerged deliberately: merging would blend an item
        description and its amount into a single string and discard the
        per-region confidence that the numeric-accuracy evaluation needs.
    """

    def __init__(
        self,
        languages: tuple[str, ...] = ("en",),
        gpu: bool = False,
        paragraph: bool = False,
    ) -> None:
        try:
            import easyocr  # imported lazily so the module is importable without it
        except ImportError as exc:
            raise EasyOcrNotAvailableError(
                "easyocr is not installed in this environment "
                "(pip install easyocr)"
            ) from exc

        self.languages = languages
        self.gpu = gpu
        self.paragraph = paragraph

        try:
            self._version = getattr(easyocr, "__version__", "unknown")
            # Built once and reused: model load is seconds-scale and must
            # not be attributed to per-image processing time.
            self._reader = easyocr.Reader(list(languages), gpu=gpu, verbose=False)
        except Exception as exc:  # noqa: BLE001 - setup failure, surfaced loudly
            raise EasyOcrNotAvailableError(
                f"Could not initialise EasyOCR Reader ({type(exc).__name__}: {exc})"
            ) from exc

        logger.info(
            "EasyOCR engine ready: v%s languages=%s gpu=%s",
            self._version, languages, gpu,
        )

    @property
    def name(self) -> str:
        return f"easyocr-{self._version}"

    def recognize(self, image_path: str | Path) -> OcrResult:
        """
        Run EasyOCR on one image.

        Uses `readtext` (detection + recognition) and reconstructs reading
        order from the detected bounding boxes, so the returned text keeps
        the invoice's visual row structure — important because a number's
        row position is what associates it with a line item.
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
            start = time.perf_counter()
            detections = self._reader.readtext(
                str(path),
                detail=1,
                paragraph=self.paragraph,
            )
            elapsed = time.perf_counter() - start
        except Exception as exc:  # noqa: BLE001 - reported as data, per contract
            logger.warning("EasyOCR failed on %s: %s", path.name, exc)
            return OcrResult(
                filename=path.name,
                success=False,
                engine=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        text, confidences, tokens = self._assemble(detections)
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
    def _assemble(detections: list) -> tuple[str, list[float], list[OcrToken]]:
        """
        Turn EasyOCR detections into (text, per-region confidences).

        EasyOCR returns `(bbox, text, confidence)` per region, where bbox
        is four corner points. Regions come back roughly in detection
        order, not reading order, so they are grouped into rows by vertical
        centre and sorted left-to-right within each row. Rows are formed
        with a tolerance proportional to the region's own height rather
        than a fixed pixel value, so the grouping works on both the small
        (~250px) and upscaled (600px) crops in this dataset.

        Confidences are rescaled from EasyOCR's 0-1 range to the 0-100
        scale that `OcrResult.mean_confidence` uses, so numbers are
        directly comparable with Tesseract's.
        """
        entries = []
        for detection in detections:
            # paragraph=True yields 2-tuples (bbox, text) with no
            # confidence; paragraph=False yields 3-tuples. Handle both so
            # the flag stays a safe knob.
            if len(detection) == 3:
                bbox, text, conf = detection
            elif len(detection) == 2:
                bbox, text = detection
                conf = None
            else:
                continue

            text = (text or "").strip()
            if not text:
                continue

            points = np.asarray(bbox, dtype=float)
            y_centre = float(points[:, 1].mean())
            x_left = float(points[:, 0].min())
            height = float(points[:, 1].max() - points[:, 1].min())
            width = float(points[:, 0].max() - points[:, 0].min())
            y_top = float(points[:, 1].min())
            entries.append((y_centre, x_left, height, text, conf, y_top, width))

        if not entries:
            return "", [], []

        entries.sort(key=lambda e: (e[0], e[1]))

        rows: list[list[tuple]] = []
        for entry in entries:
            y_centre, _, height, _, _, _, _ = entry
            tolerance = max(height * 0.6, 4.0)
            if rows and abs(y_centre - rows[-1][0][0]) <= tolerance:
                rows[-1].append(entry)
            else:
                rows.append([entry])

        lines: list[str] = []
        confidences: list[float] = []
        tokens: list[OcrToken] = []
        for row in rows:
            row.sort(key=lambda e: e[1])
            lines.append(" ".join(e[3] for e in row))
            for entry in row:
                _, x_left, height, token_text, conf, y_top, width = entry
                # EasyOCR reports confidence on a 0-1 scale; rescale to
                # 0-100 so it matches Tesseract's and OcrToken's contract.
                conf_100 = round(float(conf) * 100.0, 2) if conf is not None else 0.0
                if conf is not None:
                    confidences.append(conf_100)
                tokens.append(OcrToken(
                    text=token_text,
                    confidence=conf_100,
                    left=int(x_left),
                    top=int(y_top),
                    width=int(width),
                    height=int(height),
                ))

        return "\n".join(lines), confidences, tokens
