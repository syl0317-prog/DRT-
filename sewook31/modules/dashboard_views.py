"""Read-only overview: no route requests, dispatch calls or simulation execution."""
import hashlib
import json
import sqlite3
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from modules.session_ui import persistent_ui, scope
from modules.settings import PROJECT_DIR, setting, stops_path
from modules.reservation_manager import load_reservations
from modules.map_background import background_map


def reservation_snapshot(reservations, configured_vehicles):
    active = reservations.loc[reservations.status.isin(["예약완료","배차 검토 필요"])].copy()
    passengers = pd.to_numeric(active.passengers, errors="coerce")
    invalid = passengers.isna() | (passengers < 1) | (passengers % 1 != 0)
    return dict(active=active, active_count=len(active),
                passengers=None if invalid.any() else int(passengers.sum()),
                invalid_passenger_rows=int(invalid.sum()), configured_vehicles=int(configured_vehicles),
                assigned_vehicles=int(active.vehicle_id.dropna().nunique()))


def overview_map(stops, route_state=None, legacy_preview=None):
    """Station overview with web basemap; no editing or route requests."""
    from modules.combined_routes import route_layers, add_layers
    from modules.independent_routes import RouteStore
    result = background_map([37.474, 127.143], zoom_start=14, layer_control=False)
    store = RouteStore()
    routes = route_layers(store.original_loader(), route_state or store.snapshot())
    add_layers(result, routes, ["R01", "R02"])
    points = [[float(s["latitude"]), float(s["longitude"])] for r in routes for s in r["stops"]]
    if points:
        result.fit_bounds(points, padding=(30, 30))
    folium.LayerControl(collapsed=False).add_to(result)
    return result.get_root().render()


def matching_run():
    for path in sorted((PROJECT_DIR / "data/derived/gits_vworld").glob("*/matching_summary.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            current = all(hashlib.sha256((PROJECT_DIR / data["input_paths"][key]).read_bytes()).hexdigest() == digest
                          for key, digest in data["input_sha256"].items())
            candidates = pd.read_csv(path.parent / "matching_candidates.csv", dtype=str, encoding="utf-8-sig")
            verified = int(candidates.final_validation_status.eq("verified").sum())
            return dict(summary=data, directory=path.parent, current=current, verified=verified)
        except (OSError, ValueError, KeyError, AttributeError):
            continue
    return None


def navigate(menu):
    st.session_state["main_menu"] = menu
    st.session_state.setdefault("ui_saved_values", {})["main_menu"] = menu


def show_dashboard():
    from modules.dashboard_ui import show_operating_dashboard
    show_operating_dashboard(_show_research_monitoring)


def _show_research_monitoring(count,snapshot):
    st.divider()
    st.subheader("분석 및 모니터링")
    run = matching_run()
    left, right = st.columns(2)
    with left:
        st.markdown("**GITS 교통정보 · 매칭 검토**")
        if run:
            data = run["summary"]
            st.write(f"V-World {data['vworld_feature_count']:,}개 · GITS {data['gits_summary_rows']}개")
            st.write(f"ID 후보 {data['matched_candidate_rows']}개 · 미매칭 {data['unmatched_gits_rows']}개 · 검증 완료 {run['verified']}개")
            st.caption(f"결과 생성: {data['created_at_utc']} · 후보 상태 review_required · 실제 혼잡도 확정 아님")
            st.caption("GITS 자료: 엑셀 관측시각 미확인 · 이력 CSV는 2026-11-10 수집 스냅샷. 결과 생성 시각은 관측 시각이 아닙니다.")
            if not run["current"]:
                st.warning("저장 결과와 현재 입력의 해시가 다릅니다. 과거 분석 결과이며 재생성이 필요합니다.")
        else:
            st.info("출처를 확인할 수 있는 매칭 결과가 없습니다.")
    with right:
        st.markdown("**정시·환승 · 연구용 시뮬레이션**")
        research = st.session_state.get("punctuality_dashboard")
        if research and research.get("metadata", {}).get("route", {}).get("source"):
            selected = next(r for r in research["summary"] if r["scenario"] == research["selected"])
            st.write(f"예측 정시율 {selected['on_time_pct']:.1f}% · 환승 실패 {selected['transfer_failure_pct']:.1f}%")
            st.caption(f"실행 당시 조건 · {research['created_at']} · {research['selected']}")
            st.write(f"{research['origin_name']} → {research['destination_name']}")
            with st.expander("실행 조건과 출처"):
                st.json(research["metadata"])
        else:
            st.info("이번 세션에서 확인된 실행 결과가 없습니다. 정시율을 임의로 표시하지 않습니다.")
        st.button("시뮬레이션 및 정시성 분석으로 이동", on_click=navigate, args=("시뮬레이션 및 정시성 분석",))

    st.markdown("**최근 시뮬레이션 결과 · 운영 실적과 구분**")
    for key, title in [("shared_execution", "예약 기반 합승"), ("strategy_execution", "운영전략 비교"),
                       ("legacy_punctuality_execution", "기존 정시성 검증")]:
        record = st.session_state.get(key)
        if record:
            with st.expander(f"{title} · {record['created_at']}"):
                st.caption(record["source"])
                st.json(record["inputs"])
                value = record["value"]
                if isinstance(value, pd.DataFrame):
                    st.dataframe(value.astype(str), hide_index=True)
                else:
                    st.write({k: v for k, v in value.items() if k != "pickup_table"})
        else:
            st.caption(f"{title}: 이번 세션 실행 결과 없음")

    with st.expander("주요 알림 및 데이터 상태", expanded=True):
        st.write("트램 시각은 가상 시간표입니다. 정류장 좌표와 환승 보행시간의 현장 검증이 필요합니다.")
        st.write("GITS 후보는 검토 단계이며 실제 배차·운행시간 계산에 적용하지 않습니다.")
        available = {f"V{i:02d}" for i in range(1, int(count)+1)}
        if set(snapshot["active"].vehicle_id.dropna()) - available:
            st.warning("현재 차량 수 범위 밖에 기존 예약 차량이 있습니다. 자동 재배정하지 않습니다.")
        if snapshot["invalid_passenger_rows"]:
            st.warning("유효하지 않은 승객 수가 있어 합계를 표시하지 않습니다.")

    with scope("dashboard_detail"):
        detail = persistent_ui.radio("교통정보 상세 보기", ["요약만 보기", "GITS 상세 분석", "GITS 후보 지도"],
                                     horizontal=True, key="dashboard_detail")
    if detail == "GITS 상세 분석":
        from modules.detail_views import show_roads
        with scope("gits_roads"):
            show_roads()
    elif detail == "GITS 후보 지도":
        if run and (run["directory"] / "gits_vworld_review_map.html").is_file():
            st.caption(f"저장된 검토 지도 · 실행 결과 {run['directory'].name}")
            st.iframe(run["directory"] / "gits_vworld_review_map.html", height=700)
        else:
            st.info("생성된 지도 HTML이 없습니다.")
