"""
test_quality_analysis
=======================

Simple CLI script to run quality analysis on a single handwritten invoice
image and print the result.

This is a manual testing tool for Step 3 of the project plan, not an
automated test suite (no pytest/unittest here) and not a batch/report
tool (that's Step 5, later). It exists so you can quickly check what the
quality analysis module reports for one real sample image at a time.

Usage
-----
    python scripts/test_quality_analysis.py path/to/image.jpg

Exit codes
----------
0 - analysis ran (even if the result reports warnings)
1 - the image could not be loaded/analyzed (result.success is False)
2 - invalid command-line usage
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Allow running this script directly (python scripts/test_quality_analysis.py)
# without having installed the project as a package: add the project root
# (the parent of this scripts/ directory) to sys.path so `image_processing`
# can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_processing.quality_analysis import analyze_image_quality  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) != 2:
        print("Usage: python scripts/test_quality_analysis.py <path_to_image>")
        return 2

    image_path = sys.argv[1]
    result = analyze_image_quality(image_path)

    print(json.dumps(result.to_dict(), indent=2))

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
