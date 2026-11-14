"""Final entry point regression tests; every write uses temporary data."""
from contextlib import ExitStack,closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
import copy,json,sqlite3,sys,tempfile,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sewook31'))
from modules.independent_routes import RouteStore,RouteError,DATABASE as ROUTES_DB
from modules.unified_reservations import UnifiedReservations
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

    def tearDown(self):self.stack.close()

    def test_recovered_real_data_and_two_independent_layers(self):
        state=self.store.snapshot();catalog=self.service.catalog()
        self.assertEqual(len(catalog['boarding']),8);self.assertEqual(len(catalog['trams']),2)
        self.assertEqual([s['stop_id'] for s in state['stops']],['V05','V06','V07','V08'])
        self.assertFalse(state['routes'][0]['active']);self.assertEqual(state['routes'][0]['vehicles'],[])
        routes=route_layers(self.store.original_loader(),state,['D01','D02','D03','D04'],'T01')
        self.assertEqual([r['route_id'] for r in routes],['R01','R02'])
        self.assertAlmostEqual(routes[1]['distance_km'],1.3336);self.assertAlmostEqual(routes[1]['duration_min'],2)
        m=background_map([37.474,127.143]);add_layers(m,routes,['R01','R02']);rendered=m.get_root().render()
        self.assertIn('#2563eb',rendered);self.assertIn('#dc2626',rendered)
        self.assertEqual(rendered.count('L.circleMarker('),9)
        with patch('modules.combined_routes.calculate_road_route',return_value=None):
            fallback=route_layers(self.store.original_loader(),dict(state,segments=[]),['D01'],'T01')
        self.assertTrue(all(r['temporary'] for r in fallback));self.assertTrue(all(r['distance_km'] is None for r in fallback))

    def test_route_selection_review_creation_cancellation_and_preservation(self):
        before=self.store.snapshot();old=self.service.list_records();self.assertEqual(len(old),6)
        evidence=lambda *a,**k:dict(status='unverified',reason='offline test')
        for rid,origin,destination in [('R01','D01','D02'),('R02','V05','V08')]:
            row=self.service.create(origin,destination,self.future,1,rid,route_id=rid,evidence_provider=evidence)
            repeated=self.service.create(origin,destination,self.future,1,rid,route_id=rid,evidence_provider=evidence)
            self.assertEqual(row['public_id'],repeated['public_id'])
            self.assertEqual(len(self.service.own_records()),1 if rid=='R01' else 2)
            self.assertEqual(row['route_id'],rid);self.assertEqual(row['status'],'배차 검토 필요')
            self.assertIsNone(row['vehicle_id']);self.service.cancel(row['public_id'])
        for rid,a,b in [('R01','V05','V08'),('R02','D01','D02'),('R02','V08','V05')]:
            with self.assertRaises(RouteError):self.service.create(a,b,self.future,1,rid+a,route_id=rid,evidence_provider=evidence)
        self.assertEqual(self.csv.read_bytes(),self.original);self.assertEqual(self.store.snapshot(),before)
        self.assertEqual([r['status'] for r in self.service.own_records()],['예약취소','예약취소'])

    def test_r02_vehicle_capacity_overlap_and_cancel_in_temporary_database(self):
        with self.store.edit(self.store.snapshot()['revision']) as state:
            state['routes'][0]['vehicles']=[dict(vehicle_id='R02-TEST',capacity=1)]
        self.store.set_active('R02',True,self.store.snapshot()['revision'])
        def reserve(key,when=None):return self.service.create('V05','V08',when or self.future,1,key,route_id='R02')
        first=reserve('a');self.assertEqual(first['status'],'예약완료');self.assertEqual(first['vehicle_id'],'R02-TEST')
        self.assertEqual(reserve('b')['status'],'배차 검토 필요')
        self.assertEqual(reserve('overlap',self.future+timedelta(minutes=1))['status'],'배차 검토 필요')
        self.service.cancel(first['public_id']);self.assertEqual(reserve('c')['status'],'예약완료')
        with self.assertRaises(RouteError):self.store.create_route('R01','bad',self.store.snapshot()['revision'])

    def test_final_entry_point_all_submenus_and_eight_options(self):
        app=AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run()
        def check():self.assertEqual(len(app.exception),0,str(app.exception))
        def menu(value):app.sidebar.radio(key='main_menu').set_value(value).run();check()
        check();self.assertEqual(len(app.sidebar.radio(key='main_menu').options),6)
        menu('예약 관리');self.assertEqual(len(app.selectbox(key='ua_origin').options),8)
        self.assertEqual(len(app.selectbox(key='ua_destination').options),8)
        app.selectbox(key='ua_route').set_value('R02').run()
        app.selectbox(key='ua_origin').set_value('V05').run();app.selectbox(key='ua_destination').set_value('V08').run()
        app.button(key='ua_submit').click().run();check();self.assertEqual(len(self.service.own_records()),1)
        app.selectbox(key='ua_route_filter').set_value('R02').run();check()
        self.assertEqual(len(app.selectbox(key='ua_cancel_id').options),1)
        app.button(key='ua_cancel').click().run();check()
        app.selectbox(key='ua_route_filter').set_value('전체').run()
        app.selectbox(key='ua_route').set_value('R01').run()
        app.selectbox(key='ua_origin').set_value('D01').run();app.selectbox(key='ua_destination').set_value('D02').run()
        app.button(key='ua_submit').click().run();check()
        created=self.service.own_records()[-1]
        self.assertEqual(created['route_id'],'R01')
        app.selectbox(key='ua_cancel_id').set_value(created['public_id']).run()
        app.button(key='ua_cancel').click().run();check()
        for option in ['기존 트램 연계 예약','신규 독립 노선 예약']:
            app.radio(key='booking_section').set_value(option).run();check()
        menu('배차·경로')
        self.assertEqual(app.multiselect(key='combined_visible').value,['R01','R02'])
        for option in ['배차·픽업 계산','신규 독립 노선','지도·노선 설정']:
            app.radio(key='route_section').set_value(option).run();check()
        menu('정시·환승 분석')
        app.radio(key='punctuality_section').set_value('기존 정시성 검증').run();check()
        menu('운영 시뮬레이션');app.radio(key='simulation_section').set_value('운영전략 비교').run();check()
        menu('관리·설정')
        for option in ['실시간 관제','기존 운행 지도','도로 혼잡도 분석','운영 설정']:
            app.radio(key='admin_section').set_value(option).run();check()
        self.assertEqual(self.csv.read_bytes(),self.original)

if __name__=='__main__':unittest.main()
