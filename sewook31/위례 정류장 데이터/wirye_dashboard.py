
import streamlit as st
import pandas as pd
import folium
from folium import plugins
from streamlit_folium import st_folium
from pathlib import Path
import html
import json

# ==========================================
# 1. 페이지 기본 설정
# ==========================================

st.set_page_config(
    page_title="위례동 모빌리티 분석",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. 디자인 CSS
# ==========================================

st.markdown("""
<style>
    .stApp {
        background-color: #F5F7FB;
    }

    [data-testid="stSidebar"] {
        background-color: #15263F;
    }

    [data-testid="stSidebar"] * {
        color: #F1F5F9;
    }

    [data-testid="stSidebar"] input {
        color: #15263F !important;
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }

    h1, h2, h3 {
        color: #15263F;
    }

    [data-testid="stMetric"] {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 18px;
        box-shadow: 0 2px 8px rgba(15,23,42,0.04);
    }

    [data-testid="stMetricLabel"] {
        color: #64748B;
    }

    [data-testid="stMetricValue"] {
        color: #15263F;
    }

    .section-heading {
        font-size: 19px;
        font-weight: 700;
        color: #15263F;
        margin: 12px 0;
    }

    .info-panel {
        background: white;
        padding: 18px;
        border-radius: 14px;
        border: 1px solid #E2E8F0;
        margin-bottom: 12px;
    }

    .small-muted {
        color: #64748B;
        font-size: 13px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 기본 데이터
# ==========================================

FOLDER = Path(__file__).resolve().parent

ROUTE_FILE = (
    FOLDER / "위례동_13개정류장_버스노선_통합분석.xlsx"
)

LOCATION_FILE = (
    FOLDER / "위례동_버스정류장_위치정보.xlsx"
)

BUS_ROUTES = [
    "31", "38", "60", "200", "210",
    "231", "315", "331", "위례-01"
]

BUS_STOPS = [
    "28370", "28469", "28470", "28471",
    "28473", "05174", "05290", "05291",
    "05292", "05293", "05294", "28372",
    "28468"
]

# ==========================================
# 4. 데이터 불러오기
# ==========================================

@st.cache_data
def load_route_data():
    df = pd.read_excel(ROUTE_FILE, dtype=str)
    df.columns = df.columns.astype(str).str.strip()

    required = ["정류장번호"] + BUS_ROUTES

    missing = [
        c for c in required if c not in df.columns
    ]

    if missing:
        raise ValueError(
            f"노선 엑셀에 필요한 열이 없습니다: {missing}"
        )

    df["정류장번호"] = (
        df["정류장번호"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(5)
    )

    df = df[
        df["정류장번호"].isin(BUS_STOPS)
    ].copy()

    for route in BUS_ROUTES:
        df[route] = (
            df[route]
            .fillna("X")
            .astype(str)
            .str.strip()
            .str.upper()
        )

    df["경유노선수"] = (
        df[BUS_ROUTES] == "O"
    ).sum(axis=1)

    return df.drop_duplicates("정류장번호")


def find_column(columns, keywords):
    for col in columns:
        normalized = (
            str(col).lower().replace(" ", "").replace("_", "")
        )
        for keyword in keywords:
            if keyword.lower().replace("_", "") in normalized:
                return col
    return None


@st.cache_data
def load_location_data():
    loc = pd.read_excel(LOCATION_FILE, dtype=str)
    loc.columns = loc.columns.astype(str).str.strip()

    stop_col = find_column(
        loc.columns,
        ["정류장번호", "정류소번호", "nodeno"]
    )

    lat_col = find_column(
        loc.columns,
        ["위도", "latitude", "gpslati", "lat"]
    )

    lon_col = find_column(
        loc.columns,
        ["경도", "longitude", "gpslong", "lon"]
    )

    if not all([stop_col, lat_col, lon_col]):
        raise ValueError(
            "위치정보 엑셀의 정류장번호, 위도, 경도 열을 "
            f"찾지 못했습니다. 현재 열: {loc.columns.tolist()}"
        )

    loc["정류장번호"] = (
        loc[stop_col]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(5)
    )

    loc["lat"] = pd.to_numeric(
        loc[lat_col], errors="coerce"
    )

    loc["lon"] = pd.to_numeric(
        loc[lon_col], errors="coerce"
    )

    name_col = find_column(
        loc.columns,
        ["정류장명", "정류소명", "nodenm"]
    )

    if name_col:
        loc["정류장명"] = loc[name_col].fillna("")
    else:
        loc["정류장명"] = loc["정류장번호"]

    loc = loc[
        loc["정류장번호"].isin(BUS_STOPS)
    ].copy()

    loc = loc.dropna(subset=["lat", "lon"])

    # 위례 일대에서 벗어난 잘못된 좌표 제외
    loc = loc[
        loc["lat"].between(37.40, 37.55)
        & loc["lon"].between(127.08, 127.23)
    ]

    return loc.drop_duplicates("정류장번호")


try:
    if not ROUTE_FILE.exists():
        st.error(f"노선 엑셀 파일이 없습니다: {ROUTE_FILE.name}")
        st.stop()

    if not LOCATION_FILE.exists():
        st.error(f"위치정보 파일이 없습니다: {LOCATION_FILE.name}")
        st.stop()

    route_df = load_route_data()
    location_df = load_location_data()

    map_df = location_df.merge(
        route_df,
        on="정류장번호",
        how="inner"
    )

except Exception as e:
    st.error(f"데이터 불러오기 오류: {e}")
    st.stop()

if map_df.empty:
    st.error("지도에 표시할 정류장이 없습니다.")
    st.stop()

# ==========================================
# 5. 배차간격 데이터
# ==========================================

headway_df = pd.DataFrame({
    "버스노선": BUS_ROUTES,
    "평일 최소": [20, 18, None, 55, 30, 32, 25, 25, 15],
    "평일 최대": [30, 30, None, 65, 40, 42, 35, 35, 35],
    "주말 최소": [20, 18, None, 45, 25, 32, 20, 25, 23],
    "주말 최대": [30, 30, None, 65, 40, 42, 35, 35, 35]
})

for day in ["평일", "주말"]:
    headway_df[f"{day} 대표값"] = (
        headway_df[f"{day} 최소"]
        + headway_df[f"{day} 최대"]
    ) / 2

# ==========================================
# 6. 사이드바
# ==========================================

with st.sidebar:
    st.markdown("## 🚌 WIRYE MOBILITY")
    st.caption("대중교통 공급 및 DRT 연계 분석")

    st.divider()

    page = st.radio(
        "분석 메뉴",
        [
            "종합 대시보드",
            "🚨 트램 사각지대 분석 (취약단지)",
            "버스 노선 분석",
            "정류장 데이터"
        ]
    )

    st.divider()

    day_type = st.radio(
        "분석 기준",
        ["평일", "주말"],
        horizontal=True
    )

    selected_stop = st.selectbox(
        "분석 정류장",
        ["전체"] + map_df["정류장번호"].tolist()
    )

    st.divider()
    st.caption("스마트시티 캡스톤디자인")
    st.caption("위례동 대중교통 분석 시스템")

# ==========================================
# 7. 화면 제목
# ==========================================

st.title("위례동 대중교통 분석 대시보드")
st.caption(
    "Wirye Mobility Intelligence | "
    "버스 공급 현황 · 정류장 공간분포 · DRT 연계 분석"
)

# ==========================================
# 8. 핵심 지표
# ==========================================

k1, k2, k3, k4 = st.columns(4)

with k1:
    st.metric(
        "조사 정류장",
        f"{len(route_df)}개"
    )

with k2:
    st.metric(
        "조사 버스 노선",
        f"{len(BUS_ROUTES)}개"
    )

with k3:
    st.metric(
        "지도 표시 정류장",
        f"{len(map_df)}개"
    )

with k4:
    known_count = headway_df[
        f"{day_type} 대표값"
    ].notna().sum()

    st.metric(
        "배차간격 확인 노선",
        f"{known_count}개"
    )

st.write("")

@st.cache_data
def load_blindspot_gis_data():
    proj_root = FOLDER.parent.parent
    data_proc = proj_root / "data" / "processed"
    files = {
        "changgok": data_proc / "wirye_changgok_boundary.geojson",
        "blindspot": data_proc / "wirye_tram_blindspot_700m.geojson",
        "buffer": data_proc / "wirye_tram_buffer_700m.geojson",
        "stations": data_proc / "wirye_tram_official_stations.geojson",
        "lines": data_proc / "wirye_tram_official_lines.geojson",
        "apts": data_proc / "wirye_vulnerable_apartments.geojson"
    }
    loaded = {}
    for k, p in files.items():
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                loaded[k] = json.load(f)
    return loaded

# ==========================================
# 9. 지도 생성 함수
# ==========================================

def make_map(data, selected="전체"):

    if selected != "전체":
        center_data = data[
            data["정류장번호"] == selected
        ]
        if center_data.empty:
            center_data = data
    else:
        center_data = data

    center = [
        center_data["lat"].mean(),
        center_data["lon"].mean()
    ]

    m = folium.Map(
        location=[37.4715, 127.1470] if selected == "전체" else center,
        zoom_start=15 if selected == "전체" else 16,
        tiles="OpenStreetMap",
        control_scale=True
    )

    gis = load_blindspot_gis_data()

    # 1. 🚨 트램 도보 10분 밖 사각지대 폴리곤 (투명도 0.4 붉은색)
    if "blindspot" in gis:
        fg_poly = folium.FeatureGroup(
            name="🚨 [사각지대] 트램 도보 10분 밖 영역 (투명도 0.4 붉은색 Polygon)",
            show=True
        )
        folium.GeoJson(
            gis["blindspot"],
            style_function=lambda x: {
                "fillColor": "#EF4444",
                "fillOpacity": 0.4,
                "color": "#B91C1C",
                "weight": 2,
                "dashArray": "4, 4"
            },
            tooltip="🚨 트램 도보 10분(700m) 밖 사각지대 영역"
        ).add_to(fg_poly)
        fg_poly.add_to(m)

    # 2. 🔴 취약 아파트 서클 (투명도 0.4 붉은색 Circle)
    if "apts" in gis:
        fg_circ = folium.FeatureGroup(
            name="🔴 [단지별 권역] 취약 아파트 사각지대 서클 (투명도 0.4 붉은색 Circle)",
            show=True
        )
        for feat in gis["apts"]["features"]:
            p = feat["properties"]
            folium.Circle(
                location=[p["lat"], p["lon"]],
                radius=p.get("circle_radius", 250),
                color="#DC2626",
                weight=2,
                fill=True,
                fill_color="red",
                fill_opacity=0.4,
                tooltip=f"🔴 {p['name']} 사각지대 권역 (도보 {p['walk_time_min']}분)"
            ).add_to(fg_circ)
            folium.CircleMarker(
                location=[p["lat"], p["lon"]],
                radius=7,
                color="#FFFFFF",
                weight=2,
                fill=True,
                fill_color="#DC2626",
                fill_opacity=0.9,
                tooltip=f"📍 {p['name']}"
            ).add_to(fg_circ)
        fg_circ.add_to(m)

        # 3. 🏢 취약 아파트 상세 마커
        fg_apts = folium.FeatureGroup(
            name="🏢 취약 아파트 마커 (위례자이더시티, 호반써밋 등)",
            show=True
        )
        for feat in gis["apts"]["features"]:
            p = feat["properties"]
            is_hl = p["name"] in ["위례자이더시티", "위례호반써밋에비뉴"]
            popup_h = f"""
            <div style="font-family:sans-serif; width:260px; padding:3px;">
                <b style="font-size:13px; color:{'#DC2626' if is_hl else '#1E293B'};">🏢 {p['name']}</b>
                <span style="font-size:10px; color:#64748B;">({p['sub_title']})</span>
                <hr style="margin:4px 0;">
                <div style="font-size:11px; line-height:1.6;">
                    • <b>세대수:</b> {p['households']}<br>
                    • <b>최근접 트램역:</b> <span style="color:#2563EB;"><b>{p['nearest_tram']}</b></span><br>
                    • <b>직선거리:</b> {p['straight_dist_m']} m<br>
                    • <b>실제 보행거리:</b> 약 {p['walk_dist_m']} m<br>
                    • <b style="color:#DC2626;">도보 소요시간: 약 {p['walk_time_min']}분 (10분 기준 초과)</b><br>
                    • <b>취약 사유:</b> {p['issues']}
                </div>
            </div>
            """
            folium.Marker(
                location=[p["lat"], p["lon"]],
                popup=folium.Popup(popup_h, max_width=290),
                tooltip=f"🏢 {p['name']} (도보 {p['walk_time_min']}분 / 사각지대)",
                icon=folium.Icon(color="darkred" if is_hl else "red", icon="home")
            ).add_to(fg_apts)
        fg_apts.add_to(m)

    # 4. ⏱️ 트램 700m 도보권 버퍼 (기준선)
    if "buffer" in gis:
        fg_tb = folium.FeatureGroup(name="⏱️ [기준선] 트램 10분 도보권 (반경 700m)", show=True)
        folium.GeoJson(
            gis["buffer"],
            style_function=lambda x: {
                "fillColor": "#0EA5E9",
                "color": "#0284C7",
                "weight": 1.5,
                "dashArray": "6, 6",
                "fillOpacity": 0.10
            },
            tooltip="트램 12개 역사 10분 도보권 (반경 700m)"
        ).add_to(fg_tb)
        fg_tb.add_to(m)

    # 5. 🚇 트램 역사 및 노선망
    if "lines" in gis and "stations" in gis:
        fg_ts = folium.FeatureGroup(name="🚇 위례선 공식 트램 역사 및 노선망", show=True)
        for lf in gis["lines"]["features"]:
            coords = [[c[1], c[0]] for c in lf["geometry"]["coordinates"]]
            folium.PolyLine(coords, color=lf["properties"].get("color", "#00F2FE"), weight=5, opacity=0.85).add_to(fg_ts)
        for sf in gis["stations"]["features"]:
            c = sf["geometry"]["coordinates"]
            folium.CircleMarker(
                location=[c[1], c[0]],
                radius=7,
                color="white",
                weight=2,
                fill=True,
                fill_color="#0284C7",
                fill_opacity=0.95,
                tooltip=f"🚇 {sf['properties']['station_no']} {sf['properties']['station_name']}"
            ).add_to(fg_ts)
        fg_ts.add_to(m)

    # 6. 🚏 시내버스 정류장 마커 레이어
    fg_bus = folium.FeatureGroup(name="🚏 기존 시내버스 정류장 (13개소)", show=True)
    for _, row in data.iterrows():

        stop_no = row["정류장번호"]

        routes = [
            r for r in BUS_ROUTES
            if row[r] == "O"
        ]

        count = len(routes)

        if count <= 3:
            color = "#E35D5D"
        elif count <= 6:
            color = "#F2A640"
        else:
            color = "#3478C0"

        is_selected = stop_no == selected

        popup_html = f"""
        <div style="font-family:sans-serif;min-width:190px;">
            <b>정류장 {html.escape(stop_no)}</b>
            <hr>
            <b>경유 노선:</b> {count}개<br>
            <b>버스:</b> {html.escape(", ".join(routes))}
        </div>
        """

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=13 if is_selected else 8,
            color="#14263E" if is_selected else "white",
            weight=3 if is_selected else 2,
            fill=True,
            fill_color=color,
            fill_opacity=0.95,
            tooltip=f"{stop_no} | {count}개 노선",
            popup=folium.Popup(
                popup_html,
                max_width=280
            )
        ).add_to(fg_bus)
    fg_bus.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen(position="topright").add_to(m)

    return m


# ==========================================
# 10. 종합 대시보드
# ==========================================

if page == "종합 대시보드":

    left, right = st.columns(
        [1.75, 1],
        gap="large"
    )

    with left:
        st.markdown(
            '<div class="section-heading">'
            '🗺️ 정류장 공간분포</div>',
            unsafe_allow_html=True
        )

        m = make_map(map_df, selected_stop)

        st_folium(
            m,
            height=480,
            width=None,
            returned_objects=[]
        )

        st.caption(
            "🔴 3개 이하 · 🟠 4~6개 · "
            "🔵 7개 이상 경유 노선"
        )

    with right:
        st.markdown(
            '<div class="section-heading">'
            '🚏 정류장 상세 분석</div>',
            unsafe_allow_html=True
        )

        if selected_stop == "전체":
            st.markdown("""
            <div class="info-panel">
                <b>정류장을 선택해 주세요</b>
                <p class="small-muted">
                    왼쪽 사이드바에서 정류장 번호를
                    선택하면 경유 버스와 배차간격을
                    확인할 수 있습니다.
                </p>
            </div>
            """, unsafe_allow_html=True)

            st.metric(
                "정류장당 평균 경유 노선 수",
                f"{route_df['경유노선수'].mean():.1f}개"
            )

            st.metric(
                "경유 노선 수 최솟값",
                f"{route_df['경유노선수'].min()}개"
            )

        else:
            row = route_df[
                route_df["정류장번호"] == selected_stop
            ].iloc[0]

            available = [
                r for r in BUS_ROUTES
                if row[r] == "O"
            ]

            st.metric(
                "선택 정류장",
                selected_stop
            )

            st.metric(
                "경유 버스 노선",
                f"{len(available)}개"
            )

            st.markdown("**이용 가능한 버스**")
            st.write(", ".join(available) if available else "없음")

            st.markdown(
                f"**{day_type} 노선별 배차간격**"
            )

            detail = headway_df[
                headway_df["버스노선"].isin(available)
            ][
                [
                    "버스노선",
                    f"{day_type} 최소",
                    f"{day_type} 최대"
                ]
            ].copy()

            detail.columns = [
                "노선", "최소(분)", "최대(분)"
            ]

            st.dataframe(
                detail,
                hide_index=True,
                width="stretch"
            )

            st.caption(
                "배차간격은 노선 단위 정보이며, "
                "정류장 실제 대기시간은 아닙니다."
            )

    st.divider()

    # 하단 그래프
    graph_left, graph_right = st.columns(
        2,
        gap="large"
    )

    with graph_left:
        st.markdown(
            '<div class="section-heading">'
            '📊 정류장별 경유 노선 수</div>',
            unsafe_allow_html=True
        )

        stop_chart = route_df[
            ["정류장번호", "경유노선수"]
        ].sort_values(
            "경유노선수",
            ascending=False
        )

        st.bar_chart(
            stop_chart.set_index("정류장번호"),
            x_label="정류장",
            y_label="노선 수",
            height=330
        )

    with graph_right:
        st.markdown(
            '<div class="section-heading">'
            f'⏱️ {day_type} 버스 배차간격</div>',
            unsafe_allow_html=True
        )

        chart_data = headway_df[
            ["버스노선", f"{day_type} 대표값"]
        ].dropna()

        st.bar_chart(
            chart_data.set_index("버스노선"),
            x_label="버스 노선",
            y_label="배차간격 대표값(분)",
            height=330
        )

    st.caption(
        "배차간격 대표값은 최소·최대값의 중간값이며 "
        "실제 평균이나 예상 대기시간을 의미하지 않습니다."
    )

# ==========================================
# 11. 버스 노선 분석 화면
# ==========================================

elif page == "버스 노선 분석":

    st.subheader("🚌 버스 노선별 배차간격 분석")

    st.dataframe(
        headway_df[
            [
                "버스노선",
                "평일 최소",
                "평일 최대",
                "주말 최소",
                "주말 최대"
            ]
        ],
        hide_index=True,
        width="stretch"
    )

    st.subheader("평일·주말 배차간격 비교")

    comparison = headway_df[
        [
            "버스노선",
            "평일 대표값",
            "주말 대표값"
        ]
    ].set_index("버스노선")

    st.bar_chart(
        comparison,
        height=400,
        x_label="버스 노선",
        y_label="배차간격 대표값(분)"
    )

    st.subheader("배차간격이 긴 노선")

    ranking = headway_df[
        ["버스노선", f"{day_type} 대표값"]
    ].dropna().sort_values(
        f"{day_type} 대표값",
        ascending=False
    )

    st.dataframe(
        ranking,
        hide_index=True,
        width="stretch"
    )

    st.info(
        "60번은 배차간격 미확인 상태입니다. "
        "등록 배차간격과 실제 운행간격은 다를 수 있습니다."
    )

# ==========================================
# 11-2. 트램 사각지대 분석 (취약단지) 화면
# ==========================================

elif page == "🚨 트램 사각지대 분석 (취약단지)":

    st.subheader("🚨 위례 창곡동 대중교통 취약지 및 트램 도보 10분 사각지대 분석")
    st.caption("위례선 공식 12개 정거장 도보 10분(반경 700m) 기준 공간 차집합 연산 및 취약 아파트 단지 레이어")

    # 핵심 지표 카드
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        st.metric("성남 창곡동 총 면적", "3.19 ㎢")
    with b2:
        st.metric("트램 도보 10분 밖 사각지대", "1.53 ㎢", "창곡동의 48.0%")
    with b3:
        st.metric("조사 취약 아파트 단지", "8개 단지", "총 8,266 세대")
    with b4:
        st.metric("최대 보행 소요시간", "23분 (1.55 km)", "위례그린파크/더힐/호반")

    st.write("")

    # 데이터 경로
    proj_root = FOLDER.parent.parent
    data_proc = proj_root / "data" / "processed"

    # GeoJSON 데이터 로드
    changgok_file = data_proc / "wirye_changgok_boundary.geojson"
    blindspot_file = data_proc / "wirye_tram_blindspot_700m.geojson"
    buffer_file = data_proc / "wirye_tram_buffer_700m.geojson"
    stations_file = data_proc / "wirye_tram_official_stations.geojson"
    lines_file = data_proc / "wirye_tram_official_lines.geojson"
    apts_file = data_proc / "wirye_vulnerable_apartments.geojson"

    has_gis_data = all(f.exists() for f in [changgok_file, blindspot_file, stations_file, lines_file, apts_file])

    if not has_gis_data:
        st.warning("GIS 공간 데이터가 일부 누락되었습니다. generate_tram_blindspot_map.py 를 실행해주세요.")
    else:
        with open(changgok_file, "r", encoding="utf-8") as f:
            changgok_geo = json.load(f)
        with open(blindspot_file, "r", encoding="utf-8") as f:
            blindspot_geo = json.load(f)
        with open(buffer_file, "r", encoding="utf-8") as f:
            buffer_geo = json.load(f)
        with open(stations_file, "r", encoding="utf-8") as f:
            stations_geo = json.load(f)
        with open(lines_file, "r", encoding="utf-8") as f:
            lines_geo = json.load(f)
        with open(apts_file, "r", encoding="utf-8") as f:
            apts_geo = json.load(f)

        # Folium 맵 생성
        center_lat, center_lon = 37.4715, 127.1470
        m_blind = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=15,
            tiles="OpenStreetMap",
            control_scale=True
        )

        folium.TileLayer(
            tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
            attr='&copy; <a href="https://carto.com/">CARTO</a>',
            name="CartoDB 밝은 지도",
            control=True
        ).add_to(m_blind)

        # 1. 창곡동 경계
        fg_b = folium.FeatureGroup(name="성남 위례동(창곡동) 행정 경계", show=True)
        folium.GeoJson(
            changgok_geo,
            style_function=lambda x: {
                "fillColor": "#1E293B",
                "color": "#3B82F6",
                "weight": 2.5,
                "dashArray": "5, 5",
                "fillOpacity": 0.05
            },
            tooltip="성남시 수정구 창곡동 경계"
        ).add_to(fg_b)
        fg_b.add_to(m_blind)

        # 2. 🚨 트램 도보 10분 밖 사각지대 폴리곤 (투명도 0.4 붉은색)
        fg_poly = folium.FeatureGroup(
            name="🚨 [공간분석] 트램 도보 10분 밖 사각지대 영역 (투명도 0.4 붉은색 Polygon)",
            show=True
        )
        folium.GeoJson(
            blindspot_geo,
            style_function=lambda x: {
                "fillColor": "#EF4444",
                "fillOpacity": 0.4,
                "color": "#B91C1C",
                "weight": 2,
                "dashArray": "4, 4"
            },
            tooltip="🚨 트램역 도보 10분(700m) 이상 이격 사각지대 영역"
        ).add_to(fg_poly)
        fg_poly.add_to(m_blind)

        # 3. 🔴 취약 아파트 단지별 권역 서클 (Circle: 투명도 0.4 붉은색)
        fg_circ = folium.FeatureGroup(
            name="🔴 [단지별 권역] 취약 아파트 사각지대 권역 서클 (Circle: 투명도 0.4 붉은색)",
            show=True
        )
        for feat in apts_geo["features"]:
            props = feat["properties"]
            folium.Circle(
                location=[props["lat"], props["lon"]],
                radius=props.get("circle_radius", 250),
                color="#DC2626",
                weight=2,
                fill=True,
                fill_color="red",
                fill_opacity=0.4,
                tooltip=f"🔴 {props['name']} 사각지대 권역 (도보 {props['walk_time_min']}분 소요)"
            ).add_to(fg_circ)
            folium.CircleMarker(
                location=[props["lat"], props["lon"]],
                radius=7,
                color="#FFFFFF",
                weight=2,
                fill=True,
                fill_color="#DC2626",
                fill_opacity=0.9,
                tooltip=f"📍 {props['name']}"
            ).add_to(fg_circ)
        fg_circ.add_to(m_blind)

        # 4. 🏢 취약 아파트 상세 마커
        fg_apts = folium.FeatureGroup(
            name="🏢 취약 아파트 단지 상세 마커 (위례자이더시티, 호반써밋 등)",
            show=True
        )
        for feat in apts_geo["features"]:
            props = feat["properties"]
            is_hl = props["name"] in ["위례자이더시티", "위례호반써밋에비뉴"]
            popup_h = f"""
            <div style="font-family:sans-serif; width:260px; padding:3px;">
                <b style="font-size:13px; color:{'#DC2626' if is_hl else '#1E293B'};">🏢 {props['name']}</b>
                <span style="font-size:10px; color:#64748B;">({props['sub_title']})</span>
                <hr style="margin:4px 0;">
                <div style="font-size:11px; line-height:1.6;">
                    • <b>세대수:</b> {props['households']}<br>
                    • <b>최근접 트램역:</b> <span style="color:#2563EB;"><b>{props['nearest_tram']}</b></span><br>
                    • <b>직선거리:</b> {props['straight_dist_m']} m<br>
                    • <b>실제 보행거리:</b> 약 {props['walk_dist_m']} m<br>
                    • <b style="color:#DC2626;">도보 소요시간: 약 {props['walk_time_min']}분 (10분 기준 초과)</b><br>
                    • <b>취약 사유:</b> {props['issues']}
                </div>
            </div>
            """
            folium.Marker(
                location=[props["lat"], props["lon"]],
                popup=folium.Popup(popup_h, max_width=290),
                tooltip=f"🏢 {props['name']} (도보 {props['walk_time_min']}분 / 사각지대)",
                icon=folium.Icon(color="darkred" if is_hl else "red", icon="home")
            ).add_to(fg_apts)
        fg_apts.add_to(m_blind)

        # 5. ⏱️ 트램 700m 도보권 버퍼
        fg_tb = folium.FeatureGroup(name="⏱️ [기준선] 트램 12개 역사 10분 도보권 (반경 700m)", show=True)
        folium.GeoJson(
            buffer_geo,
            style_function=lambda x: {
                "fillColor": "#0EA5E9",
                "color": "#0284C7",
                "weight": 1.5,
                "dashArray": "6, 6",
                "fillOpacity": 0.10
            },
            tooltip="트램 12개 역사 도보 10분(반경 700m) 역세권"
        ).add_to(fg_tb)
        fg_tb.add_to(m_blind)

        # 6. 🚇 위례선 공식 트램 노선 및 역사
        fg_ts = folium.FeatureGroup(name="🚇 위례선 공식 트램 12개 역사 및 노선망", show=True)
        for lf in lines_geo["features"]:
            coords = [[c[1], c[0]] for c in lf["geometry"]["coordinates"]]
            folium.PolyLine(coords, color=lf["properties"].get("color", "#00F2FE"), weight=5, opacity=0.85).add_to(fg_ts)
        for sf in stations_geo["features"]:
            c = sf["geometry"]["coordinates"]
            folium.CircleMarker(
                location=[c[1], c[0]],
                radius=8,
                color="white",
                weight=2,
                fill=True,
                fill_color="#0284C7",
                fill_opacity=0.95,
                tooltip=f"🚇 {sf['properties']['station_no']} {sf['properties']['station_name']}"
            ).add_to(fg_ts)
        fg_ts.add_to(m_blind)

        folium.LayerControl(collapsed=False).add_to(m_blind)
        plugins.Fullscreen(position="topright").add_to(m_blind)

        # 지도 렌더링
        st_folium(m_blind, width=None, height=600, returned_objects=[])

        st.caption("💡 지도 우측 상단 레이어 컨트롤러(Layer Control)에서 각 영역 및 단지 레이어를 자유롭게 켜고 끌 수 있습니다.")

        # 하단 상세 데이터 테이블
        st.markdown("#### 📋 창곡동 대중교통 취약 아파트 단지 상세 현황")
        apt_table_data = []
        for feat in apts_geo["features"]:
            p = feat["properties"]
            apt_table_data.append({
                "아파트 단지명": p["name"],
                "단지 성격": p["sub_title"],
                "세대수": p["households"],
                "최근접 트램역": p["nearest_tram"],
                "직선거리": f"{p['straight_dist_m']} m",
                "실제 도보거리": f"{p['walk_dist_m']} m",
                "도보 소요시간": f"{p['walk_time_min']} 분",
                "취약 사유 및 DRT 필요성": p["issues"]
            })
        df_apt_summary = pd.DataFrame(apt_table_data)
        st.dataframe(df_apt_summary, hide_index=True, width="stretch")

        # HTML 다운로드 버튼
        html_map_path = proj_root / "wirye_transit_blindspot_map.html"
        if html_map_path.exists():
            with open(html_map_path, "r", encoding="utf-8") as hf:
                html_bytes = hf.read().encode("utf-8")
            st.download_button(
                "📥 인터랙티브 Folium 사각지대 지도(HTML) 다운로드",
                data=html_bytes,
                file_name="wirye_transit_blindspot_map.html",
                mime="text/html"
            )

# ==========================================
# 12. 정류장 데이터 화면
# ==========================================

elif page == "정류장 데이터":

    st.subheader("🚏 정류장별 버스 노선 현황")

    st.dataframe(
        route_df[
            ["정류장번호"] + BUS_ROUTES + ["경유노선수"]
        ],
        hide_index=True,
        width="stretch"
    )

    st.subheader("📍 정류장 위치정보")

    st.dataframe(
        location_df[
            ["정류장번호", "정류장명", "lat", "lon"]
        ],
        hide_index=True,
        width="stretch"
    )

    csv_data = route_df.to_csv(
        index=False
    ).encode("utf-8-sig")

    st.download_button(
        "📥 정류장 분석 데이터 다운로드",
        data=csv_data,
        file_name="wirye_bus_stop_analysis.csv",
        mime="text/csv"
    )

# ==========================================
# 13. 하단 안내
# ==========================================

st.divider()

st.caption(
    "Wirye Mobility Intelligence Dashboard | "
    "스마트시티 캡스톤디자인"
)

st.caption(
    "본 대시보드는 조사 대상 정류장과 등록된 노선 "
    "배차간격을 시각화한 것으로, 교통 취약지역이나 "
    "DRT 도입 효과를 확정적으로 판정하지 않습니다."
)
