"""Streamlit UI for simulated DRT/tram live-control positions."""
from datetime import date, datetime, time, timedelta
from collections import defaultdict
from html import escape
import json
import math
from pathlib import Path
from urllib.parse import quote

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
PRESETS = {"평일 출근 07~09시": (time(7, 0), time(7, 0), time(9, 0)),
           "평일 퇴근 17~19시": (time(17, 0), time(17, 0), time(19, 0))}


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


def _reset_preset_clock(widget_key, service_day):
    selected = st.session_state.get(widget_key)
    if selected in PRESETS:
        start, default_time, end = PRESETS[selected]
        st.session_state["live_window"] = (datetime.combine(service_day, start), datetime.combine(service_day, end))
        st.session_state["live_time"] = datetime.combine(service_day, default_time)


def _nearest_monday(value):
    previous = value - timedelta(days=value.weekday())
    following = previous + timedelta(days=7)
    return previous if (value - previous) <= (following - value) else following


@st.cache_data(show_spinner=False, ttl=300)
def _window_summary(preset, service_day, start_text, end_text, fleet_size, route_class):
    day = date.fromisoformat(service_day)
    start_t, end_t = time.fromisoformat(start_text), time.fromisoformat(end_text)
    result = []
    for level in ("min", "mode", "max"):
        provider = SimulatedProvider(scenario=preset, vehicle_count=fleet_size, traffic_level=level,
                                     route_class=route_class, service_date=day,
                                     service_window=(start_t, end_t))
        trips = [trip for vehicle in provider.drt_trips.values() for trip in vehicle]
        slacks = [(trip["target_tram"] - trip["arrival"]).total_seconds() / 60 for trip in trips]
        result.append({"혼잡 수준": level + (" (최악 구간 기준)" if level == "max" and route_class == "진입간선" else ""),
                       "DRT 운행 횟수": len(trips), "환승 성공": sum(not trip["missed"] for trip in trips),
                       "환승 놓침": sum(bool(trip["missed"]) for trip in trips),
                       "평균 환승 여유(분)": round(sum(slacks) / len(slacks), 2) if slacks else None})
    return result


def _visible_text(value, fallback="정보 없음"):
    if value is None or value == "":
        return fallback
    return (str(value).replace("missing", "정보 없음").replace("Missing", "정보 없음")
            .replace("MISSING", "정보 없음"))


def _marker_color(p):
    if p.get("missed_transfer"):
        return "yellow", "red"
    if p.get("delay_min") and p["delay_min"] > 0:
        return "yellow", "#c99700"
    if p.get("status") in {"정차중", "대기"}:
        return "#9ca3af", "#6b7280"
    if str(p.get("vehicle_id", "")).startswith("TR-"):
        return "#ef4444", "#991b1b"
    return "#2563eb", "#1d4ed8"


def _add_base_layers(map_obj, provider, stops):
    # OpenStreetMap tiles are attempted online; the CSS canvas remains visible offline.
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
        is_drt_stop = stop.get("stop_type") == "drt"
        folium.CircleMarker([lat, lon], radius=5 if is_drt_stop else 4,
                            color="#1d4ed8" if is_drt_stop else "#b91c1c",
                            fill=True, fill_color="#3b82f6" if is_drt_stop else "#ef4444",
                            fill_opacity=0.9,
                            tooltip=f"{stop['stop_name']} ({stop['stop_id']})").add_to(map_obj)


def _add_position(map_obj, p, display_lat=None, display_lon=None):
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
    popup = (f"<b>{escape(_visible_text(p.get('vehicle_id')))}</b><br>"
             f"상태: {escape(_visible_text(p.get('status')))}<br>"
             f"다음 정류장: {escape(_visible_text(p.get('next_stop')))}<br>"
             f"도착 예정: {_clock_label(p.get('eta'))}<br>"
             f"연결 트램: {_visible_text(p.get('connected_tram_time'))}<br>"
             f"환승 여유: {_signed_duration(p.get('transfer_buffer_seconds'))}<br>"
             f"지연(분): {_visible_text(p.get('delay_min'))}")
    if str(p.get("vehicle_id", "")).startswith("TR-"):
        folium.CircleMarker([p["lat"], p["lon"]], radius=6, color=outline, weight=2,
                            fill=True, fill_color=fill, fill_opacity=0.95,
                            tooltip=f"{_visible_text(p.get('vehicle_id'))} · {_visible_text(p.get('status'))}",
                            popup=popup).add_to(map_obj)
        return
    shown_lat = p["lat"] if display_lat is None else display_lat
    shown_lon = p["lon"] if display_lon is None else display_lon
    vehicle_label = escape(str(p.get("vehicle_id", "DRT")))
    marker_html = (
        f'<div style="display:flex;flex-direction:column;align-items:center;white-space:nowrap;'
        f'font:600 10px/1.2 sans-serif;color:#111827;text-shadow:0 1px 2px #fff">'
        f'<span style="padding:2px 4px;background:#fff;border:1px solid #9ca3af;border-radius:3px">'
        f'{vehicle_label}</span><span style="margin-top:2px;width:10px;height:10px;border-radius:50%;'
        f'background:{fill};border:2px solid {outline};box-shadow:0 1px 3px #555"></span></div>'
    )
    folium.Marker([shown_lat, shown_lon], icon=folium.DivIcon(
        html=marker_html, icon_size=(48, 31), icon_anchor=(24, 29)),
        tooltip=f"{vehicle_label} · {escape(_visible_text(p.get('status')))}",
        popup=folium.Popup(popup, max_width=280)).add_to(map_obj)


def _display_positions(positions):
    """Return display-only offsets for coincident DRT markers; source coordinates stay intact."""
    groups = defaultdict(list)
    for index, position in enumerate(positions):
        if (str(position.get("vehicle_id", "")).startswith("TR-")
                or position.get("lat") is None or position.get("lon") is None):
            continue
        groups[(round(float(position["lat"]), 6), round(float(position["lon"]), 6))].append(index)
    display = {}
    for (lat, lon), indices in groups.items():
        if len(indices) == 1:
            point = positions[indices[0]]
            display[indices[0]] = (point["lat"], point["lon"])
            continue
        center = positions[indices[0]]
        center_lat, center_lon = float(center["lat"]), float(center["lon"])
        # Small deterministic screen-only ring (about five metres from the real point).
        for order, index in enumerate(indices):
            angle = 2 * math.pi * order / len(indices)
            north_m, east_m = 5 * math.sin(angle), 5 * math.cos(angle)
            display[index] = (center_lat + north_m / 111_320,
                              center_lon + east_m / (111_320 * max(math.cos(math.radians(center_lat)), 0.01)))
    return display


def _map_bounds(provider, stops, positions):
    points = []
    for feature in provider.get_station_features():
        props = feature.get("properties", {})
        if props.get("lat") is not None and props.get("lon") is not None:
            points.append([float(props["lat"]), float(props["lon"])])
    for stop in stops:
        if stop.get("stop_type") != "drt":
            continue
        try:
            points.append([float(stop["latitude"]), float(stop["longitude"])])
        except (KeyError, TypeError, ValueError):
            pass
    points.extend([[float(p["lat"]), float(p["lon"])] for p in positions
                   if p.get("lat") is not None and p.get("lon") is not None])
    if not points:
        return None
    return [[min(point[0] for point in points), min(point[1] for point in points)],
            [max(point[0] for point in points), max(point[1] for point in points)]]


def _add_legend(map_obj):
    legend = """<div style="position:fixed;z-index:9999;right:12px;bottom:22px;background:#fff;
    border:1px solid #9ca3af;border-radius:5px;padding:7px 9px;font:11px/1.55 sans-serif;
    box-shadow:0 1px 5px #777;">
    <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#ef4444;margin-right:5px"></i>트램</div>
    <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#2563eb;margin-right:5px"></i>DRT 운행중</div>
    <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#9ca3af;margin-right:5px"></i>DRT 정차·대기</div>
    <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#facc15;margin-right:5px"></i>지연</div>
    <div><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#facc15;border:2px solid #dc2626;margin-right:5px"></i>환승 놓침</div>
    <div><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#3b82f6;margin-right:5px"></i>가상정류장</div>
    <div><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;margin-right:5px"></i>트램 정거장</div>
    </div>"""
    map_obj.get_root().html.add_child(folium.Element(legend))


def _timestamped_features(snapshots):
    features = []
    for stamp, positions in snapshots:
        display_positions = _display_positions(positions)
        for index, p in enumerate(positions):
            if p.get("lat") is None or p.get("lon") is None:
                continue
            fill, outline = _marker_color(p)
            shown_lat, shown_lon = display_positions.get(index, (p["lat"], p["lon"]))
            details = (f"<b>{escape(_visible_text(p.get('vehicle_id')))}</b>"
                       f"<br>상태: {escape(_visible_text(p.get('status')))}"
                       f"<br>다음 정류장: {escape(_visible_text(p.get('next_stop')))}"
                       f"<br>도착 예정: {_clock_label(p.get('eta'))}"
                       f"<br>환승 여유: {_signed_duration(p.get('transfer_buffer_seconds'))}")
            props = {"time": stamp.isoformat(), "popup": details,
                     "tooltip": p["vehicle_id"], "icon": "circle"}
            if str(p.get("vehicle_id", "")).startswith("TR-"):
                props["iconstyle"] = {"fillColor": fill, "color": outline, "fillOpacity": 0.95,
                                       "stroke": True, "radius": 6}
            else:
                vehicle_label = escape(str(p.get("vehicle_id", "DRT")))
                svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="56" height="38" viewBox="0 0 56 38">'
                       f'<rect x="1" y="1" width="54" height="17" rx="3" fill="white" stroke="#9ca3af"/>'
                       f'<text x="28" y="13" text-anchor="middle" font-family="sans-serif" font-size="10" '
                       f'font-weight="bold" fill="#111827">{vehicle_label}</text>'
                       f'<circle cx="28" cy="29" r="6" fill="{fill}" stroke="{outline}" stroke-width="3"/></svg>')
                props["iconstyle"] = {"iconUrl": "data:image/svg+xml," + quote(svg),
                                       "iconSize": [56, 38], "iconAnchor": [28, 36]}
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [shown_lon, shown_lat]},
                             "properties": props})
    return {"type": "FeatureCollection", "features": features}


def _signed_duration(seconds):
    if seconds is None:
        return "정보 없음"
    seconds = int(round(seconds))
    sign = "−" if seconds < 0 else "+"
    minutes, remainder = divmod(abs(seconds), 60)
    return f"{sign}{minutes}분 {remainder:02d}초"


def _clock_label(value):
    if not value:
        return "정보 없음"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return _visible_text(value)


def show_live_control():
    st.header("🚦 실시간 관제")
    cfg = _config()
    vehicle_data = cfg.get("vehicle_count", {})
    fleet_size = int(vehicle_data.get("value", 0)) if isinstance(vehicle_data, dict) else int(vehicle_data or 0)
    if fleet_size < 1:
        st.warning("차량 수 정보가 없어 관제 위치를 계산할 수 없습니다.")
        return
    day = _nearest_monday(date.today())
    st.caption("평일 기준 · 저수요 시간대(낮·주말)는 이번 구현 범위에서 제외")
    if "live_preset" not in st.session_state or st.session_state["live_preset"] not in PRESETS:
        st.session_state["live_preset"] = next(iter(PRESETS))
    preset = st.session_state["live_preset"]
    default_start, default_time, default_end = PRESETS[preset]
    if "live_window" not in st.session_state:
        st.session_state["live_window"] = (datetime.combine(day, default_start), datetime.combine(day, default_end))
    if "live_time" not in st.session_state:
        st.session_state["live_time"] = datetime.combine(day, default_time)

    row1 = st.columns([1.5, 1.5, 4], vertical_alignment="bottom")
    with row1[0]:
        preset = st.selectbox("시나리오", list(PRESETS), key="live_preset",
                              on_change=_reset_preset_clock, args=("live_preset", day))
    window_key = "live_window"
    with row1[1]:
        traffic_level = st.selectbox("혼잡 수준", ["min", "mode", "max"], index=1, key="live_traffic_level")
    with row1[2]:
        window = st.slider("운행 시간대 조절", min_value=datetime.combine(day, time(6, 0)),
                           max_value=datetime.combine(day, time(22, 0)),
                           value=st.session_state[window_key], step=timedelta(minutes=30),
                           format="HH:mm", key=window_key)
    start_dt, end_dt = window
    if end_dt <= start_dt:
        end_dt = min(start_dt + timedelta(minutes=30), datetime.combine(day, time(22, 0)))
        window = (start_dt, end_dt)
        st.session_state[window_key] = window
    time_key = "live_time"
    if time_key not in st.session_state or not start_dt <= st.session_state[time_key] <= end_dt:
        st.session_state[time_key] = datetime.combine(day, default_time)
        st.session_state[time_key] = min(max(st.session_state[time_key], start_dt), end_dt)

    row2 = st.columns([6, 1.3, 1])
    with row2[0]:
        sim_time = st.slider("시뮬레이션 시각", min_value=start_dt, max_value=end_dt,
                             value=st.session_state[time_key], step=timedelta(minutes=1),
                             format="HH:mm", key=time_key)
    with row2[1]:
        st.button("재생 ▶ 1분 진행", key="live_step", on_click=_step_clock,
                  args=(time_key, end_dt), help="슬라이더 시각을 1분 이동합니다.", width="stretch")
    with row2[2]:
        st.button("정지 ■", key="live_stop", on_click=_stop_clock)

    with st.expander("고급 설정"):
        adv1, adv2, adv3, adv4 = st.columns([1, 1.3, 1.7, 2])
        with adv1:
            speed = st.selectbox("배속", [1, 10, 60], format_func=lambda x: f"{x}배", key="live_speed")
        with adv2:
            route_class = st.selectbox("OSRM 구간 가정", ["진입간선", "단지내"], key="live_route_class")
        with adv3:
            playback_mode = st.radio("표시 방식", ["시간 슬라이더", "지도 자동 재생"], horizontal=True, key="live_playback_mode")
        with adv4:
            duration_min = st.selectbox("자동 재생 범위", [15, 30, 60, 120], index=2, key="live_range")
        vehicle_count = st.slider("DRT 차량 수", 1, fleet_size, fleet_size, key="live_vehicle_count")

    service_window = (start_dt.time(), end_dt.time())
    provider = SimulatedProvider(scenario=preset, vehicle_count=vehicle_count,
                                 traffic_level=traffic_level, route_class=route_class,
                                 service_date=day, service_window=service_window)
    positions = provider.get_positions(sim_time)
    import csv
    stops_path = ROOT / "sewook31" / "data" / str(cfg.get("stops_file", "drt_stops.csv"))
    if not stops_path.exists():
        stops_path = ROOT / "sewook31" / "data" / "drt_stops.csv"
    with stops_path.open(encoding="utf-8-sig", newline="") as f:
        stops = list(csv.DictReader(f))

    headway = 15
    try:
        timetable = json.loads((ROOT / "data/assumptions/tram_timetable.json").read_text(encoding="utf-8"))["service"]
        hhmm = sim_time.strftime("%H:%M")
        headway = int(timetable.get("headway_off_peak", {}).get("value", 15))
        for peak in timetable.get("peak_periods", []):
            if peak.get("start") <= hhmm < peak.get("end"):
                headway = int(timetable.get("headway_peak", {}).get("value", 10))
                break
    except (OSError, ValueError, KeyError, TypeError):
        pass
    source = "data/processed/congestion_by_hour.csv" if route_class == "진입간선" else "sim_params.json 단지내 가정값"
    max_note = " · 최악 구간 기준" if traffic_level == "max" and route_class == "진입간선" else ""
    st.caption(f"{sim_time:%H:%M:%S} · {preset} · 혼잡 {traffic_level}{max_note} · 출처: {source} · 현재 트램 배차 {headway}분")

    signature = ("stations-stops-vehicles-v3", preset)
    scenario_changed = st.session_state.get("live_map_view_signature") != signature
    if scenario_changed:
        st.session_state.pop("live_map_center", None)
        st.session_state.pop("live_map_zoom", None)
        st.session_state["live_map_view_signature"] = signature
    saved_center = st.session_state.get("live_map_center", [37.474, 127.143])
    saved_zoom = st.session_state.get("live_map_zoom", 13)
    map_obj = folium.Map(location=saved_center, zoom_start=saved_zoom, tiles="OpenStreetMap", control_scale=True)
    map_obj.get_root().header.add_child(folium.Element("<style>.leaflet-container{background:#edf0f2 !important;}</style>"))
    _add_base_layers(map_obj, provider, stops)
    if playback_mode == "지도 자동 재생":
        try:
            if TimestampedGeoJson is None:
                raise RuntimeError("folium.plugins.TimestampedGeoJson을 사용할 수 없습니다.")
            end_time = min(sim_time + timedelta(minutes=duration_min), end_dt)
            features = _timestamped_features(provider.get_autoplay_positions(sim_time, end_time))
            if not features["features"]:
                raise RuntimeError("자동 재생용 위치가 없습니다.")
            TimestampedGeoJson(features, period="PT1M", duration="PT1M", transition_time=max(1, 200 // speed),
                               loop=False, auto_play=False, add_last_point=True, max_speed=speed,
                               loop_button=True, date_options="YYYY-MM-DD HH:mm", time_slider_drag_update=True).add_to(map_obj)
            st.caption(f"지도 자동 재생 위치 {len(features['features']):,}건을 1분 간격으로 미리 계산했습니다.")
        except Exception as exc:
            st.warning(f"자동 재생을 사용할 수 없어 시각 슬라이더로 전환했습니다: {type(exc).__name__}")
            for p in positions:
                _add_position(map_obj, p)
    else:
        displayed = _display_positions(positions)
        for i, p in enumerate(positions):
            _add_position(map_obj, p, *(displayed[i] if i in displayed else (None, None)))
    if scenario_changed:
        bounds = _map_bounds(provider, stops, positions)
        if bounds:
            map_obj.fit_bounds(bounds, padding=(24, 24), max_zoom=16)
    _add_legend(map_obj)
    map_state = st_folium(map_obj, width=None, height=520, returned_objects=["center", "zoom"], key="live_control_map")
    if isinstance(map_state, dict):
        center, zoom = map_state.get("center"), map_state.get("zoom")
        if isinstance(center, dict) and center.get("lat") is not None and center.get("lng") is not None:
            st.session_state["live_map_center"] = [center["lat"], center["lng"]]
        if isinstance(zoom, (int, float)):
            st.session_state["live_map_zoom"] = zoom

    st.caption("탑승 인원은 실제 예약 기록이 없어 시뮬레이션에서 집계하지 않았습니다")
    table = []
    for p in positions:
        is_tram = str(p.get("vehicle_id", "")).startswith("TR-")
        no_trip = not is_tram and (p.get("status") == "대기" or not p.get("trip_id"))
        dash = is_tram or no_trip
        table.append({"차량 번호": _visible_text(p.get("vehicle_id")), "상태": _visible_text(p.get("status")),
                      "탑승 인원": "-" if is_tram else (p.get("load") if p.get("load") is not None else "미집계"),
                      "다음 정류장": _visible_text(p.get("next_stop")), "도착 예정 시각": _clock_label(p.get("eta")),
                      "운행 번호": "-" if dash else _visible_text(p.get("trip_id")),
                      "연결 예정 트램 시각": "-" if dash else _visible_text(p.get("connected_tram_time")),
                      "설계 여유": "-" if dash else _signed_duration(p.get("planned_transfer_buffer_seconds")),
                      "혼잡 반영 후 여유": "-" if dash else _signed_duration(p.get("transfer_buffer_seconds")),
                      "지연(분)": "-" if dash else _visible_text(p.get("delay_min"))})
    if table:
        st.dataframe(pd.DataFrame(table).astype(str), hide_index=True, width="stretch")
    else:
        st.info("현재 시각에 운행 중인 열차나 경로가 준비된 DRT 차량이 없습니다.")
    try:
        summary = _window_summary(preset, day.isoformat(), service_window[0].isoformat(), service_window[1].isoformat(),
                                  vehicle_count, route_class)
        st.subheader("선택 시간대 요약")
        st.dataframe(pd.DataFrame(summary).astype(str), hide_index=True, width="stretch")
    except Exception as exc:
        st.warning(f"선택 시간대 요약 계산을 마치지 못했습니다: {type(exc).__name__}")
    for p in positions:
        if p.get("missed_transfer"):
            st.error(f"{_visible_text(p.get('vehicle_id'))} 환승 놓침(다음 트램까지 {_visible_text(p.get('next_tram_minutes'))}분)")
    for warning in provider.warnings:
        st.warning(_visible_text(warning))
    st.caption("지도 배경은 인터넷 연결 시에만 표시됩니다 · 지도 데이터 출처: © OpenStreetMap contributors")
    st.caption("OSRM 경로의 도로 종류는 링크별로 확인되지 않아 선택 구간 유형의 혼잡 계수를 전체 DRT 경로에 적용합니다(assumption).")
    st.info("개통 전이라 실제 GPS 데이터가 없어 시뮬레이션으로 표출합니다. 혼잡 계수는 위례 진입 간선 12개 구간 시간대별 속도 기반(평일, 시간 구간 대응은 추정)이고, 단지 내 구간은 가정값입니다. 실제 운영 시 차량 위치 데이터(API)로 교체됩니다.")

    st.caption("이 시스템의 트램 운행은 가상 시간표를 기준으로 설계된 시뮬레이션입니다.")
