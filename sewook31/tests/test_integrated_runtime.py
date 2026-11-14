"""Operating-policy regressions. All writes use temporary CSV/SQLite copies."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
import copy,json,sqlite3,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sewook31'))
from modules.independent_routes import RouteStore,RouteError,DATABASE as ROUTES_DB
from modules.unified_reservations import UnifiedReservations
from modules.fixed_routes import resolve_stop
from modules.combined_routes import route_layers,add_layers
from modules.map_background import background_map
from streamlit.testing.v1 import AppTest


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.temp=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.registry=self.temp/'routes.sqlite3';self.db=self.temp/'requests.sqlite3';self.csv=self.temp/'reservations.csv'
        with closing(sqlite3.connect(ROUTES_DB)) as src,closing(sqlite3.connect(self.registry)) as dst:src.backup(dst)
        self.csv.write_bytes((ROOT/'sewook31/data/reservations.csv').read_bytes());self.original=self.csv.read_bytes()
        self.stack.enter_context(patch('modules.independent_routes.DATABASE',self.registry))
        self.stack.enter_context(patch('modules.unified_reservations.DATABASE',self.db))
        self.stack.enter_context(patch('modules.reservation_manager.RESERVATION_FILE',self.csv))
        self.store=RouteStore();self.service=UnifiedReservations();self.future=datetime.now(timezone.utc)+timedelta(days=2)

    def tearDown(self):
        self.assertEqual(self.csv.read_bytes(),self.original)
        self.stack.close()

    def reserve(self,origin='V05',destination='T02',key='test',**kw):
        return self.service.create(origin,destination,kw.pop('when',self.future),kw.pop('passengers',1),key,**kw)

    def ready(self):
        # Synthetic missing tail is TEST ONLY and never written to the real registry.
        with self.store.edit(self.store.snapshot()['revision']) as state:
            route=state['routes'][0]
            route.update(vehicles=[dict(vehicle_id='R02-TEST',capacity=1)],transfer_stop_id='T02',end_stop='T02')
            state['segments'].append(dict(route_id='R02',position=4,origin='V08',destination='T02',
                duration_min=2,distance_km=.2,coordinates=[state['segments'][-1]['coordinates'][-1],[37.47034,127.14195]],source='TEST ONLY'))
        self.store.set_active('R02',True,self.store.snapshot()['revision'])
        from modules.fixed_dispatch import register_vehicle,register_run
        register_vehicle(self.service,'R02-TEST',1,'TEST ONLY',test_only=True)
        self.run=register_run(self.service,'R02','R02-TEST',self.future,dict(zip(['V05','V06','V07','V08','T02'],[0,2,4,6,8])),'TEST ONLY access')

    def test_all_eight_memberships_and_ambiguity(self):
        state=self.store.snapshot(); originals=self.store.original_loader()
        for sid in ['D01','D02','D03','D04']:
            self.assertEqual(resolve_stop(originals,state,sid),('R01','T01'))
        for sid in ['V05','V06','V07','V08']:
            self.assertEqual(resolve_stop(originals,state,sid),('R02','T02'))
        ambiguous=copy.deepcopy(state);ambiguous['routes'][0]['stop_order'].append('D01')
        with self.assertRaises(RouteError):resolve_stop(originals,ambiguous,'D01')
        with self.assertRaises(RouteError):resolve_stop(originals,state,'UNKNOWN')

    def test_road_layers_colors_coordinates_and_missing_tail(self):
        routes=route_layers(self.store.original_loader(),self.store.snapshot())
        self.assertEqual([len(r['stops']) for r in routes],[5,5])
        self.assertEqual(len(routes[0]['paths']),1)
        self.assertFalse(routes[0]['temporary']);self.assertTrue(routes[1]['temporary'])
        self.assertEqual(len(routes[1]['paths']),1)
        self.assertEqual(len(routes[1]['estimated_paths']),1)
        self.assertIsNone(routes[1]['distance_km'])
        for r in routes:
            for line in r['paths']+r['estimated_paths']:
                self.assertTrue(all(37 < lat < 38 and 127 < lon < 128 for lat,lon in line))
        m=background_map([37.474,127.143]);add_layers(m,routes,['R01','R02']);html=m.get_root().render()
        self.assertIn('#2563EB',html);self.assertIn('#F97316',html)
        self.assertEqual(html.count('L.marker('),10)
        self.assertIn('8,8',html)
        with patch('modules.sequential_routes.ARCHIVE',self.temp/'missing_archive.json'):
            fallback=route_layers(self.store.original_loader(),dict(self.store.snapshot(),segments=[]))
        self.assertTrue(all(r['temporary'] for r in fallback))

    def test_create_reload_cancel_originals_unchanged(self):
        before=self.store.snapshot();old=self.service.list_records()
        for rid,a,b in [('R01','D01','T01'),('R02','V05','T02')]:
            row=self.reserve(a,b,rid)
            self.assertEqual(row['route_id'],rid);self.assertEqual(row['status'],'배차 검토 필요')
            self.assertIsNone(row['vehicle_id'])
            repeated=self.reserve(a,b,rid);self.assertEqual(row['public_id'],repeated['public_id'])
            reloaded=UnifiedReservations(self.db,self.store,self.csv)
            self.assertIn(row['public_id'],[r['public_id'] for r in reloaded.list_records()])
            reloaded.cancel(row['public_id']);reloaded.cancel(row['public_id'])
        self.assertEqual([r['status'] for r in self.service.own_records()],['예약취소']*2)
        self.assertEqual(self.store.snapshot(),before)
        old_ids={r['public_id'] for r in old}
        self.assertEqual([r for r in self.service.list_records() if r['public_id'] in old_ids],old)

    def test_invalid_combinations_and_input_rejected(self):
        for a,b,rid in [('D01','T02',None),('V05','T01',None),('V05','V08',None),('D01','D02','R01'),('V05','T02','R01')]:
            with self.assertRaises(RouteError):self.reserve(a,b,a+b,route_id=rid)
        for kw in [dict(passengers=0),dict(passengers=1000),dict(when=self.future.replace(tzinfo=None)),dict(when=self.future-timedelta(days=5))]:
            with self.assertRaises(RouteError):self.reserve(**kw)

    def test_inactive_and_missing_tail_never_confirmed(self):
        before=self.store.snapshot();row=self.reserve()
        self.assertEqual(row['status'],'배차 검토 필요');self.assertEqual(row['route_id'],'R02')
        self.assertEqual(self.service.retry_dispatch(row['public_id'])['status'],'배차 검토 필요')
        with self.assertRaises(RouteError):self.store.set_active('R02',True,before['revision'])
        self.assertEqual(self.store.snapshot(),before)

    def test_dispatch_capacity_conflicts_cancel_and_retry(self):
        pending=self.reserve(key='pending');self.ready()
        first=self.service.retry_dispatch(pending['public_id'])
        self.assertEqual(first['status'],'예약완료');self.assertEqual(first['vehicle_id'],'R02-TEST')
        second=self.reserve(key='second');self.assertEqual(second['status'],'배차 검토 필요')
        overlap=self.reserve(key='overlap',when=self.future+timedelta(minutes=1))
        self.assertEqual(overlap['status'],'배차 검토 필요')
        self.service.cancel(first['public_id'])
        retry=self.service.retry_dispatch(second['public_id']);self.assertEqual(retry['status'],'예약완료')
        with self.assertRaises(RouteError):self.service.retry_dispatch(first['public_id'])

    def test_concurrent_idempotency(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(lambda _:self.reserve(key='same'),range(4)))
        self.assertEqual(len({r['public_id'] for r in rows}),1)
        self.assertEqual(len(self.service.own_records()),1)
        with self.assertRaises(RouteError):self.reserve(key='same',when=self.future+timedelta(minutes=5))

    def test_legacy_cancel_overlay(self):
        row=next(r for r in self.service.list_records() if r['source']=='legacy_csv' and r['status']=='예약완료')
        self.service.cancel(row['public_id'])
        from modules.reservation_manager import load_reservations
        frame=load_reservations()
        self.assertEqual(frame.loc[frame.reservation_id.eq(row['raw_id']),'status'].iloc[0],'예약취소')

    def test_all_menus_and_booking_auto_destination(self):
        app=AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run()
        def check():self.assertEqual(len(app.exception),0,str(app.exception))
        def menu(value):app.sidebar.radio(key='main_menu').set_value(value).run();check()
        check();self.assertEqual(len(app.sidebar.radio(key='main_menu').options),5)
        menu('예약 및 배차 관리');self.assertEqual(len(app.selectbox(key='ua_origin').options),8)
        self.assertNotIn('ua_destination',[s.key for s in app.selectbox])
        app.selectbox(key='ua_origin').set_value('V05').run();check()
        app.button(key='ua_submit').click().run();check()
        row=self.service.own_records()[0];self.assertEqual((row['route_id'],row['destination_stop']),('R02','T02'))
        app.button(key='ua_cancel').click().run();check()
        app.selectbox(key='ua_origin').set_value('D01').run()
        app.button(key='ua_submit').click().run();check()
        row=self.service.own_records()[-1];self.assertEqual((row['route_id'],row['destination_stop']),('R01','T01'))
        menu('노선 및 운영 관리')
        for option in ['R02 등록부 및 차량','운영 설정','기존 경유지 연구 도구','관제 모형','통합 노선 지도']:
            app.radio(key='operations_section').set_value(option).run();check()
        menu('시뮬레이션 및 정시성 분석')
        for option in ['기존 정시성 검증','정시성 계산·검증 결과','예약 기반 합승','운영전략 비교']:
            app.radio(key='analysis_section').set_value(option).run();check()
        menu('데이터 및 시스템 관리');menu('통합 대시보드')

if __name__=='__main__':unittest.main()
