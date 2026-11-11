"""Offline topology, conservative connectivity and serialization regression tests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import networkx as nx

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from modules.vworld_graph import build_graph, save_build


def feature(coords, kind="LineString", **properties):
    return dict(type="Feature", properties=properties,
                geometry=dict(type=kind, coordinates=coords))


def build(*features):
    return build_graph(dict(type="FeatureCollection", features=list(features)))


class GraphTests(unittest.TestCase):
    def test_lines_and_multipart_remain_separate(self):
        g, r = build(feature([[0, 0], [1, 0]]), feature(
            [[[1, 0], [2, 0]], [[5, 0], [6, 0]]], "MultiLineString"))
        self.assertEqual((len(g), g.number_of_edges(), r["component_count"]), (5, 3, 2))
        self.assertEqual(len(r["dead_end_node_ids"]), 4)

    def test_wgs84_length_and_properties(self):
        g, _ = build(feature([[0, 0], [1, 0]], link_id="001", road_name="도로", max_spd=30, extra={"a": 1}))
        d = next(iter(g.edges(data=True)))[2]
        # WGS84 semi-major axis * pi/180 at the equator.
        self.assertAlmostEqual(d["length_m"], 111319.49079327357, places=6)
        self.assertEqual(json.loads(d["source_properties_json"])["extra"], {"a": 1})
        self.assertEqual((d["link_id"], d["road_name"], d["max_spd"]), ("001", "도로", "30"))

    def test_duplicates_parallel_links_and_unknown_direction(self):
        g, r = build(feature([[0, 0], [0, 0], [1, 0]]), feature([[1, 0], [0, 0]]))
        self.assertEqual((len(g), g.number_of_edges()), (2, 2))
        self.assertEqual(r["issue_counts"]["consecutive_duplicate_coordinates"], 1)
        self.assertTrue(all(d["direction"] == "unknown" for *_, d in g.edges(data=True)))
        self.assertFalse(g.graph["routing_permitted"])

    def test_grade_separated_crossing_not_connected(self):
        g, r = build(feature([[-1, 0, 10], [1, 0, 10]]), feature([[0, -1, 0], [0, 1, 0]]))
        self.assertEqual((len(g), r["component_count"]), (4, 2))
        self.assertEqual(r["intersection_candidate_counts"]["interior_crossing"], 1)

    def test_t_junction_not_split(self):
        g, r = build(feature([[-1, 0], [1, 0]]), feature([[0, 0], [0, 1]]))
        self.assertEqual((len(g), r["component_count"]), (4, 2))
        self.assertEqual(r["intersection_candidate_counts"]["endpoint_interior"], 1)

    def test_nearby_endpoints_not_snapped(self):
        _, r = build(feature([[0, 0], [1, 0]]), feature([[1.00000001, 0], [2, 0]]))
        self.assertEqual(r["component_count"], 2)

    def test_invalid_empty_and_zero_length(self):
        g, r = build(feature([]), feature([[0, 0], [0, 0]]), feature([[181, 0], [0, 0]]),
                     feature([[0, 0], [float("nan"), 0]]), feature([0, 0], "Point"))
        self.assertEqual(len(g), 0)
        self.assertEqual(len(r["issues"]), 5)

    def test_export_roundtrip_unique_runs_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/"source.geojson"
            source.write_text(json.dumps(dict(type="FeatureCollection", features=[
                feature([[0, 0], [1, 0]], link_id="a"), feature([[0, 0], [1, 0]], link_id="b")])), encoding="utf-8")
            before = source.read_bytes()
            first, _ = save_build(source, Path(tmp)/"out")
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in first.iterdir()}
            second, _ = save_build(source, Path(tmp)/"out")
            self.assertNotEqual(first, second)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in first.iterdir()})
            self.assertEqual(len(hashes), 5)
            restored = nx.read_graphml(first/"vworld_graph.graphml", force_multigraph=True)
            self.assertEqual((len(restored), restored.number_of_edges()), (2, 2))
            self.assertFalse(restored.graph["routing_permitted"])
            for name in ("vworld_nodes.geojson", "vworld_edges.geojson", "connectivity_report.json", "build_metadata.json"):
                self.assertIsInstance(json.loads((first/name).read_text(encoding="utf-8")), dict)

    def test_project_data_matches_baseline(self):
        source = BASE.parent/"data/vworld/wirye_road_links.geojson"
        g, r = build_graph(json.loads(source.read_text(encoding="utf-8-sig")))
        self.assertEqual((len(g), g.number_of_edges(), r["component_count"]), (2250, 3221, 11))
        self.assertEqual(r["components"][0]["node_count"], 2219)
        self.assertEqual(len(r["dead_end_node_ids"]), 177)


if __name__ == "__main__":
    unittest.main()
