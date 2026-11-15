"""Match R01~R04 stored road models to national standard node-link (MOCT_LINK) links.

Input : data/raw/[2026-09-14]NODELINKDATA/MOCT_LINK.shp (git-ignored, read-only)
Output: data/processed/route_link_matching.csv (tracked; the app reads only this file)

Method: sample each route polyline every STEP_M metres; assign a sample to the nearest
link within MAX_DIST_M whose direction agrees with the travel direction (< MAX_ANGLE deg).
Consecutive samples on the same link become one row. Unassigned samples are kept as
"미매칭" rows so the matched share is visible. Congestion sections are attached only
where the corridor/direction correspondence is unambiguous (see SECTION_RULES).
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))

LINKS = ROOT / "data/raw/[2026-09-14]NODELINKDATA/MOCT_LINK.shp"
OUT = ROOT / "data/processed/route_link_matching.csv"
STEP_M, MAX_DIST_M, MAX_ANGLE = 10.0, 15.0, 45.0
FIELDS = ["route_id", "seq", "link_id", "road_name", "road_no", "road_rank", "max_speed_kmh",
          "length_m", "share", "heading", "congestion_section", "section_rule", "source"]

# National Route 3 south of Bokjeong is 성남대로 (복정역 ↔ 여수사거리 section in wirye_speed_raw).
# Other corridor sections (송파대로 장지IC↔갈현교차로, 분당수서로, 국도45호선) are not attached
# because their end points have not been verified against the link geometry.
SECTION_RULES = [
    dict(road_no="3", road_name="성남대로", heading="북", section="일반국도3호선 (상행: 여수사거리→복정역)"),
    dict(road_no="3", road_name="성남대로", heading="남", section="일반국도3호선 (하행: 복정역→여수사거리)"),
]


def heading_label(dx, dy):
    return "북" if dy >= abs(dx) else "남" if -dy >= abs(dx) else "동" if dx > 0 else "서"


def route_paths():
    from modules.independent_routes import RouteStore, read_original_stops
    from modules.sequential_routes import route_plans
    for plan in route_plans(read_original_stops(), RouteStore().snapshot()):
        paths = plan.get("paths") or []
        if len(paths) == 1 and len(paths[0]) >= 2:
            yield plan["route_id"], paths[0]


def match():
    import pyogrio
    from pyproj import Transformer
    from shapely.geometry import LineString
    from shapely.strtree import STRtree

    to_tm = Transformer.from_crs(4326, 5186, always_xy=True).transform
    routes = [(rid, LineString([to_tm(float(lon), float(lat)) for lat, lon in path])) for rid, path in route_paths()]
    if not routes:
        raise SystemExit("도로 모형이 완성된 노선이 없습니다.")
    xmin = min(r.bounds[0] for _, r in routes) - 200; ymin = min(r.bounds[1] for _, r in routes) - 200
    xmax = max(r.bounds[2] for _, r in routes) + 200; ymax = max(r.bounds[3] for _, r in routes) + 200
    links = pyogrio.read_dataframe(LINKS, bbox=(xmin, ymin, xmax, ymax))
    links = links[links.geometry.notna()].reset_index(drop=True)
    geometries = [g if g.geom_type == "LineString" else max(g.geoms, key=lambda p: p.length) for g in links.geometry]
    tree = STRtree(geometries)
    rows = []
    for rid, line in routes:
        samples, distance = [], 0.0
        while distance < line.length:
            a = line.interpolate(distance); b = line.interpolate(min(distance + 1.0, line.length))
            dx, dy = b.x - a.x, b.y - a.y
            best = None
            for index in tree.query(a.buffer(MAX_DIST_M)):
                geom = geometries[index]
                gap = geom.distance(a)
                if gap > MAX_DIST_M:
                    continue
                position = geom.project(a)
                p = geom.interpolate(max(position - 1, 0)); q = geom.interpolate(min(position + 1, geom.length))
                lx, ly = q.x - p.x, q.y - p.y
                norm = math.hypot(dx, dy) * math.hypot(lx, ly)
                if norm == 0:
                    continue
                angle = math.degrees(math.acos(max(-1, min(1, (dx * lx + dy * ly) / norm))))
                if angle < MAX_ANGLE and (best is None or gap < best[0]):
                    best = (gap, index)
            samples.append((best[1] if best else None, heading_label(dx, dy)))
            distance += STEP_M
        runs = []
        for index, heading in samples:
            if runs and runs[-1][0] == index:
                runs[-1][2] += 1
            else:
                runs.append([index, heading, 1])
        total = len(samples)
        for seq, (index, heading, count) in enumerate(runs, 1):
            link = links.iloc[index] if index is not None else None
            road_no = str(link["ROAD_NO"]).strip() if link is not None else ""
            road_name = str(link["ROAD_NAME"]).strip() if link is not None else "미매칭"
            rule = next((r for r in SECTION_RULES if link is not None and r["road_no"] == road_no
                         and r["road_name"] == road_name and r["heading"] == heading), None)
            rows.append(dict(route_id=rid, seq=seq, link_id=str(link["LINK_ID"]) if link is not None else "",
                             road_name=road_name, road_no=road_no, road_rank=str(link["ROAD_RANK"]) if link is not None else "",
                             max_speed_kmh=int(link["MAX_SPD"]) if link is not None else "",
                             length_m=round(count * STEP_M, 1), share=round(count / total, 4), heading=heading,
                             congestion_section=rule["section"] if rule else "",
                             section_rule=f"국도{rule['road_no']}호선 {rule['road_name']} {rule['heading']}향" if rule else "",
                             source="MOCT_LINK 2026-09-14 · 저장 OSRM 도로 모형 10m 표본 매칭(15m·45° 이내)"))
    return rows


def main():
    rows = match()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)
    print(f"저장: {OUT} ({len(rows)}행)")
    for rid in sorted({r["route_id"] for r in rows}):
        own = [r for r in rows if r["route_id"] == rid]
        matched = sum(r["share"] for r in own if r["link_id"])
        corridor = sum(r["share"] for r in own if r["congestion_section"])
        roads = {}
        for r in own:
            roads[r["road_name"]] = roads.get(r["road_name"], 0) + r["length_m"]
        print(f"{rid}: 매칭 {matched:.0%} · 시간대 혼잡자료 구간 {corridor:.0%} · " +
              ", ".join(f"{k} {v:.0f}m" for k, v in sorted(roads.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
