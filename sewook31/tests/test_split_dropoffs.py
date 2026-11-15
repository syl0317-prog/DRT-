"""Lossless migration, isolated dropoffs and display-only R04 straight line."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'sewook31'),str(ROOT/'sewook31/tests')]
from modules import new_stop_settings as settings
from modules.new_routes import plans, destination_stops
from modules.combined_routes import add_layers
from modules.map_background import background_map


class SplitDropoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.work')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'locations.json'
        active=patch('modules.new_stop_settings.SETTINGS_FILE',self.path)
        active.start();self.addCleanup(active.stop)
        self.legacy=dict(version=1,revision=10,stops={},roads={},custom_metadata={'keep':'unchanged'})
        points={'R03-S01':(37.49,127.15),'R03-S02':(37.485,127.145),
                'R04-S01':(37.48,127.14),'R04-S02':(37.475,127.135),'BOKJEONG':(37.47,127.13)}
        for sid,(lat,lon) in points.items():
            self.legacy['stops'][sid]=dict(latitude=lat,longitude=lon,source=settings.SOURCE,
                updated_at='legacy',access_status='검증 필요',custom_field='keep')
        for rid in ('R03','R04'):
            pts=[list(points[rid+'-S01']),list(points[rid+'-S02']),list(points['BOKJEONG'])]
            shape=[pts[0],[pts[0][0]-.001,pts[0][1]-.003],pts[1],
                   [pts[1][0]-.003,pts[1][1]-.001],pts[2]]
            road=dict(coordinates=shape,distance_km=3.4,duration_min=11.2,
                      source='OSRM TEST FIXTURE',retrieved_at='legacy')
            self.legacy['roads'][rid]=settings.checked_road(road,pts)
        self.path.write_text(json.dumps(self.legacy,ensure_ascii=False,indent=2),encoding='utf-8')
        self.original=self.path.read_bytes()

    def test_lossless_idempotent_migration_with_exact_backup_and_legacy_retained(self):
        projected=settings.load()
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertEqual(projected['version'],2)
        for rid in ('R03','R04'):
            self.assertEqual(projected['stops'][rid+'-BOKJEONG']['latitude'],37.47)
            self.assertEqual(projected['stops'][rid+'-BOKJEONG']['inherited_from'],'BOKJEONG')
        migrated=settings.migrate_file()
        self.assertEqual(migrated['revision'],11)
        self.assertEqual(migrated['roads'],self.legacy['roads'])
        for sid,row in self.legacy['stops'].items():
            self.assertEqual(migrated['stops'][sid],row)
        self.assertEqual(migrated['custom_metadata'],self.legacy['custom_metadata'])
        self.assertTrue(any(p.read_bytes()==self.original for p in (self.path.parent/'backups').glob('*.json')))
        current=self.path.read_bytes()
        settings.migrate_file()
        self.assertEqual(self.path.read_bytes(),current)
        self.assertEqual(len(list((self.path.parent/'backups').glob('*.json'))),1)
        # Mixed older settings with one explicitly saved split point keep it.
        mixed=copy.deepcopy(self.legacy)
        mixed['stops']['R03-BOKJEONG']=dict(mixed['stops']['BOKJEONG'],latitude=37.471)
        self.assertEqual(settings.migrate(mixed)['stops']['R03-BOKJEONG']['latitude'],37.471)

    def test_independent_updates_preserve_other_destination_and_road_and_restart(self):
        settings.migrate_file()
        for rid,other,lat in [('R03','R04',37.471),('R04','R03',37.472)]:
            before=settings.load()
            settings.save_stop(rid+'-BOKJEONG',lat,127.131,before['revision'])
            after=settings.load()
            self.assertEqual(after['stops'][other+'-BOKJEONG'],before['stops'][other+'-BOKJEONG'])
            self.assertEqual(after['roads'].get(other),before['roads'].get(other))
            self.assertNotIn(rid,after['roads'])
            self.assertEqual(after['stops']['BOKJEONG'],self.legacy['stops']['BOKJEONG'])
        code=('import sys,json;sys.path.insert(0,"sewook31");'
              'from modules.new_stop_settings import load;'
              'd=load(sys.argv[1]);print(json.dumps([d["stops"][r+"-BOKJEONG"]["latitude"] for r in ("R03","R04")]))')
        result=subprocess.check_output([sys.executable,'-B','-c',code,str(self.path)],cwd=ROOT,text=True)
        self.assertEqual(json.loads(result),[37.471,37.472])
        self.assertEqual([s['stop_id'] for s in destination_stops()],['R03-BOKJEONG','R04-BOKJEONG'])
        with self.assertRaises(ValueError):
            settings.save_stop('BOKJEONG',37.47,127.13,settings.load()['revision'])

    def test_complete_osrm_route_on_map_and_full_metrics_unchanged(self):
        r03,r04=plans()
        self.assertEqual(r04['paths'],[self.legacy['roads']['R04']['coordinates']])
        self.assertEqual(r03['display_paths'],r03['paths'])
        self.assertEqual(r04['distance_km'],3.4)
        self.assertEqual(r04['duration_min'],11.2)
        self.assertFalse(r04['road_complete'])
        self.assertEqual(r04['visualization_paths'],[])
        self.assertEqual(r04['display_paths'],r04['paths'])
        m=background_map([37.47,127.14]);add_layers(m,[r04],['R04'])
        layer=next(c for c in m._children.values() if c.__class__.__name__=='FeatureGroup')
        lines=[c for c in layer._children.values() if c.__class__.__name__=='PolyLine']
        self.assertEqual(len(lines),1)
        self.assertEqual([line.locations for line in lines],r04['paths'])
        self.assertTrue(all(line.options['color']=='#16A34A' for line in lines))
        self.assertNotIn('시각화용 직선',m.get_root().render())
        self.assertEqual(settings.load()['roads'],self.legacy['roads'])

    def test_missing_or_invalid_osrm_never_falls_back_to_a_straight_line(self):
        for mode in ('missing','reversed','stale','malformed'):
            data=copy.deepcopy(self.legacy)
            if mode=='missing':data['roads'].pop('R04')
            elif mode=='reversed':data['roads']['R04']['coordinates'].reverse()
            elif mode=='stale':data['roads']['R04']['coordinate_signature']='stale'
            else:data['roads']['R04']['coordinates']=[]
            self.path.write_text(json.dumps(data),encoding='utf-8')
            original=self.path.read_bytes()
            r04=plans()[1]
            self.assertFalse(r04['road_model_complete'])
            self.assertEqual(r04['display_paths'],[])
            self.assertEqual(r04['visualization_paths'],[])
            self.assertIsNone(r04['distance_km'])
            self.assertIsNone(r04['duration_min'])
            m=background_map([37.47,127.14]);add_layers(m,[r04],['R04'])
            self.assertNotIn('L.polyline(',m.get_root().render())
            self.assertEqual(self.path.read_bytes(),original)
            self.assertTrue(plans()[0]['road_model_complete'])

    def test_migration_failure_preserves_original_and_legacy_booking_audit(self):
        with patch('modules.new_stop_settings.os.replace',side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):settings.migrate_file()
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertTrue(any(p.read_bytes()==self.original for p in (self.path.parent/'backups').glob('*.json')))
        from modules.reservation_audit import audit_records
        from modules.independent_routes import RouteStore
        store=RouteStore()
        old=dict(route_id='R03',boarding_stop='R03-S01',destination_stop='BOKJEONG',
                 source='unified_sqlite',status='배차 검토 필요')
        original=copy.deepcopy(old)
        audited=audit_records([old],store.original_loader(),store.snapshot())[0]
        self.assertTrue(audited['policy_valid'])
        self.assertIn('이전 공통 복정역',audited['review_reason'])
        self.assertEqual(old,original)
