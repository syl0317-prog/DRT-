"""Tram-anchored reverse timetable, windows, repeat days and demand sizing (offline)."""
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sewook31'))

from modules import peak_operations as po  # noqa: E402

MONDAY = date(2026, 11, 16)


def legs(route_id='R01', destination='T01'):
    road = [6.0, 4.0, 2.0, 0.5]
    return [dict(route_id=route_id, stop_id=f'S{i}', stop_name=f'S{i}', position=i + 1, road_min=r,
                 destination_id=destination) for i, r in enumerate(road)]


class PeakOperationTests(unittest.TestCase):
    def test_virtual_tram_times_use_station_offsets(self):
        times, station = po.tram_departures('T01', MONDAY, '출근')
        self.assertEqual(station, '위례별')
        # 06:00 first train + 101→106 segment minutes (7.003) → :07, every 10 minutes.
        self.assertEqual(times[0].strftime('%H:%M'), '07:07')
        self.assertEqual(len(times), 12)
        self.assertTrue(all(b - a == timedelta(minutes=10) for a, b in zip(times, times[1:])))
        later, _ = po.tram_departures('R03-BOKJEONG', MONDAY, '퇴근')
        self.assertTrue(all(t.hour in (17, 18) for t in later))

    def test_reverse_timetable_meets_reliability_and_orders_windows(self):
        model = po.route_model(legs('R03', 'R03-BOKJEONG'), '출근', runs=2000, dwell_min=1)
        self.assertGreater(model['q95'], model['q50'])
        self.assertIn('GITS', model['basis'])
        tram = datetime(2026, 11, 16, 8, 4, tzinfo=po.KST)
        trip = po.build_trips(model, [tram], walk_min=3, reliability=.95)[0]
        self.assertGreaterEqual(trip['success_pct'], 95)
        self.assertLessEqual(trip['departure'], tram - timedelta(minutes=3 + model['q95']))
        starts = [w['start'] for w in trip['windows']]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(w['start'] <= w['end'] for w in trip['windows']))
        self.assertLessEqual(trip['arrival_end'] + timedelta(minutes=3), tram + timedelta(minutes=1))

    def test_residential_routes_use_documented_assumption(self):
        model = po.route_model(legs(), '출근', runs=500, dwell_min=1)
        self.assertEqual(model['k'], po.RESIDENTIAL_K)
        self.assertAlmostEqual(model['free_flow'], 6.0 + 3)

    def test_weekend_rejected_and_repeat_days_skip_weekend(self):
        with self.assertRaises(ValueError):
            po.timetable('R01', date(2026, 11, 21), '출근', legs=legs())
        friday = date(2026, 11, 20)
        self.assertEqual(po.next_weekdays(friday, 3), [friday, date(2026, 11, 23), date(2026, 11, 24)])

    def test_demand_counts_slots_and_recommends_headway(self):
        table = po.timetable('R01', MONDAY, '출근', legs=legs())
        first, second = table['trips'][:2]
        window = first['windows'][1]
        records = [dict(status='배차 검토 필요', boarding_stop='S1', passengers=3,
                        requested_at=window['start'].isoformat(), tram_departure=None),
                   dict(status='배차 검토 필요', boarding_stop='S0', passengers=2, requested_at=None,
                        tram_departure=second['tram_departure'].isoformat()),
                   dict(status='예약취소', boarding_stop='S0', passengers=9, requested_at=None,
                        tram_departure=second['tram_departure'].isoformat())]
        result = po.demand(table, records, capacity=8)
        self.assertEqual([r['passengers'] for r in result['rows'][:2]], [3, 2])
        self.assertTrue(result['every_other'])
        self.assertEqual(result['drt_headway'], 20)
        records.append(dict(status='예약완료', boarding_stop='S0', passengers=7, requested_at=None,
                            tram_departure=second['tram_departure'].isoformat()))
        busy = po.demand(table, records, capacity=8)
        self.assertFalse(busy['every_other'])
        self.assertEqual(busy['rows'][1]['vehicles'], 2)
        self.assertGreaterEqual(busy['vehicles'], 2)


class PeakBookingFlowTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_sequential_dispatch as fixture_module
        self.fx = fixture_module.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)

    def test_timetable_slot_and_weekly_repeat_booking(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / 'sewook31/app.py'), default_timeout=60).run()
        app.sidebar.radio(key='main_menu').set_value('예약 및 배차 관리').run()
        app.selectbox(key='ua_origin').set_value('D02').run()
        self.assertEqual(app.radio(key='ua_time_mode').value, '트램 연계 시간표 (출퇴근)')
        self.assertIn('트램 ←', app.selectbox(key='ua_peak_trip').options[0])
        app.radio(key='ua_repeat').set_value('1주일 (평일 5일)').run()
        app.button(key='ua_submit').click().run()
        self.assertFalse(app.exception, str(app.exception))
        records = self.fx.service.own_records()
        self.assertEqual(len(records), 5)
        days = {datetime.fromisoformat(r['requested_at']).astimezone(po.KST).date() for r in records}
        self.assertEqual(len(days), 5)
        self.assertTrue(all(d.weekday() < 5 for d in days))
        self.assertTrue(all(r['tram_departure'] and r['route_id'] == 'R01' for r in records))
        app.sidebar.radio(key='main_menu').set_value('노선 및 운영 관리').run()
        app.radio(key='operations_section').set_value('출퇴근 시간표·운영 조정').run()
        self.assertFalse(app.exception, str(app.exception))


if __name__ == '__main__':
    unittest.main()
