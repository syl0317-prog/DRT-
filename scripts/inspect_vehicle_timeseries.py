"""Read-only diagnostic for the weekday AM simulated fleet timeline."""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))
from modules.vehicle_positions import SimulatedProvider  # noqa: E402


def haversine_m(a, b):
    from math import atan2, cos, radians, sin, sqrt
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    z = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371000 * 2 * atan2(sqrt(z), sqrt(1 - z))


def main():
    p = SimulatedProvider(scenario="평일 출근 07~09시", service_date=date(2026, 11, 16))
    previous = {}
    history = {f"V{i:02d}": [] for i in range(1, 5)}
    for minute in range(6 * 60 + 30, 9 * 60 + 1, 5):
        t = datetime.combine(date(2026, 11, 16), time(minute // 60, minute % 60))
        for pos in p.get_positions(t):
            vid = pos["vehicle_id"]
            if not vid.startswith("V"):
                continue
            prev = previous.get(vid)
            dist = haversine_m((prev["lat"], prev["lon"]), (pos["lat"], pos["lon"])) if prev else None
            trip = next((x for x in p.drt_trips.get(vid, []) if x["planned_start"] <= t <= x["return_arrival"]), None)
            row = {"time": t, "vehicle": vid, "lat": pos["lat"], "lon": pos["lon"],
                   "status": pos["status"], "distance_m": dist,
                   "trip": f"{vid}-{trip['target_tram']:%Y%m%d-%H%M%S}" if trip else None,
                   "next_stop": pos.get("next_stop")}
            history[vid].append(row)
            previous[vid] = pos
    print("시각,차량,위도,경도,상태,직전샘플_이동거리_m,운행번호,다음정차지점")
    for vid, rows in history.items():
        for r in rows:
            dist_label = "missing" if r["distance_m"] is None else f"{r['distance_m']:.1f}"
            trip_label = r["trip"] or "missing"
            print(f"{r['time']:%H:%M},{vid},{r['lat']:.6f},{r['lon']:.6f},{r['status']},"
                  f"{dist_label},{trip_label},{r['next_stop'] or 'missing'}")
    output = ROOT / "data" / "processed" / "vehicle_timeseries_am.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["시각", "차량", "위도", "경도", "상태", "직전 샘플 대비 이동거리(m)", "현재 운행 번호", "다음 정차 지점"])
        for rows in history.values():
            for r in rows:
                writer.writerow([r["time"].strftime("%H:%M"), r["vehicle"], f"{r['lat']:.6f}", f"{r['lon']:.6f}",
                                 r["status"], "missing" if r["distance_m"] is None else f"{r['distance_m']:.1f}",
                                 r["trip"] or "missing", r["next_stop"] or "missing"])
    print(f"\n시계열 CSV: {output.relative_to(ROOT)} ({sum(map(len, history.values()))}행)")
    print("\n정지 구간(연속 10분 이상 거의 0):")
    for vid, rows in history.items():
        stationary = [r for r in rows if r["distance_m"] is not None and r["distance_m"] < 10]
        longest = 0
        run = 0
        for r in rows:
            run = run + 5 if r["distance_m"] is not None and r["distance_m"] < 10 else 0
            longest = max(longest, run)
        print(f"{vid}: {longest}분; schedule trips={len(p.drt_trips.get(vid, []))}; "
              f"first={p.drt_trips.get(vid, [{}])[0].get('planned_start') if p.drt_trips.get(vid) else 'none'}; "
              f"last={p.drt_trips.get(vid, [{}])[-1].get('return_arrival') if p.drt_trips.get(vid) else 'none'}")
        peak = [x for x in p.drt_trips.get(vid, [])
                if datetime.combine(p.day, time(7)) <= x["target_tram"] < datetime.combine(p.day, time(9))]
        gaps = [round((b["planned_start"] - a["return_arrival"]).total_seconds() / 60, 1)
                for a, b in zip(peak, peak[1:])]
        print(f"  peak trips={len(peak)}, home={peak[0]['home_id'] if peak else 'missing'}, "
              f"targets={[x['target_tram'].strftime('%H:%M:%S') for x in peak[:6]]}, "
              f"return-to-next-start gaps(min)={gaps[:5]}")
    for level in ("mode", "max"):
        warn_provider = SimulatedProvider(scenario="평일 출근 07~09시", traffic_level=level,
                                          service_date=date(2026, 11, 16))
        print(f"\n경고 분류 traffic_level={level}:")
        for category, messages in warn_provider.get_warning_categories().items():
            for message in messages:
                print(f"[{category}] {message}")
    print("\nInputs:")
    for rel in ("data/processed/apartment_classification.csv", "data/assumptions/demand_weight_params.json",
                "data/assumptions/apartment_households.csv", "data/processed/apartment_master.csv",
                "data/processed/apartment_tram_access.csv", "sewook31/sim_params.json"):
        path = ROOT / rel
        print(f"{rel}: {'present' if path.exists() else 'missing'}")
        if path.exists() and path.suffix == ".json":
            print(json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
        elif path.exists():
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                print("columns:", reader.fieldnames)
                print("sample:", next(reader, None))
    print("capacity:", json.dumps(p.config.get("vehicle_capacity", "missing"), ensure_ascii=False))
    print("Warnings:", json.dumps(p.get_warnings(), ensure_ascii=False))


if __name__ == "__main__":
    main()
