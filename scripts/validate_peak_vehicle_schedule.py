"""Validate repeated AM DRT trip assignment and movement status labels."""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))
from modules.vehicle_positions import SimulatedProvider, _haversine  # noqa: E402


def main():
    day = date(2026, 11, 16)  # Monday, fixed for reproducible weekday peak checks.
    provider = SimulatedProvider(scenario="평일 출근 07~09시", traffic_level="mode", service_date=day)
    start, end = datetime.combine(day, time(6, 30)), datetime.combine(day, time(9))
    previous = {}
    moving_without_motion = []
    repeated = {f"V{i:02d}": 0 for i in range(1, 5)}
    cursor = start
    while cursor <= end:
        for row in provider.get_positions(cursor):
            vid = row["vehicle_id"]
            if not vid.startswith("V"):
                continue
            if row.get("status") == "운행중" and vid in previous:
                distance = _haversine((previous[vid]["lat"], previous[vid]["lon"]),
                                      (row["lat"], row["lon"]))
                if distance < 1:
                    moving_without_motion.append((cursor.strftime("%H:%M"), vid, distance))
            previous[vid] = row
            if row.get("trip_id"):
                repeated[vid] += 1
        cursor += timedelta(minutes=1)

    print("평일 출근 일정 검증 (고정 날짜 2026-11-16, assumption: 시뮬레이션 날짜)")
    homes, target_times = set(), set()
    for vid in sorted(provider.drt_trips):
        peak = [x for x in provider.drt_trips[vid]
                if datetime.combine(day, time(7)) <= x["target_tram"] < datetime.combine(day, time(9))]
        homes.update(x["home_id"] for x in peak)
        target_times.update(x["target_tram"] for x in peak)
        gaps = [(b["planned_start"] - a["return_arrival"]).total_seconds() / 60
                for a, b in zip(peak, peak[1:])]
        print(f"{vid}: 운행지점={peak[0]['home_id'] if peak else 'missing'}, "
              f"07~09시 운행수={len(peak)}, "
              f"트램시각={[x['target_tram'].strftime('%H:%M:%S') for x in peak]}, "
              f"운행간 대기(분)={[round(x, 1) for x in gaps]}")
    print(f"차량별 서로 다른 운행지점 수={len(homes)}; peak 트램 배정시각 수={len(target_times)}")
    print(f"운행중 1분 샘플 이동거리 1m 미만={len(moving_without_motion)}")
    print(f"4대 모두 반복 배정={all(any(x['planned_start'] < end for x in provider.drt_trips[v]) for v in repeated)}")
    print(f"차량별 06:30~09:00 표본에서 trip 표시 횟수={repeated}")
    print("경고 유형:")
    for level in ("mode", "max"):
        checked = SimulatedProvider(scenario="평일 출근 07~09시", traffic_level=level, service_date=day)
        print(f"  {level}: 총 {sum(map(len, checked.get_warning_categories().values()))}건")
        for category, messages in checked.get_warning_categories().items():
            print(f"    {category}: {len(messages)}건")
            for message in messages:
                print(f"      - {message}")
    if moving_without_motion:
        raise SystemExit("운행중인데 1분 동안 사실상 정지한 차량 샘플이 있습니다.")
    if len(homes) != 4 or any(len([x for x in provider.drt_trips[v]
                                  if datetime.combine(day, time(7)) <= x['target_tram'] < end]) < 2
                               for v in provider.drt_trips):
        raise SystemExit("차량 네 대의 서로 다른 정류장/반복 peak 운행 확인 실패")


if __name__ == "__main__":
    main()
