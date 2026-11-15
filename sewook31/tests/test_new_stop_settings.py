"""Isolated candidate settings, backup/recovery and actual Streamlit editor tests."""
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'sewook31'), str(ROOT/'sewook31/tests')]
from modules import new_stop_settings as settings
from modules.new_routes import boarding_stops, destination_stop, destination_stops, plans
import test_sequential_dispatch as fixtures


class StopSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.work')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'locations.json'
        self.addCleanup(patch.stopall)
        patch('modules.new_stop_settings.SETTINGS_FILE', self.path).start()

    def save(self, sid, lat=37.48, lon=127.14):
        settings.save_stop(sid, lat, lon, settings.load()['revision'])

    def ready(self):
        self.save('R03-S01', 37.48, 127.14)
        self.save('R03-S02', 37.475, 127.135)
        self.save('R03-BOKJEONG', 37.47, 127.13)

    @staticmethod
    def router(points, allow_network):
        assert allow_network
        return dict(coordinates=points, distance_km=2.0, duration_min=8.0,
                    source='OSRM TEST FIXTURE ONLY', retrieved_at='test')

    def test_public_lookup_contracts_and_all_production_call_sites(self):
        import ast
        import inspect
        self.assertEqual(list(inspect.signature(boarding_stops).parameters), [])
        self.assertEqual(list(inspect.signature(destination_stop).parameters), [])
        for folder in ('sewook31', 'drt_system'):
            for path in (ROOT/folder).rglob('*.py'):
                if 'tests' in path.parts:
                    continue
                tree=ast.parse(path.read_text(encoding='utf-8-sig'))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    name=getattr(node.func,'id',None) or getattr(node.func,'attr',None)
                    if name in ('boarding_stops','destination_stop'):
                        self.assertEqual((node.args,node.keywords),([],[]),f'{path}:{node.lineno}')
        from modules import new_routes
        snapshot=settings.load()
        with patch('modules.new_stop_settings.load',return_value=snapshot) as read:
            new_routes.plans()
            self.assertEqual(read.call_count,1)

    def test_both_routes_with_strict_legacy_functions_save_edit_and_app_restart(self):
        fx=fixtures.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        fx.setUp()
        try:
            from streamlit.testing.v1 import AppTest
            # These genuinely zero-argument functions reproduce the reported
            # contract mismatch if a settings dict is passed by any UI call.
            def legacy_boarding():
                return boarding_stops()
            def legacy_destination():
                return destination_stops()
            event={}
            def click_map(*args,**kwargs):
                return event.copy()
            with patch('modules.new_stop_views.boarding_stops',side_effect=legacy_boarding), \
                 patch('modules.new_stop_views.destination_stops',side_effect=legacy_destination), \
                 patch('modules.new_stop_views.st_folium',side_effect=click_map) as maps:
                def open_editor():
                    app=AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run()
                    app.sidebar.radio(key='main_menu').set_value('노선 및 운영 관리').run()
                    app.radio(key='operations_section').set_value('신규 정류장 위치 설정').run()
                    return app
                def check(app):
                    self.assertFalse(app.exception,str(app.exception))
                    self.assertFalse(app.error,str([e.value for e in app.error]))
                app=open_editor();check(app)
                expected={}
                for index,rid in enumerate(('R03','R04')):
                    app.selectbox(key='ns_route').set_value(rid).run();check(app)
                    selector='ns_stop_'+rid
                    self.assertEqual(len(app.selectbox(key=selector).options),3)
                    table=next(d.value for d in app.dataframe if '정류장' in d.value.columns)
                    self.assertEqual(list(table['정류장']),[rid+'-S01',rid+'-S02',rid+'-BOKJEONG'])
                    for position,sid in enumerate((rid+'-S01',rid+'-S02',rid+'-BOKJEONG')):
                        app.selectbox(key=selector).set_value(sid).run();check(app)
                        lat,lon=37.48+index*.005+position*.001,127.14-position*.001
                        event['last_clicked']={'lat':lat,'lng':lon}
                        app.run();check(app)
                        self.assertTrue(any('선택 위도:' in m.value for m in app.markdown))
                        self.assertIn('저장 전 임시 후보',maps.call_args.args[0].get_root().render())
                        event.clear()
                        app.button(key='ns_save').click().run();check(app)
                        expected[sid]=(lat,lon)
                        self.assertEqual(settings.load()['stops'][sid]['latitude'],lat)
                # Edit an already saved stop through the same map-click UI.
                app.selectbox(key='ns_stop_R04').set_value('R04-S01').run()
                event['last_clicked']={'lat':37.49,'lng':127.15}
                app.run();check(app);event.clear()
                app.button(key='ns_save').click().run();check(app)
                expected['R04-S01']=(37.49,127.15)
                app=open_editor();check(app)
                for rid in ('R03','R04'):
                    app.selectbox(key='ns_route').set_value(rid).run();check(app)
                    table=next(d.value for d in app.dataframe if '정류장' in d.value.columns)
                    for _,row in table.iterrows():
                        self.assertEqual((row['위도'],row['경도']),expected[row['정류장']])
                self.assertTrue(list((self.path.parent/'backups').glob('*.json')))
        finally:
            fx.tearDown()

    def test_click_validation_save_reload_update_backup(self):
        self.assertIsNone(settings.clicked_point({}))
        self.assertEqual(settings.clicked_point({'last_clicked':{'lat':37.48,'lng':127.14}}),
                         {'latitude':37.48,'longitude':127.14})
        for lat, lon in [(None,127.14),(float('nan'),127.14),(37.48,float('inf')),
                         (127.14,37.48),(0,0),(True,127.14)]:
            with self.assertRaises(ValueError):
                settings.clicked_point({'last_clicked':{'lat':lat,'lng':lon}})
        for sid in settings.STOP_IDS:
            self.save(sid)
        original = self.path.read_bytes()
        self.save('R03-S01',37.481,127.141)
        backups = list((self.path.parent/'backups').glob('*.json'))
        self.assertTrue(any(p.read_bytes()==original for p in backups))
        self.assertEqual(settings.load()['stops']['R03-S01']['latitude'],37.481)
        self.assertEqual(boarding_stops()[0]['source'],'사용자 지정 후보 좌표')
        self.assertEqual(destination_stops()[0]['latitude'],37.48)
        # A fresh interpreter, rather than in-memory session state, loads the same file.
        import subprocess
        code = ('import sys;sys.path.insert(0,"sewook31");'
                'from modules.new_stop_settings import load;'
                'print(load(sys.argv[1])["stops"]["R03-S01"]["latitude"])')
        output = subprocess.check_output([sys.executable,'-B','-c',code,str(self.path)],cwd=ROOT,text=True)
        self.assertEqual(float(output.strip()),37.481)

    def test_stale_invalid_and_failed_write_preserve_previous_data(self):
        self.save('R03-S01')
        original = self.path.read_bytes()
        with self.assertRaises(ValueError): settings.save_stop('R03-S01',37.48,127.14,0)
        with self.assertRaises(ValueError): self.save('D01')
        with patch('modules.new_stop_settings.os.replace',side_effect=OSError('disk denied')):
            with self.assertRaises(OSError): self.save('R03-S02')
        self.assertEqual(self.path.read_bytes(),original)
        self.assertFalse(self.path.with_suffix('.lock').exists())
        self.path.with_suffix('.lock').write_text('busy')
        with self.assertRaises(ValueError): self.save('R03-S02')
        self.path.with_suffix('.lock').unlink()
        self.assertEqual(self.path.read_bytes(),original)
        self.path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ValueError): self.save('R03-S02')
        self.assertEqual(self.path.read_text(),'{broken')

    def test_route_model_is_separate_from_dispatch_and_coordinate_changes_invalidate(self):
        with self.assertRaises(ValueError): settings.query_road('R03',0,router=self.router)
        self.ready()
        settings.query_road('R03',settings.load()['revision'],router=self.router)
        plan=plans()[0]
        self.assertTrue(plan['road_model_complete'])
        self.assertFalse(plan['road_complete'])
        self.assertEqual(plan['distance_km'],2)
        self.assertEqual(len(plan['paths']),1)
        self.save('R03-S01',37.481,127.141)
        self.assertFalse(plans()[0]['road_model_complete'])
        self.assertIsNone(plans()[0]['distance_km'])
        settings.query_road('R03',settings.load()['revision'],router=self.router)
        self.save('R03-BOKJEONG',37.471,127.131)
        self.assertEqual(settings.load()['roads'],{})

    def test_failed_and_reversed_route_never_displayed_as_confirmed(self):
        self.ready()
        settings.query_road('R03',settings.load()['revision'],router=self.router)
        with self.assertRaises(ValueError):
            settings.query_road('R03',settings.load()['revision'],router=lambda *a,**k:None)
        self.assertEqual(settings.load()['roads'],{})
        def reverse(points,allow_network):
            return dict(self.router(points,allow_network),coordinates=list(reversed(points)))
        with self.assertRaises(ValueError):
            settings.query_road('R03',settings.load()['revision'],router=reverse)

    def test_markers_use_saved_points_and_display_switches(self):
        self.ready()
        from modules.combined_routes import add_layers
        from modules.map_background import background_map
        m=background_map([37.47,127.14])
        add_layers(m,plans(),['R03'])
        html=m.get_root().render()
        self.assertEqual(html.count('L.marker('),4)
        self.assertIn('R03-S01',html)
        self.assertIn('37.48000000',html)
        self.assertEqual(html.count('L.polyline('),0)

    def test_actual_menu_click_save_and_target_switch(self):
        fx=fixtures.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        fx.setUp()
        try:
            from streamlit.testing.v1 import AppTest
            event={'last_clicked':{'lat':37.48,'lng':127.14}}
            with patch('modules.new_stop_views.st_folium',return_value=event):
                app=AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run()
                app.sidebar.radio(key='main_menu').set_value('노선 및 운영 관리').run()
                app.radio(key='operations_section').set_value('신규 정류장 위치 설정').run()
                self.assertFalse(app.exception,str(app.exception))
                app.button(key='ns_save').click().run()
                self.assertFalse(app.error,str(app.error))
                self.assertEqual(settings.load()['stops']['R03-S01']['latitude'],37.48)
                with patch('modules.new_stop_views.save_stop',side_effect=OSError('test write denied')):
                    app.button(key='ns_save').click().run()
                    self.assertTrue(any('test write denied' in e.value for e in app.error))
            with patch('modules.new_stop_views.st_folium',return_value={}):
                app.selectbox(key='ns_stop_R03').set_value('R03-S02').run()
                self.assertTrue(app.button(key='ns_save').disabled)
                app.selectbox(key='ns_stop_R03').set_value('R03-BOKJEONG').run()
                self.assertTrue(app.button(key='ns_save').disabled)
                app.selectbox(key='ns_route').set_value('R04').run()
                self.assertFalse(app.exception,str(app.exception))
            with patch('modules.new_stop_views.st_folium',return_value={'last_clicked':{'lat':0,'lng':0}}):
                app.run()
                self.assertTrue(app.error)
        finally:
            fx.tearDown()
