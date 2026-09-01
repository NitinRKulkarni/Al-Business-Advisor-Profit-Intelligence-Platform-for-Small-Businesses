"""
Tests for OCR report generation (`ocr/reporting.py`).

Why these matter
-----------------
The Phase 2 evaluation conclusions rest entirely on these calculations. A
mis-bucketed confidence, a zero-word image counted as a success with no
caveat, or a mis-parsed collage mapping would silently distort the report
that decisions are made from. Bucket boundaries in particular are exactly
the kind of off-by-one that never gets noticed by eye.

These tests use small hand-built records so expected values can be checked
by hand, rather than depending on the 156-image dataset.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ocr.reporting import (
    BASELINE_CSV_FIELDS,
    CONFIDENCE_BUCKETS,
    bucket_confidence,
    escape_text,
    load_collage_map,
    rank_by_confidence,
    read_records_csv,
    summarize,
    write_records_csv,
)


def make_record(
    filename: str,
    success: bool = True,
    mean_confidence: float | None = 50.0,
    word_count: int = 10,
    character_count: int = 40,
    processing_time: float = 0.3,
    source_collage: str = "invoice_01.png",
    extracted_text: str = "text",
    error: str = "",
) -> dict:
    return {
        "filename": filename,
        "source_image": f"data/samples/{filename}.png",
        "source_collage": source_collage,
        "preprocessing_output": f"data/processed/{filename}/final.png",
        "success": success,
        "mean_confidence": mean_confidence,
        "word_count": word_count,
        "character_count": character_count,
        "processing_time": processing_time,
        "extracted_text": extracted_text,
        "error": error,
    }


# ------------------------------------------------------------ escape_text

class TestEscapeText:
    def test_newlines_become_literal_backslash_n(self):
        # Keeps one image to exactly one physical CSV row.
        assert escape_text("a\nb") == "a\\nb"

    def test_windows_and_bare_carriage_returns_are_normalised(self):
        assert escape_text("a\r\nb") == "a\\nb"
        assert escape_text("a\rb") == "a\\nb"

    def test_empty_and_none_are_handled(self):
        assert escape_text("") == ""
        assert escape_text(None) == ""

    def test_text_without_newlines_is_unchanged(self):
        assert escape_text("Total 250.00") == "Total 250.00"


# ------------------------------------------------------ bucket_confidence

class TestBucketConfidence:
    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            (0.0, "below_30"),
            (29.99, "below_30"),
            (30.0, "30_to_50"),      # lower bound inclusive
            (49.99, "30_to_50"),
            (50.0, "50_to_70"),      # lower bound inclusive
            (69.99, "50_to_70"),
            (70.0, "above_70"),      # lower bound inclusive
            (100.0, "above_70"),
        ],
    )
    def test_bucket_boundaries_are_lower_inclusive(self, confidence, expected):
        assert bucket_confidence(confidence) == expected

    def test_missing_confidence_is_not_bucketed(self):
        # None must not collapse into "below_30": an image that returned no
        # words is a different failure from one returning words it was 0%
        # sure about, and summarize() counts them separately.
        assert bucket_confidence(None) is None

    def test_every_bucket_name_is_declared(self):
        produced = {bucket_confidence(v) for v in (10.0, 40.0, 60.0, 80.0)}

        assert produced == set(CONFIDENCE_BUCKETS)


# ------------------------------------------------------- load_collage_map

class TestLoadCollageMap:
    def test_maps_output_filename_to_source_collage(self, tmp_path: Path):
        manifest = tmp_path / "manifest.csv"
        manifest.write_text(
            "source_collage,output_filename,row,column\n"
            "invoice_01.png,batch2_invoice_001.png,1,1\n"
            "invoice_02.png,batch2_invoice_009.png,1,1\n",
            encoding="utf-8",
        )

        mapping = load_collage_map(manifest)

        assert mapping["batch2_invoice_001.png"] == "invoice_01.png"
        assert mapping["batch2_invoice_009.png"] == "invoice_02.png"

    def test_missing_manifest_raises_rather_than_returning_empty(self, tmp_path: Path):
        # Silently returning {} would produce an ungrouped report that looks
        # valid, so this must fail loudly.
        with pytest.raises(FileNotFoundError):
            load_collage_map(tmp_path / "nope.csv")


# --------------------------------------------------------------- summarize

class TestSummarize:
    def test_counts_successes_and_failures_separately(self):
        records = [
            make_record("a"),
            make_record("b"),
            make_record("c", success=False, mean_confidence=None, word_count=0,
                        character_count=0, error="boom"),
        ]

        stats = summarize(records)

        assert stats["total_images"] == 3
        assert stats["successful"] == 2
        assert stats["failed"] == 1
        assert stats["failed_filenames"] == ["c"]

    def test_zero_word_successes_are_counted_apart_from_failures(self):
        # The important case: the engine succeeded but produced nothing. A
        # naive success count would report 100% and hide this entirely.
        records = [
            make_record("a", word_count=10),
            make_record("b", mean_confidence=None, word_count=0, character_count=0),
        ]

        stats = summarize(records)

        assert stats["failed"] == 0
        assert stats["successful"] == 2
        assert stats["zero_word_count"] == 1
        assert stats["zero_word_filenames"] == ["b"]
        assert stats["images_without_confidence"] == 1

    def test_confidence_statistics_exclude_records_without_confidence(self):
        records = [
            make_record("a", mean_confidence=40.0),
            make_record("b", mean_confidence=60.0),
            make_record("c", mean_confidence=None, word_count=0),
        ]

        stats = summarize(records)

        assert stats["confidence"]["mean"] == 50.0
        assert stats["confidence"]["min"] == 40.0
        assert stats["confidence"]["max"] == 60.0

    def test_bucket_counts_cover_all_confident_successes(self):
        records = [
            make_record("a", mean_confidence=10.0),
            make_record("b", mean_confidence=35.0),
            make_record("c", mean_confidence=55.0),
            make_record("d", mean_confidence=95.0),
            make_record("e", mean_confidence=None, word_count=0),
        ]

        stats = summarize(records)
        buckets = stats["confidence_buckets"]

        assert buckets == {
            "below_30": 1,
            "30_to_50": 1,
            "50_to_70": 1,
            "above_70": 1,
        }
        assert sum(buckets.values()) + stats["images_without_confidence"] == 5

    def test_totals_are_summed_across_successes(self):
        records = [
            make_record("a", word_count=10, character_count=40),
            make_record("b", word_count=5, character_count=20),
        ]

        stats = summarize(records)

        assert stats["total_words"] == 15
        assert stats["total_characters"] == 60

    def test_processing_time_includes_failures(self):
        # Time spent on a failed image is still time spent; excluding it
        # would understate total runtime.
        records = [
            make_record("a", processing_time=0.2),
            make_record("b", success=False, mean_confidence=None,
                        word_count=0, processing_time=0.4),
        ]

        stats = summarize(records)

        assert stats["total_processing_time"] == pytest.approx(0.6)

    def test_groups_by_source_collage(self):
        records = [
            make_record("a", source_collage="invoice_01.png", mean_confidence=70.0, word_count=10),
            make_record("b", source_collage="invoice_01.png", mean_confidence=50.0, word_count=20),
            make_record("c", source_collage="invoice_07.png", mean_confidence=20.0, word_count=5),
            make_record("d", source_collage="invoice_07.png", mean_confidence=None, word_count=0),
        ]

        stats = summarize(records)
        per_collage = stats["per_collage"]

        assert set(per_collage) == {"invoice_01.png", "invoice_07.png"}
        assert per_collage["invoice_01.png"]["images"] == 2
        assert per_collage["invoice_01.png"]["confidence"]["mean"] == 60.0
        assert per_collage["invoice_01.png"]["total_words"] == 30
        assert per_collage["invoice_07.png"]["zero_word"] == 1
        assert per_collage["invoice_07.png"]["confidence"]["mean"] == 20.0

    def test_empty_input_does_not_raise(self):
        stats = summarize([])

        assert stats["total_images"] == 0
        assert stats["confidence"]["mean"] is None
        assert stats["per_collage"] == {}


# -------------------------------------------------------- rank_by_confidence

class TestRankByConfidence:
    def test_worst_puts_missing_confidence_first(self):
        # Zero-output images are the most important to inspect, so they must
        # surface at the top of the "worst" list rather than being skipped.
        records = [
            make_record("high", mean_confidence=80.0),
            make_record("mid", mean_confidence=45.0),
            make_record("none", mean_confidence=None, word_count=0),
        ]

        worst = rank_by_confidence(records, 3, worst=True)

        assert [r["filename"] for r in worst] == ["none", "mid", "high"]

    def test_best_orders_descending_and_respects_count(self):
        records = [
            make_record("a", mean_confidence=10.0),
            make_record("b", mean_confidence=90.0),
            make_record("c", mean_confidence=50.0),
        ]

        best = rank_by_confidence(records, 2, worst=False)

        assert [r["filename"] for r in best] == ["b", "c"]

    def test_failed_records_are_excluded_from_ranking(self):
        records = [
            make_record("ok", mean_confidence=50.0),
            make_record("bad", success=False, mean_confidence=None, word_count=0),
        ]

        assert [r["filename"] for r in rank_by_confidence(records, 5, worst=True)] == ["ok"]

    def test_requesting_more_than_available_returns_all(self):
        records = [make_record("a", mean_confidence=50.0)]

        assert len(rank_by_confidence(records, 20, worst=True)) == 1


# ----------------------------------------------------------- CSV round trip

class TestCsvIo:
    def test_write_creates_parent_directories_and_header(self, tmp_path: Path):
        out = tmp_path / "nested" / "deeper" / "report.csv"

        write_records_csv([make_record("a")], out)

        assert out.is_file()
        with out.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert list(rows[0].keys()) == BASELINE_CSV_FIELDS

    def test_round_trip_restores_types(self, tmp_path: Path):
        out = tmp_path / "report.csv"
        original = [
            make_record("a", mean_confidence=61.5, word_count=12,
                        character_count=48, processing_time=0.25),
            make_record("b", success=False, mean_confidence=None,
                        word_count=0, character_count=0, error="boom"),
        ]

        write_records_csv(original, out)
        restored = read_records_csv(out)

        assert restored[0]["success"] is True
        assert restored[0]["mean_confidence"] == 61.5
        assert restored[0]["word_count"] == 12
        assert restored[0]["character_count"] == 48
        assert restored[0]["processing_time"] == pytest.approx(0.25)

        assert restored[1]["success"] is False
        assert restored[1]["mean_confidence"] is None
        assert restored[1]["word_count"] == 0

    def test_multiline_text_stays_on_one_csv_row(self, tmp_path: Path):
        out = tmp_path / "report.csv"
        record = make_record("a", extracted_text=escape_text("line1\nline2\nline3"))

        write_records_csv([record], out)

        # Header + exactly one data row, despite the text containing newlines.
        assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_summarize_works_on_records_read_back_from_disk(self, tmp_path: Path):
        # End-to-end guard for the real workflow: the summary report is a
        # separate step that re-reads the CSV instead of re-running OCR.
        out = tmp_path / "report.csv"
        write_records_csv(
            [
                make_record("a", mean_confidence=80.0, word_count=50),
                make_record("b", mean_confidence=None, word_count=0),
            ],
            out,
        )

        stats = summarize(read_records_csv(out))

        assert stats["total_images"] == 2
        assert stats["zero_word_count"] == 1
        assert stats["confidence"]["mean"] == 80.0

    def test_unknown_extra_keys_are_ignored_rather_than_crashing(self, tmp_path: Path):
        out = tmp_path / "report.csv"
        record = make_record("a")
        record["some_future_field"] = "value"

        write_records_csv([record], out)

        assert read_records_csv(out)[0]["filename"] == "a"
