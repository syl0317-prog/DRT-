"""New route tests: invented positions exist only in temporary test databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import folium
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'drt_system'))
from modules.independent_routes import RouteStore, RouteError, RevisionConflict, booking_schedule, read_original_stops
from modules.independent_routes import readonly_osrm
from modules.independent_route_views import overlay_routes
from modules.dashboard_views import overview_map, reservation_snapshot

START=datetime(2026,11,14,23,50,tzinfo=ZoneInfo('Asia/Seoul'))
POSITIONS=[(37.475,127.146),(37.476,127.147),(37.477,127.148),(37.478,127.149)]


def fake_router(coordinates, **kwargs):
    return dict(distance_km=1.,duration_min=5.,coordinates=coordinates,source='TEST FIXTURE ONLY',retrieved_at='test')


def add_four(store):
    for number,(lat,lon) in enumerate(POSITIONS,5):
        store.put_stop('R02',f'V{number:02d}',f'TEST ONLY stop {number}',lat,lon,number-4,
                       'research_candidate',store.snapshot()['revision'])


def ready(store, transfer=None, capacity=2):
    if not store.snapshot()['routes']:
        store.create_route('R02','TEST ONLY',store.snapshot()['revision'])
    add_four(store)
    store.configure('R02',['V05','V06','V07','V08'],transfer,[dict(vehicle_id='R02-V01',capacity=capacity)],store.snapshot()['revision'])
    store.calculate('R02',store.snapshot()['revision'],router=fake_router)
    store.set_active('R02',True,store.snapshot()['revision'])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=RouteStore(Path(self.tmp.name)/'routes.sqlite3')
        self.store.create_route('R02','TEST ONLY',0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_four_stops_nearest_road_and_restored_data(self):
        original_path=ROOT/'drt_system/data/drt_stops.csv'
        digest=hashlib.sha256(original_path.read_bytes()).hexdigest()
        add_four(self.store)
        state=self.store.snapshot()
        self.assertEqual(len(state['stops']),4)
        self.assertEqual(state['routes'][0]['stop_order'],['V05','V06','V07','V08'])
        self.assertTrue(all(s['nearest_road_m']>=0 for s in state['stops']))
        self.assertEqual(RouteStore(self.store.path).snapshot(),state)
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(),digest)
        with self.assertRaises(RouteError):
            self.store.put_stop('R02','V09','extra',37.479,127.15,1,'research_candidate',state['revision'])

    def test_duplicate_ids_positions_and_auto_suggestions(self):
        originals=read_original_stops()
        extra=dict(originals[0],stop_id='V05')
        store=RouteStore(self.store.path,original_loader=lambda:originals+[extra])
        self.assertEqual(store.suggested_stop_ids()[0],'V06')
        for stop_id in ('D01','V05'):
            with self.assertRaises(RouteError):
                store.put_stop('R02',stop_id,'duplicate',*POSITIONS[0],1,'research_candidate',store.snapshot()['revision'])
        self.store.put_stop('R02','V05','one',*POSITIONS[0],1,'research_candidate',self.store.snapshot()['revision'])
        for stop_id,position,coordinates in [('V05',2,POSITIONS[1]),('V06',1,POSITIONS[1]),('V06',2,POSITIONS[0])]:
            with self.assertRaises(RouteError):
                self.store.put_stop('R02',stop_id,'bad',*coordinates,position,'research_candidate',self.store.snapshot()['revision'])

    def test_bad_coordinates_not_saved(self):
        for lat,lon in [(None,None),(91,127),(37,float('nan')),(0,0),(float('inf'),127)]:
            with self.assertRaises(RouteError):
                self.store.put_stop('R02','V05','bad',lat,lon,1,'research_candidate',self.store.snapshot()['revision'])
        self.assertEqual(self.store.snapshot()['stops'],[])

    def test_exact_four_and_calculation_required_for_activation(self):
        for count in range(4):
            with self.assertRaises(RouteError):
                self.store.set_active('R02',True,self.store.snapshot()['revision'])
            lat,lon=POSITIONS[count]
            self.store.put_stop('R02',f'V{count+5:02d}','test',lat,lon,count+1,'research_candidate',self.store.snapshot()['revision'])
        with self.assertRaises(RouteError):
            self.store.set_active('R02',True,self.store.snapshot()['revision'])
        with self.assertRaises(RouteError):
            self.store.create_route('R03','extra route',self.store.snapshot()['revision'])

    def test_order_transfer_segment_totals_and_changes_invalidate(self):
        add_four(self.store)
        order=['V08','V06','V07','V05']
        self.store.configure('R02',order,'T01',[dict(vehicle_id='R02-V01',capacity=3)],self.store.snapshot()['revision'])
        calls=[]
        def router(coords,**kwargs):
            calls.append(coords)
            return fake_router(coords)
        self.assertTrue(self.store.calculate('R02',self.store.snapshot()['revision'],router=router))
        state=self.store.snapshot(); route=state['routes'][0]
        self.assertEqual(route['stop_order'],order)
        self.assertEqual((route['start_stop'],route['end_stop']),('V08','T01'))
        self.assertEqual((route['distance_km'],route['duration_min']),(4,20))
        self.assertEqual(len(calls),4)
        self.assertEqual([s['origin'] for s in state['segments']],order)
        self.store.set_active('R02',True,state['revision'])
        self.store.configure('R02',order,None,[dict(vehicle_id='R02-V01',capacity=3)],self.store.snapshot()['revision'])
        self.assertFalse(self.store.snapshot()['routes'][0]['active'])
        self.assertEqual(self.store.snapshot()['segments'],[])

    def test_osrm_failure_clears_geometry_no_straight_fallback(self):
        add_four(self.store)
        with patch('modules.independent_routes.readonly_osrm',side_effect=[fake_router([[37.475,127.146],[37.476,127.147]]),None]):
            self.assertFalse(self.store.calculate('R02',self.store.snapshot()['revision']))
        state=self.store.snapshot()
        self.assertEqual(state['segments'],[])
        self.assertEqual(state['routes'][0]['calculation_status'],'failed')
        self.assertIsNone(state['routes'][0]['distance_km'])
        self.assertIn('V06',state['routes'][0]['error'])

    def test_readonly_osrm_cache_and_live_geometry(self):
        cache=ROOT/'drt_system/data/osrm_cache.json';before=cache.read_bytes()
        coordinates=[[37.475,127.146],[37.476,127.147]]
        with patch('modules.independent_routes.calculate_road_route',return_value=fake_router(coordinates)) as cached:
            self.assertEqual(readonly_osrm(coordinates)['duration_min'],5)
            cached.assert_called_once_with(coordinates,allow_network=False)
        with patch('modules.independent_routes.calculate_road_route',return_value=None), \
             patch('modules.independent_routes.requests.get') as request:
            request.return_value.json.return_value={'code':'Ok','routes':[dict(distance=2000,duration=600,geometry=dict(coordinates=[[127.146,37.475],[127.147,37.476]]))]}
            result=readonly_osrm(coordinates,allow_network=True)
            self.assertEqual(result['coordinates'],coordinates)
            self.assertEqual((result['distance_km'],result['duration_min']),(2,10))
        self.assertEqual(cache.read_bytes(),before)

    def test_update_stop_and_optimistic_conflict(self):
        add_four(self.store)
        stale=self.store.snapshot()['revision']
        self.store.put_stop('R02','V05','edited',37.4751,127.1461,1,'reviewed',stale,replace_id='V05')
        with self.assertRaises(RevisionConflict):
            self.store.set_active('R02',False,stale)
        self.assertEqual(len(self.store.snapshot()['stops']),4)
        self.assertEqual(self.store.snapshot()['stops'][-1]['registration_status'],'reviewed')

    def test_reservation_capacity_isolation_direction_and_cancel(self):
        ready(self.store)
        original=ROOT/'drt_system/data/reservations.csv';before=original.read_bytes()
        booking=self.store.reserve('R02','V05','V08','R02-V01',START,2,self.store.snapshot()['revision'])
        self.assertEqual(booking['route_id'],'R02')
        with self.assertRaises(RouteError):
            self.store.reserve('R02','V05','V08','R02-V01',START,1,self.store.snapshot()['revision'])
        for boarding,destination,vehicle in [('D01','V08','R02-V01'),('V08','V05','R02-V01'),('V05','V08','V01')]:
            with self.assertRaises(RouteError):
                self.store.reserve('R02',boarding,destination,vehicle,START+timedelta(hours=2),1,self.store.snapshot()['revision'])
        with self.assertRaises(RouteError):
            self.store.configure('R02',['V05','V06','V07','V08'],None,[dict(vehicle_id='R02-V01',capacity=3)],self.store.snapshot()['revision'])
        self.store.cancel(booking['reservation_id'],self.store.snapshot()['revision'])
        self.assertEqual(self.store.snapshot()['bookings'][0]['status'],'cancelled')
        self.assertEqual(original.read_bytes(),before)

    def test_vehicle_overlap_midnight_and_schedule(self):
        ready(self.store)
        booking=self.store.reserve('R02','V05','V08','R02-V01',START,1,self.store.snapshot()['revision'])
        schedule=booking_schedule(booking)
        self.assertEqual(len(schedule['rows']),4)
        self.assertEqual(datetime.fromisoformat(schedule['arrival']).astimezone(START.tzinfo).day,15)
        with self.assertRaises(RouteError):
            self.store.reserve('R02','V05','V08','R02-V01',START+timedelta(minutes=10),1,self.store.snapshot()['revision'])
        self.store.reserve('R02','V05','V08','R02-V01',START+timedelta(hours=1),1,self.store.snapshot()['revision'])

    def test_concurrent_reservations_no_lost_writes(self):
        ready(self.store)
        revision=self.store.snapshot()['revision']
        def reserve(_):
            try:
                return self.store.reserve('R02','V05','V08','R02-V01',START,1,revision)['reservation_id']
            except RevisionConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,range(2)))
        self.assertEqual(results.count('conflict'),1)
        self.assertEqual(len(self.store.snapshot()['bookings']),1)

    def test_export_new_files_only_and_write_failure(self):
        add_four(self.store)
        out=self.store.export()
        self.assertEqual({p.name for p in out.iterdir()},{'routes.json','virtual_stops.csv','route_segments.csv','reservations.csv'})
        self.assertEqual(len(pd.read_csv(out/'virtual_stops.csv')),4)
        self.assertEqual(json.loads((out/'routes.json').read_text(encoding='utf-8'))['routes'][0]['route_id'],'R02')
        blocked=Path(self.tmp.name)/'blocked';blocked.write_text('file')
        with self.assertRaises(OSError):
            RouteStore(blocked/'x.sqlite3').create_route('R02','test',0)

    def test_new_overlay_and_dashboard_do_not_double_count(self):
        ready(self.store)
        state=self.store.snapshot()
        self.store.reserve('R02','V05','V08','R02-V01',START,1,state['revision'])
        state=self.store.snapshot()
        stops=pd.read_csv(ROOT/'drt_system/data/drt_stops.csv')
        rendered=overview_map(stops,state)
        self.assertEqual(rendered.count('L.circleMarker('),10)
        self.assertEqual(rendered.count('L.polyline('),3)
        self.assertIn('#15803d',rendered)
        original=pd.read_csv(ROOT/'drt_system/data/reservations.csv')
        snapshot=reservation_snapshot(original,4)
        self.assertEqual(snapshot['active_count'],6)
        self.assertEqual(sum(b['status']=='reserved' for b in state['bookings']),1)


class RouteUITests(unittest.TestCase):
    def test_map_click_uses_separate_state_and_requires_confirmation(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp, \
             patch('modules.independent_routes.DATABASE',Path(temp)/'routes.sqlite3'), \
             patch('modules.route_views.calculate_road_route',side_effect=fake_router), \
             patch('modules.route_views.st_folium',return_value={'last_clicked':None}), \
             patch('modules.independent_route_views.st_folium',return_value={'last_clicked':{'lat':POSITIONS[0][0],'lng':POSITIONS[0][1]}}):
            store=RouteStore();store.create_route('R02','TEST MAP ONLY',0)
            app=AppTest.from_file(str(ROOT/'drt_system/app.py'),default_timeout=40).run()
            app.sidebar.radio(key='main_menu').set_value('배차·경로').run()
            app.radio(key='route_section').set_value('신규 독립 노선').run()
            app.radio(key='nr_coord_source').set_value('지도에서 선택한 위치').run()
            app.text_input(key='nr_stop_name_new_V05').set_value('TEST MAP ONLY').run()
            app.button(key='nr_save_stop').click().run()
            self.assertEqual(len(store.snapshot()['stops']),0)
            self.assertGreater(len(app.error),0)
            next(c for c in app.checkbox if c.label.startswith('정류장 이름')).set_value(True).run()
            app.button(key='nr_save_stop').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertEqual(store.snapshot()['stops'][0]['latitude'],POSITIONS[0][0])
            self.assertNotIn('selected_lat',app.session_state)

    def test_stale_open_form_is_blocked_until_explicit_reload(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp, \
             patch('modules.independent_routes.DATABASE',Path(temp)/'routes.sqlite3'), \
             patch('modules.route_views.calculate_road_route',side_effect=fake_router), \
             patch('modules.route_views.st_folium',return_value={'last_clicked':None}), \
             patch('modules.independent_route_views.st_folium',return_value={'last_clicked':None}):
            store=RouteStore();store.create_route('R02','TEST CONFLICT ONLY',0)
            app=AppTest.from_file(str(ROOT/'drt_system/app.py'),default_timeout=40).run()
            app.sidebar.radio(key='main_menu').set_value('배차·경로').run()
            app.radio(key='route_section').set_value('신규 독립 노선').run()
            store.put_stop('R02','V05','other editor',*POSITIONS[0],1,'research_candidate',store.snapshot()['revision'])
            app.button(key='nr_save_stop').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertGreater(len(app.warning),0)
            self.assertEqual(len(store.snapshot()['stops']),1)
            app.button(key='nr_reload').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertEqual(app.text_input(key='nr_stop_id_new_V06').value,'V06')

    def test_register_four_calculate_activate_book_and_restore(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp, \
             patch('modules.independent_routes.DATABASE',Path(temp)/'routes.sqlite3'), \
             patch('modules.unified_reservations.DATABASE',Path(temp)/'unified.sqlite3'), \
             patch('modules.independent_routes.readonly_osrm',side_effect=fake_router), \
             patch('modules.route_views.calculate_road_route',side_effect=fake_router), \
             patch('modules.independent_route_views.st_folium',return_value={'last_clicked':None}):
            store=RouteStore();store.create_route('R02','TEST UI ONLY',0)
            app=AppTest.from_file(str(ROOT/'drt_system/app.py'),default_timeout=40).run()
            app.sidebar.radio(key='main_menu').set_value('배차·경로').run()
            # Avoid making a real request while switching from the legacy map default.
            app.radio(key='route_section').set_value('신규 독립 노선').run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            for number,(lat,lon) in enumerate(POSITIONS,5):
                suffix=f'new_V{number:02d}'
                app.text_input(key='nr_stop_name_'+suffix).set_value('TEST UI ONLY '+str(number))
                app.number_input(key='nr_lat_'+suffix).set_value(lat)
                app.number_input(key='nr_lon_'+suffix).set_value(lon).run()
                next(c for c in app.checkbox if c.label.startswith('정류장 이름')).set_value(True).run()
                app.button(key='nr_save_stop').click().run()
                self.assertEqual(len(app.exception),0,str(app.exception))
                self.assertEqual(len(app.error),0,str(app.error))
                self.assertEqual(len(store.snapshot()['stops']),number-4)
            app.button(key='nr_configure').click().run()
            app.button(key='nr_calculate').click().run()
            app.button(key='nr_activate').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertTrue(store.snapshot()['routes'][0]['active'])
            app.sidebar.radio(key='main_menu').set_value('예약 관리').run()
            app.selectbox(key='ua_origin').set_value('V05').run()
            app.selectbox(key='ua_destination').set_value('V08').run()
            app.button(key='ua_submit').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            from modules.unified_reservations import UnifiedReservations
            own=UnifiedReservations().own_records()
            self.assertEqual(len(own),1)
            self.assertEqual(own[0]['status'],'예약완료')
            app.sidebar.radio(key='main_menu').set_value('통합 대시보드').run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertEqual([m.value for m in app.metric][:2],['7','7'])
            self.assertTrue(any('등록된 신규 노선 수: 1' in m.value for m in app.markdown))
            app.sidebar.radio(key='main_menu').set_value('예약 관리').run()
            app.selectbox(key='ua_cancel_id').set_value(own[0]['public_id']).run()
            app.button(key='ua_cancel').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertEqual(UnifiedReservations().own_records()[0]['status'],'예약취소')


if __name__=='__main__':
    unittest.main()
