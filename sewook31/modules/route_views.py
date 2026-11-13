# UI copy of map_view: durable widgets and selectable web basemaps; routing unchanged.
from modules.settings import stops_path, setting

from pathlib import Path

import folium
from modules.map_background import background_map
import pandas as pd
from modules.session_ui import persistent_ui as st
from streamlit_folium import st_folium

from modules.route_engine import calculate_road_route


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

VWORLD_ROADS_FILE = (
    PROJECT_DIR / "data" / "vworld" / "wirye_road_links.geojson"
)
STOPS_FILE = stops_path()

import json

@st.cache_data
def load_vworld_roads():
    with open(VWORLD_ROADS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def show_legacy_route_settings():
    st.subheader("위례동 DRT 정류장 및 노선 관리")


    show_vworld = st.checkbox(
        "V-World 도로망 표시",
        value=False
    )

    # 정류장 데이터 불러오기
    stops = pd.read_csv(
        stops_path(),
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
    m = background_map(
        location=[37.474, 127.143],
        zoom_start=14,
        layer_control=False
    )
        # V-World 도로망 표시
    if show_vworld:
        if VWORLD_ROADS_FILE.is_file():
            roads = load_vworld_roads()

            folium.GeoJson(
                roads,
                name="V-World 도로망",
                style_function=lambda feature: {
                    "color": "green",
                    "weight": 2,
                    "opacity": 0.6
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["link_id", "road_name"],
                    aliases=["도로 링크 ID", "도로명"]
                )
            ).add_to(m)

            st.success(
                f"V-World 도로 링크 {len(roads['features']):,}개 로딩 완료"
            )

        else:
            st.warning("V-World 도로망 파일을 찾을 수 없습니다.")

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
    st.session_state.pop("legacy_map_preview", None)
    if len(route_coords) >= 2:

        with st.spinner("도로 경로 계산 중..."):
            road_route = calculate_road_route(route_coords, allow_network=False)

        if road_route:
            from datetime import datetime, timezone
            st.session_state["legacy_map_preview"] = dict(route=road_route, route_ids=route_ids,
                source="Existing user-selected temporary path; not a registered fixed route",
                generated_at=datetime.now(timezone.utc).isoformat())

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
    folium.LayerControl(collapsed=False).add_to(m)
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

    st.info("정류장 원본은 읽기 전용입니다. 변경 위치는 별도 검증이 필요합니다.")

    st.divider()

    # 방문 순서 표시
    st.subheader("현재 노선 방문 순서")

    for i, stop_id in enumerate(route_ids, start=1):
        st.write(f"{i}. {stop_names[stop_id]}")

    st.subheader("등록된 정류장")

    st.dataframe(
        stops,
        width="stretch"
    )


def show_drt_map():
    from modules.combined_routes import show_combined_map
    show_combined_map()
    with st.expander("기존 경유지 지도·좌표 확인"):
        show_legacy_route_settings()
