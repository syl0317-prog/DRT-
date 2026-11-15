"""Peak-hour fixed-route DRT: tram-anchored reverse timetable, time windows and demand sizing.

Pipeline (research model, not observed operation):
1. Virtual tram timetable at each route's transfer station
   (first train + main-line station offset + n x peak headway, tram_timetable.json).
2. DRT travel time = road model x congestion factor k + intermediate dwell.
   k ~ triangular(min, mode, max):
   * R03/R04 (Bokjeong entrance corridor): weekday hourly GITS speed ratios
     k = free-flow speed / hourly speed (congestion_by_hour.csv), period min/median/max;
   * R01/R02 (inside residential area): (1.0, 1.1, 1.2) assumption, no observed data yet.
3. Reverse calculation: first-stop departure D0 = tram - walk - Q_target(total travel),
   so the transfer succeeds with the target probability (default 95%).
4. Boarding time window at each stop = D0 + [Q5, Q95] of travel to that stop.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from modules.settings import PROJECT_DIR, setting

KST = ZoneInfo("Asia/Seoul")
TIMETABLE = PROJECT_DIR / "data/assumptions/tram_timetable.json"
STATIONS = PROJECT_DIR / "data/processed/wirye_tram_official_stations.geojson"
CONGESTION = PROJECT_DIR / "data/processed/congestion_by_hour.csv"
PERIODS = {"출근": (time(7, 0), time(9, 0)), "퇴근": (time(17, 0), time(19, 0))}
RESIDENTIAL_K = (1.0, 1.1, 1.2)
CORRIDOR_ROUTES = {"R03", "R04"}
TRANSFER_STATION = {"T01": "106", "T02": "108", "R03-BOKJEONG": "112", "R04-BOKJEONG": "112"}
RUNS = 5000
SEED = 20261113
LAYOVER_MIN = 2.0
ACTIVE_STATUSES = {"예약완료", "배차 검토 필요", "배차 대기"}


def _hhmm(value):
    hour, minute = map(int, str(value).split(":"))
    return time(hour, minute)


def tram_service():
    data = json.loads(TIMETABLE.read_text(encoding="utf-8"))
    service = data["service"]
    offsets, total = {data["main_line"]["station_order"][0]: 0.0}, 0.0
    for segment in data["main_line"]["segments"]:
        total += float(segment["minutes"])
        offsets[segment["to"]] = total
    names = {f["properties"]["station_no"]: f["properties"]["station_name"]
             for f in json.loads(STATIONS.read_text(encoding="utf-8"))["features"]}
    return dict(first=_hhmm(service["first_train"]["value"]), last=_hhmm(service["last_train"]["value"]),
                headway=float(service["headway_peak"]["value"]), offsets=offsets, names=names,
                status=service["headway_peak"]["status"])


def tram_departures(destination_id, day, period, service=None):
    """Virtual departures (direction 101 마천 → 112 복정) at the route's transfer station."""
    service = service or tram_service()
    station = TRANSFER_STATION.get(destination_id)
    if station not in service["offsets"]:
        raise ValueError(f"{destination_id}: 트램 정거장 시각 오프셋이 없습니다.")
    start, end = PERIODS[period]
    cursor = datetime.combine(day, service["first"], KST) + timedelta(minutes=service["offsets"][station])
    period_start, period_end = datetime.combine(day, start, KST), datetime.combine(day, end, KST)
    result = []
    while cursor < period_end:
        if cursor >= period_start:
            result.append(cursor.replace(second=0, microsecond=0) if cursor.second < 30 else
                          (cursor + timedelta(minutes=1)).replace(second=0, microsecond=0))
        cursor += timedelta(minutes=service["headway"])
    return result, service["names"].get(station, station)


def congestion_factors(route_id, period):
    """Triangular (min, mode, max) congestion factor and its documented basis."""
    if route_id not in CORRIDOR_ROUTES:
        return RESIDENTIAL_K, "단지내 도로 가정값 1.0/1.1/1.2 · 실측 보정 전"
    hours = range(PERIODS[period][0].hour, PERIODS[period][1].hour + 1)
    with CONGESTION.open(encoding="utf-8-sig", newline="") as handle:
        values = sorted(float(r["k"]) for r in csv.DictReader(handle)
                        if int(r["시간"]) in hours and r.get("k") not in (None, ""))
    if not values:
        raise ValueError(f"congestion_by_hour.csv에 {period} 혼잡값이 없습니다.")
    median = float(np.median(values))
    return (values[0], median, values[-1]), (
        f"GITS 평일 시간대 속도 기반 k=자유류속도/시간대속도 · {period} {hours.start}~{hours.stop - 1}시 "
        f"{len(values)}개 값의 최소/중앙/최대 · 복정역 진입 간선 구간 적용 가정")


def route_model(legs, period, runs=RUNS, seed=SEED, dwell_min=None):
    """Monte Carlo travel distributions from first stop to each stop and to the destination."""
    legs = sorted(legs, key=lambda leg: leg["position"])
    if not legs or any(leg["road_min"] is None for leg in legs):
        raise ValueError("도로 모형이 없는 정류장이 있어 시간표를 만들 수 없습니다.")
    dwell = float(setting("dwell_minutes") if dwell_min is None else dwell_min)
    (lo, mode, hi), basis = congestion_factors(legs[0]["route_id"], period)
    rng = np.random.default_rng(seed)
    k = np.full(runs, lo) if lo == hi else rng.triangular(lo, mode, hi, size=runs)
    road0 = legs[0]["road_min"]
    to_stop = [(road0 - leg["road_min"]) * k + index * dwell for index, leg in enumerate(legs)]
    total = road0 * k + (len(legs) - 1) * dwell
    free_flow = road0 + (len(legs) - 1) * dwell
    return dict(legs=legs, to_stop=to_stop, total=total, k=(lo, mode, hi), basis=basis,
                free_flow=free_flow, mean=float(total.mean()), q05=float(np.quantile(total, .05)),
                q50=float(np.quantile(total, .5)), q95=float(np.quantile(total, .95)),
                buffer_index=float((np.quantile(total, .95) - total.mean()) / total.mean()),
                planning_time_index=float(np.quantile(total, .95) / free_flow))


def _floor_minute(value):
    return value.replace(second=0, microsecond=0)


def _ceil_minute(value):
    floored = _floor_minute(value)
    return floored if floored == value else floored + timedelta(minutes=1)


def build_trips(model, tram_times, walk_min=3.0, reliability=.95):
    """Reverse-calculated trips; every published time is rounded toward safety."""
    if not 0.5 <= reliability < 1:
        raise ValueError("환승 성공 목표는 50% 이상 100% 미만이어야 합니다.")
    planned = float(np.quantile(model["total"], reliability))
    trips = []
    for number, tram in enumerate(tram_times, 1):
        departure = _floor_minute(tram - timedelta(minutes=walk_min + planned))
        offset = (tram - departure).total_seconds() / 60
        windows = []
        for leg, travel in zip(model["legs"], model["to_stop"]):
            windows.append(dict(stop_id=leg["stop_id"], stop_name=leg["stop_name"],
                                start=_floor_minute(departure + timedelta(minutes=float(np.quantile(travel, .05)))),
                                end=_ceil_minute(departure + timedelta(minutes=float(np.quantile(travel, .95))))))
        arrivals = model["total"] + walk_min
        trips.append(dict(trip=number, tram_departure=tram, departure=departure, windows=windows,
                          arrival_start=_floor_minute(departure + timedelta(minutes=model["q05"])),
                          arrival_end=_ceil_minute(departure + timedelta(minutes=model["q95"])),
                          success_pct=float((arrivals <= offset).mean() * 100),
                          mean_tram_wait=float(np.maximum(offset - arrivals, 0).mean())))
    return trips


def vehicles_needed(model, drt_headway):
    """Cycle = reliable outbound + return deadhead (same road model, mode k, assumption) + layover."""
    cycle = model["q95"] + model["legs"][0]["road_min"] * model["k"][1] + LAYOVER_MIN
    return math.ceil(cycle / drt_headway), cycle


def timetable(route_id, day, period, walk_min=3.0, reliability=.95, legs=None):
    from modules.punctuality_routes import route_legs
    if day.weekday() >= 5:
        raise ValueError("출퇴근 고정노선은 평일에만 운행합니다. (낮·주말 호출형은 미구현)")
    legs = legs if legs is not None else route_legs()[0]
    own = [leg for leg in legs if leg["route_id"] == route_id]
    if not own:
        raise ValueError(f"{route_id}: 운영 노선 정류장이 없습니다.")
    model = route_model(own, period)
    trams, station = tram_departures(own[0]["destination_id"], day, period)
    return dict(route_id=route_id, period=period, day=day, station=station, model=model,
                trips=build_trips(model, trams, walk_min, reliability), walk_min=walk_min,
                reliability=reliability)


def slot_for(table, stop_id, requested_at=None, tram_departure=None):
    """Trip a reservation belongs to: explicit tram time first, else boarding window."""
    for trip in table["trips"]:
        if tram_departure is not None and abs((trip["tram_departure"] - tram_departure).total_seconds()) < 60:
            return trip
    if requested_at is None:
        return None
    for trip in table["trips"]:
        window = next(w for w in trip["windows"] if w["stop_id"] == stop_id)
        if requested_at <= window["end"]:
            return trip if requested_at >= window["start"] - timedelta(minutes=15) else None
    return None


def demand(table, records, capacity=None):
    """Per-trip booked passengers, load factor and the sizing recommendation."""
    capacity = int(capacity or setting("vehicle_capacity"))
    counts = {trip["trip"]: 0 for trip in table["trips"]}
    stops = {leg["stop_id"] for leg in table["model"]["legs"]}
    for record in records:
        if record.get("status") not in ACTIVE_STATUSES or record.get("boarding_stop") not in stops:
            continue
        try:
            requested = datetime.fromisoformat(record["requested_at"]).astimezone(KST) if record.get("requested_at") else None
            tram = datetime.fromisoformat(record["tram_departure"]).astimezone(KST) if record.get("tram_departure") else None
        except (TypeError, ValueError):
            continue
        if (requested or tram) is None or (requested or tram).date() != table["day"]:
            continue
        trip = slot_for(table, record["boarding_stop"], requested, tram)
        if trip:
            counts[trip["trip"]] += int(record.get("passengers") or 0)
    rows = [dict(trip=t["trip"], tram_departure=t["tram_departure"], passengers=counts[t["trip"]],
                 vehicles=max(1, math.ceil(counts[t["trip"]] / capacity)) if counts[t["trip"]] else 0)
            for t in table["trips"]]
    for row in rows:
        row["load_pct"] = row["passengers"] / (max(row["vehicles"], 1) * capacity) * 100
    headway = tram_service()["headway"]
    pairs = [a["passengers"] + b["passengers"] for a, b in zip(rows[::2], rows[1::2])]
    every_other = bool(rows) and max(pairs + [rows[-1]["passengers"] if len(rows) % 2 else 0]) <= capacity
    drt_headway = headway * (2 if every_other else 1)
    per_trip = max([r["vehicles"] for r in rows] + [1])
    if every_other:
        per_trip = 1
    fleet, cycle = vehicles_needed(table["model"], drt_headway)
    return dict(rows=rows, capacity=capacity, total=sum(counts.values()), drt_headway=drt_headway,
                every_other=every_other, vehicles=fleet * per_trip, cycle=cycle,
                note=("인접 2개 트램편 예약 합계가 정원 이하 → 트램 2편마다 1회 운행(앞 편으로 통합) 권장"
                      if every_other else "트램 매 편 연계 운행 필요"))


def next_weekdays(day, count):
    result, cursor = [], day
    while len(result) < count:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor += timedelta(days=1)
    return result
