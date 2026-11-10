"""Meaningful offline regression checks for routing, timing, costs and Streamlit views."""
import json
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sewook31'))
from modules import osrm_cache
from modules.punctuality_sim import arrival_metrics, simulate_minutes, generate, calibrate
from modules.operating_costs import cost_table
from modules.settings import stops_path

class SimulationTests(unittest.TestCase):
    def test_arrival_boundaries_and_multiple_missed_trams(self):
        miss, wait = arrival_metrics([-3, 0, 1, 10, 21], 10)
        self.assertAlmostEqual(miss, 3/5)
        self.assertAlmostEqual(wait, (3+0+9+0+9)/5)

    def test_seed_and_buffer_effect(self):
        a = simulate_minutes(8, 10, 0, 0, (1, 1.2, 1.5), 1, 2, 10000, 42)
        self.assertEqual(a, simulate_minutes(8, 10, 0, 0, (1, 1.2, 1.5), 1, 2, 10000, 42))
        b = simulate_minutes(8, 10, 5, 0, (1, 1.2, 1.5), 1, 2, 10000, 42)
        self.assertEqual(b[0], 0)
        self.assertLess(b[0], a[0])
        self.assertGreaterEqual(simulate_minutes(8, 10, 0, 2, (1, 1.2, 1.5), 1, 2, 10000, 42)[0], a[0])

    def test_cache_direction_and_offline_miss(self):
        with tempfile.TemporaryDirectory() as d, patch.object(osrm_cache, 'CACHE_FILE', Path(d)/'cache.json'):
            response = Mock()
            response.json.return_value = {'code': 'Ok', 'routes': [{'geometry': {'coordinates': [[127, 37], [127.1, 37.1]]}, 'distance': 1000, 'duration': 360}]}
            with patch.object(osrm_cache.requests, 'get', return_value=response) as get:
                a = [[37, 127], [37.1, 127.1]]
                self.assertEqual(osrm_cache.calculate_road_route(a)['duration_min'], 6)
                self.assertTrue(osrm_cache.calculate_road_route(a, allow_network=False)['cache_hit'])
                self.assertIsNone(osrm_cache.calculate_road_route(a[::-1], allow_network=False))
                self.assertEqual(get.call_count, 1)

    def test_missing_routes_not_fabricated(self):
        with patch('modules.punctuality_sim.calculate_road_route', return_value=None):
            frame = generate()
            self.assertEqual(len(frame), 4*2*3*11)
            self.assertTrue((frame['놓칠확률'] == 'missing').all())

    def test_cost_scaling(self):
        a, b = cost_table(1), cost_table(4)
        self.assertTrue((b['연비용_원'] == a['연비용_원']*4).all())
        self.assertTrue((b['이용객당운영비_원'] == a['이용객당운영비_원']).all())
        self.assertEqual(len(a), 6)

    def test_calibration(self):
        k, n, status, source = calibrate()
        self.assertEqual((k, status), ((1, 1.2, 1.5), 'assumption'))

    def test_observed_calibration_requires_verified_pairs(self):
        from modules import punctuality_sim
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base/'data/assumptions').mkdir(parents=True)
            path = base/'data/assumptions/travel_time_observed.csv'
            path.write_text('실측소요분,OSRM소요분,검증상태,출처\n6,5,verified,fixture\n7,5,verified,fixture\n8,5,verified,fixture\n99,1,unverified,fixture\n', encoding='utf-8-sig')
            with patch.object(punctuality_sim, 'PROJECT_DIR', base):
                k, n, status, _ = calibrate()
                for actual, expected in zip(k, (1.2, 1.4, 1.6)):
                    self.assertAlmostEqual(actual, expected)
                self.assertEqual((n, status), (3, 'sourced'))

    def test_streamlit_pages(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT/'sewook31/app.py'), default_timeout=30).run()
        self.assertEqual(len(at.exception), 0)
        for menu in ('예약 관리', '트램 환승 관리', '운영 시뮬레이션', '정시성 검증', '관리자 패널'):
            at.sidebar.radio[0].set_value(menu).run()
            self.assertEqual(len(at.exception), 0, menu)
        at.sidebar.slider[0].set_value(2).run()
        self.assertEqual(at.session_state['vehicle_count'], 2)
        # Exercise plotting branch using synthetic route only inside isolated test.
        with patch('modules.punctuality_sim.calculate_road_route', return_value={'duration_min': 6}):
            at.sidebar.radio[0].set_value('정시성 검증').run()
            self.assertEqual(len(at.exception), 0)

if __name__ == '__main__':
    for path in (ROOT/'sewook31').rglob('*.py'):
        py_compile.compile(str(path), doraise=True)
    unittest.main()
