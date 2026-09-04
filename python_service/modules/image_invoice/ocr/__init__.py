"""
ocr
====

OCR (text recognition) stage for the handwritten-invoice pipeline.

Scope
------
This package takes an already-preprocessed image and returns raw
recognized text plus confidence. It deliberately does NOT do invoice
field extraction (vendor/date/total parsing), LLM post-processing,
database access, or API serving — those belong to later phases, mirroring
how `image_processing` is scoped to preprocessing only.

Design: engine-agnostic by intent
-----------------------------------
Tesseract is the first engine wired up, but it is expected to be a
*baseline* rather than the final choice — handwriting is the hard part of
this dataset and a deep-learning engine (EasyOCR / TrOCR / a cloud
handwriting API) may well replace it. To make that swap cheap, everything
here is written against the `OcrEngine` protocol in `engine.py`:

    engine: OcrEngine = TesseractOcrEngine()
    result = engine.recognize(image_path)

Callers (experiment runners, batch scripts, later pipeline stages) depend
only on `OcrEngine` and `OcrResult`, never on pytesseract directly. Adding
a second engine means writing one new class that satisfies the protocol;
no caller has to change.
"""

from .engine import OcrEngine, OcrResult, OcrToken
from .tesseract_engine import TesseractOcrEngine

__all__ = ["OcrEngine", "OcrResult", "OcrToken", "TesseractOcrEngine", "EasyOcrEngine"]


def __getattr__(name: str):
    """
    Lazily expose `EasyOcrEngine`.

    Imported on demand rather than eagerly so that merely importing this
    package does not pull in PyTorch (seconds of import time and hundreds
    of MB of memory). Callers that only need Tesseract pay nothing for
    EasyOCR being available.
    """
    if name == "EasyOcrEngine":
        from .easyocr_engine import EasyOcrEngine

        return EasyOcrEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
