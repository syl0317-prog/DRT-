"""Independent research route registry. Original stops/reservations are read-only.

SQLite is the canonical transactional store; JSON/CSV are explicit snapshot exports.
No route optimization, safety approval, or physical fleet availability is inferred.
"""
from contextlib import contextmanager, closing
import copy
import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

import requests
from pyproj import Geod, Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from modules.settings import PROJECT_DIR, stops_path
from modules.route_engine import calculate_road_route

DATA_DIR = PROJECT_DIR / "data/derived/drt_routes"
DATABASE = DATA_DIR / "routes.sqlite3"
GEOD = Geod(ellps="WGS84")


class RouteError(ValueError):
    pass


class RevisionConflict(RouteError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def read_original_stops():
    with stops_path().open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def empty_state():
    return dict(routes=[], stops=[], segments=[], bookings=[])


def identifier(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,31}", value):
        raise RouteError("ID는 영문자로 시작하는 2~32자 영문·숫자·밑줄·하이픈이어야 합니다.")
    return value


@lru_cache(maxsize=2)
def road_context(path, modified, size):
    raw = Path(path).read_bytes()
    collection = json.loads(raw.decode("utf-8-sig"))
    lines = [shape(f["geometry"]) for f in collection["features"]]
    if not lines or any(g.is_empty or not g.is_valid for g in lines):
        raise RouteError("도로망 형상으로 분석 범위를 확인할 수 없습니다.")
    bounds = (min(g.bounds[0] for g in lines), min(g.bounds[1] for g in lines),
              max(g.bounds[2] for g in lines), max(g.bounds[3] for g in lines))
    project = Transformer.from_crs(4326, 32652, always_xy=True).transform
    projected = [transform(project, g) for g in lines]
    return bounds, project, STRtree(projected), projected, hashlib.sha256(raw).hexdigest()


def inspect_location(lat, lon, existing, roads_file=None, exclude_id=None):
    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        raise RouteError("위도와 경도를 숫자로 입력하세요.") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise RouteError("유효한 위도·경도 범위를 벗어났습니다.")
    path = Path(roads_file or PROJECT_DIR / "data/vworld/wirye_road_links.geojson")
    stat = path.stat()
    bounds, project, tree, lines, digest = road_context(str(path), stat.st_mtime_ns, stat.st_size)
    if not bounds[0] <= lon <= bounds[2] or not bounds[1] <= lat <= bounds[3]:
        raise RouteError("현재 V-World 분석 데이터 범위 밖입니다. 이 범위는 위례 행정경계가 아닙니다.")
    for stop in existing:
        if stop["stop_id"] == exclude_id:
            continue
        distance = GEOD.inv(lon, lat, float(stop["longitude"]), float(stop["latitude"]))[2]
        if distance < 1:
            raise RouteError(f"기존/신규 정류장 {stop['stop_id']}와 1m 미만으로 중복됩니다.")
    point = Point(*project(lon, lat))
    nearest = int(tree.nearest(point))
    return dict(latitude=lat, longitude=lon, nearest_road_m=point.distance(lines[nearest]),
                area_check="V-World data envelope; not administrative boundary", roads_sha256=digest,
                coordinate_assumption="source coordinates treated as WGS84; distance EPSG:32652",
                checked_at=now())


def readonly_osrm(coordinates, allow_network=False):
    """Reuse original directional cache, optionally fetch full geometry without writes."""
    cached = calculate_road_route(coordinates, allow_network=False)
    if cached:
        return cached
    if not allow_network:
        return None
    coords = ";".join(f"{lon:.7f},{lat:.7f}" for lat, lon in coordinates)
    try:
        response = requests.get("https://router.project-osrm.org/route/v1/driving/"+coords,
                                params={"overview": "full", "geometries": "geojson", "steps": "false"}, timeout=8)
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        route = data["routes"][0]
        return dict(distance_km=route["distance"]/1000, duration_min=route["duration"]/60,
                    coordinates=[[lat, lon] for lon, lat in route["geometry"]["coordinates"]],
                    source="OSRM online driving model; not observed", retrieved_at=now())
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None


class RouteStore:
    def __init__(self, database=None, original_loader=None, roads_file=None):
        self.path = Path(database or DATABASE)
        self.original_loader = original_loader or read_original_stops
        self.roads_file = roads_file

    def snapshot(self):
        if not self.path.exists():
            return dict(empty_state(), revision=0)
        with closing(sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)) as connection:
            if not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='registry'").fetchone():
                return dict(empty_state(), revision=0)
            row = connection.execute("SELECT revision,payload FROM registry WHERE singleton=1").fetchone()
        if row is None:
            return dict(empty_state(), revision=0)
        return dict(json.loads(row[1]), revision=row[0])

    @contextmanager
    def edit(self, expected_revision):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS registry(singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO registry VALUES(1,0,?)", (json.dumps(empty_state()),))
            revision, payload = connection.execute("SELECT revision,payload FROM registry WHERE singleton=1").fetchone()
            if revision != expected_revision:
                raise RevisionConflict("다른 사용자가 데이터를 변경했습니다. 화면을 새로 불러온 뒤 다시 시도하세요.")
            state = json.loads(payload)
            yield state
            connection.execute("UPDATE registry SET revision=?,payload=? WHERE singleton=1",
                               (revision+1, json.dumps(state, ensure_ascii=False, allow_nan=False)))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def route(state, route_id):
        try:
            return next(r for r in state["routes"] if r["route_id"] == route_id)
        except StopIteration:
            raise RouteError("등록된 노선이 없습니다.") from None

    def editable(self, state, route_id):
        if any(b["route_id"] == route_id and b["status"] == "reserved" for b in state["bookings"]):
            raise RouteError("유효 예약이 있어 노선 구조를 변경할 수 없습니다. 먼저 신규 노선 예약을 취소하세요.")
        from modules.unified_reservations import route_has_unified_bookings
        if route_has_unified_bookings(route_id,self.path):
            raise RouteError("유효한 통합 예약이 있어 노선을 변경할 수 없습니다. 먼저 통합 예약을 취소하세요.")

    @staticmethod
    def invalidate(state, route):
        route.update(active=False, calculation_status="not_calculated", distance_km=None,
                     duration_min=None, updated_at=now(), error=None)
        state["segments"] = [s for s in state["segments"] if s["route_id"] != route["route_id"]]

    def suggested_stop_ids(self):
        state = self.snapshot()
        used = {s["stop_id"].upper() for s in self.original_loader()+state["stops"]}
        result, number = [], 5
        while len(result) < 4:
            candidate = f"V{number:02d}"
            if candidate not in used:
                result.append(candidate)
            number += 1
        return result

    def create_route(self, route_id, name, expected_revision):
        route_id = identifier(route_id)
        if route_id == "R01":
            raise RouteError("R01은 기존 CSV 노선 식별자이므로 독립 노선으로 생성할 수 없습니다.")
        if not str(name).strip():
            raise RouteError("노선명을 입력하세요.")
        with self.edit(expected_revision) as state:
            if any(r["route_id"] == route_id for r in state["routes"]):
                raise RouteError("중복된 노선 ID입니다.")
            if state["routes"]:
                raise RouteError("이번 단계는 신규 독립 노선 1개만 관리합니다.")
            state["routes"].append(dict(route_id=route_id, name=str(name).strip(), mode="independent",
                route_type="research_virtual_drt", research_only=True, active=False, stop_order=[],
                transfer_stop_id=None, vehicles=[], start_stop=None, end_stop=None,
                calculation_status="not_calculated", distance_km=None, duration_min=None,
                created_at=now(), updated_at=now(), error=None))

    def put_stop(self, route_id, stop_id, name, latitude, longitude, position, registration_status,
                 expected_revision, replace_id=None):
        stop_id = identifier(stop_id)
        if not str(name).strip() or registration_status not in ("research_candidate", "reviewed"):
            raise RouteError("정류장명과 유효한 등록 상태가 필요합니다.")
        if type(position) is not int or position not in (1, 2, 3, 4):
            raise RouteError("방문 순서는 1~4 정수여야 합니다.")
        with self.edit(expected_revision) as state:
            route = self.route(state, route_id)
            self.editable(state, route_id)
            original = self.original_loader()
            if any(s["stop_id"].upper() == stop_id for s in original):
                raise RouteError("기존 정류장 ID와 중복됩니다.")
            others = [s for s in state["stops"] if s["stop_id"] != replace_id]
            if replace_id is not None and (replace_id != stop_id or not any(s["stop_id"] == replace_id and s["route_id"] == route_id for s in state["stops"])):
                raise RouteError("수정 대상 정류장을 확인하세요. ID 변경은 지원하지 않습니다.")
            if any(s["stop_id"] == stop_id for s in others):
                raise RouteError("신규 정류장 ID가 중복됩니다. 제안 ID를 사용하세요.")
            if sum(s["route_id"] == route_id for s in others) >= 4:
                raise RouteError("가상정류장은 정확히 4개까지만 등록할 수 있습니다.")
            if any(s["route_id"] == route_id and s["position"] == position for s in others):
                raise RouteError("방문 순서가 중복됩니다. 별도 방문 순서 설정을 사용하세요.")
            check = inspect_location(latitude, longitude, original+others, self.roads_file)
            stop = dict(stop_id=stop_id, name=str(name).strip(), route_id=route_id, position=position,
                        stop_type="virtual", registration_status=registration_status, **check)
            state["stops"] = others+[stop]
            ordered = sorted([s for s in state["stops"] if s["route_id"] == route_id], key=lambda s:s["position"])
            route["stop_order"] = [s["stop_id"] for s in ordered]
            route["start_stop"] = ordered[0]["stop_id"]
            route["end_stop"] = route["transfer_stop_id"] or ordered[-1]["stop_id"]
            self.invalidate(state, route)

    def configure(self, route_id, stop_order, transfer_stop_id, vehicles, expected_revision):
        if route_id == 'R02' and transfer_stop_id not in (None, 'T02'):
            raise RouteError('R02의 고정 목적지는 T02 위례역사공원역입니다.')
        with self.edit(expected_revision) as state:
            route = self.route(state, route_id)
            self.editable(state, route_id)
            ids = {s["stop_id"] for s in state["stops"] if s["route_id"] == route_id}
            if len(ids) != 4 or len(stop_order) != 4 or set(stop_order) != ids:
                raise RouteError("중복 없이 정확히 4개 정류장의 순서를 지정하세요.")
            trams = {s["stop_id"] for s in self.original_loader() if s["stop_type"] == "tram"}
            if transfer_stop_id is not None and transfer_stop_id not in trams:
                raise RouteError("기존 트램 환승 거점만 연결할 수 있습니다.")
            vehicle_ids = []
            for vehicle in vehicles:
                vehicle_id = identifier(vehicle["vehicle_id"])
                capacity = vehicle["capacity"]
                if not vehicle_id.startswith(route_id+"-") or type(capacity) is not int or not 1 <= capacity <= 100:
                    raise RouteError("신규 차량 ID는 노선ID- 접두사를 사용하고 정원은 1~100 정수여야 합니다.")
                if vehicle_id in vehicle_ids:
                    raise RouteError("차량 ID가 중복됩니다.")
                vehicle_ids.append(vehicle_id)
                vehicle["vehicle_id"] = vehicle_id
            if not vehicles:
                raise RouteError("별도 연구용 차량을 하나 이상 지정하세요.")
            for stop in state["stops"]:
                if stop["stop_id"] in ids:
                    stop["position"] = stop_order.index(stop["stop_id"])+1
            route.update(stop_order=list(stop_order), transfer_stop_id=transfer_stop_id,
                         vehicles=copy.deepcopy(vehicles), start_stop=stop_order[0],
                         end_stop=transfer_stop_id or stop_order[-1])
            self.invalidate(state, route)

    def calculate(self, route_id, expected_revision, allow_network=False, router=None):
        state = self.snapshot()
        if state["revision"] != expected_revision:
            raise RevisionConflict("경로 계산 전 데이터가 변경되었습니다. 다시 불러오세요.")
        route = self.route(state, route_id)
        self.editable(state, route_id)
        own = {s["stop_id"]:s for s in state["stops"] if s["route_id"] == route_id}
        if len(own) != 4 or set(route["stop_order"]) != set(own):
            raise RouteError("경로 계산 전에 정류장 4개를 등록하세요.")
        points = {key:[s["latitude"],s["longitude"]] for key,s in own.items()}
        for s in self.original_loader():
            points[s["stop_id"]] = [float(s["latitude"]),float(s["longitude"])]
        order = route["stop_order"]+([route["transfer_stop_id"]] if route["transfer_stop_id"] else [])
        segments, error = [], None
        for i, (origin, destination) in enumerate(zip(order, order[1:]), 1):
            try:
                response = (router or readonly_osrm)([points[origin], points[destination]], allow_network=allow_network)
                if not response:
                    raise RouteError("OSRM 경로 없음 또는 연결 실패")
                distance, duration = float(response["distance_km"]), float(response["duration_min"])
                geometry = response["coordinates"]
                if not math.isfinite(distance) or distance <= 0 or not math.isfinite(duration) or duration <= 0 or len(geometry) < 2:
                    raise RouteError("OSRM 거리·시간·형상이 유효하지 않습니다.")
                if any(len(p)!=2 or not all(math.isfinite(float(v)) for v in p) or not -90<=p[0]<=90 or not -180<=p[1]<=180 for p in geometry):
                    raise RouteError("OSRM 경로 좌표가 유효하지 않습니다.")
                segments.append(dict(route_id=route_id, position=i, origin=origin, destination=destination,
                    distance_km=distance, duration_min=duration, coordinates=geometry,
                    source=response.get("source", "OSRM model; not observed"), retrieved_at=response.get("retrieved_at", "missing")))
            except (RouteError, ValueError, KeyError, TypeError, requests.RequestException) as failure:
                error = f"{origin} → {destination}: {failure}"
                break
        with self.edit(expected_revision) as current:
            current_route = self.route(current, route_id)
            self.editable(current, route_id)
            self.invalidate(current, current_route)
            if error:
                current_route.update(calculation_status="failed", error=error)
            else:
                current["segments"].extend(segments)
                current_route.update(calculation_status="calculated", distance_km=sum(s["distance_km"] for s in segments),
                                     duration_min=sum(s["duration_min"] for s in segments), calculated_at=now())
        return error is None

    def set_active(self, route_id, active, expected_revision):
        with self.edit(expected_revision) as state:
            route = self.route(state, route_id)
            if active and route_id == 'R02' and route.get('transfer_stop_id') != 'T02':
                raise RouteError('R02 활성화 전 T02 연결 및 전체 구간 경로 계산이 필요합니다.')
            stops = [s for s in state["stops"] if s["route_id"] == route_id]
            if active and (len(stops)!=4 or {s["position"] for s in stops}!={1,2,3,4} or
                           route["calculation_status"]!="calculated" or not route["vehicles"]):
                raise RouteError("정류장 4개·방문 순서·차량 설정·OSRM 경로 계산을 완료해야 활성화할 수 있습니다.")
            route.update(active=bool(active), updated_at=now())

    def reserve(self, route_id, boarding_stop, destination_stop, vehicle_id, departure, passengers, expected_revision, dwell_min=1):
        if not isinstance(departure, datetime) or departure.tzinfo is None:
            raise RouteError("시간대가 포함된 운행 날짜·출발시각이 필요합니다.")
        if type(passengers) is not int or passengers < 1:
            raise RouteError("승객 수는 양의 정수여야 합니다.")
        dwell_min = float(dwell_min)
        if not math.isfinite(dwell_min) or dwell_min < 0:
            raise RouteError("정차 가정은 0 이상의 유한한 분 값이어야 합니다.")
        with self.edit(expected_revision) as state:
            route = self.route(state, route_id)
            if not route["active"] or route["calculation_status"]!="calculated":
                raise RouteError("활성화되고 경로 계산이 완료된 연구용 노선만 예약할 수 있습니다.")
            order = route["stop_order"]+([route["transfer_stop_id"]] if route["transfer_stop_id"] else [])
            if boarding_stop not in route["stop_order"] or destination_stop not in order or order.index(boarding_stop)>=order.index(destination_stop):
                raise RouteError("선택한 노선의 진행 방향에 맞는 탑승·도착 정류장을 선택하세요.")
            vehicle = next((v for v in route["vehicles"] if v["vehicle_id"]==vehicle_id), None)
            if not vehicle:
                raise RouteError("이 신규 노선에 별도로 지정된 차량을 선택하세요.")
            departure = departure.astimezone(timezone.utc)
            key = departure.isoformat()
            from modules.unified_reservations import route_unified_bookings
            all_bookings=state["bookings"]+route_unified_bookings(route_id,self.path)
            run_minutes = route["duration_min"]+dwell_min*len([s for s in state["segments"] if s["route_id"]==route_id])
            run_end = departure+timedelta(minutes=run_minutes)
            for old in all_bookings:
                if old["status"]=="reserved" and old["vehicle_id"]==vehicle_id and old["departure"]==key and old["dwell_assumption_min"]!=dwell_min:
                    raise RouteError("동일 운행편의 정차 가정을 통일하세요.")
                if old["status"]!="reserved" or old["vehicle_id"]!=vehicle_id or old["departure"]==key:
                    continue
                old_start = datetime.fromisoformat(old["departure"])
                old_end = datetime.fromisoformat(old["run_end_at"])
                if departure < old_end and old_start < run_end:
                    raise RouteError("같은 신규 차량의 다른 운행편과 예정 시간이 겹칩니다.")
            occupied = sum(b["passengers"] for b in all_bookings if b["status"]=="reserved" and b["route_id"]==route_id and b["vehicle_id"]==vehicle_id and b["departure"]==key)
            if occupied+passengers > vehicle["capacity"]:
                raise RouteError("해당 운행편의 정원을 초과합니다. 좌석은 전 구간 보수적으로 예약합니다.")
            booking = dict(reservation_id="NEW-"+uuid4().hex[:12].upper(), route_id=route_id,
                boarding_stop=boarding_stop, destination_stop=destination_stop, vehicle_id=vehicle_id,
                departure=key, run_end_at=run_end.isoformat(), dwell_assumption_min=dwell_min,
                passengers=passengers, status="reserved", created_at=now(), research_only=True,
                route_snapshot=copy.deepcopy(route), segments_snapshot=copy.deepcopy([s for s in state["segments"] if s["route_id"]==route_id]))
            state["bookings"].append(booking)
            return copy.deepcopy(booking)

    def cancel(self, reservation_id, expected_revision):
        with self.edit(expected_revision) as state:
            booking = next((b for b in state["bookings"] if b["reservation_id"]==reservation_id and b["status"]=="reserved"), None)
            if booking is None:
                raise RouteError("취소 가능한 신규 노선 예약이 없습니다.")
            booking.update(status="cancelled", cancelled_at=now())

    def export(self):
        state = self.snapshot()
        out = self.path.parent / "exports" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"_"+uuid4().hex[:8])
        out.mkdir(parents=True, exist_ok=False)
        (out / "routes.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        for name, rows in (("virtual_stops.csv", state["stops"]), ("route_segments.csv", state["segments"]), ("reservations.csv", state["bookings"])):
            flattened = [{k:json.dumps(v, ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()} for row in rows]
            keys = list(dict.fromkeys(k for row in flattened for k in row)) or ["route_id"]
            with (out/name).open("x", encoding="utf-8-sig", newline="") as handle:
                writer=csv.DictWriter(handle, fieldnames=keys); writer.writeheader(); writer.writerows(flattened)
        return out


def booking_schedule(booking, dwell_min=1, transfer_buffer_min=5):
    """Independent planned run, not the original reservation dispatch algorithm."""
    if not all(math.isfinite(float(v)) and float(v)>=0 for v in (dwell_min, transfer_buffer_min)):
        raise RouteError("정차·환승 여유시간은 0 이상의 값이어야 합니다.")
    route = booking["route_snapshot"]
    current = datetime.fromisoformat(booking["departure"])
    rows = [dict(stop_id=route["stop_order"][0], arrival=current.isoformat())]
    for segment in booking["segments_snapshot"]:
        current += timedelta(minutes=float(dwell_min)+segment["duration_min"])
        rows.append(dict(stop_id=segment["destination"], arrival=current.isoformat()))
    boarding_at = next(row["arrival"] for row in rows if row["stop_id"]==booking["boarding_stop"])
    destination_arrival = next(row["arrival"] for row in rows if row["stop_id"]==booking["destination_stop"])
    return dict(rows=rows, arrival=current.isoformat(),
                boarding_at=boarding_at, destination_arrival=destination_arrival,
                ready_at=(datetime.fromisoformat(destination_arrival)+timedelta(minutes=float(transfer_buffer_min))).isoformat(),
                source="Independent planned run; saved OSRM segments + user dwell/buffer; not observed")
