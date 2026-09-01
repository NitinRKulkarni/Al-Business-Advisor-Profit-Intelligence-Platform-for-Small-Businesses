"""
io_utils
=========

Safe image loading for the image_processing pipeline.

Why this module exists
-----------------------
`cv2.imread` is convenient but fails silently: if a file is missing,
corrupted, or an unsupported format, it just returns `None` with no
exception and no explanation. For a pipeline that must "handle invalid/
corrupted images gracefully" (per project requirements), silent `None`
is not good enough — we need to know *why* loading failed so we can report
a clear warning/error instead of crashing later with a confusing
"NoneType has no attribute shape" error.

How it works
-------------
`load_image()` validates the file up front (exists, has a supported
extension, is under the configured size limit) using settings from
`config.py`, then decodes it with OpenCV. If OpenCV fails to decode it,
we make a second attempt with Pillow purely to get a descriptive error
message (Pillow raises real exceptions on bad image data), then raise our
own `ImageLoadError` with that context. This is the only place Pillow is
used in this module — as a diagnostic fallback, not a primary decoder.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from .config import DEFAULT_CONFIG, PipelineConfig

logger = logging.getLogger(__name__)


class ImageLoadError(Exception):
    """Raised when an image file cannot be found, validated, or decoded."""


def load_image(
    image_path: str | Path,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Load an image from disk as a BGR NumPy array (OpenCV's native format).

    Parameters
    ----------
    image_path:
        Path to the image file.
    config:
        Pipeline configuration; only `config.io` is used here (supported
        extensions, max file size).

    Returns
    -------
    np.ndarray
        The decoded image, shape (height, width, 3), dtype uint8, channel
        order BGR (OpenCV's default — note this is *not* RGB).

    Raises
    ------
    ImageLoadError
        If the file is missing, has an unsupported extension, exceeds the
        configured size limit, or cannot be decoded as an image.
    """
    path = Path(image_path)

    if not path.exists() or not path.is_file():
        raise ImageLoadError(f"File not found: {path}")

    extension = path.suffix.lower().lstrip(".")
    if extension not in config.io.supported_extensions:
        supported = ", ".join(config.io.supported_extensions)
        raise ImageLoadError(
            f"Unsupported file extension '.{extension}' for {path.name}. "
            f"Supported extensions: {supported}"
        )

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > config.io.max_file_size_mb:
        raise ImageLoadError(
            f"File {path.name} is {size_mb:.1f}MB, which exceeds the "
            f"configured max of {config.io.max_file_size_mb}MB"
        )

    # cv2.IMREAD_COLOR: always decode to 3-channel BGR, even if the source
    # file is grayscale or has an alpha channel. This keeps every image
    # entering the pipeline in a consistent shape/dtype.
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)

    if image is None:
        # OpenCV gave us no reason. Ask Pillow, which will usually raise a
        # specific exception (e.g. "truncated file", "cannot identify
        # image file") that we can surface to the caller.
        try:
            with Image.open(path) as pil_image:
                pil_image.verify()
        except (UnidentifiedImageError, OSError) as pil_error:
            raise ImageLoadError(
                f"Could not decode {path.name}: file appears to be "
                f"corrupted or is not a valid image ({pil_error})"
            ) from pil_error

        # Pillow could open/verify it, but OpenCV still couldn't decode it
        # (e.g. an unusual color mode or ICC profile OpenCV doesn't
        # handle). Still unusable for this OpenCV-based pipeline.
        raise ImageLoadError(
            f"Could not decode {path.name}: file appears to be a valid "
            f"image but OpenCV was unable to read it"
        )

    if image.size == 0:
        raise ImageLoadError(f"Decoded image {path.name} is empty (0 pixels)")

    logger.debug("Loaded %s -> shape=%s dtype=%s", path.name, image.shape, image.dtype)
    return image
