"""Build apartment access distances, classifications, and a stop proposal."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sewook31.modules.access_priority import classify_and_rank
U = lambda s: s.encode("ascii").decode("unicode_escape")
N = {k: U(v) for k, v in {
    "name": r"\ub2e8\uc9c0\uba85", "hh": r"\uc138\ub300\uc218", "lon": r"\uacbd\ub3c4", "lat": r"\uc704\ub3c4",
    "admin": r"\ud589\uc815\uad6c\uc5ed", "inside": r"\uc704\ub840\ub3d9\ub0b4\ubd80", "model": r"\ubaa8\ub378\ubc18\uc601",
    "tram": r"\ud2b8\ub7a8\uc9c1\uc120\uac70\ub9ac_m", "tramname": r"\uac00\uc7a5\uac00\uae4c\uc6b4\ud2b8\ub7a8\uc815\uac70\uc7a5",
    "twalk": r"\ud2b8\ub7a8\ub3c4\ubcf4\ucd94\uc815_m", "bus": r"\ubc84\uc2a4\uc9c1\uc120\uac70\ub9ac_m",
    "busname": r"\uac00\uc7a5\uac00\uae4c\uc6b4\ubc84\uc2a4\uc815\ub958\uc7a5", "bwalk": r"\ubc84\uc2a4\ub3c4\ubcf4\ucd94\uc815_m",
    "buscount": r"500m\ub0b4_\ubc84\uc2a4\uc815\ub958\uc7a5\uc218", "access": r"\uc811\uadfc\uac70\ub9ac_m",
    "mode": r"\uac00\uae4c\uc6b4\uc218\ub2e8", "note": r"\ube44\uace0", "status": r"status",
}.items()}
TO5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform


def read_geojson(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["features"]


def main():
    out = ROOT / "data/processed"
    assumptions = ROOT / "data/assumptions"
    assumptions.mkdir(parents=True, exist_ok=True)
    params = {"tram_walk_threshold_m": 700, "bus_walk_threshold_m": 500,
              "walk_factor": 1.3, "service_stop_count": 4, "max_service_stops": 8,
              "drt_transfer_tram_ids": ["106", "108"],
              "status": "assumption", "transfer_station_basis": "사용자 제공 답사 결과"}
    (assumptions / "classification_params.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    stations = []
    for f in read_geojson(out / "wirye_tram_official_stations.geojson"):
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        stations.append({"id": str(p.get("station_no", "")), "name": p.get("station_name", ""), "lon": lon, "lat": lat,
                         "xy": transform(TO5179, Point(lon, lat))})

    boundary_features = read_geojson(out / "wirye_changgok_boundary.geojson")
    boundary = shape(boundary_features[0]["geometry"])
    crs = boundary_features[0].get("properties", {}).get("crs")
    # GeoJSON coordinates in this project are longitude/latitude; project before buffering.
    boundary_m = transform(TO5179, boundary).buffer(300)
    bus_path = ROOT / "data/raw/국토교통부_전국 버스정류장 위치정보_20251031 (1).csv"
    busdf = pd.read_csv(bus_path, encoding="cp949", dtype=str)
    bus_records, seen = [], set()
    lon_col, lat_col = N["lon"], N["lat"]
    lons, lats = pd.to_numeric(busdf[lon_col], errors="coerce"), pd.to_numeric(busdf[lat_col], errors="coerce")
    valid = lons.notna() & lats.notna()
    xs, ys = TO5179(lons[valid].to_numpy(), lats[valid].to_numpy())
    bminx, bminy, bmaxx, bmaxy = boundary_m.bounds
    prepared_buffer, prepared_boundary = prep(boundary_m), prep(transform(TO5179, boundary))
    subset_indices = list(busdf.index[valid])
    for source_i, x, y in zip(subset_indices, xs, ys):
        if x < bminx or x > bmaxx or y < bminy or y > bmaxy:
            continue
        pt = Point(float(x), float(y))
        if not prepared_buffer.covers(pt):
            continue
        lon, lat = float(lons.loc[source_i]), float(lats.loc[source_i])
        key = (round(lon, 7), round(lat, 7))
        if key in seen:
            continue
        seen.add(key)
        row = busdf.loc[source_i]
        bus_records.append({"id": str(row.get(U(r"\uc815\ub958\uc7a5\ubc88\ud638"), "")),
                            "name": str(row.get(U(r"\uc815\ub958\uc7a5\uba85"), "")), "lon": lon, "lat": lat,
                            "xy": pt, "inside": "Y" if prepared_boundary.contains(pt) else "N"})
    bus_export = [{"stop_id": b["id"], "stop_name": b["name"], "위도": b["lat"], "경도": b["lon"],
                   "위례동내부": b["inside"], "source": bus_path.name, "status": "sourced"} for b in bus_records]
    pd.DataFrame(bus_export).to_csv(out / "bus_stops_wirye_300m.csv", index=False, encoding="utf-8-sig")

    apartments = pd.read_csv(out / "apartment_master_admin.csv", encoding="utf-8-sig")
    rows = []
    for _, a in apartments.iterrows():
        d = a.to_dict()
        try:
            lon, lat = float(a[N["lon"]]), float(a[N["lat"]])
            if pd.isna(lon) or pd.isna(lat):
                raise ValueError
        except (ValueError, TypeError):
            continue
        apt_xy = transform(TO5179, Point(lon, lat))
        near_t = min(stations, key=lambda x: x["xy"].distance(apt_xy))
        near_b = min(bus_records, key=lambda x: x["xy"].distance(apt_xy)) if bus_records else None
        td = near_t["xy"].distance(apt_xy)
        bd = near_b["xy"].distance(apt_xy) if near_b else None
        bcount = sum(b["xy"].distance(apt_xy) <= 500 for b in bus_records if b["inside"] == "Y")
        tw, bw = td * 1.3, bd * 1.3 if bd is not None else None
        access = min(x for x in (tw, bw) if x is not None)
        nearest_mode = "트램" if tw <= (bw if bw is not None else float("inf")) else "버스"
        d.update({N["tramname"]: near_t["name"], N["tram"]: round(td, 1), N["twalk"]: round(tw, 1),
                  N["busname"]: near_b["name"] if near_b else "", N["bus"]: round(bd, 1) if bd is not None else "",
                  N["bwalk"]: round(bw, 1) if bw is not None else "", N["buscount"]: bcount,
                  N["access"]: round(access, 1), N["mode"]: nearest_mode,
                  N["note"]: "대표 좌표 사용; 직선거리 x 1.3 도보 추정", N["status"]: "assumption"})
        rows.append(d)

    access_path = out / "apartment_access.csv"
    raw_rows, fieldnames = [], None
    for r in rows:
        raw_rows.append(r)
    if raw_rows:
        frame = pd.DataFrame(raw_rows)
        frame.to_csv(access_path, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(access_path, index=False, encoding="utf-8-sig")
    classified, summary = classify_and_rank(raw_rows, 700, 500, 4, 8)
    pd.DataFrame(classified).to_csv(out / "drt_service_priority.csv", index=False, encoding="utf-8-sig")

    # Proposal stop list preserves the two existing tram interchange rows and schema.
    stops_path = ROOT / "sewook31/data/drt_stops.csv"
    old = pd.read_csv(stops_path, encoding="utf-8-sig", dtype=str)
    stop_cols = old.columns.tolist()
    tram_rows = old[old["stop_type"] == "tram"].head(2).to_dict("records")
    tram_candidates = [s for s in stations if s["id"] in params["drt_transfer_tram_ids"]]
    selected = [r for r in classified if r.get("\uc11c\ube44\uc2a4\ub300\uc0c1") == "Y"]
    v2_rows = list(tram_rows)
    for i, row in enumerate(selected, 1):
        apt = next(a for a in rows if a[N["name"]] == row[N["name"]])
        nearest = min(tram_candidates, key=lambda s: s["xy"].distance(transform(TO5179, Point(float(apt[N["lon"]]), float(apt[N["lat"]])))))
        tram_name = nearest["name"]
        # Keep the original stop schema; zone records the allowed interchange station.
        tram_id = nearest["id"]
        stop_rows = stop_cols
        v2_rows.append({"stop_id": f"D{i:02d}", "stop_name": str(row[N["name"]]), "stop_type": "drt",
                        "zone": f"{nearest['name']}({tram_id})", "latitude": float(apt[N["lat"]]),
                        "longitude": float(apt[N["lon"]])})
    pd.DataFrame(v2_rows, columns=stop_rows).to_csv(ROOT / "sewook31/data/drt_stops_v2.csv", index=False, encoding="utf-8-sig")

    sim_path = assumptions / "sim_params.json"
    cfg = json.loads(sim_path.read_text(encoding="utf-8"))
    cfg["stops_file"] = "drt_stops_v2.csv"
    cfg["disabled_scenarios"] = ["\ud3c9\uc77c \ub0ae \ud638\ucd9c\ud615", "\uc8fc\ub9d0"]
    sim_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"bus_points_deduplicated": len(bus_records), "bus_stops_inside": sum(b["inside"] == "Y" for b in bus_records),
                      "apartments_with_coordinates": len(rows), "priority_summary": summary,
                      "stop_columns": stop_cols}, ensure_ascii=False))


if __name__ == "__main__":
    main()
