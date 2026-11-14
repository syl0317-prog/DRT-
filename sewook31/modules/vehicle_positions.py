"""Pluggable, deterministic vehicle positions for the pre-opening DRT demo.

The simulator is explicitly a scenario model. It does not claim to represent live GPS.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path

from modules.route_engine import calculate_road_route

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parents[1]
STOPS_FILE = APP_DIR / "data" / "drt_stops.csv"
CONGESTION_HOURLY_FILE = ROOT / "data" / "processed" / "congestion_by_hour.csv"
CONFIG_FILE = ROOT / "data" / "assumptions" / "sim_params.json"
TIMETABLE_FILE = ROOT / "data" / "assumptions" / "tram_timetable.json"
STATIONS_FILE = ROOT / "data" / "processed" / "wirye_tram_official_stations.geojson"
LINES_FILE = ROOT / "data" / "processed" / "wirye_tram_official_lines.geojson"
CONGESTION_FILE = ROOT / "data" / "assumptions" / "congestion_params.json"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_stops(config=None):
    configured = (config or {}).get("stops_file", "drt_stops.csv")
    selected = APP_DIR / "data" / str(configured)
    if not selected.is_file():
        selected = STOPS_FILE
    with selected.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _clock(value, day):
    h, m = (int(part) for part in value.split(":")[:2])
    if h == 24:
        return datetime.combine(day + timedelta(days=1), time.min)
    return datetime.combine(day, time(h, m))


def _haversine(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    z = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(z), math.sqrt(1 - z))


def _polyline_lengths(points):
    lengths = [0.0]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + _haversine(a, b))
    return lengths


def _point_on_line(points, fraction):
    if not points:
        return None
    if len(points) == 1:
        return list(points[0])
    lengths = _polyline_lengths(points)
    total = lengths[-1]
    if total <= 0:
        return list(points[0])
    target = max(0.0, min(1.0, fraction)) * total
    for i in range(1, len(lengths)):
        if lengths[i] >= target:
            span = lengths[i] - lengths[i - 1]
            f = 0.0 if span == 0 else (target - lengths[i - 1]) / span
            return [points[i - 1][0] + f * (points[i][0] - points[i - 1][0]),
                    points[i - 1][1] + f * (points[i][1] - points[i - 1][1])]
    return list(points[-1])


def _route_slice(points, fraction):
    if not points:
        return [], []
    if len(points) == 1:
        return list(points), list(points)
    lengths = _polyline_lengths(points)
    total = lengths[-1]
    if total <= 0:
        return [points[0]], list(points)
    target = max(0.0, min(1.0, fraction)) * total
    current = _point_on_line(points, fraction)
    idx = next((i for i, d in enumerate(lengths) if d >= target), len(points) - 1)
    past = [list(p) for p in points[:idx]] + [current]
    future = [current] + [list(p) for p in points[idx:]]
    return past, future


def _time_label(dt):
    return dt.strftime("%H:%M:%S") if dt else "missing"


class PositionProvider:
    """Interface for replacing simulated locations with a real GPS/API source."""

    def get_positions(self, t):
        raise NotImplementedError


class ApiProvider(PositionProvider):
    """Future adapter slot for an authorized vehicle-GPS or DRT-platform API.

    Authentication, endpoint, payload schema, freshness and privacy rules are missing.
    Do not add credentials here; load them from a deployment secret store later.
    """

    def get_positions(self, t):
        raise NotImplementedError("실제 위치 API의 인증·응답 형식이 아직 정해지지 않았습니다.")


class SimulatedProvider(PositionProvider):
    """Move DRT and tram points along cached OSRM/official-line paths."""

    TRANSFER_STATION = {"T01": "106", "T02": "108"}

    def __init__(self, scenario="평일 출근 07~09시", vehicle_count=None,
                 traffic_level="mode", route_class="진입간선", service_date=None,
                 service_window=None):
        self.scenario = scenario
        self.day = service_date or date.today()
        self.warnings = []
        if scenario == "주말":
            self.warnings.append("주말 시간표 missing; 확인된 비첨두 배차 간격을 주말에 적용한 assumption")
        self.config = self._load_config()
        self.service_window = service_window
        self.timetable = _json(TIMETABLE_FILE)
        self.congestion = _json(CONGESTION_FILE)
        count = self.config.get("vehicle_count", {})
        self.vehicle_count = int(vehicle_count if vehicle_count is not None else count.get("value", 0))
        self.traffic_level = traffic_level if traffic_level in {"min", "mode", "max"} else "mode"
        self.route_class = route_class if route_class in {"진입간선", "단지내"} else "진입간선"
        selected_stops_file = APP_DIR / "data" / str(self.config.get("stops_file", "drt_stops.csv"))
        if not selected_stops_file.is_file():
            self.warnings.append("설정된 정류장 파일을 찾지 못해 기존 drt_stops.csv를 사용했습니다.")
        self.stops = {r["stop_id"]: r for r in _read_stops(self.config)}
        self.tram_stop_ids = {k: v for k, v in self.stops.items() if v.get("stop_type") == "tram"}
        self.drt_stop_ids = {k: v for k, v in self.stops.items() if v.get("stop_type") == "drt"}
        self.station_data = _json(STATIONS_FILE)
        self.line_data = _json(LINES_FILE)
        self.hourly_congestion = self._load_hourly_congestion()
        self.stations = {f["properties"]["station_no"]: {
            "name": f["properties"].get("station_name", f["properties"]["station_no"]),
            "lat": float(f["properties"]["lat"]), "lon": float(f["properties"]["lon"]),
            "route_type": f["properties"].get("route_type", "missing")
        } for f in self.station_data.get("features", [])}
        self.tram_trips = self._build_tram_trips()
        self.drt_trips = self._build_drt_trips()

    def _load_config(self):
        if CONFIG_FILE.exists():
            return _json(CONFIG_FILE)
        fallback = APP_DIR / "sim_params.json"
        self.warnings.append("data/assumptions/sim_params.json missing; sewook31/sim_params.json fallback used")
        return _json(fallback) if fallback.exists() else {}

    def _load_hourly_congestion(self):
        try:
            import pandas as pd
            frame = pd.read_csv(CONGESTION_HOURLY_FILE, encoding="utf-8-sig")
            time_col = "시간" if "시간" in frame else None
            k_col = "k" if "k" in frame else None
            if not time_col or not k_col:
                return {}
            frame[time_col] = pd.to_numeric(frame[time_col], errors="coerce")
            frame[k_col] = pd.to_numeric(frame[k_col], errors="coerce")
            result = {}
            for hour, group in frame.dropna(subset=[time_col, k_col]).groupby(time_col):
                values = group[k_col].clip(lower=1.0)
                result[int(hour)] = {"min": float(values.min()), "mode": float(values.median()),
                                     "max": float(values.max())}
            return result
        except (OSError, ValueError, ImportError):
            return {}

    def _factor(self, when):
        band = ("출근" if 7 <= when.hour < 9 else "퇴근" if 17 <= when.hour < 19
                else "낮" if 10 <= when.hour < 16 else "밤" if 20 <= when.hour < 24 else None)
        profile = self.config.get("traffic_factor_by_band", {}).get(self.route_class, {})
        values = profile if self.route_class == "단지내" else self.hourly_congestion.get(when.hour)
        if not isinstance(values, dict):
            default = self.config.get("traffic_factor_default", {}).get("value", 1.2)
            message = f"해당 시각의 시간대 혼잡계수 missing; 기존 기본값 {default} 사용 (assumption)"
            if message not in self.warnings:
                self.warnings.append(message)
            return float(default), band or "missing", "assumption"
        raw = values.get(self.traffic_level)
        if raw is None:
            return 1.0, band, "missing"
        return float(raw), band, "assumption"

    def _service(self):
        return self.timetable.get("service", {})

    def _headway(self, dt):
        service = self._service()
        if self.scenario == "주말":
            # A weekend-specific timetable is missing; use the documented off-peak interval.
            return int(service.get("headway_off_peak", {}).get("value", 0))
        peak = service.get("peak_periods", [])
        for p in peak:
            if p.get("start") <= dt.strftime("%H:%M") < p.get("end"):
                return int(service.get("headway_peak", {}).get("value", 0))
        return int(service.get("headway_off_peak", {}).get("value", 0))

    def _line_features(self):
        result = {}
        for f in self.line_data.get("features", []):
            name = f.get("properties", {}).get("line_name", "")
            typ = "branch" if "지선" in name else "main"
            result[typ] = [[float(lat), float(lon)] for lon, lat in f.get("geometry", {}).get("coordinates", [])]
        return result

    def _path_between(self, line, start_id, end_id, coords):
        if len(line) < 2:
            return [coords[start_id], coords[end_id]]
        a, b = coords[start_id], coords[end_id]
        def nearest(p):
            return min(range(len(line)), key=lambda i: _haversine(line[i], p))
        ia, ib = nearest(a), nearest(b)
        if ia <= ib:
            points = line[ia:ib + 1]
        else:
            points = list(reversed(line[ib:ia + 1]))
        return [a] + [p for p in points[1:-1]] + [b]

    def _segment_minutes(self, line_name, start, end, distance_m, main_speed_mpm):
        section = self.timetable.get("main_line" if line_name == "main" else "branch_line", {})
        for seg in section.get("segments", []):
            if seg.get("from") == start and seg.get("to") == end and seg.get("minutes") is not None:
                return float(seg["minutes"]), "sourced"
            if seg.get("from") == end and seg.get("to") == start and seg.get("minutes") is not None:
                return float(seg["minutes"]), "sourced"
        if line_name == "branch" and main_speed_mpm and distance_m > 0:
            return distance_m / main_speed_mpm, "assumption"
        return None, "missing"

    def _line_path(self, section, reverse=False):
        ids = list(section.get("station_order", []))
        if reverse:
            ids.reverse()
        coords = {k: [v["lat"], v["lon"]] for k, v in self.stations.items()}
        lines = self._line_features()
        typ = "branch" if section is self.timetable.get("branch_line") else "main"
        line = lines.get(typ, [])
        main = self.timetable.get("main_line", {})
        total_main_dist = sum(float(s.get("distance_m", 0)) for s in main.get("segments", []))
        total_main_min = float(main.get("total_minutes", {}).get("value", 0) or 0)
        speed_mpm = total_main_dist / total_main_min if total_main_min > 0 else None
        legs = []
        for a, b in zip(ids, ids[1:]):
            if a not in coords or b not in coords:
                return None, f"tram station coordinate missing: {a}/{b}"
            path = self._path_between(line, a, b, coords)
            dist = _polyline_lengths(path)[-1]
            minutes, status = self._segment_minutes(typ, a, b, dist, speed_mpm)
            if minutes is None or minutes <= 0:
                return None, f"{typ} segment time missing: {a}-{b}"
            if status == "assumption":
                self.warnings.append(f"남위례지선 {a}-{b} 운행시간은 본선 평균속도·공식 선로거리 비례 assumption")
            legs.append({"from": a, "to": b, "coordinates": path, "minutes": minutes, "status": status})
            legs[-1]["distance_m"] = dist
        return legs, None

    def _service_departures(self):
        service = self._service()
        start = _clock(service.get("first_train", {}).get("value", "06:00"), self.day)
        end = _clock(service.get("last_train", {}).get("value", "23:30"), self.day)
        if end.date() > self.day:
            end = datetime.combine(self.day, time.max)
        departures = []
        cur = start
        while cur <= end:
            departures.append(cur)
            hw = self._headway(cur)
            if hw <= 0:
                self.warnings.append("트램 배차 간격 missing; 이후 트램 시각 생성 중단")
                break
            cur += timedelta(minutes=hw)
        return departures

    def _build_tram_trips(self):
        trips = []
        departures = self._service_departures()
        for typ, section_key, origins in (("본선", "main_line", ("101", "112")),
                                           ("남위례지선", "branch_line", ("108", "110"))):
            section = self.timetable.get(section_key, {})
            for reverse, origin in ((False, origins[0]), (True, origins[1])):
                legs, warning = self._line_path(section, reverse)
                if warning:
                    self.warnings.append(warning)
                    continue
                for base in departures:
                    events = []
                    current = base
                    for leg in legs:
                        arrival = current + timedelta(minutes=leg["minutes"])
                        events.append({**leg, "depart": current, "arrive": arrival})
                        current = arrival
                    trips.append({"vehicle_id": f"TR-{typ[0]}-{origin}-{base:%H%M}", "line": typ,
                                  "origin": origin, "reverse": reverse, "legs": events,
                                  "start": base, "end": current})
        return trips

    def _nearest_tram_stop(self, drt):
        candidates = []
        for sid, stop in self.tram_stop_ids.items():
            a = [float(drt["latitude"]), float(drt["longitude"])]
            b = [float(stop["latitude"]), float(stop["longitude"])]
            candidates.append((_haversine(a, b), sid, stop))
        return min(candidates, key=lambda x: x[0])[1:] if candidates else (None, None)

    def _station_events(self, stop_id):
        station_no = self.TRANSFER_STATION.get(stop_id)
        return sorted((leg["depart"] for trip in self.tram_trips for leg in trip["legs"]
                       if leg["from"] == station_no), key=lambda x: x)

    def _build_drt_trips(self):
        if not self.drt_stop_ids or not self.tram_stop_ids:
            self.warnings.append("DRT/트램 정류장 데이터가 비어 있어 DRT 차량을 생략했습니다.")
            return {f"V{i:02d}": [] for i in range(1, self.vehicle_count + 1)}
        if self.vehicle_count < 1:
            self.warnings.append("vehicle_count missing; DRT 차량을 생략했습니다.")
            return {}
        dwell = int(self.config.get("dwell_minutes", {}).get("value", 1))
        buffer = int(self.config.get("transfer_buffer_min", {}).get("value", 5))
        homes = sorted(self.drt_stop_ids.items())
        fleet = {f"V{i:02d}": [] for i in range(1, self.vehicle_count + 1)}
        ready = {vid: datetime.combine(self.day, time.min) for vid in fleet}
        for i, (home_id, home) in enumerate(homes[:self.vehicle_count]):
            vid = f"V{i + 1:02d}"
            tram_id, tram = self._nearest_tram_stop(home)
            if not tram_id or self.TRANSFER_STATION.get(tram_id) is None:
                self.warnings.append(f"{vid}: 트램역 연결 ID missing; 차량 생략")
                continue
            origin = [float(home["latitude"]), float(home["longitude"])]
            dest = [float(tram["latitude"]), float(tram["longitude"])]
            outward = calculate_road_route([origin, dest])
            inward = calculate_road_route([dest, origin])
            if not outward or not inward or not outward.get("coordinates") or not inward.get("coordinates"):
                self.warnings.append(f"{vid}: OSRM 경로/캐시 missing ({home_id}→{tram_id}); 해당 차량 생략")
                continue
            events = self._station_events(tram_id)
            if self.service_window:
                start_t, end_t = self.service_window
                lower = datetime.combine(self.day, start_t)
                upper = datetime.combine(self.day, end_t)
                events = [event for event in events if lower <= event <= upper]
            if not events:
                self.warnings.append(f"{vid}: {tram_id}에 연결할 트램 출발시각이 missing; 차량 생략")
                continue
            selected = events[i::max(self.vehicle_count, 1)]
            if not selected:
                selected = events[i::len(homes)] if len(homes) else []
            for target in selected:
                plan_probe = target - timedelta(minutes=buffer + float(outward["duration_min"]))
                plan_factor, band, _ = self._factor(plan_probe)
                # Schedule against the hourly median; apply selected min/mode/max
                # only to actual travel, preserving a reproducible comparison.
                profile = self.config.get("traffic_factor_by_band", {}).get(self.route_class, {})
                mode_values = profile if self.route_class == "단지내" else self.hourly_congestion.get(plan_probe.hour, {})
                plan_factor = float(mode_values.get("mode", plan_factor)) if isinstance(mode_values, dict) else plan_factor
                plan_start = target - timedelta(minutes=buffer + float(outward["duration_min"]) * plan_factor)
                actual_factor, band, factor_status = self._factor(plan_start)
                if plan_start < ready[vid]:
                    continue
                actual_arrival = plan_start + timedelta(minutes=float(outward["duration_min"]) * actual_factor)
                missed = actual_arrival > target
                next_train = None
                if missed:
                    later = [e for e in events if e > actual_arrival]
                    next_train = later[0] if later else None
                stop_depart = (next_train or target) + timedelta(minutes=dwell)
                if stop_depart < actual_arrival:
                    stop_depart = actual_arrival + timedelta(minutes=dwell)
                return_factor, _, _ = self._factor(stop_depart)
                return_arrival = stop_depart + timedelta(minutes=float(inward["duration_min"]) * return_factor)
                fleet[vid].append({"home_id": home_id, "home": origin, "tram_stop_id": tram_id,
                                   "tram_stop": dest, "planned_start": plan_start, "planned_arrival": target - timedelta(minutes=buffer),
                                   "target_tram": target, "arrival": actual_arrival, "stop_depart": stop_depart,
                                   "return_arrival": return_arrival, "out_route": outward["coordinates"],
                                   "back_route": inward["coordinates"], "out_base_min": float(outward["duration_min"]),
                                   "back_base_min": float(inward["duration_min"]), "factor": actual_factor,
                                   "out_speed_kmh": float(outward["distance_km"]) / max(float(outward["duration_min"]) * actual_factor / 60, 1e-9),
                                   "back_speed_kmh": float(inward["distance_km"]) / max(float(inward["duration_min"]) * return_factor / 60, 1e-9),
                                   "factor_band": band, "factor_status": factor_status,
                                   "missed": missed, "next_train": next_train,
                                   "delay_min": max(0.0, (actual_arrival - (target - timedelta(minutes=buffer))).total_seconds() / 60),
                                   "load": None, "dwell_minutes": dwell, "transfer_buffer": buffer})
                ready[vid] = return_arrival
        return fleet

    def _drt_position(self, vid, trips, t):
        home_id = next((x["home_id"] for x in trips), None)
        home = next((x["home"] for x in trips), None)
        if home is None:
            chosen = list(self.drt_stop_ids.items())
            if not chosen:
                return None
            home_id, row = chosen[0]
            home = [float(row["latitude"]), float(row["longitude"])]
        trip = next((x for x in trips if x["planned_start"] <= t <= x["return_arrival"]), None)
        base = {"vehicle_id": vid, "timestamp": t.isoformat(timespec="seconds"), "speed_kmh": None,
                "load": None, "load_status": "missing", "reservation_source": "missing",
                "connected_tram_time": None, "transfer_buffer_min": None,
                "missed_transfer": False, "next_tram_minutes": None, "delay_min": None,
                "_past_coordinates": [], "_future_coordinates": []}
        if trip is None:
            next_trip = next((x for x in trips if x["planned_start"] > t), None)
            base.update({"lat": home[0], "lon": home[1], "status": "대기", "next_stop": home_id,
                         "eta": next_trip["planned_start"].isoformat(timespec="seconds") if next_trip else None})
            return base
        base["load"] = trip["load"]
        base["trip_id"] = f"{vid}-{trip['target_tram']:%Y%m%d-%H%M%S}"
        base["connected_tram_time"] = _time_label(trip["target_tram"])
        actual_slack = (trip["target_tram"] - trip["arrival"]).total_seconds() / 60
        base["transfer_buffer_min"] = actual_slack
        base["transfer_buffer_seconds"] = int(round(actual_slack * 60))
        base["planned_transfer_buffer_min"] = trip["transfer_buffer"]
        base["planned_transfer_buffer_seconds"] = int(round(trip["transfer_buffer"] * 60))
        base["trip_status"] = "assumption: simulated dispatch schedule"
        base["delay_min"] = round(trip["delay_min"], 1)
        base["missed_transfer"] = trip["missed"]
        if trip["next_train"]:
            base["next_tram_minutes"] = max(0, math.ceil((trip["next_train"] - t).total_seconds() / 60))
        if t < trip["arrival"]:
            span = max((trip["arrival"] - trip["planned_start"]).total_seconds(), 1)
            fraction = (t - trip["planned_start"]).total_seconds() / span
            past, future = _route_slice(trip["out_route"], fraction)
            point = _point_on_line(trip["out_route"], fraction)
            base.update({"lat": point[0], "lon": point[1], "status": "운행중", "next_stop": trip["tram_stop_id"],
                         "eta": trip["arrival"].isoformat(timespec="seconds"), "speed_kmh": round(trip["out_speed_kmh"], 1),
                         "_past_coordinates": past, "_future_coordinates": future,
                         "position_status": "assumption: OSRM duration adjusted by selected congestion factor"})
        elif t < trip["stop_depart"]:
            remaining = max(0, math.ceil((trip["next_train"] - t).total_seconds() / 60)) if trip["missed"] and trip["next_train"] else 0
            base.update({"lat": trip["tram_stop"][0], "lon": trip["tram_stop"][1], "status": "정차중",
                         "next_stop": trip["tram_stop_id"], "eta": trip["stop_depart"].isoformat(timespec="seconds"),
                         "_past_coordinates": list(trip["out_route"]), "_future_coordinates": list(trip["back_route"]),
                         "next_tram_minutes": remaining if trip["missed"] else None})
        else:
            span = max((trip["return_arrival"] - trip["stop_depart"]).total_seconds(), 1)
            fraction = (t - trip["stop_depart"]).total_seconds() / span
            past, future = _route_slice(trip["back_route"], fraction)
            point = _point_on_line(trip["back_route"], fraction)
            base.update({"lat": point[0], "lon": point[1], "status": "회차중", "next_stop": trip["home_id"],
                         "eta": trip["return_arrival"].isoformat(timespec="seconds"),
                         "_past_coordinates": past, "_future_coordinates": future,
                         "speed_kmh": round(trip["back_speed_kmh"], 1),
                         "position_status": "assumption: OSRM duration adjusted by selected congestion factor"})
        return base

    def _tram_position(self, trip, t):
        for leg in trip["legs"]:
            if leg["depart"] <= t < leg["arrive"]:
                span = max((leg["arrive"] - leg["depart"]).total_seconds(), 1)
                fraction = (t - leg["depart"]).total_seconds() / span
                past, future = _route_slice(leg["coordinates"], fraction)
                point = _point_on_line(leg["coordinates"], fraction)
                return {"vehicle_id": trip["vehicle_id"], "timestamp": t.isoformat(timespec="seconds"),
                        "lat": point[0], "lon": point[1],
                        "speed_kmh": round(leg["distance_m"] / 1000 / (leg["minutes"] / 60), 1), "status": "운행중",
                        "load": None, "next_stop": self.stations[leg["to"]]["name"],
                        "eta": leg["arrive"].isoformat(timespec="seconds"), "delay_min": 0,
                        "connected_tram_time": None, "transfer_buffer_min": None,
                        "missed_transfer": False, "next_tram_minutes": None,
                        "position_status": f"{leg['status']}: timetable / distance",
                        "_past_coordinates": past, "_future_coordinates": future}
        return None

    def get_positions(self, t):
        if isinstance(t, str):
            t = datetime.fromisoformat(t)
        if isinstance(t, time):
            t = datetime.combine(self.day, t)
        if not isinstance(t, datetime):
            raise TypeError("t must be datetime, time, or ISO string")
        positions = []
        for vid, trips in self.drt_trips.items():
            if not trips:
                continue
            position = self._drt_position(vid, trips, t)
            if position:
                positions.append(position)
        for trip in self.tram_trips:
            if trip["start"] <= t <= trip["end"]:
                position = self._tram_position(trip, t)
                if position:
                    positions.append(position)
        # Stable, deterministic order; no random sampling is used.
        return positions

    def get_warnings(self):
        return list(dict.fromkeys(self.warnings))

    def get_warning_categories(self):
        """Return visible warnings grouped by the reason stated in each message."""
        groups = {"환승 놓침": [], "경로 문제": [], "자료 누락": [], "가정 적용": [], "기타": []}
        for message in self.get_warnings():
            if "환승 놓침" in message:
                category = "환승 놓침"
            elif "경로" in message or "OSRM" in message:
                category = "경로 문제"
            elif "missing" in message or "비어" in message:
                category = "자료 누락"
            elif "assumption" in message or "가정" in message or "기본값" in message:
                category = "가정 적용"
            else:
                category = "기타"
            groups[category].append(message)
        return {name: values for name, values in groups.items() if values}

    def get_track_features(self):
        return self.line_data.get("features", [])

    def get_station_features(self):
        return self.station_data.get("features", [])

    def get_routes_at(self, t):
        return [{"vehicle_id": p["vehicle_id"], "status": p["status"],
                 "past": p.get("_past_coordinates", []), "future": p.get("_future_coordinates", [])}
                for p in self.get_positions(t)]

    def get_autoplay_positions(self, start, end):
        """Precompute one-minute snapshots for TimestampedGeoJson playback."""
        snapshots = []
        cursor = start
        while cursor <= end:
            snapshots.append((cursor, self.get_positions(cursor)))
            cursor += timedelta(minutes=1)
        return snapshots

    @staticmethod
    def warm_demo_cache():
        """Load all four demo presets once; route_engine reads/writes OSRM cache."""
        presets = ["평일 출근 07~09시", "평일 퇴근 17~19시", "평일 낮 호출형", "주말"]
        results = {}
        for preset in presets:
            provider = SimulatedProvider(scenario=preset, traffic_level="mode")
            results[preset] = {"drt_routes": sum(len(v) for v in provider.drt_trips.values()),
                               "warnings": provider.get_warnings()}
        return results
