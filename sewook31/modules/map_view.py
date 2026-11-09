
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules.route_engine import calculate_road_route


BASE_DIR = Path(__file__).resolve().parent.parent
STOPS_FILE = BASE_DIR / "data" / "drt_stops.csv"


def show_drt_map():

    st.subheader("위례동 DRT 정류장 및 노선 관리")

    # 정류장 데이터 불러오기
    stops = pd.read_csv(
        STOPS_FILE,
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    valid_stops = stops.dropna(
        subset=["latitude", "longitude"]
    ).copy()

    stop_names = dict(
        zip(stops["stop_id"], stops["stop_name"])
    )

    # 노선 설정
    st.markdown("### DRT 운행 노선 설정")

    drt_stops = valid_stops[
        valid_stops["stop_type"] == "drt"
    ]

    tram_stops = valid_stops[
        valid_stops["stop_type"] == "tram"
    ]

    route_stops = st.multiselect(
        "경유할 DRT 정류장 선택",
        drt_stops["stop_id"].tolist(),
        default=drt_stops["stop_id"].tolist(),
        format_func=lambda x: f"{x} - {stop_names[x]}"
    )

    if tram_stops.empty:
        st.warning("트램 정거장 좌표를 먼저 등록해 주세요.")
        return

    destination = st.selectbox(
        "목적지 트램 정거장",
        tram_stops["stop_id"].tolist(),
        format_func=lambda x: f"{x} - {stop_names[x]}"
    )

    # 지도 생성
    m = folium.Map(
        location=[37.474, 127.143],
        zoom_start=14
    )

    for _, stop in valid_stops.iterrows():

        color = (
            "red"
            if stop["stop_type"] == "tram"
            else "blue"
        )

        folium.Marker(
            location=[
                stop["latitude"],
                stop["longitude"]
            ],
            tooltip=stop["stop_name"],
            popup=f"{stop['stop_name']} / {stop['zone']}",
            icon=folium.Icon(color=color)
        ).add_to(m)

    # 경유 정류장 + 목적지
    route_ids = route_stops + [destination]

    route_coords = []

    for stop_id in route_ids:

        row = valid_stops[
            valid_stops["stop_id"] == stop_id
        ].iloc[0]

        route_coords.append([
            float(row["latitude"]),
            float(row["longitude"])
        ])

    # 실제 도로 기반 노선 계산
    if len(route_coords) >= 2:

        with st.spinner("도로 경로 계산 중..."):
            road_route = calculate_road_route(route_coords)

        if road_route:

            folium.PolyLine(
                road_route["coordinates"],
                color="blue",
                weight=5,
                opacity=0.85,
                tooltip="도로 기반 DRT 운행 노선"
            ).add_to(m)

            col1, col2 = st.columns(2)

            col1.metric(
                "전체 운행거리",
                f"{road_route['distance_km']:.2f} km"
            )

            col2.metric(
                "예상 운행시간",
                f"{road_route['duration_min']:.1f} 분"
            )

            st.caption(
                "일반 자동차 도로 경로 기준 추정치이며, "
                "실제 DRT 운행시간과 다를 수 있습니다."
            )

        else:

            st.warning(
                "도로 경로를 계산하지 못해 "
                "임시 직선 노선을 표시합니다."
            )

            folium.PolyLine(
                route_coords,
                color="gray",
                weight=3,
                dash_array="8, 8"
            ).add_to(m)

    # 지도 표시 및 클릭 위치 확인
    map_data = st_folium(
        m,
        height=550,
        width=None,
        returned_objects=["last_clicked"]
    )

    clicked = (
        map_data.get("last_clicked")
        if map_data
        else None
    )

    if clicked:
        st.session_state["selected_lat"] = clicked["lat"]
        st.session_state["selected_lon"] = clicked["lng"]

    st.divider()

    # 정류장 좌표 등록
    st.subheader("정류장 위치 등록 및 수정")

    lat = st.session_state.get("selected_lat")
    lon = st.session_state.get("selected_lon")

    if lat is not None and lon is not None:
        st.success(
            f"선택 위치: {lat:.6f}, {lon:.6f}"
        )
    else:
        st.info("지도에서 위치를 클릭하세요.")

    selected_id = st.selectbox(
        "정류장 선택",
        stops["stop_id"].tolist(),
        format_func=lambda x: f"{x} - {stop_names[x]}"
    )

    if st.button("선택 위치 저장"):

        if lat is None or lon is None:
            st.warning("먼저 지도에서 위치를 클릭하세요.")

        else:
            mask = stops["stop_id"] == selected_id

            stops.loc[mask, "latitude"] = lat
            stops.loc[mask, "longitude"] = lon

            stops.to_csv(
                STOPS_FILE,
                index=False,
                encoding="utf-8-sig"
            )

            st.success("정류장 위치 저장 완료")
            st.rerun()

    st.divider()

    # 방문 순서 표시
    st.subheader("현재 노선 방문 순서")

    for i, stop_id in enumerate(route_ids, start=1):
        st.write(f"{i}. {stop_names[stop_id]}")

    st.subheader("등록된 정류장")

    st.dataframe(
        stops,
        use_container_width=True
    )
