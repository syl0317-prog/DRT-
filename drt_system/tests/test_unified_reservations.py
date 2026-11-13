"""Federated booking tests exclusively use temporary CSV/SQLite copies."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'drt_system'))
sys.path.insert(0,str(ROOT/'drt_system/tests'))
from test_independent_routes import ready,START
from modules.independent_routes import RouteStore,RouteError
from modules.unified_reservations import UnifiedReservations,apply_csv_cancellations


def path_ok(*args,**kwargs):
    return dict(status='verified_model',source='TEST ONLY OSRM',route=dict(distance_km=1,duration_min=5))


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.temp=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.db=self.temp/'unified.sqlite3';self.registry=self.temp/'routes.sqlite3';self.csv=self.temp/'legacy.csv'
        self.csv.write_bytes((ROOT/'drt_system/data/reservations.csv').read_bytes())
        self.csv_before=self.csv.read_bytes()
        self.stack.enter_context(patch('modules.unified_reservations.DATABASE',self.db))
        self.stack.enter_context(patch('modules.independent_routes.DATABASE',self.registry))
        self.stack.enter_context(patch('modules.reservation_manager.RESERVATION_FILE',self.csv))
        self.routes=RouteStore();ready(self.routes,capacity=2)
        self.service=UnifiedReservations()
        self.future=datetime.now(timezone.utc)+timedelta(days=1)

    def tearDown(self):
        self.stack.close()

    def create(self,origin='D01',destination='D02',key='test',passengers=1,when=None,**kwargs):
        return self.service.create(origin,destination,when or self.future,passengers,key,
                                   evidence_provider=path_ok,**kwargs)

    def test_eight_stops_and_optional_tram_catalog(self):
        catalog=self.service.catalog()
        self.assertEqual({s['stop_id'] for s in catalog['boarding']},{'D01','D02','D03','D04','V05','V06','V07','V08'})
        self.assertEqual(len(catalog['boarding']),8)
        self.assertEqual(len(catalog['trams']),2)

    def test_old_to_old_and_cross_route_requests_are_review_not_dispatched(self):
        for i,(a,b) in enumerate([('D01','D02'),('D01','V05'),('V05','D04'),('V08','V05'),('D01','T01')]):
            record=self.create(a,b,str(i))
            self.assertEqual(record['status'],'배차 검토 필요')
            self.assertIsNone(record['vehicle_id'])
            self.assertEqual(record['simulation_adapter'],'excluded')
        self.assertEqual(self.csv.read_bytes(),self.csv_before)

    def test_new_to_new_assignment_uses_desired_boarding_not_route_start(self):
        record=self.create('V06','V08','r02')
        self.assertEqual(record['status'],'예약완료')
        self.assertEqual(record['vehicle_id'],'R02-V01')
        requested=datetime.fromisoformat(record['requested_at'])
        departure=datetime.fromisoformat(record['booking_snapshot']['departure'])
        self.assertEqual((requested-departure).total_seconds()/60,6)
        self.assertEqual(len(self.routes.snapshot()['bookings']),0)

    def test_inactive_route_is_review_and_paths_are_unchanged(self):
        self.routes.set_active('R02',False,self.routes.snapshot()['revision'])
        before=self.routes.snapshot()
        record=self.create('V05','V08')
        self.assertEqual(record['status'],'배차 검토 필요')
        self.assertEqual(self.routes.snapshot(),before)

    def test_same_stop_date_capacity_and_no_route_validation(self):
        for args in [('D01','D01',1,self.future),('D01','D02',100,self.future),('D01','D02',1,datetime.now(timezone.utc)-timedelta(days=1))]:
            with self.assertRaises(RouteError):
                self.create(args[0],args[1],passengers=args[2],when=args[3])
        with self.assertRaises(RouteError):
            self.service.create('D01','D02',self.future,1,'no-path',evidence_provider=lambda *a,**k:dict(status='no_route'))
        self.assertEqual(self.service.own_records(),[])

    def test_unverified_path_is_explicit_review(self):
        record=self.service.create('D01','D02',self.future,1,'offline',evidence_provider=lambda *a,**k:dict(status='unverified',reason='test offline'))
        self.assertEqual(record['status'],'배차 검토 필요')
        self.assertIn('미확인',record['dispatch_status'])

    def test_virtual_tram_target_preserved_and_validated(self):
        record=self.create('D01','T01',tram_departure=self.future+timedelta(minutes=30))
        self.assertEqual(datetime.fromisoformat(record['tram_departure']),self.future+timedelta(minutes=30))
        with self.assertRaises(RouteError):
            self.create('D01','T01',key='invalid-tram',tram_departure=self.future-timedelta(minutes=1))

    def test_capacity_conflict_cancellation_releases_seats(self):
        first=self.create('V05','V08','first',passengers=2)
        second=self.create('V05','V08','second')
        self.assertEqual(first['status'],'예약완료')
        self.assertEqual(second['status'],'배차 검토 필요')
        self.service.cancel(first['public_id'])
        third=self.create('V05','V08','third',passengers=2)
        self.assertEqual(third['status'],'예약완료')
        with self.assertRaises(RouteError):
            self.routes.configure('R02',['V05','V06','V07','V08'],None,[dict(vehicle_id='R02-V01',capacity=2)],self.routes.snapshot()['revision'])

    def test_existing_r02_source_capacity_and_cancel_updates_registry(self):
        old=self.routes.reserve('R02','V05','V08','R02-V01',self.future,2,self.routes.snapshot()['revision'])
        original=self.routes.snapshot()
        denied=self.create('V05','V08','full')
        self.assertEqual(denied['status'],'배차 검토 필요')
        public=next(r['public_id'] for r in self.service.list_records() if r['raw_id']==old['reservation_id'])
        self.service.cancel(public)
        after=self.routes.snapshot()
        self.assertEqual(after['bookings'][0]['status'],'cancelled')
        self.assertEqual(after['routes'],original['routes'])
        self.assertEqual(after['stops'],original['stops'])
        self.assertEqual(after['segments'],original['segments'])
        self.assertEqual(self.create('V05','V08','released')['status'],'예약완료')

    def test_original_r02_api_also_respects_unified_seats(self):
        record=self.create('V05','V08','unified-full',passengers=2)
        with self.assertRaises(RouteError):
            self.routes.reserve('R02','V05','V08','R02-V01',self.future,1,self.routes.snapshot()['revision'])
        self.service.cancel(record['public_id'])
        self.routes.reserve('R02','V05','V08','R02-V01',self.future,2,self.routes.snapshot()['revision'])
        self.assertEqual(len(self.routes.snapshot()['bookings']),1)

    def test_csv_cancel_overlay_updates_legacy_seats_without_overwrite(self):
        from modules.reservation_manager import load_reservations,get_vehicle_status
        first=self.service.list_records()[0]
        self.service.cancel(first['public_id'])
        self.assertEqual(self.csv.read_bytes(),self.csv_before)
        frame=load_reservations()
        self.assertEqual(frame.iloc[0].status,'예약취소')
        self.assertEqual(next(r for r in self.service.list_records() if r['public_id']==first['public_id'])['status'],'예약취소')
        status=get_vehicle_status(first['destination_stop'],first['tram_departure'])
        self.assertEqual(int(status.loc[status['차량 ID']==first['vehicle_id'],'예약 인원'].iloc[0]),0)

    def test_federation_namespaces_missing_time_restart_and_no_double_save(self):
        old=self.routes.reserve('R02','V05','V08','R02-V01',self.future,1,self.routes.snapshot()['revision'])
        record=self.create('D01','D02','once')
        repeated=self.create('D01','D02','once')
        self.assertEqual(record['public_id'],repeated['public_id'])
        rows=UnifiedReservations().list_records()
        self.assertEqual(len(rows),8)
        self.assertEqual(len({r['public_id'] for r in rows}),8)
        self.assertIsNone(rows[0]['requested_at'])
        self.assertEqual({r['source'] for r in rows},{'legacy_csv','route_registry','unified_sqlite'})

    def test_concurrent_duplicate_key_saved_once(self):
        def create(_):
            return self.create(key='same')['public_id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(create,range(2)))
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(len(self.service.own_records()),1)

    def test_ui_single_form_eight_options_tram_and_cancel(self):
        app=AppTest.from_file(str(ROOT/'drt_system/app.py'),default_timeout=40).run()
        app.sidebar.radio(key='main_menu').set_value('예약 관리').run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(len(app.selectbox(key='ua_origin').options),8)
        self.assertEqual(len(app.selectbox(key='ua_destination').options),8)
        self.assertFalse(any(r.key=='reservation_route_mode' for r in app.radio))
        app.checkbox(key='ua_include_tram').set_value(True).run()
        self.assertEqual(len(app.selectbox(key='ua_destination').options),10)
        app.checkbox(key='ua_include_tram').set_value(False).run()
        app.selectbox(key='ua_origin').set_value('V05').run()
        app.selectbox(key='ua_destination').set_value('V08').run()
        app.button(key='ua_submit').click().run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        own=self.service.own_records()
        self.assertEqual(len(own),1)
        app.button(key='ua_submit').click().run()
        self.assertEqual(len(self.service.own_records()),1)
        app.sidebar.radio(key='main_menu').set_value('통합 대시보드').run()
        self.assertEqual([m.value for m in app.metric][:2],['7','7'])
        app.sidebar.radio(key='main_menu').set_value('예약 관리').run()
        app.selectbox(key='ua_cancel_id').set_value(own[0]['public_id']).run()
        app.button(key='ua_cancel').click().run()
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(self.service.own_records()[0]['status'],'예약취소')
        self.assertEqual(self.csv.read_bytes(),self.csv_before)


if __name__=='__main__':
    unittest.main()
