"""Punctuality views share the operating web's R01~R04 plans (synthetic fixtures only)."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sewook31'))
spec = importlib.util.spec_from_file_location('main_calc_routes', ROOT / 'scripts/punctuality_calc.py')
calc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calc)

from modules import punctuality_routes as pr  # noqa: E402


def stop(sid, lat, lon, kind='drt'):
    return dict(stop_id=sid, name=sid, latitude=lat, longitude=lon, stop_type=kind)


# Straight north-south road, ~111 m per 0.001 degree latitude.
LINE = [[37.470 + i * 0.001, 127.140] for i in range(5)]
SINGLE = dict(route_id='R03', name='fixture', stops=[stop('A', 37.470, 127.140), stop('B', 37.472, 127.140),
              stop('DEST', 37.474, 127.140, 'destination')], paths=[LINE], estimated_paths=[],
              duration_min=8.0, distance_km=0.44, evidence=[dict(retrieved_at='fixture')], segments=[])
SEGMENTS = dict(route_id='R02', name='fixture', stops=[stop('V1', 37.470, 127.140), stop('V2', 37.471, 127.140),
                stop('T', 37.472, 127.140, 'tram')], paths=[], estimated_paths=[], duration_min=None,
                distance_km=None, evidence=[], segments=[dict(origin='V1', destination='V2', duration_min=1.5)])


class PunctualityRouteTests(unittest.TestCase):
    def test_single_road_split_by_position_plus_dwell(self):
        legs = pr.plan_legs(SINGLE, dwell_min=1)
        self.assertEqual([l['stop_id'] for l in legs], ['A', 'B'])
        self.assertTrue(all(l['destination_id'] == 'DEST' for l in legs))
        self.assertAlmostEqual(legs[0]['road_min'], 8.0, places=3)
        self.assertAlmostEqual(legs[1]['road_min'], 4.0, places=1)
        self.assertAlmostEqual(legs[0]['ride_min'], 9.0, places=3)  # one intermediate stop
        self.assertEqual(legs[1]['dwell_min'], 0)
        self.assertIn('차량 접근', legs[0]['method'])

    def test_missing_segment_is_not_invented(self):
        with patch('modules.route_engine.calculate_road_route', return_value=None):
            legs = pr.plan_legs(SEGMENTS, dwell_min=1)
        self.assertEqual([l['status'] for l in legs], [pr.STATUS_MISSING] * 2)
        self.assertTrue(all(l['ride_min'] is None and 'V2→T' in l['missing'] for l in legs))
        with patch('modules.route_engine.calculate_road_route', return_value={'duration_min': 2.0}):
            legs = pr.plan_legs(SEGMENTS, dwell_min=1)
        self.assertEqual([l['ride_min'] for l in legs], [4.5, 2.0])

    def test_route_legs_reports_problems(self):
        with patch('modules.route_engine.calculate_road_route', return_value=None):
            legs, problems = pr.route_legs(plans=[SINGLE, SEGMENTS])
        self.assertEqual({l['route_id'] for l in legs}, {'R02', 'R03'})
        self.assertEqual(len(problems), 2)

    def test_generate_and_main_calc_carry_route_columns(self):
        from modules.punctuality_sim import generate
        legs = pr.plan_legs(SINGLE, dwell_min=1)
        frame = generate((1, 1.2, 1.5), legs=legs)
        self.assertEqual(set(frame['노선']), {'R03'})
        self.assertEqual(set(frame['환승역']), {'DEST'})
        self.assertTrue(frame['놓칠확률'].map(lambda v: v != 'missing').all())
        congestion = [{'시간': str(h), 'k': '1.2'} for h in (7, 8, 9, 17, 18, 19)]
        with patch.object(calc, 'REPS', 20):
            rows = calc.simulate([('A (A)', 9.0, 'DEST', 'R03')], {}, congestion)
        self.assertEqual({(r['노선'], r['환승역']) for r in rows}, {('R03', 'DEST')})
        self.assertEqual(set(rows[0]), set(calc.HEADERS))


if __name__ == '__main__':
    unittest.main()
