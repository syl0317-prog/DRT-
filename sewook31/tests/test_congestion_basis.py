"""Route congestion basis: link composition, observation override and entry validation."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sewook31'))

from modules import congestion_basis as cb  # noqa: E402


def write(path, header, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


class CongestionBasisTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.matching = self.temp / 'matching.csv'
        self.observed = self.temp / 'observed.csv'
        write(self.matching, ['route_id', 'link_id', 'road_name', 'road_rank', 'length_m'], [
            dict(route_id='RX', link_id='1', road_name='국도', road_rank='103', length_m='250'),
            dict(route_id='RX', link_id='2', road_name='시도', road_rank='104', length_m='500'),
            dict(route_id='RX', link_id='', road_name='미매칭', road_rank='', length_m='250')])
        write(self.observed, ['측정일', '출발지', '도착지', '실측소요분', 'OSRM소요분', '검증상태', '출처'], [])
        for name, value in (('MATCHING', self.matching), ('OBSERVED', self.observed)):
            patcher = patch.object(cb, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_composition_weights_arterial_share(self):
        comp = cb.composition('RX')
        self.assertAlmostEqual(comp['arterial'], .25)
        self.assertAlmostEqual(comp['unmatched'], .25)
        corridor, _ = cb.corridor_k('출근')
        factor = cb.route_factor('RX', '출근')
        self.assertEqual(factor['kind'], 'composite')
        for value, c, r in zip(factor['k'], corridor, cb.RESIDENTIAL_K):
            self.assertAlmostEqual(value, .25 * c + .75 * r)
        draws = factor['sample'](np.linspace(0, 1, 101))
        self.assertAlmostEqual(draws[0], factor['k'][0])
        self.assertAlmostEqual(draws[-1], factor['k'][2])
        self.assertTrue(np.all(np.diff(draws) >= 0))
        self.assertEqual(cb.route_factor('NOPE', '출근')['kind'], 'assumption')

    def test_three_verified_observations_override(self):
        base = dict(측정일='2026-11-17', 출발지='S1', 도착지='T', OSRM소요분=5, 출처='팀원 타이머',
                    노선='RX', 시간대='출근', 출발시각='07:40', 측정방식='주행', 메모='')
        for minutes in (6, 7, 8):
            cb.append_observation(dict(base, 실측소요분=minutes, 검증상태='verified'))
        cb.append_observation(dict(base, 실측소요분=50, 검증상태='unverified'))
        cb.append_observation(dict(base, 실측소요분=9, 검증상태='verified', 시간대='퇴근'))
        factor = cb.route_factor('RX', '출근')
        self.assertEqual((factor['kind'], factor['n']), ('observed', 3))
        for actual, expected in zip(factor['k'], (1.2, 1.4, 1.6)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(cb.route_factor('RX', '퇴근')['kind'], 'composite')
        with self.observed.open(encoding='utf-8-sig') as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header[:7], ['측정일', '출발지', '도착지', '실측소요분', 'OSRM소요분', '검증상태', '출처'])
        self.assertIn('노선', header)

    def test_entry_validation(self):
        good = dict(측정일='2026-11-17', 출발지='S1', 도착지='T', 실측소요분=6, OSRM소요분=5,
                    검증상태='verified', 출처='기록', 노선='RX', 시간대='출근')
        with self.assertRaises(ValueError):
            cb.append_observation(dict(good, 실측소요분=0))
        with self.assertRaises(ValueError):
            cb.append_observation(dict(good, 출처=' '))
        with self.assertRaises(ValueError):
            cb.append_observation(dict(good, OSRM소요분='x'))
        self.assertEqual(cb.read_observations(), [])


if __name__ == '__main__':
    unittest.main()
