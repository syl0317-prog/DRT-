"""Offline regression coverage for the imported main analysis model."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('main_calc', ROOT/'scripts/punctuality_calc.py')
calc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calc)


class MainPunctualityTests(unittest.TestCase):
    def test_reproducible_probabilities_and_buffer_monotonicity(self):
        routes = [('fixture', 5, 'tram')]
        congestion = [{'시간': str(h), 'k': str(k)} for h, k in [(7, 1), (8, 1.2), (9, 1.5), (17, 1), (18, 1.2), (19, 1.5)]]
        with patch.object(calc, 'REPS', 100):
            rows = calc.simulate(routes, {}, congestion)
            self.assertEqual(rows, calc.simulate(routes, {}, congestion))
        self.assertEqual(len(rows), 2*2*3*3*11)
        for start in range(0, len(rows), 11):
            group = rows[start:start+11]
            self.assertTrue(all(0 <= r['놓칠확률'] <= 1 and r['평균대기분'] >= 0 for r in group))
            self.assertTrue(all(a['놓칠확률'] >= b['놓칠확률'] for a, b in zip(group, group[1:])))
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory)/'chart.png'
            with patch.object(calc, 'OUT_PNG', image):
                calc.draw_chart(rows)
            self.assertEqual(image.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_empty_congestion_is_rejected(self):
        with self.assertRaises(ValueError):
            calc.factor_ranges([], [7, 8, 9])


if __name__ == '__main__':
    unittest.main()
