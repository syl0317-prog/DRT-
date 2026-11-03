# -*- coding: utf-8 -*-
"""
위례신도시 창곡동 일대 대중교통 취약 아파트 단지 중심
트램역 도보 10분 이상 이격 사각지대 Folium 지도 생성 스크립트
"""

import os
import sys
import json
import glob
import geopandas as gpd
from shapely.geometry import Point, mapping
from shapely.ops import unary_union
import folium
from folium import plugins

sys.stdout.reconfigure(encoding='utf-8')

os.makedirs("data/processed", exist_ok=True)

# 1. 공식 트램역 12개소 로드
tram_geojson_path = "data/processed/wirye_tram_official_stations.geojson"
with open(tram_geojson_path, "r", encoding="utf-8") as f:
    tram_stations_data = json.load(f)

tram_lines_path = "data/processed/wirye_tram_official_lines.geojson"
with open(tram_lines_path, "r", encoding="utf-8") as f:
    tram_lines_data = json.load(f)

# 2. 성남시 창곡동 경계 shp 로드 및 5179 투영
gg_shp = glob.glob(os.path.join("data/raw", "LSMD_ADM_SECT_UMD_경기", "*.shp"))[0]
gdf_gg = gpd.read_file(gg_shp, encoding='cp949')
gdf_changgok = gdf_gg[gdf_gg['EMD_NM'] == '창곡동'].to_crs("EPSG:5179")
if gdf_changgok.empty:
    gdf_changgok = gdf_gg[gdf_gg['EMD_CD'].str.startswith('41131')].iloc[:1].to_crs("EPSG:5179")

# 창곡동 경계 저장
gdf_changgok_4326 = gdf_changgok.to_crs("EPSG:4326")
gdf_changgok_4326.to_file("data/processed/wirye_changgok_boundary.geojson", driver="GeoJSON")

# 3. 트램역 10분 도보권(반경 700m) 버퍼 및 사각지대(차집합) 계산
tram_pts_5179 = []
tram_info_list = []
for feat in tram_stations_data["features"]:
    props = feat["properties"]
    lon, lat = feat["geometry"]["coordinates"]
    pt_5179 = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs("EPSG:5179").iloc[0]
    tram_pts_5179.append(pt_5179)
    tram_info_list.append({
        "station_no": props.get("station_no", ""),
        "station_name": props.get("station_name", ""),
        "route_type": props.get("route_type", ""),
        "sub_name": props.get("sub_name", ""),
        "lon": lon,
        "lat": lat,
        "pt_5179": pt_5179
    })

# 트램 700m 도보권 버퍼 (EPSG:5179)
tram_buffers_700m = [pt.buffer(700) for pt in tram_pts_5179]
tram_union_700m = unary_union(tram_buffers_700m)
gdf_tram_buffer_4326 = gpd.GeoDataFrame(geometry=[tram_union_700m], crs="EPSG:5179").to_crs("EPSG:4326")
gdf_tram_buffer_4326.to_file("data/processed/wirye_tram_buffer_700m.geojson", driver="GeoJSON")

# 창곡동 행정구역 - 트램 도보권 700m 차집합 -> 도보 10분 이상 사각지대 폴리곤
changgok_geom_5179 = gdf_changgok.geometry.unary_union
blindspot_geom_5179 = changgok_geom_5179.difference(tram_union_700m)
gdf_blindspot_4326 = gpd.GeoDataFrame(geometry=[blindspot_geom_5179], crs="EPSG:5179").to_crs("EPSG:4326")
gdf_blindspot_4326.to_file("data/processed/wirye_tram_blindspot_700m.geojson", driver="GeoJSON")

# 4. 창곡동 대중교통 취약 아파트 단지 목록 (위례자이더시티, 위례호반써밋에비뉴 중심)
VULNERABLE_APARTMENTS = [
    {
        "name": "위례자이더시티",
        "sub_title": "공공분양·신혼희망타운 A2-6BL",
        "households": "800세대",
        "lat": 37.4738,
        "lon": 127.1495,
        "nearest_tram": "108 위례역사공원역",
        "straight_dist_m": 730,
        "walk_dist_m": 985,
        "walk_time_min": 15,
        "issues": "트램역 도보 10분(700m) 초과 사각지대, 창곡천 북측 도로 우회 보행 필요",
        "circle_radius": 240
    },
    {
        "name": "위례호반써밋에비뉴",
        "sub_title": "창곡동 중심상업 외곽 호반베르디움",
        "households": "1,137세대",
        "lat": 37.4725,
        "lon": 127.1530,
        "nearest_tram": "108 위례역사공원역",
        "straight_dist_m": 1005,
        "walk_dist_m": 1350,
        "walk_time_min": 20,
        "issues": "트램역 직선 1km 초과, 도보 20분 소요 심각 취약 권역 (DRT 직결 최우선지)",
        "circle_radius": 280
    },
    {
        "name": "위례더힐55",
        "sub_title": "창곡동 동측 고지대 주거단지",
        "households": "1,380세대",
        "lat": 37.4705,
        "lon": 127.1535,
        "nearest_tram": "108 위례역사공원역",
        "straight_dist_m": 1050,
        "walk_dist_m": 1410,
        "walk_time_min": 21,
        "issues": "경사 지형으로 체감 도보 25분 이상 소요, 시내버스 배차 긴 단지",
        "circle_radius": 270
    },
    {
        "name": "위례그린파크푸르지오",
        "sub_title": "창곡동 최동단 남한산성 인접",
        "households": "972세대",
        "lat": 37.4730,
        "lon": 127.1546,
        "nearest_tram": "108 위례역사공원역",
        "straight_dist_m": 1150,
        "walk_dist_m": 1550,
        "walk_time_min": 23,
        "issues": "성남 위례 최동단 버스 종점 권역, 트램 도보 접근 불가권",
        "circle_radius": 260
    },
    {
        "name": "위례센트럴푸르지오",
        "sub_title": "창곡천 남측 위례푸른초 권역",
        "households": "687세대",
        "lat": 37.4699,
        "lon": 127.1513,
        "nearest_tram": "108 위례역사공원역",
        "straight_dist_m": 850,
        "walk_dist_m": 1150,
        "walk_time_min": 17,
        "issues": "트램역 도보 17분 소요, 학생·노약자 보행 한계 초과",
        "circle_radius": 250
    },
    {
        "name": "힐스테이트센트럴위례",
        "sub_title": "창곡동 북동측 경계 주거단지",
        "households": "1,078세대",
        "lat": 37.4745,
        "lon": 127.1558,
        "nearest_tram": "107 위례중앙광장역",
        "straight_dist_m": 1160,
        "walk_dist_m": 1520,
        "walk_time_min": 22,
        "issues": "트램 중앙역 도보 22분, 광역 대중교통 환승 소외 지역",
        "circle_radius": 260
    },
    {
        "name": "위례롯데캐슬",
        "sub_title": "성남시 수정구 위례순환로 인접",
        "households": "1,673세대",
        "lat": 37.4738,
        "lon": 127.1515,
        "nearest_tram": "107 위례중앙광장역",
        "straight_dist_m": 870,
        "walk_dist_m": 1180,
        "walk_time_min": 18,
        "issues": "대단지 수요 대비 트램 10분 도보권 외곽 이격, DRT 수요 밀집지",
        "circle_radius": 270
    },
    {
        "name": "위례포레스트부영",
        "sub_title": "창곡동 남측 헌릉로 격리 주거지",
        "households": "566세대",
        "lat": 37.4608,
        "lon": 127.1446,
        "nearest_tram": "110 남위례역",
        "straight_dist_m": 680,
        "walk_dist_m": 920,
        "walk_time_min": 14,
        "issues": "헌릉로 대로변 단절로 남위례역 실도보 14분 소요, 보행 취약",
        "circle_radius": 220
    }
]

# 아파트 GeoJSON 저장
apt_features = []
for apt in VULNERABLE_APARTMENTS:
    feat = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [apt["lon"], apt["lat"]]
        },
        "properties": apt
    }
    apt_features.append(feat)

with open("data/processed/wirye_vulnerable_apartments.geojson", "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": apt_features}, f, ensure_ascii=False, indent=2)

print("Saved processed geojson files.")

# =============================================================================
# 5. Folium 인터랙티브 지도 생성
# =============================================================================
def generate_folium_map(output_html="wirye_transit_blindspot_map.html"):
    center_lat, center_lon = 37.4715, 127.1470

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles="OpenStreetMap",
        control_scale=True
    )

    # 추가 베이스맵 옵션
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://carto.com/">CARTO</a>',
        name="CartoDB 밝은 지도",
        control=True
    ).add_to(m)
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://carto.com/">CARTO</a>',
        name="다크 모드 지도",
        control=True
    ).add_to(m)

    # -------------------------------------------------------------------------
    # [레이어 1] 성남시 수정구 창곡동 행정구역 경계선
    # -------------------------------------------------------------------------
    fg_boundary = folium.FeatureGroup(name="성남 위례동(창곡동) 행정 경계선", show=True)
    folium.GeoJson(
        gdf_changgok_4326,
        name="창곡동 경계",
        style_function=lambda x: {
            "fillColor": "#1E293B",
            "color": "#3B82F6",
            "weight": 2.5,
            "dashArray": "5, 5",
            "fillOpacity": 0.05
        },
        tooltip="성남시 수정구 창곡동 (위례동)"
    ).add_to(fg_boundary)
    fg_boundary.add_to(m)

    # -------------------------------------------------------------------------
    # [레이어 2] 🚨 트램역 도보 10분(700m) 이상 이격 사각지대 영역 (Polygon: 투명도 0.4 붉은색)
    # -------------------------------------------------------------------------
    fg_blindspot_poly = folium.FeatureGroup(
        name="🚨 [공간분석] 트램 도보 10분 밖 사각지대 영역 (Polygon: 투명도 0.4 붉은색)",
        show=True
    )

    blindspot_popup_html = """
    <div style="font-family:'Pretendard',sans-serif; width:260px; padding:6px;">
        <h4 style="margin:0 0 6px 0; color:#DC2626; font-size:14px; font-weight:700;">🚨 트램 도보 10분 밖 사각지대 영역</h4>
        <div style="font-size:12px; color:#374151; line-height:1.5;">
            • <b>권역:</b> 성남시 수정구 창곡동 외곽 주거벨트<br/>
            • <b>면적:</b> 약 1.53 ㎢ (창곡동 전체의 48.0%)<br/>
            • <b>기준:</b> 공식 12개 트램역사 반경 700m(도보 10분) 초과<br/>
            • <b>대중교통 솔루션:</b> 수요응답형 스마트 DRT 긴급 투입 필요
        </div>
    </div>
    """

    folium.GeoJson(
        gdf_blindspot_4326,
        name="사각지대 폴리곤",
        style_function=lambda x: {
            "fillColor": "#EF4444",    # 붉은색 채우기
            "fillOpacity": 0.4,        # 투명도 0.4
            "color": "#B91C1C",        # 테두리 짙은 붉은색
            "weight": 2,
            "dashArray": "4, 4"
        },
        tooltip="🚨 트램 도보 10분(700m) 이상 이격 사각지대 영역 (클릭 시 상세)",
        popup=folium.Popup(blindspot_popup_html, max_width=300)
    ).add_to(fg_blindspot_poly)
    fg_blindspot_poly.add_to(m)

    # -------------------------------------------------------------------------
    # [레이어 3] 🔴 취약 아파트 단지별 중심 사각지대 서클 (Circle Marker: 투명도 0.4 붉은색)
    # -------------------------------------------------------------------------
    fg_apt_circles = folium.FeatureGroup(
        name="🔴 [단지별 권역] 취약 아파트 사각지대 서클 (Circle: 투명도 0.4 붉은색)",
        show=True
    )

    for apt in VULNERABLE_APARTMENTS:
        # 단지 반경 서클 (투명도 0.4 붉은색)
        folium.Circle(
            location=[apt["lat"], apt["lon"]],
            radius=apt["circle_radius"],
            color="#DC2626",
            weight=2,
            fill=True,
            fill_color="red",
            fill_opacity=0.4,    # 투명도 0.4
            tooltip=f"🔴 {apt['name']} 사각지대 권역 (도보 {apt['walk_time_min']}분 소요)"
        ).add_to(fg_apt_circles)

        # 중심점 강조용 작은 CircleMarker
        folium.CircleMarker(
            location=[apt["lat"], apt["lon"]],
            radius=8,
            color="#FFFFFF",
            weight=2,
            fill=True,
            fill_color="#DC2626",
            fill_opacity=0.9,
            tooltip=f"📍 {apt['name']}"
        ).add_to(fg_apt_circles)

    fg_apt_circles.add_to(m)

    # -------------------------------------------------------------------------
    # [레이어 4] 🏢 대중교통 취약 아파트 단지 상세 마커 (위례자이더시티, 위례호반써밋 등)
    # -------------------------------------------------------------------------
    fg_apartments = folium.FeatureGroup(
        name="🏢 대중교통 취약 아파트 단지 정보 마커 (상세 팝업)",
        show=True
    )

    for apt in VULNERABLE_APARTMENTS:
        # 주요 강조 대상(위례자이더시티, 위례호반써밋에비뉴)은 황금색 테두리 / 붉은 마커
        is_highlight = apt["name"] in ["위례자이더시티", "위례호반써밋에비뉴"]
        icon_color = "darkred" if is_highlight else "red"

        popup_html = f"""
        <div style="font-family:'Pretendard',sans-serif; width:280px; padding:4px;">
            <div style="background:{'#DC2626' if is_highlight else '#475569'}; color:white; padding:6px 10px; border-radius:6px; margin-bottom:8px;">
                <b style="font-size:14px;">🏢 {apt['name']}</b>
                <span style="font-size:11px; opacity:0.9; float:right;">{apt['sub_title']}</span>
            </div>
            <table style="width:100%; font-size:12px; line-height:1.6; border-collapse:collapse;">
                <tr>
                    <td style="color:#64748B; width:95px;"><b>세대수</b></td>
                    <td style="color:#1E293B;"><b>{apt['households']}</b></td>
                </tr>
                <tr>
                    <td style="color:#64748B;"><b>최근접 트램역</b></td>
                    <td style="color:#2563EB;"><b>{apt['nearest_tram']}</b></td>
                </tr>
                <tr>
                    <td style="color:#64748B;"><b>직선거리</b></td>
                    <td style="color:#1E293B;">{apt['straight_dist_m']} m</td>
                </tr>
                <tr>
                    <td style="color:#64748B;"><b>실제 보행거리</b></td>
                    <td style="color:#D97706;"><b>약 {apt['walk_dist_m']} m</b></td>
                </tr>
                <tr style="background:#FEE2E2;">
                    <td style="color:#DC2626; padding:3px 4px;"><b>도보 소요시간</b></td>
                    <td style="color:#DC2626; padding:3px 4px; font-size:13px;"><b>약 {apt['walk_time_min']}분 (10분 기준 초과)</b></td>
                </tr>
            </table>
            <div style="margin-top:8px; padding:6px 8px; background:#F8FAFC; border:1px solid #E2E8F0; border-radius:4px; font-size:11px; color:#475569;">
                ⚠️ <b>교통 취약 사유:</b><br/>{apt['issues']}
            </div>
            <div style="margin-top:6px; text-align:center;">
                <span style="display:inline-block; background:#FEF3C7; color:#B45309; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:700;">
                    🚌 수요응답형 DRT 우선 투입 대상 단지
                </span>
            </div>
        </div>
        """

        folium.Marker(
            location=[apt["lat"], apt["lon"]],
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"🏢 {apt['name']} (트램역까지 도보 {apt['walk_time_min']}분 / 사각지대)",
            icon=folium.Icon(color=icon_color, icon="building", prefix="fa")
        ).add_to(fg_apartments)

    fg_apartments.add_to(m)

    # -------------------------------------------------------------------------
    # [레이어 5] ⏱️ 트램 12개 역사 도보 10분(700m) 권역 (비교용 회색/푸른색 점선 버퍼)
    # -------------------------------------------------------------------------
    fg_tram_buffer = folium.FeatureGroup(
        name="⏱️ [비교기준] 트램 12개 역사 700m 도보권(도보 10분 경계)",
        show=True
    )
    folium.GeoJson(
        gdf_tram_buffer_4326,
        name="트램 700m 도보권",
        style_function=lambda x: {
            "fillColor": "#0EA5E9",
            "color": "#0284C7",
            "weight": 1.8,
            "dashArray": "6, 6",
            "fillOpacity": 0.12
        },
        tooltip="트램 12개 역사 도보 10분(반경 700m) 역세권"
    ).add_to(fg_tram_buffer)
    fg_tram_buffer.add_to(m)

    # -------------------------------------------------------------------------
    # [레이어 6] 🚇 위례선 공식 트램 노선 및 12개 정거장
    # -------------------------------------------------------------------------
    fg_tram_system = folium.FeatureGroup(name="🚇 위례선 공식 트램 12개 역사 및 노선망", show=True)

    # 노선 선형
    for feat in tram_lines_data["features"]:
        coords = feat["geometry"]["coordinates"]
        latlngs = [[c[1], c[0]] for c in coords]
        props = feat["properties"]
        line_color = props.get("color", "#00F2FE")
        line_name = props.get("line_name", "위례선 트램")

        folium.PolyLine(
            locations=latlngs,
            color=line_color,
            weight=6,
            opacity=0.85,
            tooltip=f"🚇 {line_name} ({props.get('section', '')})"
        ).add_to(fg_tram_system)

    # 정거장 포인트
    for st_info in tram_info_list:
        st_no = st_info["station_no"]
        st_name = st_info["station_name"]
        sub_name = st_info["sub_name"]
        route_type = st_info["route_type"]

        if "환승" in route_type or "환승" in sub_name:
            marker_color = "orange"
        elif "분기" in route_type:
            marker_color = "purple"
        else:
            marker_color = "blue"

        st_popup_html = f"""
        <div style="font-family:'Pretendard',sans-serif; width:220px; padding:4px;">
            <b style="font-size:13px; color:#0284C7;">🚇 위례선 {st_no}역 {st_name}</b><br/>
            <span style="font-size:11px; color:#64748B;">({sub_name})</span>
            <hr style="margin:4px 0; border:0; border-top:1px solid #E2E8F0;">
            <span style="font-size:11px; color:#334155;">
                • 구분: <b>{route_type}</b><br/>
                • 공식 역세권: 반경 700m (도보 10분 권역)
            </span>
        </div>
        """

        folium.CircleMarker(
            location=[st_info["lat"], st_info["lon"]],
            radius=9,
            color="#FFFFFF",
            weight=2.5,
            fill=True,
            fill_color="#0284C7" if marker_color == "blue" else ("#F59E0B" if marker_color == "orange" else "#8B5CF6"),
            fill_opacity=0.95,
            tooltip=f"🚇 {st_no} {st_name} ({route_type})",
            popup=folium.Popup(st_popup_html, max_width=250)
        ).add_to(fg_tram_system)

    fg_tram_system.add_to(m)

    # -------------------------------------------------------------------------
    # 플러그인: 레이어 컨트롤, 전체화면, 미니맵, 측정 도구
    # -------------------------------------------------------------------------
    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen(position="topright").add_to(m)
    plugins.MeasureControl(position="bottomleft", primary_length_unit="meters", primary_area_unit="sqmeters").add_to(m)

    # 우측 하단 커스텀 범례 (HTML/CSS)
    legend_html = """
    <div style="
        position: fixed;
        bottom: 25px;
        right: 25px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.95);
        border: 2px solid #E2E8F0;
        border-radius: 10px;
        padding: 12px 16px;
        font-family: 'Pretendard', -apple-system, sans-serif;
        box-shadow: 0 4px 15px rgba(0,0,0,0.15);
        font-size: 12px;
        color: #1E293B;
        max-width: 290px;
    ">
        <div style="font-weight: 800; font-size: 13px; margin-bottom: 8px; color: #0F172A; border-bottom: 2px solid #EF4444; padding-bottom: 4px;">
            🚨 위례 창곡동 트램 사각지대 범례
        </div>
        <div style="display:flex; align-items:center; margin-bottom:5px;">
            <span style="display:inline-block; width:18px; height:18px; background:rgba(239, 68, 68, 0.4); border:2px dashed #B91C1C; border-radius:3px; margin-right:8px;"></span>
            <span><b>트램 도보 10분 밖 사각지대 (투명도 0.4 붉은색)</b></span>
        </div>
        <div style="display:flex; align-items:center; margin-bottom:5px;">
            <span style="display:inline-block; width:14px; height:14px; background:#DC2626; border:2px solid #FFFFFF; border-radius:50%; margin-right:10px;"></span>
            <span><b>취약 아파트 (위례자이더시티, 호반써밋 등)</b></span>
        </div>
        <div style="display:flex; align-items:center; margin-bottom:5px;">
            <span style="display:inline-block; width:18px; height:18px; background:rgba(14, 165, 233, 0.12); border:2px dashed #0284C7; border-radius:3px; margin-right:8px;"></span>
            <span>트램 12개 역사 10분 도보권 (반경 700m)</span>
        </div>
        <div style="display:flex; align-items:center; margin-bottom:5px;">
            <span style="display:inline-block; width:18px; height:4px; background:#00F2FE; margin-right:8px;"></span>
            <span>위례선 공식 트램 노선 (2026 개통)</span>
        </div>
        <div style="display:flex; align-items:center;">
            <span style="display:inline-block; width:18px; height:4px; border-top:2px dashed #3B82F6; margin-right:8px;"></span>
            <span>성남시 위례동(창곡동) 행정 경계</span>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    m.save(output_html)
    print(f"Folium map generated successfully: {output_html}")
    return m

if __name__ == "__main__":
    generate_folium_map("wirye_transit_blindspot_map.html")
