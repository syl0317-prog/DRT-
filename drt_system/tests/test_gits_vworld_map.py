"""Read-only integration and boundary checks for review artifacts."""
import copy
import json
import re
import shutil
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "drt_system"))
from modules.gits_vworld_map import combine, length_m, make_map, popup_html, read_csv, road_bounds
import folium


class ReviewMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads((ROOT / "data/vworld/wirye_road_links.geojson").read_text(encoding="utf-8-sig"))
        cls.observations = read_csv(ROOT / "data/processed/gits_link_summary.csv")
        cls.previous = read_csv(ROOT / "data/processed/vworld_gits_matching.csv")

    def test_real_inputs_preserved_and_partitioned(self):
        snapshot = copy.deepcopy(self.original)
        enriched, candidates, unmatched = combine(self.original, self.observations, self.previous)
        self.assertEqual(snapshot, self.original)
        self.assertEqual(len(enriched["features"]), 3221)
        self.assertEqual((len(candidates), len(unmatched)), (16, 44))
        self.assertEqual(Counter(r["match_status"] for r in candidates),
                         {"candidate_low_error": 8, "candidate_high_error": 8})
        self.assertEqual(sum(not f["properties"]["gits_observations"] for f in enriched["features"]), 3205)
        self.assertTrue(all(r["previous_matching_consistent"] for r in candidates))
        self.assertTrue(all(r["final_validation_status"] == "review_required" and not r["drt_applicable"] for r in candidates))
        self.assertEqual({r["gits_link_id"] for r in candidates + unmatched}, {r["link_id"] for r in self.observations})
        for before, after in zip(self.original["features"], enriched["features"]):
            self.assertEqual(before["geometry"], after["geometry"])
            for key, value in before["properties"].items():
                self.assertEqual(value, after["properties"][key])

    def test_threshold_missing_and_string_ids(self):
        feature = copy.deepcopy(self.original["features"][0])
        feature["properties"]["link_id"] = "001A"
        collection = dict(type="FeatureCollection", features=[feature])
        length = length_m(feature["geometry"])
        rows = [dict(link_id=" 001A ", mean_speed_kmh="36", mean_travel_time_sec=length * factor / 10)
                for factor in (1.09999, 1.10001)]
        rows.append(dict(link_id="001A", mean_speed_kmh="missing", mean_travel_time_sec="10"))
        _, matches, _ = combine(collection, rows, [])
        self.assertEqual([r["match_status"] for r in matches],
                         ["candidate_low_error", "candidate_high_error", "candidate_missing_length"])
        self.assertTrue(all(r["gits_link_id"] == "001A" for r in matches))
        with self.assertRaises(ValueError):
            combine(dict(features=[feature, feature]), [], [])

    def test_map_layers_popups_and_html(self):
        enriched, candidates, _ = combine(self.original, self.observations, self.previous)
        rendered = make_map(enriched).get_root().render()
        self.assertEqual(rendered.count(".bindPopup("), 16)
        for token in ("#888888", "#2474d2", "#ef8a17", "L.control.layers", "review_required"):
            self.assertIn(token, rendered)
        for row in candidates:
            popup = popup_html([row])
            for field in ("gits_link_id", "observed_or_collected_at", "source", "match_status"):
                self.assertIn(row[field], popup)
        self.assertIn("&lt;script&gt;", popup_html([dict(road_name="<script>")]))
        self.assertNotIn("<script>", popup_html([dict(road_name="<script>")]))

    def test_tile_free_map_contains_every_road_and_correct_styles(self):
        enriched, _, _ = combine(self.original, self.observations, self.previous)
        map_object = make_map(enriched)
        features, colors, popup_count = [], Counter(), 0

        def visit(element):
            nonlocal popup_count
            self.assertNotIsInstance(element, folium.TileLayer)
            if isinstance(element, folium.GeoJson):
                for feature in element.data["features"]:
                    features.append(feature)
                    colors[element.style_function(feature)["color"]] += 1
            if isinstance(element, folium.Popup):
                popup_count += 1
            for child in element._children.values():
                visit(child)

        visit(map_object)
        self.assertEqual(len(features), 3221)
        self.assertEqual(colors, {"#888888": 3205, "#2474d2": 8, "#ef8a17": 8})
        self.assertEqual(popup_count, 16)
        rendered = map_object.get_root().render()
        self.assertNotIn("L.tileLayer(", rendered)
        self.assertNotIn("tile.openstreetmap.org", rendered)
        self.assertIn('"zoomControl": true', rendered)
        self.assertIn('"preferCanvas": true', rendered)
        self.assertIn(".fitBounds(", rendered)
        self.assertEqual(map_object.location, [(a+b)/2 for a, b in zip(*road_bounds(enriched))])

    def test_bounds_use_actual_coordinates_and_reject_empty_input(self):
        sample = dict(features=[dict(geometry=dict(type="LineString", coordinates=[[128, 36], [129, 38]]))])
        self.assertEqual(road_bounds(sample), [[36, 128], [38, 129]])
        with self.assertRaises(ValueError):
            road_bounds(dict(features=[]))

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable for JavaScript syntax check")
    def test_generated_javascript_syntax(self):
        enriched, _, _ = combine(self.original, self.observations, self.previous)
        rendered = make_map(enriched).get_root().render()
        scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", rendered, re.S)
        code = "\n".join(scripts)
        self.assertIn("L.geoJson(", code)
        checked = subprocess.run([shutil.which("node"), "--check"], input=code, text=True,
                                 encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
