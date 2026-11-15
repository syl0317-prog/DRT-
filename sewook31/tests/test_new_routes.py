"""Candidate bookings remain pending; all writes use isolated fixture stores."""
import copy
import unittest
from unittest.mock import patch

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sewook31"), str(ROOT / "sewook31/tests")]
import test_sequential_dispatch as fixture_module
from modules.new_routes import boarding_stops, plans, destination_stop
from modules.fixed_routes import resolve_stop, COLORS
from modules.fixed_dispatch import register_vehicle, register_run
from modules.reservation_audit import audit_records
from modules.combined_routes import add_layers
from modules.map_background import background_map
from modules.independent_routes import RouteError


class NewRouteTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixture_module.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)

    def test_candidates_do_not_invent_coordinates_or_road_geometry(self):
        self.assertEqual([s['name'] for s in boarding_stops()], [
            '위례포레샤인 23단지 인근', '서울송례초등학교 인근',
            '위례중앙푸르지오 인근', '위례센트럴자이 인근'])
        self.assertEqual(COLORS['R03'], '#1D4ED8')
        self.assertEqual(COLORS['R04'], '#16A34A')
        for stop in boarding_stops():
            self.assertIsNone(stop['latitude'])
            self.assertIsNone(stop['longitude'])
        self.assertEqual(destination_stop()['name'], '복정역')
        for plan in plans():
            rid = plan['route_id']
            self.assertEqual(plan['order'], [rid+'-S01', rid+'-S02', rid+'-BOKJEONG'])
            self.assertFalse(plan['road_complete'])
            self.assertIsNone(plan['distance_km'])
            self.assertEqual(plan['paths'], [])
            self.assertEqual(plan['estimated_paths'], [])
            self.assertIsNone(plan['duration_min'])
            self.assertTrue(all('검증 필요' in s['access_status'] for s in plan['stops']))
            self.assertFalse(any('터널' in s['name'] for s in plan['stops']))
        self.assertEqual(len(plans()[1]['road_candidates']), 1)

    def test_all_four_stops_create_reload_retry_cancel_without_dispatch(self):
        service = self.fx.service
        before = copy.deepcopy(self.fx.store.snapshot())
        for stop in boarding_stops():
            sid, rid = stop['stop_id'], stop['route_id']
            self.assertEqual(resolve_stop(self.fx.store.original_loader(), before, sid), (rid, rid+'-BOKJEONG'))
            row = service.create(sid, rid+'-BOKJEONG', self.fx.future, 2, sid, route_id=rid)
            self.assertEqual(row['status'], '배차 검토 필요')
            self.assertIsNone(row['vehicle_id'])
            self.assertEqual(row['simulation_adapter'], 'excluded')
            self.assertEqual(row['path_evidence']['route_order'], [rid+'-S01', rid+'-S02', rid+'-BOKJEONG'])
            self.assertEqual(service.create(sid, rid+'-BOKJEONG', self.fx.future, 2, sid)['public_id'], row['public_id'])
            self.assertEqual(service.retry_dispatch(row['public_id'])['status'], '배차 검토 필요')
            self.assertTrue(audit_records([row], self.fx.store.original_loader(), before)[0]['operating_record'])
            for target in ('T01', 'T02', 'BOKJEONG', ('R04' if rid=='R03' else 'R03')+'-BOKJEONG'):
                with self.assertRaises(RouteError):
                    service.create(sid, target, self.fx.future, 1, sid+target)
            with self.assertRaises(RouteError):
                service.create(sid, rid+'-BOKJEONG', self.fx.future, 1, sid+'wrong', route_id='R01')
            service.cancel(row['public_id'])
        self.assertEqual(len(service.own_records()), 4)
        self.assertTrue(all(r['status'] == '예약취소' for r in service.own_records()))
        self.assertEqual(self.fx.store.snapshot(), before)

    def test_verified_vehicle_cannot_bypass_missing_roads(self):
        register_vehicle(self.fx.service, 'NEW-TEST', 4, 'test evidence', test_only=True)
        for plan in plans():
            with self.assertRaises(RouteError):
                register_run(self.fx.service, plan['route_id'], 'NEW-TEST', self.fx.future,
                             dict(zip(plan['order'], [0, 10, 20])), 'test access')
        self.assertEqual(self.fx.service.operations()['runs'], [])

    def test_legacy_common_destination_request_can_be_viewed_retried_and_cancelled(self):
        import json
        service=self.fx.service
        row=service.create('R03-S01','R03-BOKJEONG',self.fx.future,1,'legacy-compatibility')
        # Model a pre-split request only in this test's isolated SQLite DB.
        row['destination_stop']='BOKJEONG'
        with service.transaction() as (connection,state,attached):
            connection.execute('UPDATE requests SET payload=? WHERE public_id=?',
                (json.dumps(row,ensure_ascii=False),row['public_id']))
        self.assertEqual(service.list_records()[-1]['destination_stop'],'BOKJEONG')
        retried=service.retry_dispatch(row['public_id'])
        self.assertEqual(retried['destination_stop'],'BOKJEONG')
        self.assertEqual(retried['status'],'배차 검토 필요')
        service.cancel(row['public_id'])
        self.assertEqual(service.own_records()[-1]['status'],'예약취소')

    def test_map_layers_have_independent_visibility_and_no_unknown_markers(self):
        m = background_map([37.474, 127.143])
        add_layers(m, plans(), ['R04'])
        groups = [v for v in m._children.values() if v.__class__.__name__ == 'FeatureGroup']
        self.assertEqual([g.show for g in groups], [False, True])
        html = m.get_root().render()
        self.assertEqual(html.count('L.marker('), 2)
        self.assertIn('#1D4ED8', html)
        self.assertIn('#16A34A', html)

    def test_booking_route_filter_and_all_menus(self):
        from streamlit.testing.v1 import AppTest
        from pathlib import Path
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=60).run()
        menus = app.sidebar.radio(key='main_menu').options
        app.sidebar.radio(key='main_menu').set_value(menus[1]).run()
        for rid in ('R03', 'R04'):
            app.selectbox(key='ua_booking_route').set_value(rid).run()
            self.assertEqual(len(app.selectbox(key='ua_origin').options), 2)
            for sid in (rid+'-S01', rid+'-S02'):
                app.selectbox(key='ua_origin').set_value(sid).run()
                app.button(key='ua_submit').click().run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertFalse(app.error, str(app.error))
        self.assertEqual(len(self.fx.service.own_records()), 4)
        for menu in menus:
            app.sidebar.radio(key='main_menu').set_value(menu).run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertFalse(app.error, str(app.error))
