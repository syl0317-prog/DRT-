"""Timing boundaries, research distributions, read-only adapters and real app execution."""
from datetime import datetime, timedelta, time
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "drt_system"))
from modules.punctuality_simulation import DelayModel, evaluate_timing, simulate, sample_delays
from modules.punctuality_inputs import resolve_duration, route_duration, load_stops

KST = ZoneInfo("Asia/Seoul")
START = datetime(2026, 11, 13, 8, tzinfo=KST)


class TimingTests(unittest.TestCase):
    def test_punctuality_boundary_and_tolerance(self):
        target = START+timedelta(minutes=20)
        exact = evaluate_timing(START, 15, target, target, 5, walk_min=0, buffer_min=0)
        self.assertTrue(exact["on_time"])
        self.assertEqual(exact["target_margin_min"], 0)
        late = evaluate_timing(START, 15, target, target, 6, tolerance_min=1)
        self.assertTrue(late["on_time"])
        self.assertFalse(evaluate_timing(START, 15, target, target, 6.001, tolerance_min=1)["on_time"])
        self.assertEqual(exact["expected_arrival"], START+timedelta(minutes=15))

    def test_transfer_exact_and_failure(self):
        tram = START+timedelta(minutes=25)
        exact = evaluate_timing(START, 15, tram, tram, 5, walk_min=3, buffer_min=2)
        self.assertTrue(exact["transfer_success"])
        self.assertEqual(exact["transfer_margin_min"], 0)
        failed = evaluate_timing(START, 15, tram, tram, 6, walk_min=3, buffer_min=2)
        self.assertFalse(failed["transfer_success"])
        self.assertEqual(failed["transfer_excess_min"], 1)

    def test_midnight(self):
        start = START.replace(hour=23, minute=50)
        target = (start+timedelta(days=1)).replace(hour=0, minute=10)
        tram = target+timedelta(minutes=5)
        result = evaluate_timing(start, 15, target, tram, 5)
        self.assertEqual(result["delayed_arrival"], target)
        self.assertTrue(result["on_time"] and result["transfer_success"])
        sim = simulate(start, 15, target, tram, DelayModel(kind="fixed", fixed=5))
        self.assertEqual(sim["summary"][0]["on_time_pct"], 100)
        with self.assertRaises(ValueError):
            evaluate_timing(start, 15, target.replace(day=start.day), tram)

    def test_invalid_inputs(self):
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                evaluate_timing(START, value, START, START)
        with self.assertRaises(ValueError):
            simulate(START, 10, START, START, general_increase_pct=50, severe_increase_pct=20)


class DistributionTests(unittest.TestCase):
    def test_fixed_uniform_and_truncated_normal(self):
        np.testing.assert_array_equal(sample_delays(DelayModel(kind="fixed", fixed=3), 10), np.full(10, 3))
        uniform = sample_delays(DelayModel(minimum=2, maximum=8), 10000)
        self.assertTrue(np.all((uniform >= 2) & (uniform <= 8)))
        self.assertAlmostEqual(uniform.mean(), 5, delta=.1)
        normal = sample_delays(DelayModel(kind="truncated_normal", minimum=0, maximum=10, mean=5, std=2), 10000)
        self.assertTrue(np.all((normal > 0) & (normal < 10)))
        self.assertAlmostEqual(normal.mean(), 5, delta=.1)
        self.assertLess(normal.std(), 2)

    def test_distribution_validation(self):
        for model in [DelayModel(kind="fixed", fixed=-1), DelayModel(minimum=4, maximum=2),
                      DelayModel(kind="truncated_normal", std=0), DelayModel(kind="truncated_normal", mean=200),
                      DelayModel(kind="unknown")]:
            with self.assertRaises(ValueError):
                sample_delays(model)
        for runs in (0, 1.5, 100001):
            with self.assertRaises(ValueError):
                sample_delays(DelayModel(), runs)

    def test_reproducibility_probabilities_and_scenario_order(self):
        args = (START, 15, START+timedelta(minutes=22), START+timedelta(minutes=27))
        one, two = simulate(*args), simulate(*args)
        self.assertEqual(one["summary"], two["summary"])
        for name in one["samples"]:
            np.testing.assert_array_equal(one["samples"][name]["delay_min"], two["samples"][name]["delay_min"])
        for row in one["summary"]:
            for key in ("on_time_pct", "transfer_success_pct", "transfer_failure_pct"):
                self.assertTrue(0 <= row[key] <= 100)
            self.assertAlmostEqual(row["transfer_success_pct"]+row["transfer_failure_pct"], 100)
        rows = one["summary"]
        self.assertEqual([r["travel_min"] for r in rows], [15, 18, 22.5])
        self.assertGreaterEqual(rows[0]["on_time_pct"], rows[1]["on_time_pct"])
        self.assertGreaterEqual(rows[1]["on_time_pct"], rows[2]["on_time_pct"])
        self.assertLessEqual(rows[0]["transfer_failure_pct"], rows[2]["transfer_failure_pct"])


class InputTests(unittest.TestCase):
    def test_stops_and_cache_read_only(self):
        stops = load_stops()
        self.assertEqual(len(stops), 6)
        cache = ROOT / "drt_system/data/osrm_cache.json"
        before = cache.read_bytes()
        import json
        key = next(iter(json.loads(before)))
        coordinates = [[float(pair.split(",")[1]), float(pair.split(",")[0])] for pair in key.split("|")[1].split(";")]
        route, error = route_duration(coordinates)
        self.assertIsNone(error)
        self.assertGreater(route["duration_min"], 0)
        self.assertIn("캐시", route["source"])
        self.assertEqual(before, cache.read_bytes())

    @patch("modules.punctuality_inputs.calculate_road_route", return_value=None)
    @patch("modules.punctuality_inputs.requests.get", side_effect=requests.ConnectionError("test offline"))
    def test_osrm_failure_then_manual(self, get, cached):
        result, error = resolve_duration("osrm", 12, [[37.47, 127.14], [37.48, 127.15]], True)
        self.assertIsNone(result)
        self.assertIn("수동 입력", error)
        manual, error = resolve_duration("manual", 12, [])
        self.assertIsNone(error)
        self.assertEqual(manual["duration_min"], 12)
        self.assertIn("OSRM 계산값 아님", manual["source"])
        cached.assert_called_once()

    @patch("modules.punctuality_inputs.calculate_road_route", return_value=None)
    @patch("modules.punctuality_inputs.requests.get")
    def test_live_duration_without_cache_write(self, get, cached):
        get.return_value = Mock()
        get.return_value.json.return_value = {"code": "Ok", "routes": [{"duration": 900}]}
        cache = ROOT / "drt_system/data/osrm_cache.json"
        before = cache.read_bytes()
        route, error = route_duration([[37.47, 127.14], [37.48, 127.15]], True)
        self.assertIsNone(error)
        self.assertEqual(route["duration_min"], 15)
        self.assertEqual(before, cache.read_bytes())


class StreamlitTests(unittest.TestCase):
    def test_full_app_menu_and_manual_dashboard(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "drt_system/app.py"), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        app.sidebar.radio[0].set_value("정시·환승 분석").run()
        self.assertEqual(len(app.exception), 0)
        # Default route uses the existing cached route, without a network request.
        app.button(key="pa_run").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertEqual(len(app.metric), 4)
        app.radio(key="pa_mode").set_value("직접 입력").run()
        app.button(key="pa_run").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(len(app.error), 0)
        self.assertEqual(len(app.metric), 4)
        self.assertEqual(len(app.dataframe), 2)
        self.assertEqual(sum("vega_lite_chart" in getattr(node, "type", "") for node in app), 4)
        # Changing an input clears the old result, rather than showing stale probabilities.
        app.number_input(key="pa_manual").set_value(20.).run()
        self.assertEqual(len(app.metric), 0)

    @patch("modules.punctuality_inputs.calculate_road_route", return_value=None)
    def test_app_failure_fallback_and_truncated_normal(self, cached):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "drt_system/app.py"), default_timeout=30).run()
        app.sidebar.radio[0].set_value("정시·환승 분석").run()
        app.button(key="pa_run").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("수동 입력" in error.value for error in app.error))
        app.radio(key="pa_mode").set_value("직접 입력").run()
        app.selectbox(key="pa_distribution").set_value("절단 정규분포").run()
        app.number_input(key="pa_target_day").set_value(1).run()
        app.number_input(key="pa_tram_day").set_value(1).run()
        app.time_input(key="pa_start").set_value(time(23, 50)).run()
        app.time_input(key="pa_target").set_value(time(0, 10)).run()
        app.time_input(key="pa_tram").set_value(time(0, 20)).run()
        app.button(key="pa_run").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(len(app.error), 0)
        self.assertEqual(len(app.metric), 4)


if __name__ == "__main__":
    unittest.main()
