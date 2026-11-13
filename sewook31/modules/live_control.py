"""Streamlit UI for simulated DRT/tram live-control positions."""
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

try:
    from folium.plugins import TimestampedGeoJson
except ImportError:
    TimestampedGeoJson = None

from modules.vehicle_positions import SimulatedProvider


ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "data" / "assumptions" / "sim_params.json"
PRESETS = {
    "평일 출근 07~09시": time(7, 0),
    "평일 퇴근 17~19시": time(17, 0),
    "평일 낮 호출형": time(12, 0),
    "주말": time(10, 0),
}


def _config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _step_clock(key, upper):
    current = st.session_state.get(key)
    if isinstance(current, datetime):
        st.session_state[key] = min(current + timedelta(minutes=1), upper)


def _stop_clock():
    st.session_state["live_playing"] = False


def _marker_color(p):
    if p.get("missed_transfer"):
        return "yellow", "red"
    if p.get("delay_min") and p["delay_min"] > 0:
        return "yellow", "#c99700"
    if p.get("status") == "정차중":
        return "#9ca3af", "#6b7280"
    if str(p.get("vehicle_id", "")).startswith("TR-"):
        return "#ef4444", "#991b1b"
    return "#2563eb", "#1d4ed8"


def _add_base_layers(map_obj, provider, stops):
    # No basemap tiles are requested: geometry remains visible on a white canvas offline.
    for feature in provider.get_track_features():
        coords = feature.get("geometry", {}).get("coordinates", [])
        props = feature.get("properties", {})
        if coords:
            folium.PolyLine([[lat, lon] for lon, lat in coords], color=props.get("color", "#0ea5e9"),
                            weight=4, opacity=0.75, tooltip=props.get("line_name", "트램 선로")).add_to(map_obj)
    for feature in provider.get_station_features():
        props = feature.get("properties", {})
        lat, lon = props.get("lat"), props.get("lon")
        if lat is not None and lon is not None:
            folium.CircleMarker([float(lat), float(lon)], radius=4, color="#b91c1c", fill=True,
                                fill_color="#ef4444", fill_opacity=0.85,
                                tooltip=f"트램 {props.get('station_no', '')} {props.get('station_name', '')}").add_to(map_obj)
    for stop in stops:
        try:
            lat, lon = float(stop["latitude"]), float(stop["longitude"])
        except (TypeError, ValueError):
            continue
        folium.Marker([lat, lon], tooltip=f"{stop['stop_name']} ({stop['stop_id']})",
                      icon=folium.Icon(color="blue" if stop.get("stop_type") == "drt" else "red",
                                       icon="bus" if stop.get("stop_type") == "drt" else "train",
                                       prefix="fa")).add_to(map_obj)


def _add_position(map_obj, p):
    if p.get("lat") is None or p.get("lon") is None:
        return
    past = p.get("_past_coordinates", [])
    future = p.get("_future_coordinates", [])
    if len(past) > 1:
        folium.PolyLine(past, color="#93c5fd", weight=4, opacity=0.45,
                        tooltip=f"{p['vehicle_id']} 지나온 길").add_to(map_obj)
    if len(future) > 1:
        folium.PolyLine(future, color="#60a5fa", weight=3, opacity=0.8,
                        dash_array="8, 8", tooltip=f"{p['vehicle_id']} 앞으로 갈 길").add_to(map_obj)
    fill, outline = _marker_color(p)
    popup = (f"<b>{p['vehicle_id']}</b><br>상태: {p.get('status', 'missing')}<br>"
             f"다음 정류장: {p.get('next_stop', 'missing')}<br>도착 예정: {p.get('eta') or 'missing'}<br>"
             f"연결 트램: {p.get('connected_tram_time') or 'missing'}<br>지연(분): {p.get('delay_min', 'missing')}")
    folium.CircleMarker([p["lat"], p["lon"]], radius=8, color=outline, weight=3,
                        fill=True, fill_color=fill, fill_opacity=0.95,
                        tooltip=f"{p['vehicle_id']} · {p.get('status')}", popup=popup).add_to(map_obj)


def _timestamped_features(snapshots):
    features = []
    for stamp, positions in snapshots:
        for p in positions:
            if p.get("lat") is None or p.get("lon") is None:
                continue
            fill, outline = _marker_color(p)
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                             "properties": {"time": stamp.isoformat(), "popup": f"{p['vehicle_id']} · {p.get('status')}",
                                            "tooltip": p["vehicle_id"],
                                            "icon": "circle", "iconstyle": {"fillColor": fill, "color": outline,
                                                                                 "fillOpacity": 0.95, "stroke": True,
                                                                                 "radius": 7}}})
    return {"type": "FeatureCollection", "features": features}


def _signed_duration(seconds):
    if seconds is None:
        return "missing"
    seconds = int(round(seconds))
    sign = "−" if seconds < 0 else "+"
    minutes, remainder = divmod(abs(seconds), 60)
    return f"{sign}{minutes}분 {remainder:02d}초"


def _clock_label(value):
    if not value:
        return "missing"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def show_live_control():
    st.header("🚦 실시간 관제")
    cfg = _config()
    vehicle_data = cfg.get("vehicle_count", {})
    fleet_size = int(vehicle_data.get("value", 0)) if isinstance(vehicle_data, dict) else int(vehicle_data or 0)
    if fleet_size < 1:
        st.warning("차량 수가 missing이어서 관제 위치를 계산할 수 없습니다.")
        return

    preset = st.selectbox("시나리오 프리셋", list(PRESETS), key="live_preset")
    today = date.today()
    lower = datetime.combine(today, time(6, 0))
    upper = datetime.combine(today + timedelta(days=1), time(0, 0))
    default = datetime.combine(today, PRESETS[preset])
    slider_key = f"live_time_{preset}"
    if slider_key not in st.session_state:
        st.session_state[slider_key] = default

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        sim_time = st.slider("시뮬레이션 시각", min_value=lower, max_value=upper,
                             step=timedelta(minutes=1),
                             format="HH:mm", key=slider_key)
    with col2:
        traffic_level = st.selectbox("혼잡 수준", ["min", "mode", "max"], index=1, key="live_traffic_level")
    with col3:
        route_class = st.selectbox("OSRM 경로 구간 가정", ["진입간선", "단지내"], key="live_route_class")

    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 2])
    with ctrl1:
        st.button("재생 ▶ 1분 진행", key="live_step", on_click=_step_clock,
                  args=(slider_key, upper), help="수동 모드의 안정적인 한 단계 재생입니다.")
    with ctrl2:
        st.button("정지 ■", key="live_stop", on_click=_stop_clock)
    with ctrl3:
        speed = st.selectbox("배속", [1, 10, 60], format_func=lambda x: f"{x}배", key="live_speed")
    with ctrl4:
        vehicle_count = st.slider("DRT 차량 수", 1, fleet_size, fleet_size, key="live_vehicle_count")

    playback_mode = st.radio("표시 방식", ["시간 슬라이더", "지도 자동 재생"], horizontal=True,
                             help="기본은 시각 슬라이더입니다. 자동 재생은 1분 단위 위치를 미리 계산합니다.")
    duration_min = st.selectbox("자동 재생 범위(분)", [15, 30, 60, 120], index=2, key="live_range")

    provider = SimulatedProvider(scenario=preset, vehicle_count=vehicle_count,
                                 traffic_level=traffic_level, route_class=route_class, service_date=today)
    positions = provider.get_positions(sim_time)
    stops = []
    with (ROOT / "sewook31" / "data" / "drt_stops.csv").open(encoding="utf-8-sig", newline="") as f:
        import csv
        stops = list(csv.DictReader(f))

    map_obj = folium.Map(location=[37.474, 127.143], zoom_start=13, tiles=None, control_scale=True)
    _add_base_layers(map_obj, provider, stops)
    if playback_mode == "지도 자동 재생":
        try:
            if TimestampedGeoJson is None:
                raise RuntimeError("folium.plugins.TimestampedGeoJson is missing")
            end_time = min(sim_time + timedelta(minutes=duration_min), upper)
            snapshots = provider.get_autoplay_positions(sim_time, end_time)
            data = _timestamped_features(snapshots)
            if data["features"]:
                TimestampedGeoJson(data, period="PT1M", duration="PT1M", transition_time=max(1, 200 // speed),
                                   loop=False, auto_play=False, add_last_point=True,
                                   max_speed=speed, loop_button=True,
                                   date_options="YYYY-MM-DD HH:mm", time_slider_drag_update=True).add_to(map_obj)
                st.caption(f"지도 자동 재생용 위치 {len(data['features']):,}건을 1분 간격으로 미리 계산했습니다.")
            else:
                st.warning("자동 재생 위치가 없어 시간 슬라이더 화면으로 표시합니다.")
                for p in positions:
                    _add_position(map_obj, p)
        except Exception as exc:
            st.warning(f"자동 재생 플러그인을 사용할 수 없어 슬라이더 화면으로 전환했습니다: {type(exc).__name__}")
            for p in positions:
                _add_position(map_obj, p)
    else:
        for p in positions:
            _add_position(map_obj, p)

    st_folium(map_obj, width=None, height=590, returned_objects=[], key="live_control_map")

    table = []
    for p in positions:
        tram_time = p.get("connected_tram_time")
        buffer_value = p.get("transfer_buffer_seconds")
        table.append({"차량 번호": p["vehicle_id"], "상태": p.get("status", "missing"),
                      "탑승 인원": p.get("load") if p.get("load") is not None else "missing",
                      "다음 정류장": p.get("next_stop") or "missing",
                      "도착 예정 시각": _clock_label(p.get("eta")),
                      "운행 번호": p.get("trip_id") or "missing",
                      "연결 예정 트램 시각": tram_time or "missing",
                      "설계 여유": _signed_duration(p.get("planned_transfer_buffer_seconds")),
                      "혼잡 반영 후 여유": _signed_duration(buffer_value),
                      "지연(분)": p.get("delay_min") if p.get("delay_min") is not None else "missing"})
    if table:
        st.dataframe(pd.DataFrame(table).astype(str), hide_index=True, width="stretch")
    else:
        st.info("현재 시각에 운행 중인 열차나 경로가 준비된 DRT 차량이 없습니다.")

    missed = [p for p in positions if p.get("missed_transfer")]
    for p in missed:
        n = p.get("next_tram_minutes")
        st.error(f"{p['vehicle_id']} 환승 놓침(다음 트램까지 {n if n is not None else 'missing'}분)")
    capacity_data = cfg.get("vehicle_capacity", {})
    capacity_value = capacity_data.get("value") if isinstance(capacity_data, dict) else None
    capacity_label = f"차량 정원 {capacity_value}명(status={capacity_data.get('status', 'missing')})" if capacity_value is not None else "차량 정원 missing"
    st.caption(f"탑승 인원: 시뮬레이션 예약 기반(가상) — apartment_classification.csv와 거리 가중치가 없어 현재 load는 missing입니다. {capacity_label}. 실제 예약 기록과는 분리되어 있습니다.")
    warning_categories = provider.get_warning_categories()
    if warning_categories:
        for category, messages in warning_categories.items():
            with st.expander(f"{category} ({len(messages)})"):
                for warning in messages:
                    st.warning(warning)

    if preset == "주말":
        st.caption("주말 혼잡 관측값은 missing이며, 현재 진입간선 값은 평일 자료를 대입한 assumption입니다.")
    st.caption("OSRM 경로의 도로 종류는 현재 링크별로 확인되지 않아, 선택한 구간 유형의 혼잡 계수를 전체 DRT 경로에 적용합니다(assumption).")
    st.info("개통 전이라 실제 GPS 데이터가 없어 시뮬레이션으로 표출합니다. 혼잡 계수는 위례 진입 간선 12개 구간 시간대별 속도 기반(평일, 시간 구간 대응은 추정)이고, 단지 내 구간은 가정값입니다. 실제 운영 시 차량 위치 데이터(API)로 교체됩니다.")
