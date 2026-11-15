"""Review labels agree across UI surfaces without touching operational data."""
import copy
import html
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'sewook31'), str(ROOT/'sewook31/tests')]
import test_sequential_dispatch as fixtures
from modules import new_stop_settings
from modules.stop_labels import CANDIDATE_NAMES, stop_label
from modules.sequential_routes import route_plans
from modules.fixed_dispatch_views import dispatch_tables
from modules.reservation_audit import audit_service, display_rows
from modules.combined_routes import add_layers
from modules.map_background import background_map
from streamlit.testing.v1 import AppTest


class StopLabelTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        # Synthetic coordinates belong only to the isolated editor store.
        for rid, offset in (('R03', 0), ('R04', .005)):
            for suffix, lat, lon in (('S01',37.49,127.15),('S02',37.485,127.145),('BOKJEONG',37.48,127.14)):
                new_stop_settings.save_stop(rid+'-'+suffix,lat+offset,lon,new_stop_settings.load()['revision'])
        self.service = self.fx.service
        self.store = self.fx.store

    def test_names_are_presentation_only_and_do_not_change_route_signatures(self):
        catalog = self.service.catalog()
        plans = route_plans(self.store.original_loader(), self.store.snapshot())
        ids = {s['stop_id'] for s in catalog['boarding']}
        self.assertEqual(ids, set(CANDIDATE_NAMES))
        self.assertEqual(len(ids), 12)
        with patch('modules.stop_labels.CANDIDATE_NAMES', dict(CANDIDATE_NAMES, V05='Changed review label')):
            self.assertEqual(self.service.catalog(), catalog)
            self.assertEqual(route_plans(self.store.original_loader(), self.store.snapshot()), plans)
        self.assertEqual(stop_label('T01', '위례별역'), '위례별역 (T01)')
        self.assertEqual(stop_label('UNKNOWN'), 'UNKNOWN')

    def test_map_and_dispatch_labels_match_without_mutating_plans(self):
        plans = route_plans(self.store.original_loader(), self.store.snapshot())
        before = copy.deepcopy(plans)
        map_object = background_map([37.474, 127.143])
        add_layers(map_object, plans, ['R01','R02','R03','R04'])
        rendered = html.unescape(map_object.get_root().render())
        rows = {s['정류장']:s for s in dispatch_tables(self.service)['stops']}
        for sid in CANDIDATE_NAMES:
            label = stop_label(sid)
            self.assertIn(label, rendered)
            self.assertEqual(rows[sid]['표시명'], label)
            self.assertEqual(rows[sid]['정류장'], sid)
        for sid in ('R04-S01','R04-S02'):
            self.assertIn('위치 검증 필요', rows[sid]['표시명'])
        self.assertEqual(plans, before)
        self.assertFalse(next(p for p in plans if p['route_id']=='R04')['active'])

    def test_historical_snapshot_names_remain_available_and_unchanged(self):
        record = self.service.create('V05','T02',self.fx.future,1,'candidate-history',route_id='R02')
        saved = copy.deepcopy(self.service.own_records())
        audited = next(r for r in audit_service(self.service) if r['public_id']==record['public_id'])
        display = display_rows([audited])[0]
        self.assertEqual(display['승차'], stop_label('V05'))
        self.assertEqual(display['저장 당시 승차명'], record['stop_snapshot']['V05']['name'])
        self.assertEqual(self.service.own_records(), saved)
        self.assertIsNone(record['vehicle_id'])

    def test_booking_options_and_dispatch_ui_show_same_twelve_names(self):
        app = AppTest.from_file(str(ROOT/'sewook31/app.py'), default_timeout=60).run()
        app.sidebar.radio(key='main_menu').set_value('예약 및 배차 관리').run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(app.error, str([e.value for e in app.error]))
        options = app.selectbox(key='ua_origin').options
        self.assertEqual(set(options), {stop_label(sid) for sid in CANDIDATE_NAMES})
        table = next(d.value for d in app.dataframe if '표시명' in d.value.columns)
        for sid in CANDIDATE_NAMES:
            self.assertIn(stop_label(sid), set(table['표시명']))
        app.selectbox(key='ua_booking_route').set_value('R04').run()
        self.assertEqual(len(app.selectbox(key='ua_origin').options), 2)
        self.assertTrue(any('위치 검증 필요' in w.value for w in app.warning))
        self.assertFalse(app.exception, str(app.exception))


if __name__ == '__main__':
    unittest.main()
