"""Shared booking flow and pending sequential loads; isolated stores only."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'sewook31'),str(ROOT/'sewook31/tests')]
import test_sequential_dispatch as fixtures
from modules import new_stop_settings as settings
from modules.fixed_dispatch_views import dispatch_tables
from modules.fixed_dispatch import register_vehicle,register_run
from modules.independent_routes import RouteError
from modules.new_routes import plans
from streamlit.testing.v1 import AppTest


class FinalBookingFlowTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.service=self.fx.service
        for rid,offset in [('R03',0),('R04',.005)]:
            for sid,lat,lon in [(rid+'-S01',37.49+offset,127.15),
                               (rid+'-S02',37.485+offset,127.145),
                               (rid+'-BOKJEONG',37.48+offset,127.14)]:
                settings.save_stop(sid,lat,lon,settings.load()['revision'])
            def router(points,allow_network):
                return dict(coordinates=[points[0],[points[0][0]-.001,points[0][1]-.003],points[1],
                                         [points[1][0]-.003,points[1][1]-.001],points[2]],
                    distance_km=3.2,duration_min=12.0,source='OSRM TEST FIXTURE ONLY',retrieved_at='test')
            settings.query_road(rid,settings.load()['revision'],router=router)

    def check(self,app):
        self.assertFalse(app.exception,str(app.exception))
        self.assertFalse(app.error,str([e.value for e in app.error]))

    def test_common_ui_booking_cancellation_sequential_loads_and_dashboard(self):
        app=AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run();self.check(app)
        app.sidebar.radio(key='main_menu').set_value('예약 및 배차 관리').run();self.check(app)
        self.assertEqual(app.selectbox(key='ua_booking_route').options,['전체','R01','R02','R03','R04'])
        before=settings.load()
        for rid in ('R03','R04'):
            app.selectbox(key='ua_booking_route').set_value(rid).run();self.check(app)
            self.assertEqual(len(app.selectbox(key='ua_origin').options),2)
            # Submit S02 first: visit order must still be S01 -> S02 -> destination.
            for sid,count in [(rid+'-S02',3),(rid+'-S01',2)]:
                app.selectbox(key='ua_origin').set_value(sid).run();self.check(app)
                self.assertTrue(any(rid+'-BOKJEONG' in i.value for i in app.info))
                app.number_input(key='ua_passengers').set_value(count).run()
                app.button(key='ua_submit').click().run();self.check(app)
            app.selectbox(key='ua_route_filter').set_value(rid).run();self.check(app)
            rows=next(d.value for d in app.dataframe if '표시 상태' in d.value.columns)
            self.assertEqual(len(rows),2)
            self.assertTrue(rows['하차'].eq(rid+'-BOKJEONG').all())
            self.assertEqual(int(rows['인원'].sum()),5)
            self.assertTrue(rows['표시 상태'].eq('예약 접수 · 배차 대기').all())
        records=self.service.own_records()
        self.assertEqual(len(records),4)
        for row in records:
            rid=row['route_id']
            self.assertEqual(row['path_evidence']['route_order'],[rid+'-S01',rid+'-S02',rid+'-BOKJEONG'])
            self.assertEqual(row['status'],'배차 검토 필요')
            self.assertIsNone(row['vehicle_id'])
            self.assertEqual(row['simulation_adapter'],'excluded')
        table=dispatch_tables(self.service,data_scope='operating')
        for rid in ('R03','R04'):
            ordered=[s for s in table['stops'] if s['노선']==rid]
            self.assertEqual([s['정류장'] for s in ordered],[rid+'-S01',rid+'-S02',rid+'-BOKJEONG'])
            self.assertEqual([s['대기_승객'] for s in ordered],[2,3,0])
            self.assertEqual(sum(s['배정_승객'] for s in ordered),0)
        app.sidebar.radio(key='main_menu').set_value('통합 대시보드').run();self.check(app)
        self.assertEqual(next(m.value for m in app.metric if m.label=='신규 유효 접수'),'4')
        self.assertEqual(next(m.value for m in app.metric if m.label=='배차 확정'),'0')
        dashboard=next(d.value for d in app.dataframe if '등록 운행편' in d.value.columns)
        self.assertEqual(list(dashboard['노선']),['R01','R02','R03','R04'])
        self.assertEqual(list(dashboard[dashboard['노선'].isin(['R03','R04'])]['대기']),[2,2])
        self.assertFalse(any('시각화용 직선' in m.value for m in app.markdown))
        html=next(f.proto.srcdoc for f in app.get('iframe') if f.proto.srcdoc)
        self.assertNotIn('시각화용 직선',html)
        for rid in ('R03','R04'):
            app.sidebar.radio(key='main_menu').set_value('예약 및 배차 관리').run()
            app.selectbox(key='ua_route_filter').set_value(rid).run();self.check(app)
            public=next(r['public_id'] for r in records if r['route_id']==rid and r['passengers']==3)
            app.selectbox(key='ua_cancel_id').set_value(public).run()
            app.button(key='ua_cancel').click().run();self.check(app)
        app.sidebar.radio(key='main_menu').set_value('통합 대시보드').run();self.check(app)
        self.assertEqual(next(m.value for m in app.metric if m.label=='신규 유효 접수'),'2')
        self.assertEqual(next(m.value for m in app.metric if m.label=='배차 대기'),'2')
        self.assertEqual(sum(r['status']=='예약취소' for r in self.service.own_records()),2)
        table=dispatch_tables(self.service,data_scope='operating')
        self.assertEqual(sum(s['대기_승객'] for s in table['stops']),4)
        self.assertEqual(settings.load(),before)

    def test_valid_osrm_and_registered_test_vehicle_do_not_authorize_new_route_dispatch(self):
        register_vehicle(self.service,'TEST-ONLY',8,'TEST ONLY',test_only=True)
        for plan in plans():
            self.assertTrue(plan['road_model_complete'])
            self.assertFalse(plan['road_complete'])
            with self.assertRaises(RouteError):
                register_run(self.service,plan['route_id'],'TEST-ONLY',self.fx.future,
                    dict(zip(plan['order'],[0,10,20])),'TEST ONLY')
        self.assertEqual(self.service.operations()['runs'],[])
