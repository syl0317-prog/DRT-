
import json
from pathlib import Path

import folium
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent

VWORLD_FILE = PROJECT_DIR / "data" / "vworld" / "wirye_road_links.geojson"
MATCHED_FILE = PROJECT_DIR / "data" / "processed" / "vworld_gits_matching.csv"
OUTPUT_FILE = PROJECT_DIR / "data" / "processed" / "vworld_gits_matched_map.html"

# 1. 데이터 불러오기
with open(VWORLD_FILE, "r", encoding="utf-8") as f:
    roads = json.load(f)

matched = pd.read_csv(
    MATCHED_FILE,
    dtype={"link_id": str},
    encoding="utf-8-sig"
)

matched_ids = set(matched["link_id"].dropna().str.strip())

matched_features = [
    feature
    for feature in roads["features"]
    if str(feature.get("properties", {}).get("link_id", "")).strip()
    in matched_ids
]

# 2. 지도 생성
m = folium.Map(
    location=[37.474, 127.143],
    zoom_start=14,
    tiles=None
)

# 전체 도로망: 녹색
folium.GeoJson(
    roads,
    name="V-World 전체 도로망",
    style_function=lambda feature: {
        "color": "green",
        "weight": 1,
        "opacity": 0.3
    }
).add_to(m)

# GITS 매칭 도로: 빨간색
if matched_features:
    folium.GeoJson(
        {
            "type": "FeatureCollection",
            "features": matched_features
        },
        name="GITS 매칭 도로",
        style_function=lambda feature: {
            "color": "red",
            "weight": 6,
            "opacity": 0.9
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["link_id", "road_name"],
            aliases=["링크 ID", "도로명"]
        )
    ).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# 3. 지도 저장
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
m.save(str(OUTPUT_FILE))

print("=" * 50)
print("V-World / GITS 매칭 도로 시각화")
print("=" * 50)
print(f"GITS 매칭 ID 수: {len(matched_ids)}개")
print(f"지도에 표시된 링크 수: {len(matched_features)}개")
print(f"저장 위치: {OUTPUT_FILE}")
