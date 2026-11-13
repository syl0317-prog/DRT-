"""Numerical smoke checks for the live-control position simulator."""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))

from modules.vehicle_positions import SimulatedProvider, _haversine, _polyline_lengths


def point_segment_distance_m(point, a, b):
    lat0 = math.radians(point[0])
    scale_x = math.cos(lat0) * 111320
    scale_y = 110540
    px, py = point[1] * scale_x, point[0] * scale_y
    ax, ay = a[1] * scale_x, a[0] * scale_y
    bx, by = b[1] * scale_x, b[0] * scale_y
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    f = 0 if denom == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / denom))
    return math.hypot(px - (ax + f * dx), py - (ay + f * dy))


def route_distance(point, path):
    if len(path) == 1:
        return _haversine(point, path[0])
    return min(point_segment_distance_m(point, a, b) for a, b in zip(path, path[1:]))


def print_snapshot(provider, when):
    positions = provider.get_positions(when)
    drt = [p for p in positions if p["vehicle_id"].startswith("V")]
    tram = [p for p in positions if p["vehicle_id"].startswith("TR-")]
    print(f"\n{when:%H:%M}: DRT={len(drt)}, 트램={len(tram)}")
    for p in drt[:4] + tram[:4]:
        extra = f"환승여유={p.get('transfer_buffer_min', 'missing')}분" if p["vehicle_id"].startswith("V") else "환승여유=missing"
        print(f"{p['vehicle_id']} ({p['lat']:.6f},{p['lon']:.6f}) {p['status']} next={p.get('next_stop')} ETA={p.get('eta')} {extra}")
    drt_checks = []
    for p in drt:
        trip = next((tr for tr in provider.drt_trips.get(p["vehicle_id"], [])
                     if tr["planned_start"] <= when <= tr["return_arrival"]), None)
        if not trip:
            continue
        if p["status"] in ("운행중", "회차중"):
            path = trip["out_route"] if p["status"] == "운행중" else trip["back_route"]
            drt_checks.append(route_distance([p["lat"], p["lon"]], path) <= 5.0)
        elif p["status"] == "정차중":
            drt_checks.append(_haversine([p["lat"], p["lon"]], trip["tram_stop"]) < 0.01)
    if drt_checks:
        print(f"경로/정류장 좌표 검증: {sum(drt_checks)}/{len(drt_checks)} 통과 (5m 허용, 정차점은 동일 좌표)")


def main():
    day = date.today()
    provider = SimulatedProvider("평일 출근 07~09시", traffic_level="mode", service_date=day)
    for hh, mm in [(7, 0), (7, 10), (7, 20), (8, 0)]:
        print_snapshot(provider, datetime.combine(day, time(hh, mm)))

    # Monotonic progress on a single vehicle cycle (outbound, station wait, return).
    trips = sorted((trip for group in provider.drt_trips.values() for trip in group
                    if datetime.combine(day, time(7)) <= trip["planned_start"] < datetime.combine(day, time(9))),
                   key=lambda x: x["planned_start"])
    monotonic = None
    if trips:
        trip = trips[0]
        trip_vehicle = next(k for k, v in provider.drt_trips.items() if trip in v)
        stopped_at = trip["arrival"] + timedelta(minutes=1)
        stopped_position = next((p for p in provider.get_positions(stopped_at)
                                 if p["vehicle_id"] == trip_vehicle), None)
        if stopped_position and stopped_position["status"] == "정차중":
            stop_error = _haversine([stopped_position["lat"], stopped_position["lon"]], trip["tram_stop"])
            print(f"정차 좌표 검증: {trip_vehicle} at {stopped_at:%H:%M}, stop={trip['tram_stop_id']}, 좌표차={stop_error:.4f}m")
        else:
            print("정차 좌표 검증: 정차 표본 missing")
        samples = []
        cursor = trip["planned_start"]
        while cursor <= trip["return_arrival"]:
            positions = provider.get_positions(cursor)
            p = next((x for x in positions if x["vehicle_id"] == trip_vehicle), None)
            if p:
                if p["status"] == "운행중":
                    dist = _polyline_lengths(p.get("_past_coordinates", []))[-1] if p.get("_past_coordinates") else 0
                elif p["status"] == "정차중":
                    dist = _polyline_lengths(trip["out_route"])[-1]
                elif p["status"] == "회차중":
                    back = _polyline_lengths(p.get("_past_coordinates", []))[-1] if p.get("_past_coordinates") else 0
                    dist = _polyline_lengths(trip["out_route"])[-1] + back
                else:
                    dist = None
                if dist is not None:
                    samples.append(dist)
            cursor += timedelta(minutes=1)
        monotonic = all(b >= a - 1 for a, b in zip(samples, samples[1:]))
        print(f"\n동일 DRT 운행 1분 간격 이동거리 단조 증가: {monotonic}; 검사 프레임={len(samples)}")
    else:
        print("\n동일 DRT 운행 단조성: 확인 못함 (07~09시 trips missing)")

    high = SimulatedProvider("평일 출근 07~09시", traffic_level="max", service_date=day)
    missed = [(vid, trip) for vid, group in high.drt_trips.items() for trip in group if trip["missed"]]
    if missed:
        vid, trip = missed[0]
        slack = (trip["target_tram"] - trip["arrival"]).total_seconds() / 60
        wait = (trip["next_train"] - trip["arrival"]).total_seconds() / 60 if trip["next_train"] else None
        print(f"혼잡 max 환승 놓침 사례: {vid}, 트램={trip['target_tram']:%H:%M}, DRT 도착={trip['arrival']:%H:%M}, 여유={slack:.1f}분, 다음 트램 대기={math.ceil(wait) if wait is not None else 'missing'}분")
    else:
        print("혼잡 max 환승 놓침 사례: 없음 (현재 설정에서 missed transfer missing)")
    print(f"mode 경고 수={len(provider.get_warnings())}; max 경고 수={len(high.get_warnings())}")


if __name__ == "__main__":
    main()
