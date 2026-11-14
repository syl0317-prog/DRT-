"""First-run data and preservation checks, using temporary stores only."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("team_init", ROOT / "scripts/init_team_runtime.py")
team_init = importlib.util.module_from_spec(spec)
spec.loader.exec_module(team_init)


class TeamRuntimeTests(unittest.TestCase):
    def test_offline_analysis_and_all_catalog_map_points(self):
        import sys
        sys.path.insert(0, str(ROOT / "sewook31"))
        import requests
        from streamlit.testing.v1 import AppTest
        from modules.independent_routes import RouteStore
        from modules.unified_reservations import UnifiedReservations
        from modules.combined_routes import route_layers, add_layers
        from modules.map_background import background_map
        store = RouteStore()
        catalog = UnifiedReservations().catalog()
        self.assertEqual((len(catalog["boarding"]), len(catalog["trams"])), (8, 2))
        observed = set()
        for tram in ("T01", "T02"):
            routes = route_layers(store.original_loader(), store.snapshot(), ["D01", "D02", "D03", "D04"], tram)
            self.assertEqual([r["route_id"] for r in routes], ["R01", "R02"])
            observed.update(s["stop_id"] for r in routes for s in r["stops"])
            map_object = background_map([37.474, 127.143])
            add_layers(map_object, routes, ["R01", "R02"])
            self.assertEqual(map_object.get_root().render().count("L.circleMarker("), 0)
            self.assertEqual(map_object.get_root().render().count("L.marker("), 10)
        self.assertEqual(len(observed), 10)
        with patch("requests.sessions.Session.request", side_effect=requests.ConnectionError("offline verification")) as network:
            app = AppTest.from_file(str(ROOT / "sewook31/app.py"), default_timeout=60).run()
            app.sidebar.radio(key="main_menu").set_value("시뮬레이션 및 정시성 분석").run()
            app.radio(key="pa_mode").set_value("직접 입력").run()
            app.button(key="pa_run").click().run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertGreater(len(app.dataframe), 0)
            app.radio(key="analysis_section").set_value("정시성 계산·검증 결과").run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertGreater(len(app.get("vega_lite_chart")), 0)
            app.radio(key="analysis_section").set_value("운영전략 비교").run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertGreater(len(app.dataframe), 0)
            self.assertEqual(network.call_count, 0)

    def test_first_run_and_existing_reservations_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/seeds").mkdir(parents=True)
            shutil.copyfile(ROOT / "data/seeds/drt_routes.json", root / "data/seeds/drt_routes.json")
            result = team_init.initialize(root)
            self.assertEqual(set(result.values()), {"created"})
            paths = [root / relative for relative in result]
            with closing(sqlite3.connect(paths[0])) as connection:
                state = json.loads(connection.execute("SELECT payload FROM registry").fetchone()[0])
                self.assertEqual(len(state["stops"]), 4)
                self.assertEqual(len(state["segments"]), 3)
                self.assertEqual(state["bookings"], [])
            with closing(sqlite3.connect(paths[1])) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM requests").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT count(*) FROM csv_cancellations").fetchone()[0], 0)
                connection.execute("INSERT INTO requests VALUES('preserve','key','signature','{}')")
                connection.commit()
            before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
            self.assertEqual(set(team_init.initialize(root).values()), {"preserved"})
            self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_existing_non_database_files_are_not_opened(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/seeds").mkdir(parents=True)
            shutil.copyfile(ROOT / "data/seeds/drt_routes.json", root / "data/seeds/drt_routes.json")
            for relative in ("data/derived/drt_routes/routes.sqlite3", "data/derived/unified_reservations/reservations.sqlite3"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"existing file must stay unchanged")
            self.assertEqual(set(team_init.initialize(root).values()), {"preserved"})
            self.assertEqual(path.read_bytes(), b"existing file must stay unchanged")


if __name__ == "__main__":
    unittest.main()
