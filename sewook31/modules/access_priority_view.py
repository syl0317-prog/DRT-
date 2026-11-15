"""Apartment access classification and service-priority Streamlit tab."""
import json
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules.access_priority import classify_and_rank

ROOT = Path(__file__).resolve().parents[2]
PARAMS = ROOT / "data/assumptions/classification_params.json"
ACCESS = ROOT / "data/processed/apartment_access.csv"
BUS = ROOT / "data/processed/bus_stops_wirye_300m.csv"
TRAM = ROOT / "data/processed/wirye_tram_official_stations.geojson"


def _load():
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    access = pd.read_csv(ACCESS, encoding="utf-8-sig")
    bus = pd.read_csv(BUS, encoding="utf-8-sig") if BUS.exists() else pd.DataFrame()
    stations = pd.read_json(TRAM) if False else json.loads(TRAM.read_text(encoding="utf-8"))["features"]
    return params, access, bus, stations


def show_access_priority():
    st.header("이용객 유형 구분")
    st.write("트램 700m 안은 도보입니다.")
    st.write("버스 500m 안은 시내버스입니다.")
    st.write("둘 다 어려운 단지에 DRT를 투입하고 접근거리가 먼 단지부터 우선 서비스합니다.")
    try:
        params, base, buses, stations = _load()
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"접근거리 자료를 읽지 못했습니다: {type(exc).__name__}")
        return
    c1, c2, c3 = st.columns(3)
    tram_limit = c1.slider("트램 기준(m)", 0, 2000, int(params["tram_walk_threshold_m"]), 50)
    bus_limit = c2.slider("버스 기준(m)", 0, 1500, int(params["bus_walk_threshold_m"]), 50)
    stop_n = c3.slider("서비스 정류장 수 N", 1, int(params["max_service_stops"]),
                       int(params["service_stop_count"]), 1)
    records, summary = classify_and_rank(base.to_dict("records"), tram_limit, bus_limit,
                                          stop_n, int(params["max_service_stops"]))
    frame = pd.DataFrame(records)
    typ = frame.groupby("유형", dropna=False).agg(단지수=("단지명", "count"), 세대수=("세대수", "sum")).reset_index()
    drt_households = summary["drt_target_households"]
    covered = summary["served_drt_target_households"]
    ratio = covered / drt_households if drt_households else None
    a, b, c = st.columns(3)
    a.metric("분석 단지", summary["analysis_count"])
    b.metric(f"서비스 {stop_n}곳 커버 세대", f"{summary['service_households']:,}")
    c.metric("DRT대상 커버 비율", f"{ratio:.1%}" if ratio is not None else "미집계")
    st.dataframe(typ, use_container_width=True, hide_index=True)

    with st.expander("지도 설정", expanded=True):
        show_bus = st.checkbox("버스정류장 표시", True)
        show_line = st.checkbox("선택 단지와 가까운 정류장 연결", True)
    valid = frame.dropna(subset=["위도", "경도"]).copy()
    if valid.empty:
        st.warning("좌표가 확인된 단지가 없어 지도를 표시할 수 없습니다.")
        return
    selected_name = st.selectbox("연결선을 볼 단지", valid["단지명"].tolist())
    center = [valid["위도"].astype(float).mean(), valid["경도"].astype(float).mean()]
    m = folium.Map(location=center, zoom_start=14, tiles="OpenStreetMap", control_scale=True)
    m.get_root().header.add_child(folium.Element("<style>.leaflet-container{background:#edf0f2 !important;}</style>"))
    colors = {"도보형": "green", "버스형": "blue", "DRT대상": "red", "타 지자체 협의 필요": "gray", "미집계": "gray"}
    ranked = frame.sort_values("우선순위", na_position="last")
    rank_map = {r["단지명"]: r["우선순위"] for _, r in ranked.iterrows() if pd.notna(r["우선순위"]) and int(r["우선순위"]) <= stop_n}
    for _, row in valid.iterrows():
        hh = pd.to_numeric(row.get("세대수"), errors="coerce")
        radius = min(11, max(4, 3 + (float(hh) ** 0.5 / 18 if pd.notna(hh) else 0)))
        label = f"{int(rank_map[row['단지명']])}: {row['단지명']}" if row["단지명"] in rank_map else str(row["단지명"])
        folium.CircleMarker([float(row["위도"]), float(row["경도"])], radius=radius,
                            color=colors.get(row["유형"], "gray"), fill=True,
                            fill_color=colors.get(row["유형"], "gray"), fill_opacity=.8,
                            tooltip=label, popup=f"{row['단지명']} · {row['유형']}").add_to(m)
    for feature in stations:
        p = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"][:2]
        folium.CircleMarker([lat, lon], radius=4, color="#9b1c1c", fill=True,
                            fill_color="#ef4444", tooltip=p.get("station_name", "트램정거장")).add_to(m)
    if show_bus and not buses.empty:
        for row in buses[buses["위례동내부"] == "Y"].itertuples(index=False):
            folium.CircleMarker([row.위도, row.경도], radius=2, color="#2563eb", fill=True,
                                fill_color="#60a5fa", fill_opacity=.7, tooltip=row.stop_name).add_to(m)
    if show_line:
        row = valid[valid["단지명"] == selected_name].iloc[0]
        latlon = [float(row["위도"]), float(row["경도"])]
        if row["가장가까운수단"] == "트램":
            feature = min(stations, key=lambda f: ((f["geometry"]["coordinates"][0] - latlon[1]) ** 2 + (f["geometry"]["coordinates"][1] - latlon[0]) ** 2))
            coords = feature["geometry"]["coordinates"]
            target = [coords[1], coords[0]]
        else:
            candidates = buses[buses["위례동내부"] == "Y"]
            if candidates.empty:
                target = None
            else:
                nearest = ((candidates["경도"] - latlon[1]) ** 2 + (candidates["위도"] - latlon[0]) ** 2).idxmin()
                target = [float(candidates.loc[nearest, "위도"]), float(candidates.loc[nearest, "경도"])]
        if target:
            folium.PolyLine([latlon, target], color="#111827", weight=2, dash_array="5,5").add_to(m)
    st_folium(m, height=500, use_container_width=True, key="access_priority_map")
    ranking = frame[frame["우선순위"].notna()][["우선순위", "단지명", "세대수", "트램도보추정_m", "버스도보추정_m",
                    "접근거리_m", "유형", "누적세대수"]]
    ranking = ranking.rename(columns={"트램도보추정_m": "트램 도보 추정(m)", "버스도보추정_m": "버스 도보 추정(m)", "접근거리_m": "접근거리(m)"})
    st.dataframe(ranking, use_container_width=True, hide_index=True)
    st.caption("관제 탭은 drt_stops_v2.csv를 사용합니다.")
    st.caption("접근거리는 직선거리 x 1.3(도보 추정)이고 버스 운행 빈도는 반영하지 않았습니다. 좌표는 카카오 대표 좌표입니다.")
