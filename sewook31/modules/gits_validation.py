"""Offline evidence audit. Summary values never establish verified observations."""
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from modules.gits_analysis import AS_OF
from modules.vworld_graph import GEOD


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def geometry_length(geometry):
    """Reuse stage-one WGS84 geodesic, without building topology."""
    if not geometry or geometry.get("type") not in ("LineString", "MultiLineString"):
        return None
    parts = [geometry.get("coordinates")] if geometry["type"] == "LineString" else geometry.get("coordinates")
    try:
        if not parts:
            return None
        total = 0
        for part in parts:
            if len(part) < 2 or any(len(p) < 2 or number(p[0]) is None or number(p[1]) is None
                    or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in part):
                return None
            length = GEOD.line_length([p[0] for p in part], [p[1] for p in part])
            if length <= 0:
                return None
            total += length
        return total
    except (TypeError, ValueError, IndexError):
        return None


def audit(features, observations, quality_rows, matching_rows):
    """One output per summary row, including unmatched rows.

    No evidence registry exists in these inputs; verified is deliberately
    unreachable. Name/length differences are review flags, not proof of a bad
    mapping. Missing values require review; nonpositive/nonfinite numeric values
    are unusable. Mean(speed)*mean(time) is not mean individual implied length.
    """
    roads, qualities, previous = defaultdict(list), defaultdict(list), defaultdict(list)
    for feature in features:
        roads[str(feature.get("properties", {}).get("link_id", "")).strip()].append(feature)
    for row in quality_rows:
        qualities[(row.get("source", ""), row.get("link_id", "").strip())].append(row)
    for row in matching_rows:
        previous[(row.get("source", ""), row.get("link_id", "").strip())].append(row)
    keys = Counter((r.get("source", ""), r.get("link_id", "").strip()) for r in observations)
    ids = Counter(r.get("link_id", "").strip() for r in observations)
    results = []
    for row in observations:
        link = row.get("link_id", "").strip()
        source = row.get("source", "")
        key = (source, link)
        matches = roads.get(link, []) if link else []
        reasons = []
        invalid = False
        speed, seconds, recorded = (number(row.get(k)) for k in ("mean_speed_kmh", "mean_travel_time_sec", "length_m"))
        for field, value in (("mean_speed_kmh", speed), ("mean_travel_time_sec", seconds), ("length_m", recorded)):
            raw = str(row.get(field, "")).strip()
            if raw.lower() in ("", "missing", "none", "null"):
                reasons.append(field + "_missing")
            elif value is None or value <= 0:
                invalid = True
                reasons.append(field + "_invalid")
        valid_speed_time = speed is not None and seconds is not None and min(speed, seconds) > 0
        implied = speed * seconds / 3.6 if valid_speed_time else None
        if implied is not None and not math.isfinite(implied):
            implied = None
            invalid = True
            reasons.append("implied_length_overflow")
        road = matches[0] if len(matches) == 1 else None
        length = geometry_length(road.get("geometry")) if road else None
        name = str(road.get("properties", {}).get("road_name", "")) if road else ""
        name_match = bool(name.strip() and name.strip() == row.get("road_name", "").strip())
        if not matches:
            reasons.append("vworld_id_unmatched; spatial_crosswalk_required")
        elif len(matches) > 1:
            reasons.append("vworld_id_ambiguous")
        elif length is None:
            invalid = True
            reasons.append("vworld_geometry_invalid")
        if road and not name_match:
            reasons.append("road_name_missing_or_different; not_confirmed_wrong_match")
        error = abs(length-implied)/length if length is not None and implied is not None else None
        recorded_error = abs(length-recorded)/length if length is not None and recorded is not None and recorded > 0 else None
        if error is not None and error > .1:
            reasons.append("geometry_vs_implied_length_over_10pct; screening_only")
        if recorded_error is not None and recorded_error > .1:
            reasons.append("geometry_vs_recorded_length_over_10pct")
        timestamps = row.get("observed_at", "")
        tokens = timestamps.split(";")
        parsed = True
        try:
            for token in tokens:
                if datetime.fromisoformat(token.replace("Z", "+00:00")).tzinfo is None:
                    parsed = False
        except ValueError:
            parsed = False
        reasons.extend(["direction_to_geometry_unverified", "actual_segment_location_unverified",
            "provider_and_original_source_lineage_unverified", "timestamp_semantics_unverified",
            "observation_deduplication_not_possible_from_summary"])
        if not parsed:
            reasons.append("timestamp_missing_invalid_or_timezone_missing")
        if "wirye_traffic_history.csv" in source:
            reasons.append("observed_at_derived_from_collected_at; not_verified_measurement_time")
        count = number(row.get("observation_count"))
        if count is None or count < 1 or count != int(count):
            reasons.append("observation_count_missing_or_invalid")
        elif count > 1:
            reasons.append("multiple_observations_not_proof_of_duplicates; product_of_means_reference_only")
        if keys[key] > 1 or ids[link] > 1:
            reasons.append("duplicate_summary_key_or_cross_source_link; do_not_pool")
        q = qualities.get(key, [])
        if len(q) != 1:
            reasons.append("quality_record_missing_or_ambiguous")
        elif any(q[0].get(k) != row.get(k) for k in ("observation_count", "valid_count", "invalid_count", "quality", "length_consistency")):
            reasons.append("quality_summary_disagreement")
        if (number(row.get("invalid_count")) or 0) > 0:
            reasons.append("source_contains_invalid_observations")
        old = previous.get(key, [])
        old_consistent = len(old) == 1 and road is not None
        if old_consistent:
            try:
                old_consistent = (old[0].get("vworld_road_name") == name and
                    json.loads(old[0].get("geometry", "null")) == road.get("geometry") and
                    all(old[0].get(k) == row.get(k) for k in ("road_name", "mean_speed_kmh", "mean_travel_time_sec", "observed_at")))
            except (ValueError, TypeError):
                old_consistent = False
        if matches and not old_consistent:
            reasons.append("previous_matching_missing_ambiguous_or_stale")
        results.append(dict(summary_row_index=len(results), link_id=link, source=source,
            road_name=row.get("road_name", ""), vworld_road_name=name, id_match=bool(matches),
            vworld_match_count=len(matches), road_name_match=name_match,
            mean_speed_kmh=speed, mean_travel_time_sec=seconds, vworld_length_m=length,
            gits_recorded_length_m=recorded, implied_length_reference_m=implied,
            geometry_implied_error_pct=error*100 if error is not None else None,
            geometry_recorded_error_pct=recorded_error*100 if recorded_error is not None else None,
            observed_at=timestamps, timestamp_timezone_parseable=parsed,
            timestamp_semantics="unverified; collection time possible", direction=row.get("direction", ""),
            direction_verified=False, location_verified=False, provider_verified=False,
            observation_count=count, valid_count=number(row.get("valid_count")), invalid_count=number(row.get("invalid_count")),
            summary_key_count=keys[key], link_summary_row_count=ids[link],
            quality_record_count=len(q), previous_matching_consistent=old_consistent,
            status="unusable" if invalid else "review_required", drt_applicable=False,
            reasons=" | ".join(reasons)))
    matched = [r for r in results if r["id_match"]]
    counts = lambda rows: {s: sum(r["status"] == s for r in rows) for s in ("verified", "review_required", "unusable")}
    return results, dict(total_summary_rows=len(results), total_unique_gits_links=len(set(r["link_id"] for r in results)),
        matched_unique_links=len(set(r["link_id"] for r in matched)), all_status_counts=counts(results),
        matched_status_counts=counts(matched), applicable_rows=sum(r["drt_applicable"] for r in results),
        length_error_definition="100*abs(vworld_length-implied_length)/vworld_length; implied is reference only",
        threshold_pct=10, threshold_semantics="screening only, never verification or proof of mismatch",
        prior_matching_row_count=len(matching_rows),
        prior_matching_keys_without_summary=[list(k) for k in previous if k not in keys],
        limitations=["No independent segment/direction/provider/time evidence in inputs; no automatic verified classification.",
            "Summary counts cannot distinguish repeats from exact duplicate observations.",
            "Product of mean speed and mean time need not equal mean implied length.",
            "No traffic speed applied; no external APIs; no route or scheduling changes."])


def run_audit(root, output_root=None):
    root = Path(root)
    inputs = {name: root/"data/processed"/name for name in
              ("gits_link_summary.csv", "gits_data_quality.csv", "vworld_gits_matching.csv")}
    inputs["wirye_road_links.geojson"] = root/"data/vworld/wirye_road_links.geojson"
    features = json.loads(inputs["wirye_road_links.geojson"].read_text(encoding="utf-8-sig"))["features"]
    rows, report = audit(features, *(read_csv(inputs[n]) for n in
        ("gits_link_summary.csv", "gits_data_quality.csv", "vworld_gits_matching.csv")))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid4().hex
    out = Path(output_root or root/"drt_system/data/derived")/run_id
    out.mkdir(parents=True, exist_ok=False)
    with (out/"gits_link_validation.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["link_id", "status"])
        writer.writeheader()
        writer.writerows({k: "missing" if v is None else v for k, v in r.items()} for r in rows)
    for filename, data in [("gits_validation_report.json", report), ("build_metadata.json", dict(
            run_id=run_id, audit_at_utc=datetime.now(timezone.utc).isoformat(), existing_analysis_as_of=AS_OF,
            input_sha256={n: hashlib.sha256(p.read_bytes()).hexdigest() for n,p in inputs.items()},
            implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            policy="offline summary audit; no independent evidence registry; verified blocked"))]:
        with (out/filename).open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return out, report
