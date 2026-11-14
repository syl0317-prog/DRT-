"""Offline candidate matching and review maps; never used by operational routing."""
import copy
import csv
import hashlib
import html
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import folium
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
COLORS = {"no_gits": "#888888", "candidate_low_error": "#2474d2",
          "candidate_high_error": "#ef8a17", "candidate_missing_length": "#a855f7"}


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def length_m(geometry):
    if geometry.get("type") not in ("LineString", "MultiLineString"):
        raise ValueError("Expected road line geometry")
    parts = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
    if not parts:
        raise ValueError("Empty road geometry")
    total = 0
    for part in parts:
        if len(part) < 2 or any(len(p) < 2 or not math.isfinite(p[0]) or not math.isfinite(p[1])
                               or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in part):
            raise ValueError("Invalid longitude/latitude coordinates")
        total += GEOD.line_length([p[0] for p in part], [p[1] for p in part])
    if total <= 0:
        raise ValueError("Nonpositive road length")
    return total


def combine(collection, observations, previous):
    """Keep every road; preserve all observation rows and reject ambiguous road IDs."""
    enriched = copy.deepcopy(collection)
    roads = {}
    for feature in enriched["features"]:
        key = str(feature["properties"].get("link_id", "")).strip()
        if not key or key in roads:
            raise ValueError("Missing or duplicate V-World link ID")
        roads[key] = feature
        feature["properties"].update(gits_observations=[], gits_match_class="no_gits",
                                     gits_final_validation_status="review_required",
                                     gits_match_method="none", gits_drt_applicable=False)
    candidates, unmatched = [], []
    for observation in observations:
        key = str(observation.get("link_id", "")).strip()
        feature = roads.get(key)
        if feature is None:
            unmatched.append(dict(observation, gits_link_id=key, match_method="id_exact",
                                  match_status="unmatched", final_validation_status="review_required",
                                  reason="No identical V-World link ID; crosswalk required"))
            continue
        length = length_m(feature["geometry"])
        speed, seconds = positive(observation.get("mean_speed_kmh")), positive(observation.get("mean_travel_time_sec"))
        implied = speed * seconds / 3.6 if speed is not None and seconds is not None else None
        if implied is not None and not math.isfinite(implied):
            implied = None
        error = abs(length - implied) / length * 100 if implied is not None else None
        status = ("candidate_missing_length" if error is None else
                  "candidate_low_error" if error <= 10 else "candidate_high_error")
        old = [row for row in previous if row.get("link_id", "").strip() == key
               and row.get("source") == observation.get("source")]
        consistent = len(old) == 1
        if consistent:
            try:
                consistent = (json.loads(old[0].get("geometry", "null")) == feature["geometry"]
                              and old[0].get("vworld_road_name") == feature["properties"].get("road_name")
                              and all(old[0].get(k) == v for k, v in observation.items()))
            except (ValueError, TypeError):
                consistent = False
        history = "wirye_traffic_history.csv" in observation.get("source", "")
        row = dict(vworld_link_id=key, gits_link_id=key, road_name=feature["properties"].get("road_name", ""),
                   gits_road_name=observation.get("road_name", ""), direction=observation.get("direction", ""),
                   vworld_length_m=length, mean_speed_kmh=speed, mean_travel_time_sec=seconds,
                   implied_length_m=implied, length_error_pct=error,
                   observed_or_collected_at=observation.get("observed_at", "missing"),
                   timestamp_semantics="collection_time; measurement_time_unverified" if history else "unverified",
                   collected_at=observation.get("observed_at", "missing") if history else None,
                   source=observation.get("source", ""), vworld_source="data/vworld/wirye_road_links.geojson",
                   match_method="id_exact", match_status=status, final_validation_status="review_required",
                   geometry_verified=False, direction_verified=False, drt_applicable=False,
                   previous_matching_consistent=consistent,
                   observation_count=observation.get("observation_count", ""))
        candidates.append(row)
        feature["properties"]["gits_observations"].append(row)
        feature["properties"]["gits_match_method"] = "id_exact"
    for feature in enriched["features"]:
        rows = feature["properties"]["gits_observations"]
        if rows:
            classes = {row["match_status"] for row in rows}
            feature["properties"]["gits_match_class"] = next(
                c for c in ("candidate_missing_length", "candidate_high_error", "candidate_low_error") if c in classes)
    return enriched, candidates, unmatched


def popup_html(rows):
    labels = [("road_name", "도로명"), ("vworld_link_id", "V-World 링크 ID"), ("gits_link_id", "GITS 링크 ID"),
              ("mean_speed_kmh", "GITS 평균속도 (km/h)"), ("mean_travel_time_sec", "GITS 평균 통행시간 (s)"),
              ("vworld_length_m", "V-World 길이 (m)"), ("implied_length_m", "환산 길이 (m)"),
              ("length_error_pct", "길이 차이율 (%)"), ("observed_or_collected_at", "관측 또는 수집 시각"),
              ("timestamp_semantics", "시각 의미"), ("source", "출처"), ("match_status", "후보 분류"),
              ("final_validation_status", "최종 검증 상태")]
    sections = []
    for row in rows:
        cells = []
        for key, label in labels:
            value = row.get(key)
            value = f"{value:.3f}" if isinstance(value, float) else "missing" if value is None else str(value)
            cells.append(f"<tr><th>{label}</th><td>{html.escape(value)}</td></tr>")
        sections.append("<table>" + "".join(cells) + "</table>")
    return "<hr>".join(sections)


def road_bounds(collection):
    """Return Leaflet latitude/longitude bounds from all input road coordinates."""
    points = []
    for feature in collection["features"]:
        geometry = feature["geometry"]
        length_m(geometry)  # Reject invalid or non-geographic input, rather than hide it.
        parts = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        points.extend(point for part in parts for point in part)
    if not points:
        raise ValueError("Cannot fit a map to an empty road collection")
    return [[min(p[1] for p in points), min(p[0] for p in points)],
            [max(p[1] for p in points), max(p[0] for p in points)]]


def make_map(collection):
    """Build road overlays independently of any external background tile service.

    Leaflet JS/CSS still load from Folium's CDNs. This is tile-free, not a fully
    offline bundle. No tile requests, provider bypass, or HTML postprocessing.
    """
    bounds = road_bounds(collection)
    center = [(bounds[0][i] + bounds[1][i]) / 2 for i in (0, 1)]
    result = folium.Map(location=center, zoom_start=13, tiles=None,
                        zoom_control=True, control_scale=True, prefer_canvas=True)
    result.get_root().header.add_child(folium.Element(
        "<style>.leaflet-container { background: #f8fafc !important; } "
        ".leaflet-popup-content table { border-collapse: collapse; } "
        ".leaflet-popup-content th, .leaflet-popup-content td { padding: 3px 6px; text-align: left; }</style>"))
    background = folium.FeatureGroup(name="GITS 교통정보 없음 (회색)")
    roads = [f for f in collection["features"] if not f["properties"]["gits_observations"]]
    folium.GeoJson(dict(type="FeatureCollection", features=roads),
                   style_function=lambda _: dict(color=COLORS["no_gits"], weight=2, opacity=.75)).add_to(background)
    background.add_to(result)
    groups = {c: folium.FeatureGroup(name=label).add_to(result) for c, label in [
        ("candidate_low_error", "후보: 길이 차이 10% 이내 (파랑)"),
        ("candidate_high_error", "후보: 길이 차이 10% 초과 (주황)"),
        ("candidate_missing_length", "후보: 길이 비교 불가 (보라)")]}
    for feature in collection["features"]:
        rows = feature["properties"]["gits_observations"]
        if not rows:
            continue
        color = COLORS[feature["properties"]["gits_match_class"]]
        # Pass geometry only; raw input strings never enter the executable map JavaScript.
        layer = folium.GeoJson(feature["geometry"], style_function=lambda _, color=color: dict(color=color, weight=6, opacity=.95),
                               highlight_function=lambda _: dict(weight=9))
        folium.Popup(popup_html(rows), max_width=560).add_to(layer)
        layer.add_to(groups[feature["properties"]["gits_match_class"]])
    folium.LayerControl(collapsed=False).add_to(result)
    result.fit_bounds(bounds, padding=(20, 20))
    result.get_root().html.add_child(folium.Element('''<div style="position:fixed;bottom:25px;left:15px;z-index:9999;background:white;padding:12px;border:1px solid #777;max-width:450px">
    <b>GITS · V-World 매칭 후보 검토 지도</b><br>
    <span style="color:#888888">■</span> GITS 없음
    <span style="color:#2474d2">■</span> 길이 차이 ≤10%
    <span style="color:#ef8a17">■</span> 길이 차이 &gt;10%<br>
    모든 후보: review_required · 실제 혼잡도 확정 지도 아님<br>
    배경 타일 없음 · 시각 및 출처는 링크 클릭으로 확인<br>
    길이 환산 = 평균속도 × 평균 통행시간 ÷ 3.6 (검토용)<br>
    DRT 배차·운행시간 계산에 적용하지 않음</div>'''))
    return result


def write_csv(path, rows):
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["gits_link_id"])
        writer.writeheader()
        writer.writerows(rows)


def run(root):
    root = Path(root).resolve()
    paths = {"vworld": root / "data/vworld/wirye_road_links.geojson",
             "gits": root / "data/processed/gits_link_summary.csv",
             "previous_matching": root / "data/processed/vworld_gits_matching.csv"}
    before = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
    original = json.loads(paths["vworld"].read_text(encoding="utf-8-sig"))
    observations = read_csv(paths["gits"])
    enriched, candidates, unmatched = combine(original, observations, read_csv(paths["previous_matching"]))
    out = root / "data/derived/gits_vworld" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "matching_candidates.csv", candidates)
    write_csv(out / "unmatched_gits.csv", unmatched)
    (out / "vworld_with_gits.geojson").write_text(json.dumps(enriched, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    make_map(enriched).save(str(out / "gits_vworld_review_map.html"))
    summary = dict(created_at_utc=datetime.now(timezone.utc).isoformat(), input_paths={k: str(p.relative_to(root)) for k, p in paths.items()},
                   input_sha256=before, vworld_feature_count=len(original["features"]), gits_summary_rows=len(observations),
                   matched_candidate_rows=len(candidates), matched_vworld_links=len({r["vworld_link_id"] for r in candidates}),
                   unmatched_gits_rows=len(unmatched), roads_without_gits=sum(not f["properties"]["gits_observations"] for f in enriched["features"]),
                   candidate_counts=dict(Counter(r["match_status"] for r in candidates)),
                   final_validation_status="review_required", match_method="trimmed string link_id exact equality",
                   source_counts=dict(Counter(r["source"] for r in observations)),
                   previous_matching_consistent_rows=sum(r["previous_matching_consistent"] for r in candidates),
                   crs_policy="No explicit source CRS; WGS84 longitude/latitude assumed; provenance unverified",
                   length_method="pyproj.Geod WGS84 ellipsoid; sum of line parts in meters",
                   error_definition="100 * abs(geometry_length - mean_speed * mean_time / 3.6) / geometry_length",
                   threshold_pct=10, drt_applicable=False,
                   map_mode="tiles_none", map_bounds=road_bounds(enriched),
                   external_background_tile_requests=False,
                   limitations=["ID equality and low length error do not verify segment or direction.",
                                "History timestamps are collection times, not verified measurement times.",
                                "Product of means is a screening reference only.",
                                "No external background tiles. Leaflet JS/CSS assets still require CDN access."])
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != before[key] for key, path in paths.items()):
        raise RuntimeError("Input changed during execution")
    (out / "matching_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out, summary
