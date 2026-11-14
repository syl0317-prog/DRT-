"""GITS evidence, reproducibility, scheduling and additive UI regression checks."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'sewook31'))
from modules.strategy_sim import compare

class GitsTests(unittest.TestCase):
    def test_sources_unchanged(self):
        hashes = json.loads((ROOT/'data/processed/gits_source_hashes.json').read_text(encoding='utf-8'))
        for name, digest in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), digest, name)

    def test_quality_and_no_fabricated_matching(self):
        s = pd.read_csv(ROOT/'data/processed/gits_link_summary.csv', encoding='utf-8-sig')
        self.assertEqual((len(s), s.observation_count.sum()), (60, 62))
        p = pd.read_csv(ROOT/'data/processed/gits_time_profiles.csv', encoding='utf-8-sig')
        self.assertTrue((p.mean_speed_kmh == 'missing').all())
        r = pd.read_csv(ROOT/'data/processed/gits_route_matching.csv', encoding='utf-8-sig')
        self.assertTrue((r.observed_distance_fraction == 0).all())
        self.assertTrue((r.gits_duration_min == 'missing').all())

    def test_paired_rules_and_reproducibility(self):
        routes = pd.DataFrame([dict(route_id='fixture', osrm_duration_min=2, distance_km=1)])
        a = compare(routes, 'fixture', 15, buffer=1)
        pd.testing.assert_frame_equal(a, compare(routes, 'fixture', 15, buffer=1))
        A, B, C = [a[a.strategy == key].iloc[0] for key in 'ABC']
        self.assertGreater(B.pickup_mean_min, A.pickup_mean_min)
        self.assertEqual(A.vehicle_travel_min, B.vehicle_travel_min)
        self.assertGreaterEqual(B.failure_rate, A.failure_rate)
        self.assertEqual(C.failure_rate, 'missing')
        self.assertEqual(A.rejection_rate, 'missing')
        self.assertEqual(compare(routes, 'fixture', 15, shared=8).iloc[0].quality, 'blocked_capacity')

    def test_additional_pages(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT/'sewook31/app.py'), default_timeout=30).run()
        for menu in ['도로 혼잡도 분석','운영전략 비교']:
            at.sidebar.radio[0].set_value(menu).run()
            self.assertEqual(len(at.exception), 0)

if __name__ == '__main__':
    unittest.main()
