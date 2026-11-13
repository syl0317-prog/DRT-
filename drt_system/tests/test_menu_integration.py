"""Six-menu integration with real algorithms and isolated reservation writes."""
from contextlib import ExitStack
import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "drt_system"))
from modules.dashboard_views import reservation_snapshot, overview_map
from modules.reservation_manager import COLUMNS

MENUS = ["통합 대시보드", "예약 관리", "배차·경로", "정시·환승 분석", "운영 시뮬레이션", "관리·설정"]


def fake_route(coordinates, **kwargs):
    return dict(duration_min=5*(len(coordinates)-1), distance_km=len(coordinates)-1,
                coordinates=coordinates, source="TEST FIXTURE ONLY", retrieved_at="test", cache_hit=True)


class DashboardTests(unittest.TestCase):
    def test_reservation_metrics_and_invalid_passenger(self):
        frame = pd.DataFrame([
            dict(status="예약완료", passengers=2, vehicle_id="V01"),
            dict(status="예약완료", passengers=3, vehicle_id="V01"),
            dict(status="예약취소", passengers=9, vehicle_id="V02")])
        snapshot = reservation_snapshot(frame, 4)
        self.assertEqual((snapshot["active_count"], snapshot["passengers"], snapshot["assigned_vehicles"]), (2, 5, 1))
        frame.loc[0, "passengers"] = -1
        self.assertIsNone(reservation_snapshot(frame, 4)["passengers"])

    def test_overview_map_is_read_only_with_background_without_routes(self):
        stops = pd.read_csv(ROOT / "drt_system/data/drt_stops.csv")
        rendered = overview_map(stops)
        self.assertEqual(rendered.count("L.circleMarker("), 6)
        self.assertEqual(rendered.count("L.tileLayer("), 2)
        self.assertNotIn("router.project-osrm.org", rendered)
        self.assertNotIn("L.polyline(", rendered)


class MenuTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.stack = ExitStack()
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.reservation_path = Path(temp) / "reservations.csv"
        self.reservation_path.write_bytes((ROOT / "drt_system/data/reservations.csv").read_bytes())
        self.stack.enter_context(patch("modules.reservation_manager.RESERVATION_FILE", self.reservation_path))
        self.stack.enter_context(patch("modules.unified_reservations.DATABASE", Path(temp)/"unified.sqlite3"))
        self.route = self.stack.enter_context(patch("modules.route_views.calculate_road_route", side_effect=fake_route))
        self.stack.enter_context(patch("modules.route_views.st_folium", return_value={"last_clicked": None}))
        for module in ("integrated_scheduler", "pickup_scheduler", "reservation_manager"):
            self.stack.enter_context(patch(f"modules.{module}.calculate_road_route", side_effect=fake_route))
        self.app = AppTest.from_file(str(ROOT / "drt_system/app.py"), default_timeout=40).run()
        self.check()

    def tearDown(self):
        self.stack.close()

    def check(self):
        self.assertEqual(len(self.app.exception), 0, str(self.app.exception))

    def menu(self, name):
        self.app.sidebar.radio(key="main_menu").set_value(name).run()
        self.check()

    def test_all_ten_functions_accessible_and_hidden_calculations_not_run(self):
        app = self.app
        self.assertEqual(app.sidebar.radio(key="main_menu").options, MENUS)
        self.assertEqual([m.value for m in app.metric], ["6", "6", "4", "2"])
        self.route.assert_not_called()
        with patch("modules.detail_views.original_generate", wraps=__import__("modules.punctuality_sim", fromlist=["generate"]).generate) as old_sim, \
             patch("modules.detail_views.original_compare", wraps=__import__("modules.strategy_sim", fromlist=["compare"]).compare) as strategy:
            self.menu("예약 관리")
            self.assertTrue(any(button.label == "예약 신청" for button in app.button))
            self.menu("배차·경로")
            self.assertTrue(any(s.label == "목적지 트램 정거장" for s in app.selectbox))
            self.route.assert_called()
            app.radio(key="route_section").set_value("배차·픽업 계산").run()
            self.check()
            self.assertTrue(any(b.label == "자동 배차 및 픽업시간 계산" for b in app.button))
            self.menu("정시·환승 분석")
            self.assertTrue(any(b.key == "pa_run" for b in app.button))
            old_sim.assert_not_called()
            strategy.assert_not_called()
            app.radio(key="punctuality_section").set_value("기존 정시성 검증").run()
            self.check()
            self.assertTrue(any(b.label == "현재 전체 조건 결과 CSV 저장" for b in app.button))
            self.assertEqual(old_sim.call_count, 1)
            self.menu("운영 시뮬레이션")
            self.assertTrue(any(b.label == "합승 노선 계산" for b in app.button))
            strategy.assert_not_called()
            app.radio(key="simulation_section").set_value("운영전략 비교").run()
            self.check()
            self.assertEqual(strategy.call_count, 1)
            self.assertTrue(any(s.label.startswith("캐시 경로") for s in app.selectbox))
            self.menu("통합 대시보드")
            self.assertEqual(old_sim.call_count, 1)
            self.assertEqual(strategy.call_count, 1)
            app.radio(key="dashboard_detail").set_value("GITS 상세 분석").run()
            self.check()
            self.assertTrue(any(s.label == "교통자료 출처" for s in app.selectbox))
            self.assertGreaterEqual(len(app.dataframe), 3)
            app.radio(key="dashboard_detail").set_value("GITS 후보 지도").run()
            self.check()
            self.menu("관리·설정")
            self.assertTrue(any("관리자 패널" in h.value for h in app.header))
            self.assertGreater(len(app.dataframe), 0)

    def test_create_read_cancel_reservation_with_original_algorithm(self):
        pd.DataFrame(columns=COLUMNS).to_csv(self.reservation_path, index=False, encoding="utf-8-sig")
        self.menu("예약 관리")
        app = self.app
        from modules.reservation_manager import create_reservation,load_reservations,get_vehicle_status
        create_reservation("D01","T01","08:30",1)
        app.run()
        self.check()
        rows = pd.read_csv(self.reservation_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0].status, "예약완료")
        self.assertEqual(rows.iloc[0].passengers, 1)
        self.menu("통합 대시보드")
        self.assertEqual([m.value for m in app.metric][:2], ["1", "1"])
        self.menu("예약 관리")
        next(b for b in app.button if b.label == "선택 예약 취소").click().run()
        self.check()
        self.assertEqual(pd.read_csv(self.reservation_path).iloc[0].status, "예약완료")
        self.assertEqual(load_reservations().iloc[0].status,"예약취소")
        self.assertTrue((get_vehicle_status("T01","08:30")["예약 인원"]==0).all())
        self.menu("통합 대시보드")
        self.assertEqual([m.value for m in app.metric][:2], ["0", "0"])

    def test_dispatch_and_shared_results_survive_navigation(self):
        app = self.app
        self.menu("배차·경로")
        app.radio(key="route_section").set_value("배차·픽업 계산").run()
        next(b for b in app.button if b.label == "자동 배차 및 픽업시간 계산").click().run()
        self.check()
        record = app.session_state["dispatch_execution"]
        self.assertEqual(record["value"]["pickup_result"]["total_duration"], 28)
        expected = [m.value for m in app.metric]
        self.menu("통합 대시보드")
        self.menu("배차·경로")
        self.assertEqual(app.radio(key="route_section").value, "배차·픽업 계산")
        self.assertEqual([m.value for m in app.metric], expected)
        self.menu("운영 시뮬레이션")
        next(b for b in app.button if b.label == "합승 노선 계산").click().run()
        self.check()
        self.assertIn("pickup_table", app.session_state["shared_execution"]["value"])
        expected = [m.value for m in app.metric]
        self.menu("관리·설정")
        self.menu("운영 시뮬레이션")
        self.assertEqual([m.value for m in app.metric], expected)

    def test_research_result_and_inputs_survive_menu_navigation(self):
        app = self.app
        self.menu("정시·환승 분석")
        app.radio(key="pa_mode").set_value("직접 입력").run()
        app.number_input(key="pa_manual").set_value(19.).run()
        app.button(key="pa_run").click().run()
        self.check()
        expected = [m.value for m in app.metric]
        record = app.session_state["punctuality_dashboard"]
        self.assertEqual(record["metadata"]["route"]["duration_min"], 19)
        self.menu("통합 대시보드")
        self.assertTrue(any("예측 정시율" in m.value for m in app.markdown))
        self.menu("정시·환승 분석")
        self.assertEqual(app.radio(key="pa_mode").value, "직접 입력")
        self.assertEqual(app.number_input(key="pa_manual").value, 19)
        self.assertEqual([m.value for m in app.metric], expected)
        app.number_input(key="pa_manual").set_value(20.).run()
        self.assertEqual(len(app.metric), 0)

    def test_shortcut_navigation_and_vehicle_setting_persist(self):
        app = self.app
        app.sidebar.slider(key="vehicle_count").set_value(3).run()
        next(b for b in app.button if b.label == "예약 관리로 이동").click().run()
        self.check()
        self.assertEqual(app.sidebar.radio(key="main_menu").value, "예약 관리")
        self.menu("통합 대시보드")
        self.assertEqual(app.sidebar.slider(key="vehicle_count").value, 3)
        self.assertEqual(app.metric[2].value, "3")


if __name__ == "__main__":
    unittest.main()
