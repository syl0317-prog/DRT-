
import json
from pathlib import Path

import pandas as pd

# 프로젝트 최상위 폴더
PROJECT_DIR = Path(__file__).resolve().parent.parent

VWORLD_FILE = (
    PROJECT_DIR / "data" / "vworld" / "wirye_road_links.geojson"
)

GITS_FILE = (
    PROJECT_DIR / "data" / "processed" / "gits_link_summary.csv"
)

OUTPUT_FILE = (
    PROJECT_DIR / "data" / "processed" / "vworld_gits_matching.csv"
)

# 1. V-World 도로망 읽기
with open(VWORLD_FILE, "r", encoding="utf-8") as f:
    geojson = json.load(f)

vworld_rows = []

for feature in geojson["features"]:
    props = feature.get("properties", {})

    vworld_rows.append({
        "link_id": str(props.get("link_id", "")).strip(),
        "vworld_road_name": props.get("road_name", ""),
        "geometry": json.dumps(
            feature.get("geometry"),
            ensure_ascii=False
        )
    })

vworld_df = pd.DataFrame(vworld_rows)

# 2. GITS 데이터 읽기
gits_df = pd.read_csv(
    GITS_FILE,
    dtype={"link_id": str},
    encoding="utf-8-sig"
)

gits_df["link_id"] = (
    gits_df["link_id"].fillna("").str.strip()
)

# 3. 링크 ID 기준 매칭
matched_df = pd.merge(
    vworld_df,
    gits_df,
    on="link_id",
    how="inner"
)

# 4. 결과 출력
vworld_ids = set(vworld_df["link_id"]) - {""}
gits_ids = set(gits_df["link_id"]) - {""}
matched_ids = vworld_ids & gits_ids

print("=" * 55)
print("V-World / GITS 도로 링크 매칭 분석")
print("=" * 55)

print(f"V-World 전체 링크: {len(vworld_ids):,}개")
print(f"GITS 전체 링크: {len(gits_ids):,}개")
print(f"일치하는 링크 ID: {len(matched_ids):,}개")

matching_rate = (
    len(matched_ids) / len(vworld_ids) * 100
    if vworld_ids else 0
)

print(f"V-World 기준 매칭률: {matching_rate:.2f}%")

# 5. 매칭된 도로 확인
if not matched_df.empty:
    print("\n[매칭된 도로 샘플]")

    columns = [
        "link_id",
        "vworld_road_name",
        "road_name",
        "mean_speed_kmh",
        "mean_travel_time_sec"
    ]

    available_columns = [
        c for c in columns if c in matched_df.columns
    ]

    print(
        matched_df[available_columns]
        .head(15)
        .to_string(index=False)
    )
else:
    print("\n일치하는 링크 ID가 없습니다.")

# 6. 결과 저장
OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

matched_df.to_csv(
    OUTPUT_FILE,
    index=False,
    encoding="utf-8-sig"
)

print(f"\n결과 저장: {OUTPUT_FILE}")
print("분석 완료")
