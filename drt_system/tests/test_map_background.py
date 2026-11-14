"""Basemap configuration, failure notices, and unchanged marker/route interactions."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import folium
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "drt_system"))
from modules.map_background import background_map, TileLoadNotice, PROVIDERS
from modules.dashboard_views import overview_map


class BasemapTests(unittest.TestCase):
    def test_two_attributed_basemaps_with_only_default_active(self):
        map_object = background_map([37.474, 127.143], zoom_start=14)
        layers = [c for c in map_object._children.values() if isinstance(c, folium.TileLayer)]
        self.assertEqual(len(layers), 2)
        self.assertEqual([layer.show for layer in layers], [True, False])
        rendered = map_object.get_root().render()
        for provider in PROVIDERS:
            self.assertIn(provider["url"], rendered)
        self.assertIn("OpenStreetMap contributors", rendered)
        self.assertIn("strict-origin-when-cross-origin", rendered)
        self.assertIn("tileerror", rendered)
        self.assertIn("tileload", rendered)
        self.assertNotIn(layers[1].get_name()+".addTo(", rendered)
        self.assertEqual(map_object.location, [37.474, 127.143])
        self.assertEqual(map_object.options["zoom"], 14)
        self.assertTrue(map_object.options["zoom_control"])

    def test_dashboard_markers_bounds_and_no_osrm(self):
        stops = pd.read_csv(ROOT / "drt_system/data/drt_stops.csv")
        rendered = overview_map(stops)
        self.assertEqual(rendered.count("L.circleMarker("), 6)
        self.assertEqual(rendered.count('"color": "#e17a18"'), 2)
        self.assertEqual(rendered.count('"color": "#2474d2"'), 4)
        self.assertIn(".fitBounds(", rendered)
        self.assertNotIn("router.project-osrm.org", rendered)
        self.assertNotIn("L.polyline(", rendered)

    def test_route_markers_polyline_and_click_are_preserved(self):
        from streamlit.testing.v1 import AppTest
        from modules import route_views
        seen = []
        def render(map_object, **kwargs):
            seen.append(map_object)
            self.assertEqual(kwargs["returned_objects"], ["last_clicked"])
            return {"last_clicked": {"lat": 37.475, "lng": 127.145}}
        def route(coordinates, **kwargs):
            return dict(coordinates=coordinates, duration_min=12., distance_km=3.)
        with patch.object(route_views, "st_folium", side_effect=render), \
             patch.object(route_views, "calculate_road_route", side_effect=route) as router:
            app = AppTest.from_file(str(ROOT / "drt_system/app.py"), default_timeout=30).run()
            router.assert_not_called()
            app.sidebar.radio(key="main_menu").set_value("배차·경로").run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertGreater(router.call_count, 0)
            children = list(seen[-1]._children.values())
            self.assertEqual(sum(isinstance(c, folium.Marker) for c in children), 6)
            self.assertEqual(sum(isinstance(c, folium.PolyLine) for c in children), 1)
            self.assertEqual(sum(isinstance(c, folium.TileLayer) for c in children), 2)
            self.assertEqual(seen[-1].location, [37.474, 127.143])
            self.assertEqual(seen[-1].options["zoom"], 14)
            self.assertAlmostEqual(app.session_state["selected_lat"], 37.475)
            self.assertAlmostEqual(app.session_state["selected_lon"], 127.145)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_notice_javascript_error_recovery_and_timeout(self):
        map_object = background_map([37.474, 127.143])
        layers = [c for c in map_object._children.values() if isinstance(c, folium.TileLayer)]
        macro = next(c for c in map_object._children.values() if isinstance(c, TileLoadNotice))
        script = str(macro._template.module.script(macro, {}))
        harness = """
const assert = require('node:assert/strict');
var node, active=0, timers=[];
var L={control:()=>({addTo:function(map){this.onAdd();}}),
  DomUtil:{create:()=>{node={style:{},setAttribute:()=>{}};return node;}},
  DomEvent:{disableClickPropagation:()=>{}}};
var setTimeout=(fn)=>{timers.push(fn);};
function layer(){return {events:{},on:function(name,fn){this.events[name]=fn;}};}
"""
        harness += f"var {layers[0].get_name()}=layer(), {layers[1].get_name()}=layer();\n"
        harness += f"var layers=[{layers[0].get_name()},{layers[1].get_name()}];\n"
        harness += f"var {map_object.get_name()}={{hasLayer:(l)=>l===layers[active],on:()=>{{}}}};\n"
        harness += script + """
layers[0].events.tileerror({tile:{src:'failed-tile'}});
assert.equal(node.style.display,'block');
assert.ok(node.textContent.includes('로딩 실패'));
layers[0].events.tileload({tile:{src:'failed-tile'}});
assert.equal(node.style.display,'none');
active=1;layers[1].events.add();timers.forEach(fn=>fn());
assert.equal(node.style.display,'block');
assert.ok(node.textContent.includes('지연'));
layers[1].events.tileload({tile:{src:'loaded-tile'}});
assert.equal(node.style.display,'none');
"""
        checked = subprocess.run([shutil.which("node")], input=harness, text=True,
                                 encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        rendered = map_object.get_root().render()
        code = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", rendered, re.S))
        checked = subprocess.run([shutil.which("node"), "--check"], input=code, text=True,
                                 encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
