# -*- coding: utf-8 -*-
"""
서울시 도시기반시설본부 & 국토교통부 대도시권광역교통위원회(대광위)
위례선 도시철도(트램) 건설공사 실시설계 승인 공식 12개 정거장 및 노선 GeoJSON 생성 스크립트
"""

import os
import json
import geopandas as gpd
from shapely.geometry import Point, LineString

# 서울시 고시 및 대광위 사업계획 승인 공식 12개 정거장 (본선 10개, 지선 2개, 분기: 108 위례역사공원)
OFFICIAL_TRAM_STATIONS = [
    {
        "station_no": "101",
        "station_name": "마천역",
        "sub_name": "5호선 환승역",
        "route_type": "본선",
        "address": "서울특별시 송파구 마천동 28 일대",
        "landmark": "5호선 마천역 1·2번 출구, 거여119안전센터",
        "lon": 127.1495,
        "lat": 37.4952
    },
    {
        "station_no": "102",
        "station_name": "북위례",
        "sub_name": "차량기지 인입선 분기",
        "route_type": "본선",
        "address": "서울특별시 송파구 거여동 산 32-1 일대",
        "landmark": "북위례 단독주택용지, 송파위례리슈빌 남측",
        "lon": 127.1485,
        "lat": 37.4912
    },
    {
        "station_no": "103",
        "station_name": "위례솔",
        "sub_name": "위례솔초·중학교",
        "route_type": "본선",
        "address": "서울특별시 송파구 거여동 605 일대",
        "landmark": "위례솔초등학교, 위례솔중학교 정문 앞",
        "lon": 127.1475,
        "lat": 37.4868
    },
    {
        "station_no": "104",
        "station_name": "덕수고등학교",
        "sub_name": "북위례 트랜짓몰 북단",
        "route_type": "본선",
        "address": "서울특별시 송파구 거여동 651 일대",
        "landmark": "덕수고등학교, 위례포레샤인 17단지 앞",
        "lon": 127.1458,
        "lat": 37.4832
    },
    {
        "station_no": "105",
        "station_name": "위례호수공원",
        "sub_name": "수변공원 북측",
        "route_type": "본선",
        "address": "서울특별시 송파구 장지동 887 일대",
        "landmark": "위례 호수공원 북단, 송파레이크파크 호반써밋 앞",
        "lon": 127.1445,
        "lat": 37.4805
    },
    {
        "station_no": "106",
        "station_name": "위례별",
        "sub_name": "송파위례광장",
        "route_type": "본선",
        "address": "서울특별시 송파구 장지동 894 일대",
        "landmark": "서울위례별초등학교, 송파와이즈더샵 북측",
        "lon": 127.1435,
        "lat": 37.4775
    },
    {
        "station_no": "107",
        "station_name": "위례중앙광장",
        "sub_name": "위례신사선 환승 예정",
        "route_type": "본선/지선공통",
        "address": "서울특별시 송파구 장지동 / 경기도 성남시 수정구 창곡동 경계",
        "landmark": "위례중앙타워, 위례중앙푸르지오 트랜짓몰 중심광장",
        "lon": 127.1428,
        "lat": 37.4752
    },
    {
        "station_no": "108",
        "station_name": "위례역사공원",
        "sub_name": "본선-지선 분기역",
        "route_type": "분기거점",
        "address": "경기도 성남시 수정구 창곡동 498 일대",
        "landmark": "창곡천 수변공원, 밀리토피아호텔 동측, 위례자연앤래미안 서측",
        "lon": 127.1418,
        "lat": 37.4715
    },
    {
        "station_no": "109",
        "station_name": "위례트램스퀘어",
        "sub_name": "남위례지선",
        "route_type": "남위례지선",
        "address": "경기도 성남시 수정구 창곡동 520 일대",
        "landmark": "위례아트리버푸르지오, 성남위례동 주민센터 인근",
        "lon": 127.1395,
        "lat": 37.4675
    },
    {
        "station_no": "110",
        "station_name": "남위례역",
        "sub_name": "8호선 환승역(지선종점)",
        "route_type": "남위례지선",
        "address": "경기도 성남시 수정구 복정동 147-1 일대",
        "landmark": "8호선 남위례역 3·4번 출구 앞 트램 전용 승강장",
        "lon": 127.1375,
        "lat": 37.4628
    },
    {
        "station_no": "111",
        "station_name": "위례스마트시티",
        "sub_name": "창곡교차로/위례서로",
        "route_type": "본선",
        "address": "경기도 성남시 수정구 창곡동 560 일대",
        "landmark": "창곡교차로, LH 스마트도시 관제센터 앞",
        "lon": 127.1332,
        "lat": 37.4710
    },
    {
        "station_no": "112",
        "station_name": "복정역",
        "sub_name": "8호선/수인분당선 환승역(본선종점)",
        "route_type": "본선",
        "address": "서울특별시 송파구 장지동 597-2 / 경기도 성남시 수정구 복정동",
        "landmark": "8호선·수인분당선 복정역 1·2번 출구 환승복합센터",
        "lon": 127.1265,
        "lat": 37.4702
    }
]

# 노선 선형 (Path)
# 1. 본선: 101 -> 102 -> 103 -> 104 -> 105 -> 106 -> 107 -> 108 -> 111 -> 112
main_line_coords = [
    [s["lon"], s["lat"]] for s in OFFICIAL_TRAM_STATIONS if s["station_no"] in ["101", "102", "103", "104", "105", "106", "107", "108", "111", "112"]
]
# 2. 남위례지선: 108(분기역) -> 109 -> 110
branch_line_coords = [
    [s["lon"], s["lat"]] for s in OFFICIAL_TRAM_STATIONS if s["station_no"] in ["108", "109", "110"]
]

os.makedirs("data/processed", exist_ok=True)

# 1. 정거장 GeoJSON 생성
features = []
for st in OFFICIAL_TRAM_STATIONS:
    feat = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [st["lon"], st["lat"]]
        },
        "properties": st
    }
    features.append(feat)

station_geojson = {
    "type": "FeatureCollection",
    "name": "Wirye_Tram_Official_Stations",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    "features": features
}

with open("data/processed/wirye_tram_official_stations.geojson", "w", encoding="utf-8") as f:
    json.dump(station_geojson, f, ensure_ascii=False, indent=2)

# 2. 노선 GeoJSON 생성
line_features = [
    {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": main_line_coords
        },
        "properties": {
            "line_name": "위례선 트램 본선",
            "section": "마천역 ~ 위례중앙광장 ~ 복정역",
            "color": "#00F2FE"
        }
    },
    {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": branch_line_coords
        },
        "properties": {
            "line_name": "위례선 트램 남위례지선",
            "section": "위례역사공원역(분기) ~ 남위례역",
            "color": "#38BDF8"
        }
    }
]

line_geojson = {
    "type": "FeatureCollection",
    "name": "Wirye_Tram_Official_Lines",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    "features": line_features
}

with open("data/processed/wirye_tram_official_lines.geojson", "w", encoding="utf-8") as f:
    json.dump(line_geojson, f, ensure_ascii=False, indent=2)

print("Saved official tram stations and line geometry to data/processed/")
