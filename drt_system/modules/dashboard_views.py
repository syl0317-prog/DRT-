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
    valid = stops.copy()
    for key in ("latitude", "longitude"):
        valid[key] = pd.to_numeric(valid[key], errors="coerce")
    valid = valid.loc[valid.latitude.between(-90, 90) & valid.longitude.between(-180, 180)]
    if valid.empty:
        return None
    result = background_map(location=[float(valid.latitude.mean()), float(valid.longitude.mean())],
                            zoom_start=14, control_scale=True)
    import html
    for _, row in valid.iterrows():
        folium.CircleMarker([row.latitude, row.longitude], radius=7,
                            color="#e17a18" if row.stop_type == "tram" else "#2474d2",
                            fill=True, fill_opacity=.85,
                            tooltip=html.escape(f"{row.stop_name} ({row.stop_id})")).add_to(result)
    bounds_points = [[valid.latitude.min(), valid.longitude.min()], [valid.latitude.max(), valid.longitude.max()]]
    if route_state is not None:
        from modules.independent_route_views import overlay_routes
        overlay_routes(result, route_state, show_original=False, legacy_preview=legacy_preview)
        bounds_points.extend([[s["latitude"],s["longitude"]] for s in route_state["stops"]])
    result.fit_bounds(bounds_points, padding=(30, 30), max_zoom=15)
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
    st.header("통합 대시보드")
    st.caption("저장된 운영 데이터와 연구용 예측을 구분해 확인합니다.")
    reservations = load_reservations()
    from modules.unified_reservations import UnifiedReservations
    from modules.unified_reservation_views import records_frame
    try:
        all_records=UnifiedReservations().list_records()
        unified_frame=records_frame(all_records)
    except (OSError,ValueError,sqlite3.Error) as error:
        st.error(f"통합 예약 집계를 읽지 못했습니다: {error}")
        return
    count = st.session_state.get("vehicle_count", setting("vehicle_count"))
    snapshot = reservation_snapshot(unified_frame, count)
    from modules.independent_routes import RouteStore, RouteError
    try:
        route_state = RouteStore().snapshot()
    except (OSError, sqlite3.Error, RouteError) as error:
        route_state = None
        st.error(f"별도 신규 노선 등록부를 읽지 못했습니다: {error}")
    cols = st.columns(4)
    for col, label, value in zip(cols, ["통합 유효 접수", "통합 접수 승객", "설정 차량 수", "예약 배정 차량 수"],
                                 [snapshot["active_count"], snapshot["passengers"] if snapshot["passengers"] is not None else "확인 필요", count, snapshot["assigned_vehicles"]]):
        col.metric(label, value)
    review_count=int(unified_frame.status.eq("배차 검토 필요").sum())
    st.caption(f"기존 CSV·R02·통합 요청을 중복 없이 집계합니다. 배차 검토 필요 {review_count}건을 포함한 접수 건수이며 배차 완료 실적이 아닙니다. 날짜 미기록 예약이 있어 오늘 예약으로 해석하지 않습니다.")
    st.divider()
    st.subheader("운영 현황 · 저장 데이터")
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("**정류장 및 환승 거점 개요**")
        try:
            stops = pd.read_csv(stops_path(), dtype={"stop_id": str}, encoding="utf-8-sig")
            rendered = overview_map(stops, route_state, st.session_state.get("legacy_map_preview"))
            if rendered:
                st.iframe(rendered, height=350)
            else:
                st.info("표시 가능한 정류장 좌표가 없습니다.")
            st.caption(f"DRT 정류장 {int(stops.stop_type.eq('drt').sum())}개 · 환승 거점 {int(stops.stop_type.eq('tram').sum())}개 · 후보 좌표, 현장 검증 필요")
        except (OSError, ValueError, KeyError) as error:
            st.warning(f"정류장 개요를 읽지 못했습니다: {error}")
    with right:
        st.markdown("**예약 현황**")
        active = snapshot["active"]
        if active.empty:
            st.info("유효 예약이 없습니다.")
        else:
            table=active[["public_id","boarding_stop","destination_stop","requested_at","passengers","status","route_id","vehicle_id"]].fillna("미기록/미배정")
            st.dataframe(table.rename(columns={"public_id":"예약 ID","boarding_stop":"탑승","destination_stop":"하차","requested_at":"시각(저장 시간대)","passengers":"인원","status":"상태","route_id":"내부 경로","vehicle_id":"차량"}),hide_index=True)
        st.button("예약 관리로 이동", on_click=navigate, args=("예약 관리",))
        st.button("배차·경로로 이동", on_click=navigate, args=("배차·경로",))
        st.caption("배차 완료 건수·실제 운행시간은 기록이 없어 집계하지 않습니다.")

    if route_state is not None:
        from modules.independent_route_views import show_route_summary
        show_route_summary(route_state, reservations, all_records)
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
        st.button("정시·환승 분석으로 이동", on_click=navigate, args=("정시·환승 분석",))

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
