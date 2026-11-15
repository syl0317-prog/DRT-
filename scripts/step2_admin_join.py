from __future__ import annotations

import csv
import json
import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"


def read_shapes(folder):
    frames = []
    for path in folder.rglob("*.shp"):
        frame = gpd.read_file(path, encoding="cp949")
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def sigungu(code, row):
    code = str(code or "")[:5]
    labels = {"41131": "성남시 수정구", "41450": "하남시", "11710": "송파구"}
    if code in labels:
        return labels[code]
    for col in ("SIG_KOR_NM", "SGG_NM", "SIGUNGU_NM"):
        if col in row and row[col]:
            return str(row[col])
    return "missing"


def join_points(points, polygons):
    gdf = gpd.GeoDataFrame(points, geometry=[Point(x, y) for x, y in zip(points.longitude, points.latitude)], crs="EPSG:4326")
    gdf = gdf.to_crs(polygons.crs)
    joined = gpd.sjoin(gdf, polygons, how="left", predicate="within")
    records = []
    for _, row in joined.iterrows():
        emd = row.get("EMD_NM")
        code = row.get("EMD_CD", "")
        area = f"{sigungu(code, row)} {emd}" if pd.notna(emd) else "missing"
        records.append({**{key: row[key] for key in points.columns if key in row}, "행정구역": area})
    return records


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def save_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apartment-input", default=str(OUT / "apartment_master.csv"))
    parser.add_argument("--apartment-output", default=str(OUT / "apartment_master.csv"))
    parser.add_argument("--apartments-only", action="store_true",
                        help="only enrich the requested apartment file; leave other outputs untouched")
    args = parser.parse_args()
    polygons = pd.concat([
        read_shapes(RAW / "LSMD_ADM_SECT_UMD_경기"),
        read_shapes(RAW / "LSMD_ADM_SECT_UMD_서울"),
    ], ignore_index=True)
    polygons = gpd.GeoDataFrame(polygons, geometry="geometry", crs="EPSG:5186")
    boundary_data = json.loads((OUT / "wirye_changgok_boundary.geojson").read_text(encoding="utf-8"))
    boundary = gpd.GeoDataFrame.from_features(boundary_data["features"], crs="EPSG:4326").to_crs("EPSG:4326").geometry.iloc[0]

    apt_path = Path(args.apartment_input)
    apt_out = Path(args.apartment_output)
    apartments = csv_rows(apt_path)
    pts = pd.DataFrame([{"종류": "아파트", "이름": row["단지명"], "longitude": float(row["경도"]), "latitude": float(row["위도"])} for row in apartments if row["경도"] and row["위도"]])
    joined_apts = {(r["이름"]): r for r in join_points(pts, polygons)}
    for apt in apartments:
        match = joined_apts.get(apt["단지명"])
        apt["행정구역"] = match["행정구역"] if match else "missing"
        apt["위례동내부"] = "Y" if apt["경도"] and boundary.contains(Point(float(apt["경도"]), float(apt["위도"]))) else ("N" if apt["경도"] else "missing")
    fields = list(apartments[0])
    if "행정구역" not in fields: fields.extend(["행정구역", "위례동내부"])
    save_csv(apt_out, fields, apartments)
    if args.apartments_only:
        print(f"APARTMENTS_WRITTEN\t{apt_out}")
        print(f"APARTMENT_ROWS\t{len(apartments)}")
        return

    candidate_path = OUT / "virtual_stop_candidates.csv"
    candidates = csv_rows(candidate_path)
    candidate_points = []
    for row in candidates:
        apt = next((a for a in apartments if a["단지명"] == row["단지명"]), None)
        if apt and apt["경도"]:
            candidate_points.append({"종류": "가상정류장 후보", "이름": row["단지명"], "longitude": float(apt["경도"]), "latitude": float(apt["위도"])})
    joined_candidates = {r["이름"]: r for r in join_points(pd.DataFrame(candidate_points), polygons)} if candidate_points else {}
    for row in candidates:
        match = joined_candidates.get(row["단지명"])
        apt = next((a for a in apartments if a["단지명"] == row["단지명"]), None)
        row["행정구역"] = match["행정구역"] if match else "missing"
        row["위례동내부"] = apt["위례동내부"] if apt else "missing"
    fields = list(candidates[0])
    if "행정구역" not in fields: fields.extend(["행정구역", "위례동내부"])
    save_csv(candidate_path, fields, candidates)

    station_features = json.loads((OUT / "wirye_tram_official_stations.geojson").read_text(encoding="utf-8"))["features"]
    points = []
    for feature in station_features:
        prop = feature["properties"]; lon, lat = feature["geometry"]["coordinates"]
        points.append({"종류": "트램", "ID": str(prop.get("station_no", "")), "이름": prop.get("station_name", ""), "longitude": lon, "latitude": lat})
    for stop in csv_rows(ROOT / "sewook31" / "data" / "drt_stops.csv"):
        points.append({"종류": "DRT", "ID": stop["stop_id"], "이름": stop["stop_name"], "longitude": float(stop["longitude"]), "latitude": float(stop["latitude"])})
    joined = join_points(pd.DataFrame(points), polygons)
    for row in joined:
        row["위례동내부"] = "Y" if boundary.contains(Point(row["longitude"], row["latitude"])) else "N"
    save_csv(OUT / "stops_with_admin.csv", ["종류", "ID", "이름", "longitude", "latitude", "행정구역", "위례동내부"], joined)

    print("행정구역 열: EMD_NM (법정동), 시군구는 shapefile에 없음; EMD_CD 앞 5자리로 시군구 구분")
    print("시군구 구분: 41131 성남시 수정구, 41450 하남시, 11710 송파구")
    for row in apartments:
        if row["행정구역"] != "성남시 수정구 창곡동":
            print(f"APARTMENT_OUTSIDE\t{row['단지명']}\t{row['행정구역']}")
    print(f"STOPS_WRITTEN\t{len(joined)}")


if __name__ == "__main__":
    main()
