"""Sequential routes and shared runs. All writes go to temporary SQLite stores."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack,closing
from datetime import datetime,timedelta,timezone
import copy,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sewook31'))
from modules.independent_routes import RouteStore,RouteError,DATABASE
from modules.unified_reservations import UnifiedReservations
from modules.fixed_dispatch import register_vehicle,register_run,boarding_at
from modules.sequential_routes import route_plans,ARCHIVE
from modules.fixed_dispatch_views import dispatch_tables
from modules.combined_routes import add_layers
from modules.map_background import background_map


class SequentialDispatchTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        (ROOT/'.work').mkdir(exist_ok=True)
        self.temp=Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='sequential_',dir=ROOT/'.work')))
        self.registry=self.temp/'routes.sqlite3';self.db=self.temp/'bookings.sqlite3';self.csv=self.temp/'reservations.csv'
        with closing(sqlite3.connect(DATABASE.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(self.registry)) as dst:src.backup(dst)
        self.csv.write_bytes((ROOT/'sewook31/data/reservations.csv').read_bytes());self.csv_before=self.csv.read_bytes()
        self.stack.enter_context(patch('modules.independent_routes.DATABASE',self.registry))
        self.stack.enter_context(patch('modules.unified_reservations.DATABASE',self.db))
        self.stack.enter_context(patch('modules.reservation_manager.RESERVATION_FILE',self.csv))
        self.network=self.stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')))
        self.store=RouteStore();self.service=UnifiedReservations()
        self.future=(datetime.now(timezone.utc)+timedelta(days=2)).replace(microsecond=0)

    def tearDown(self):
        self.assertEqual(self.csv.read_bytes(),self.csv_before)
        self.assertEqual(self.network.call_count,0)
        self.stack.close()

    def ready_r02(self):
        with self.store.edit(self.store.snapshot()['revision']) as state:
            route=state['routes'][0]
            route.update(active=True,transfer_stop_id='T02',end_stop='T02')
            state['segments'].append(dict(route_id='R02',position=4,origin='V08',destination='T02',duration_min=2,distance_km=.2,
                coordinates=[state['segments'][-1]['coordinates'][-1],[37.47033951973533,127.1419490406675]],source='TEST ONLY SYNTHETIC'))

    def make_run(self,rid='R01',vehicle='TEST-BUS',capacity=4,departure=None):
        if not any(v['vehicle_id']==vehicle for v in self.service.operations()['vehicles']):
            register_vehicle(self.service,vehicle,capacity,'TEST ONLY synthetic vehicle',test_only=True)
        plan=next(p for p in route_plans(self.store.original_loader(),self.store.snapshot()) if p['route_id']==rid)
        return register_run(self.service,rid,vehicle,departure or self.future,dict(zip(plan['order'],[0,3,6,9,12])),'TEST ONLY stop access')

    def reserve(self,run,stop,key,count=1):
        return self.service.create(stop,run['order'][-1],boarding_at(run,stop),count,key,run_id=run['run_id'])

    def test_sequential_shapes_order_and_numbered_markers(self):
        plans=route_plans(self.store.original_loader(),self.store.snapshot())
        self.assertEqual(plans[0]['order'],['D01','D02','D03','D04','T01'])
        self.assertEqual(plans[1]['order'],['V05','V06','V07','V08','T02'])
        self.assertEqual([len(p['paths']) for p in plans],[1,1])
        self.assertEqual([len(p['estimated_paths']) for p in plans],[0,1])
        self.assertAlmostEqual(plans[0]['distance_km'],1.76)
        self.assertIsNone(plans[1]['duration_min'])
        positions=plans[0]['evidence'][0]['positions_m']
        self.assertTrue(all(b>a for a,b in zip(positions,positions[1:])))
        m=background_map([37.474,127.143]);add_layers(m,plans,['R01','R02']);html=m.get_root().render()
        self.assertEqual(html.count('L.marker('),10)
        self.assertIn('#2563EB',html);self.assertIn('#F97316',html)
        self.assertIn('4. ',html);self.assertIn('5. ',html)

    def test_reversed_cache_is_not_a_verified_route(self):
        cache=json.loads(ARCHIVE.read_text())
        key=next(k for k in cache if k.count(';')==4)
        cache[key]['coordinates'].reverse()
        file=self.temp/'bad.json';file.write_text(json.dumps(cache))
        plan=route_plans(self.store.original_loader(),self.store.snapshot(),archive=file)[0]
        self.assertFalse(plan['road_complete']);self.assertEqual(len(plan['estimated_paths']),4)

    def test_four_stops_share_one_run_capacity_cancel_and_stop_loads(self):
        run=self.make_run()
        before=self.store.snapshot()
        rows=[self.reserve(run,s,str(i)) for i,s in enumerate(run['order'][:-1])]
        self.assertTrue(all(r['status']=='예약완료' for r in rows))
        self.assertEqual({r['run_id'] for r in rows},{run['run_id']})
        self.assertTrue(all(r['research_only'] and '테스트' in r['dispatch_status'] for r in rows))
        pending=self.reserve(run,'D02','overflow')
        self.assertEqual(pending['status'],'배차 검토 필요')
        table=dispatch_tables(self.service,run['run_id'])
        self.assertEqual(table['runs'][0]['탑승예정'],4)
        self.assertEqual(sum(s['배정_승객'] for s in table['stops']),4)
        self.service.cancel(rows[0]['public_id'])
        self.assertEqual(dispatch_tables(self.service,run['run_id'])['runs'][0]['탑승예정'],3)
        retry=self.service.retry_dispatch(pending['public_id'])
        self.assertEqual(retry['status'],'예약완료')
        self.assertEqual(self.store.snapshot(),before)

    def test_r02_missing_tail_blocked_then_test_only_shared_run(self):
        register_vehicle(self.service,'TEST-BUS',4,'TEST ONLY',test_only=True)
        with self.assertRaises(RouteError):
            register_run(self.service,'R02','TEST-BUS',self.future,dict(zip(['V05','V06','V07','V08','T02'],[0,3,6,9,12])),'TEST access')
        self.ready_r02();run=self.make_run('R02')
        rows=[self.reserve(run,s,s) for s in run['order'][:-1]]
        self.assertTrue(all(r['status']=='예약완료' for r in rows))
        self.assertEqual(dispatch_tables(self.service,run['run_id'])['runs'][0]['탑승예정'],4)

    def test_no_vehicle_and_no_inferred_run(self):
        row=self.service.create('D01','T01',self.future,1,'pending')
        self.assertEqual(row['status'],'배차 검토 필요');self.assertIsNone(row['vehicle_id'])
        self.assertEqual(self.service.operations(),dict(vehicles=[],runs=[]))
        with self.assertRaises(RouteError):register_run(self.service,'R01','MISSING',self.future,dict(zip(['D01','D02','D03','D04','T01'],[0,3,6,9,12])),'access')

    def test_cross_route_vehicle_time_conflict_blocked_before_any_booking(self):
        self.make_run();self.ready_r02()
        with self.assertRaises(RouteError):self.make_run('R02',departure=self.future+timedelta(minutes=1))

    def test_concurrent_different_stops_cannot_overbook(self):
        run=self.make_run(capacity=3)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(lambda i:self.reserve(run,run['order'][i%4],str(i)),range(8)))
        self.assertEqual(sum(r['status']=='예약완료' for r in rows),3)

    def test_explicit_retry_time_consent_and_reload(self):
        run=self.make_run()
        desired=self.future+timedelta(hours=1)
        row=self.service.create('D03','T01',desired,1,'review')
        kept=self.service.retry_dispatch(row['public_id'],run_id=run['run_id'])
        self.assertEqual(kept['status'],'배차 검토 필요')
        assigned=self.service.retry_dispatch(row['public_id'],run_id=run['run_id'],accept_run_time=True)
        self.assertEqual(assigned['status'],'예약완료')
        self.assertEqual(datetime.fromisoformat(assigned['original_requested_at']),desired)
        self.assertEqual(datetime.fromisoformat(assigned['requested_at']),boarding_at(run,'D03'))
        reloaded=UnifiedReservations(self.db,self.store,self.csv)
        self.assertEqual(next(r for r in reloaded.list_records() if r['public_id']==row['public_id'])['run_id'],run['run_id'])

    def test_access_evidence_and_invalid_timetable_are_required(self):
        register_vehicle(self.service,'TEST-BUS',4,'TEST',test_only=True)
        offsets=dict(zip(['D01','D02','D03','D04','T01'],[0,3,6,9,12]))
        with self.assertRaises(RouteError):register_run(self.service,'R01','TEST-BUS',self.future,offsets,'')
        for values in ([0,3,2,9,12],[0,1,2,3,4],[0,float('nan'),6,9,12]):
            with self.assertRaises(RouteError):register_run(self.service,'R01','TEST-BUS',self.future,dict(zip(offsets,values)),'TEST access')

    def test_stale_route_signature_prevents_new_assignment(self):
        self.ready_r02();run=self.make_run('R02')
        with self.store.edit(self.store.snapshot()['revision']) as state:
            state['segments'][-1]['coordinates'][-1][0]+=.00001
        row=self.reserve(run,'V05','stale')
        self.assertEqual(row['status'],'배차 검토 필요');self.assertIsNone(row['vehicle_id'])

    def test_no_operational_run_on_synthetic_geometry(self):
        self.ready_r02()
        register_vehicle(self.service,'REAL-ID',4,'operator-provided identity',test_only=False)
        with self.assertRaises(RouteError):register_run(self.service,'R02','REAL-ID',self.future,dict(zip(['V05','V06','V07','V08','T02'],[0,3,6,9,12])),'access')

    def test_menu_booking_and_numbered_map_smoke_without_punctuality(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run()
        def check():
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertEqual(len(app.error),0,str([e.value for e in app.error]))
        check();menus=app.sidebar.radio(key='main_menu').options;self.assertEqual(len(menus),5)
        app.sidebar.radio(key='main_menu').set_value(menus[1]).run();check()
        self.assertEqual(len(app.selectbox(key='ua_origin').options),8)
        run=self.make_run()
        app.run();app.selectbox(key='ua_origin').set_value('D01').run()
        app.selectbox(key='ua_run').set_value(run['run_id']).run()
        app.button(key='ua_submit').click().run();check()
        app.selectbox(key='ua_origin').set_value('D03').run()
        app.button(key='ua_submit').click().run();check()
        self.assertEqual(sum(r['status']=='예약완료' for r in self.service.own_records()),2)
        app.selectbox(key='ua_cancel_id').set_value(self.service.own_records()[0]['public_id']).run()
        app.button(key='ua_cancel').click().run();check()
        self.assertEqual(dispatch_tables(self.service,run['run_id'])['runs'][0]['탑승예정'],1)
        app.sidebar.radio(key='main_menu').set_value(menus[2]).run();check()
        for value in app.radio(key='operations_section').options:
            app.radio(key='operations_section').set_value(value).run();check()
        app.session_state['ui_saved_values']['analysis_section']='예약 기반 합승'
        app.sidebar.radio(key='main_menu').set_value(menus[3]).run();check()
        app.sidebar.radio(key='main_menu').set_value(menus[4]).run();check()
        app.sidebar.radio(key='main_menu').set_value(menus[0]).run();check()


if __name__=='__main__':unittest.main()
