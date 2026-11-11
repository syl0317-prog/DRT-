import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from modules.vworld_graph import build_graph
from modules.vworld_router import VWorldRouter


def road(coords, link):
    return dict(properties=dict(link_id=link, road_name="road_"+link),
                geometry=dict(type="LineString", coordinates=coords))


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.graph, _ = build_graph(dict(features=[road([[0, 0], [.001, 0]], "a"),
            road([[.001, 0], [.002, 0]], "b"), road([[1, 1], [1.001, 1]], "isolated")]))
        self.router = VWorldRouter(self.graph)

    def test_normal_path_geojson_scenarios_ids(self):
        r = self.router.route((0, 0), (0, .002), "experimental")
        self.assertTrue(r["success"])
        self.assertEqual(r["link_ids"], ["a", "b"])
        self.assertEqual(r["traversals"][0]["road_name"], "road_a")
        self.assertEqual(r["route_geojson"]["geometry"]["coordinates"], [[0, 0], [.001, 0], [.002, 0]])
        self.assertAlmostEqual(r["road_distance_m"], 222.6389815865)
        self.assertEqual([s["assumed_speed_kmh"] for s in r["scenarios"]], [15, 20, 25])
        self.assertAlmostEqual(r["scenarios"][1]["assumed_travel_time_min"], r["road_distance_m"]/1000/20*60)

    def test_unknown_direction_blocked(self):
        r = self.router.route((0, 0), (0, .002))
        self.assertFalse(r["success"])
        self.assertEqual(r["reason"], "no_verified_direction_and_connectivity_links")
        self.assertEqual(r["scenarios"], [])

    def test_experimental_reverse_geometry(self):
        r = self.router.route((0, .002), (0, 0), "experimental")
        self.assertEqual(r["link_ids"], ["b", "a"])
        self.assertEqual(r["route_geojson"]["geometry"]["coordinates"][0], [.002, 0])

    def test_disconnected(self):
        r = self.router.route((0, 0), (1, 1), "experimental")
        self.assertEqual(r["reason"], "different_geometric_components")

    def test_snap_limits_both_ends(self):
        self.assertEqual(self.router.route((.01, 0), (0, .002), "experimental")["reason"], "origin_snap_too_far")
        self.assertEqual(self.router.route((0, 0), (.01, .002), "experimental")["reason"], "destination_snap_too_far")

    def test_parallel_shortest_edge_and_duplicates(self):
        graph, _ = build_graph(dict(features=[road([[0, 0], [0, .001], [.001, 0]], "long"),
            road([[0, 0], [0, 0], [.001, 0]], "short")]))
        r = VWorldRouter(graph).route((0, 0), (0, .001), "experimental")
        self.assertEqual(r["link_ids"], ["short"])
        self.assertEqual(len(r["route_geojson"]["geometry"]["coordinates"]), 2)

    def test_verified_direction_and_evidence(self):
        for _, d in self.graph.nodes(data=True):
            d.update(connectivity_verified=True, connectivity_evidence="fixture junction survey",
                     access_verified=True, access_evidence="fixture access survey")
        for *_, d in self.graph.edges(data=True):
            d.update(direction="forward", direction_verified=True, direction_evidence="fixture direction survey")
        router = VWorldRouter(self.graph)
        self.assertTrue(router.route((0, 0), (0, .002))["success"])
        self.assertEqual(router.route((0, .002), (0, 0))["reason"], "no_path_in_selected_mode")

    def test_missing_access_evidence_blocks(self):
        for _, d in self.graph.nodes(data=True):
            d.update(connectivity_verified=True, connectivity_evidence="fixture")
        for *_, d in self.graph.edges(data=True):
            d.update(direction="both", direction_verified=True, direction_evidence="fixture")
        self.assertEqual(VWorldRouter(self.graph).route((0, 0), (0, .002))["reason"], "origin_or_destination_access_unverified")

    def test_crossing_not_added(self):
        g, _ = build_graph(dict(features=[road([[-.001, 0], [.001, 0]], "a"), road([[0, -.001], [0, .001]], "b")]))
        self.assertEqual(VWorldRouter(g).route((0, -.001), (.001, 0), "experimental")["reason"], "different_geometric_components")

    def test_invalid_input_and_empty_graph(self):
        self.assertFalse(self.router.route((float("nan"), 0), (0, 0))["success"])
        self.assertEqual(self.router.route((0, 0), (0, 0), "bad")["reason"], "invalid_mode")
        self.assertFalse(self.router.route((0, 0), (0, 0), max_snap_m=-1)["success"])
        self.graph.clear()
        self.assertEqual(VWorldRouter(self.graph).route((0, 0), (0, 0))["reason"], "empty_graph")

    def test_same_node_zero_distance(self):
        r = self.router.route((0, 0), (0, 0), "experimental")
        self.assertTrue(r["success"])
        self.assertEqual(r["road_distance_m"], 0)
        self.assertEqual(r["route_geojson"]["geometry"]["type"], "Point")

    def test_graphml_real_data(self):
        path = next((BASE/"data/derived").glob("*/vworld_graph.graphml"))
        router = VWorldRouter.from_graphml(path)
        component = max(__import__("networkx").connected_components(router.graph), key=len)
        nodes = sorted(component)
        a, b = router._node_point(nodes[0]), router._node_point(nodes[-1])
        r = router.route(a, b, "experimental")
        self.assertTrue(r["success"])
        self.assertGreater(r["road_distance_m"], 0)
        self.assertFalse(router.route(a, b, "verified")["success"])


if __name__ == "__main__":
    unittest.main()
