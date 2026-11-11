import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from modules.gits_validation import audit, geometry_length, run_audit


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.f = dict(properties=dict(link_id="001", road_name="도로"),
                      geometry=dict(type="LineString", coordinates=[[0, 0], [.001, 0]]))
        self.r = dict(link_id="001", road_name="도로", source="fixture", direction="상행",
                      mean_speed_kmh="36", mean_travel_time_sec="10", length_m="missing",
                      observed_at="2026-11-10T00:00:00+09:00", observation_count="1", valid_count="1",
                      invalid_count="0", quality="single_snapshot", length_consistency="missing")

    def check_row(self, **changes):
        row = dict(self.r, **changes)
        return audit([self.f], [row], [row], [])[0][0]

    def test_valid_numbers_do_not_verify(self):
        r = self.check_row()
        self.assertEqual(r["status"], "review_required")
        self.assertFalse(r["drt_applicable"])
        self.assertEqual(r["implied_length_reference_m"], 100)
        self.assertAlmostEqual(r["vworld_length_m"], 111.319490793, places=6)
        self.assertAlmostEqual(r["geometry_implied_error_pct"], 100*abs(111.319490793-100)/111.319490793)
        self.assertIsNone(r["gits_recorded_length_m"])

    def test_invalid_numeric_values(self):
        for value in ("0", "-1", "nan", "inf", "bad"):
            with self.subTest(value=value):
                self.assertEqual(self.check_row(mean_speed_kmh=value)["status"], "unusable")

    def test_missing_values_require_review(self):
        r = self.check_row(mean_speed_kmh="missing", observed_at="missing")
        self.assertEqual(r["status"], "review_required")
        self.assertIsNone(r["implied_length_reference_m"])
        self.assertFalse(r["timestamp_timezone_parseable"])

    def test_recorded_length_and_mismatch_are_screening(self):
        r = self.check_row(length_m="200", road_name="다른 이름")
        self.assertGreater(r["geometry_recorded_error_pct"], 10)
        self.assertEqual(r["status"], "review_required")

    def test_unmatched_and_ambiguous_links(self):
        self.assertFalse(self.check_row(link_id="other")["id_match"])
        rows, _ = audit([self.f, self.f], [self.r], [], [])
        self.assertEqual(rows[0]["vworld_match_count"], 2)
        self.assertIsNone(rows[0]["vworld_length_m"])

    def test_duplicates_quality_and_collection_time(self):
        r = dict(self.r, source="wirye_traffic_history.csv", observation_count="2")
        rows, _ = audit([self.f], [r, r], [], [])
        self.assertEqual(rows[0]["summary_key_count"], 2)
        for reason in ("collected_at", "multiple_observations", "quality_record_missing", "do_not_pool"):
            self.assertIn(reason, rows[0]["reasons"])

    def test_geometry_variants(self):
        geom = self.f["geometry"]
        multi = dict(type="MultiLineString", coordinates=[geom["coordinates"], geom["coordinates"]])
        self.assertAlmostEqual(geometry_length(multi), 2*geometry_length(geom))
        self.assertIsNone(geometry_length(dict(type="LineString", coordinates=[[0, 0], [0, 0]])))
        self.assertIsNone(geometry_length(None))

    def test_previous_matching_stale(self):
        old = dict(self.r, vworld_road_name="도로", geometry=json.dumps(self.f["geometry"]))
        rows, _ = audit([self.f], [self.r], [self.r], [old])
        self.assertTrue(rows[0]["previous_matching_consistent"])
        old["mean_speed_kmh"] = "99"
        rows, _ = audit([self.f], [self.r], [dict(self.r, valid_count="0")], [old])
        self.assertFalse(rows[0]["previous_matching_consistent"])
        self.assertIn("quality_summary_disagreement", rows[0]["reasons"])

    def test_real_data_and_output_nonoverwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            first, report = run_audit(BASE.parent, temp)
            before = {p.name:p.read_bytes() for p in first.iterdir()}
            second, _ = run_audit(BASE.parent, temp)
            self.assertNotEqual(first, second)
            self.assertEqual(before, {p.name:p.read_bytes() for p in first.iterdir()})
            self.assertEqual(report["total_unique_gits_links"], 60)
            self.assertEqual(report["matched_unique_links"], 16)
            self.assertEqual(report["matched_status_counts"], dict(verified=0, review_required=16, unusable=0))
            self.assertEqual(report["applicable_rows"], 0)


if __name__ == "__main__":
    unittest.main()
