"""Federated reservations: immutable CSV + existing R02 + new dated requests.

New writes live here. CSV cancellations are durable overlays, applied at the
legacy read boundary. Existing registry cancellations update its own payload.
"""
from contextlib import closing, contextmanager
import copy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from uuid import uuid4

import requests
from modules.settings import PROJECT_DIR, setting
from modules.independent_routes import RouteStore, RouteError, booking_schedule, now
from modules.route_engine import calculate_road_route

DATABASE = PROJECT_DIR / "data/derived/unified_reservations/reservations.sqlite3"
ACTIVE = {"예약완료", "배차 검토 필요"}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def csv_public_id(row, path):
    fields=["reservation_id","created_at","vehicle_id","boarding_stop","tram_stop","tram_departure","passengers"]
    values={k:str(row.get(k,"")) for k in fields}
    return "CSV:"+digest(str(Path(path).resolve()))[:8]+":"+values["reservation_id"]+":"+digest(values)[:10]


def csv_cancellations(database=None):
    path=Path(database or DATABASE)
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as connection:
        if not connection.execute("SELECT name FROM sqlite_master WHERE name='csv_cancellations'").fetchone():
            return set()
        return {row[0] for row in connection.execute("SELECT public_id FROM csv_cancellations")}


def apply_csv_cancellations(frame, path, database=None):
    """Legacy algorithms see released seats without overwriting the original CSV."""
    cancelled=csv_cancellations(database)
    if not cancelled or frame.empty:
        return frame
    frame=frame.copy()
    for index,row in frame.iterrows():
        if csv_public_id(row.to_dict(),path) in cancelled:
            frame.loc[index,"status"]="예약취소"
    return frame


def route_unified_bookings(route_id,registry_path):
    path=Path(DATABASE)
    if not path.exists():
        return []
    result=[]
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as connection:
        for (payload,) in connection.execute("SELECT payload FROM requests"):
            row=json.loads(payload)
            if row.get("registry_path")==str(Path(registry_path).resolve()) and row["route_id"]==route_id and row["status"]=="예약완료":
                result.append(row["booking_snapshot"])
    return result


def route_has_unified_bookings(route_id,registry_path):
    return bool(route_unified_bookings(route_id,registry_path))


def path_evidence(coordinates,allow_network=False):
    cached=calculate_road_route(coordinates,allow_network=False)
    if cached:
        return dict(status="verified_model",route=cached,source="OSRM 캐시 · 실측 아님")
    if not allow_network:
        return dict(status="unverified",reason="방향성 OSRM 캐시 없음; 온라인 조회 미허용")
    coords=";".join(f"{lon:.7f},{lat:.7f}" for lat,lon in coordinates)
    try:
        response=requests.get("https://router.project-osrm.org/route/v1/driving/"+coords,
            params={"overview":"full","geometries":"geojson","steps":"false"},timeout=8)
        response.raise_for_status(); data=response.json()
        if data.get("code")=="NoRoute":
            return dict(status="no_route",reason="OSRM이 이동 가능한 경로 없음으로 응답")
        if data.get("code")!="Ok" or not data.get("routes"):
            return dict(status="unverified",reason="OSRM 경로 응답 미확인")
        route=data["routes"][0]
        return dict(status="verified_model",source="OSRM 온라인 모형 · 실측 아님",route=dict(
            distance_km=route["distance"]/1000,duration_min=route["duration"]/60,
            coordinates=[[lat,lon] for lon,lat in route["geometry"]["coordinates"]],retrieved_at=now()))
    except (requests.RequestException,ValueError,KeyError,TypeError):
        return dict(status="unverified",reason="OSRM 연결/응답 실패; 경로 미확인")


class UnifiedReservations:
    def __init__(self,database=None,route_store=None,legacy_path=None):
        self.path=Path(database or DATABASE)
        self.routes=route_store or RouteStore()
        if legacy_path is None:
            from modules.reservation_manager import RESERVATION_FILE
            legacy_path=RESERVATION_FILE
        self.legacy_path=Path(legacy_path)

    def catalog(self,state=None):
        state=state or self.routes.snapshot()
        boarding,trams=[],[]
        for row in self.routes.original_loader():
            stop=dict(stop_id=row["stop_id"],name=row["stop_name"],latitude=float(row["latitude"]),
                      longitude=float(row["longitude"]),source="legacy",route_id='R01' if row['stop_type']=='drt' else None)
            (trams if row["stop_type"]=="tram" else boarding).append(stop)
        for row in sorted(state["stops"],key=lambda s:s["position"]):
            boarding.append(dict(stop_id=row["stop_id"],name=row["name"],latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),source="registry",route_id=row["route_id"]))
        ids=[s["stop_id"].upper() for s in boarding+trams]
        if len(ids)!=len(set(ids)):
            raise RouteError("기존/신규 정류장 ID가 중복됩니다. 예약 전에 등록부를 확인하세요.")
        for s in boarding+trams:
            if not math.isfinite(s["latitude"]) or not math.isfinite(s["longitude"]) or not -90<=s["latitude"]<=90 or not -180<=s["longitude"]<=180:
                raise RouteError("저장된 정류장 좌표가 유효하지 않습니다.")
        from modules.fixed_routes import resolve_stop
        originals=self.routes.original_loader()
        for stop in boarding:
            stop['route_id'],stop['destination_stop_id']=resolve_stop(originals,state,stop['stop_id'])
        return dict(boarding=boarding,trams=trams)

    def _csv_rows(self):
        if not self.legacy_path.exists():
            return []
        with self.legacy_path.open(encoding="utf-8-sig",newline="") as handle:
            return list(csv.DictReader(handle))

    def own_records(self):
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM requests ORDER BY rowid")]

    def operations(self):
        from modules.fixed_dispatch import read_rows
        if not self.path.exists():
            return dict(vehicles=[],runs=[])
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
            return dict(vehicles=read_rows(connection,'fixed_vehicles'),runs=read_rows(connection,'fixed_runs'))

    def list_records(self):
        state=self.routes.snapshot(); cancelled=csv_cancellations(self.path); result=[]
        for row in self._csv_rows():
            public=csv_public_id(row,self.legacy_path)
            result.append(dict(public_id=public,raw_id=row["reservation_id"],source="legacy_csv",
                boarding_stop=row["boarding_stop"],destination_stop=row["tram_stop"],requested_at=None,
                time_basis="탑승 희망 날짜·시간은 기존 CSV에 미기록",
                tram_departure=row.get("tram_departure"),passengers=int(row["passengers"]),
                status="예약취소" if public in cancelled else row["status"],route_id="R01",
                vehicle_id=row.get("vehicle_id"),dispatch_status="기존 차량 배정; 운행일자 미기록",
                simulation_adapter="legacy",research_only=True))
        prefix="R02:"+digest(str(self.routes.path.resolve()))[:8]+":"
        for row in state["bookings"]:
            schedule=booking_schedule(row,row.get("dwell_assumption_min",1))
            result.append(dict(public_id=prefix+row["reservation_id"],raw_id=row["reservation_id"],source="route_registry",
                boarding_stop=row["boarding_stop"],destination_stop=row["destination_stop"],requested_at=schedule["boarding_at"],
                time_basis="저장 운행편으로 산출한 예정 탑승시각 (희망시각 원문 없음)",tram_departure=None,
                passengers=row["passengers"],status="예약완료" if row["status"]=="reserved" else "예약취소",
                route_id=row["route_id"],vehicle_id=row["vehicle_id"],dispatch_status="독립 연구용 운행편 배정",
                simulation_adapter="r02",research_only=True,booking_snapshot=row))
        result.extend(self.own_records())
        return result

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        connection=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS requests(public_id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, signature TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS csv_cancellations(public_id TEXT PRIMARY KEY, cancelled_at TEXT NOT NULL)")
            attached=self.routes.path.exists()
            if attached:
                connection.execute("ATTACH DATABASE ? AS route_registry",(str(self.routes.path),))
            connection.execute("BEGIN IMMEDIATE")
            if attached:
                revision,payload=connection.execute("SELECT revision,payload FROM route_registry.registry WHERE singleton=1").fetchone()
                state=dict(json.loads(payload),revision=revision)
            else:
                state=self.routes.snapshot()
            yield connection,state,attached
            connection.commit()
        except BaseException:
            connection.rollback(); raise
        finally:
            connection.close()

    @staticmethod
    def _ordered_route(state,origin,destination):
        for route in state["routes"]:
            order=route["stop_order"]+([route["transfer_stop_id"]] if route["transfer_stop_id"] else [])
            if origin in order and destination in order and order.index(origin)<order.index(destination):
                return route,order
        return None,None

    def create(self,origin,destination,requested_at,passengers,request_key,allow_network=False,
               evidence_provider=None,reference_now=None,tram_departure=None,route_id=None,run_id=None):
        if origin==destination:
            raise RouteError("탑승 정류장과 하차 정류장은 서로 달라야 합니다.")
        if not isinstance(requested_at,datetime) or requested_at.tzinfo is None:
            raise RouteError("유효한 날짜·시간 및 시간대가 필요합니다.")
        if requested_at < (reference_now or datetime.now(timezone.utc)):
            raise RouteError("탑승 희망 날짜·시간이 현재보다 이전입니다.")
        if tram_departure is not None and (not isinstance(tram_departure,datetime) or tram_departure.tzinfo is None or tram_departure<=requested_at):
            raise RouteError("가상 트램 출발시각은 시간대가 있는 탑승 희망시각 이후여야 합니다.")
        if type(passengers) is not int or passengers<1:
            raise RouteError("탑승 인원은 양의 정수여야 합니다.")
        if not str(request_key).strip():
            raise RouteError("중복 저장 방지를 위한 요청 키가 필요합니다.")
        initial=self.routes.snapshot();catalog=self.catalog(initial)
        stops={s["stop_id"]:s for s in catalog["boarding"]+catalog["trams"]}
        if origin not in {s["stop_id"] for s in catalog["boarding"]} or destination not in stops:
            raise RouteError("현재 저장된 정류장을 선택하세요.")
        from modules.fixed_routes import resolve_stop
        fixed_route, fixed_destination = resolve_stop(self.routes.original_loader(), initial, origin)
        if destination != fixed_destination or route_id not in (None, fixed_route):
            raise RouteError(f"{origin}은 {fixed_route} 소속이며 목적지는 {fixed_destination}로 고정됩니다.")
        route_id = fixed_route
        from modules.sequential_routes import route_plans
        plan=next(p for p in route_plans(self.routes.original_loader(),initial) if p['route_id']==route_id)
        if passengers>100:
            raise RouteError('한 요청의 지원 인원은 최대 100명입니다. 실제 배정은 등록 차량 정원 내에서만 가능합니다.')
        evidence=dict(status='verified_model' if plan['road_complete'] else 'unverified',
            source='fixed sequential route; archived road model; stop access requires operator evidence',
            route_order=plan['order'],route_signature=plan['signature'])
        if self.routes.snapshot()["revision"]!=initial["revision"]:
            raise RouteError("경로 확인 중 등록부가 변경됐습니다. 다시 신청하세요.")
        request_time=requested_at.astimezone(timezone.utc).isoformat()
        tram_time=tram_departure.astimezone(timezone.utc).isoformat() if tram_departure else None
        fingerprint=digest([origin,destination,request_time,passengers,tram_time,route_id,run_id])
        with self.transaction() as (connection,state,attached):
            previous=connection.execute("SELECT signature,payload FROM requests WHERE request_key=?",(str(request_key),)).fetchone()
            if previous:
                if previous[0]!=fingerprint:
                    raise RouteError("요청 키가 다른 입력에 재사용되었습니다.")
                return json.loads(previous[1])
            if state["revision"]!=initial["revision"]:
                raise RouteError("경로 확인 후 등록부가 변경되었습니다. 다시 신청하세요.")
            # Recheck the locked registry, never assume that the earlier route is still active.
            route,order=self._ordered_route(state,origin,destination)
            record=dict(public_id="UNI:"+uuid4().hex.upper(),raw_id=None,source="unified_sqlite",
                boarding_stop=origin,destination_stop=destination,requested_at=request_time,time_basis="사용자 입력 희망 탑승시각",
                tram_departure=tram_time,passengers=passengers,status="배차 검토 필요",vehicle_id=None,
                route_id=route_id,
                dispatch_status="현재 배차 엔진이 이 조합·날짜 기반 운행을 자동 배차하지 않음",
                simulation_adapter="excluded",research_only=True,path_evidence=evidence,created_at=now(),registry_path=str(self.routes.path.resolve()),
                stop_snapshot={k:copy.deepcopy(stops[k]) for k in (origin,destination)},registry_revision=initial["revision"])
            from modules.fixed_dispatch import assign
            record['requested_run_id']=run_id
            if run_id:
                record['time_basis']='선택한 고정 운행편의 정류장별 예정 승차시각'
            assign(self,connection,state,record,run_id,reference_now)
            connection.execute("INSERT INTO requests VALUES(?,?,?,?)",(record["public_id"],str(request_key),fingerprint,json.dumps(record,ensure_ascii=False,allow_nan=False)))
            return record

    @staticmethod
    def complete_segments(segments, order):
        ordered = sorted(segments, key=lambda s:s['position'])
        return len(ordered) == len(order)-1 and all(
            s['origin'] == a and s['destination'] == b and len(s.get('coordinates', [])) >= 2
            and math.isfinite(float(s['duration_min'])) and float(s['duration_min']) > 0
            for s,a,b in zip(ordered, order, order[1:]))

    def retry_dispatch(self, public_id, run_id=None, accept_run_time=False):
        """Re-evaluate an existing dated request atomically; never duplicate it."""
        with self.transaction() as (connection, state, attached):
            row = connection.execute('SELECT payload FROM requests WHERE public_id=?', (public_id,)).fetchone()
            if row is None:
                raise RouteError('날짜 기반 SQLite 접수만 재배차할 수 있습니다.')
            record = json.loads(row[0])
            if record['status'] != '배차 검토 필요':
                raise RouteError('배차 검토 필요 상태의 접수만 재검토할 수 있습니다.')
            from modules.fixed_routes import resolve_stop
            rid, target = resolve_stop(self.routes.original_loader(), state, record['boarding_stop'])
            if rid != record['route_id'] or target != record['destination_stop']:
                raise RouteError('현재 노선 및 고정 목적지와 맞지 않는 과거 요청입니다.')
            if run_id is not None:
                from modules.fixed_dispatch import read_rows,boarding_at
                selected=next((r for r in read_rows(connection,'fixed_runs') if r['run_id']==run_id and r['route_id']==rid),None)
                if not selected:
                    raise RouteError('선택한 운행편이 없거나 예약 노선과 다릅니다.')
                record['requested_run_id']=run_id
                if accept_run_time:
                    record.setdefault('original_requested_at',record['requested_at'])
                    record['requested_at']=boarding_at(selected,record['boarding_stop']).isoformat()
                    record['time_basis']='운영자가 선택한 운행편 시각으로 변경; 원래 희망시각 별도 보존'
            from modules.fixed_dispatch import assign
            assign(self,connection,state,record,record.get('requested_run_id'))
            record['updated_at'] = now()
            connection.execute('UPDATE requests SET payload=? WHERE public_id=?',(json.dumps(record,ensure_ascii=False,allow_nan=False),public_id))
            return record

    @staticmethod
    def _assign_r02(connection,state,record,route,order,requested_at,reference_now,uncertain_vehicles):
        segments=sorted([s for s in state["segments"] if s["route_id"]==route["route_id"]],key=lambda s:s["position"])
        dwell=float(setting("dwell_minutes"))
        boarding_index=order.index(record["boarding_stop"])
        offset=sum(s["duration_min"]+dwell for s in segments[:boarding_index])
        departure=requested_at.astimezone(timezone.utc)-timedelta(minutes=offset)
        if departure<reference_now:
            record["dispatch_status"]="탑승 지점 역산 시 첫 정류장 출발이 이미 경과하여 배차 검토 필요"
            return
        run_end=departure+timedelta(minutes=sum(s["duration_min"]+dwell for s in segments))
        key=departure.isoformat()
        existing=[b for b in state["bookings"] if b["status"]=="reserved"]
        for (payload,) in connection.execute("SELECT payload FROM requests"):
            row=json.loads(payload)
            if row["status"]=="예약완료" and row.get("booking_snapshot"):
                existing.append(row["booking_snapshot"])
        for vehicle in route["vehicles"]:
            if vehicle["vehicle_id"] in uncertain_vehicles:
                continue  # Legacy dates are unknown; never assert this vehicle is free.
            occupied=0;conflict=False
            for old in existing:
                if old["vehicle_id"]!=vehicle["vehicle_id"]:
                    continue
                start=datetime.fromisoformat(old["departure"]);end=datetime.fromisoformat(old["run_end_at"])
                if start==departure:
                    if old["route_id"] != route["route_id"] or old["route_snapshot"]["stop_order"] != route["stop_order"]:
                        conflict=True
                    if old.get("dwell_assumption_min",1)!=dwell:
                        conflict=True
                    occupied+=old["passengers"]
                elif departure<end and start<run_end:
                    conflict=True
            if conflict or occupied+record["passengers"]>vehicle["capacity"]:
                continue
            booking=dict(reservation_id=record["public_id"],route_id=route["route_id"],boarding_stop=record["boarding_stop"],
                destination_stop=record["destination_stop"],vehicle_id=vehicle["vehicle_id"],departure=key,
                run_end_at=run_end.isoformat(),dwell_assumption_min=dwell,passengers=record["passengers"],status="reserved",
                route_snapshot=copy.deepcopy(route),segments_snapshot=copy.deepcopy(segments),created_at=now(),research_only=True)
            record.update(status="예약완료",vehicle_id=vehicle["vehicle_id"],dispatch_status="독립 연구용 운행편 배정; 실제 운행 확정 아님",
                          simulation_adapter="r02",booking_snapshot=booking)
            return
        record["dispatch_status"]="신규 차량 정원 또는 운행편 시간 충돌; 배차 검토 필요"

    def cancel(self,public_id):
        records={r["public_id"]:r for r in self.list_records()}
        if public_id not in records:
            raise RouteError("예약을 찾을 수 없습니다.")
        record=records[public_id]
        if record["status"] not in ACTIVE:
            return
        with self.transaction() as (connection,state,attached):
            if record["source"]=="unified_sqlite":
                row=connection.execute("SELECT payload FROM requests WHERE public_id=?",(public_id,)).fetchone()
                if not row:
                    raise RouteError("예약이 변경되었습니다.")
                updated=json.loads(row[0]);updated.update(status="예약취소",cancelled_at=now())
                if updated.get("booking_snapshot"):
                    updated["booking_snapshot"]["status"]="cancelled"
                connection.execute("UPDATE requests SET payload=? WHERE public_id=?",(json.dumps(updated,ensure_ascii=False),public_id))
            elif record["source"]=="legacy_csv":
                if not any(csv_public_id(row,self.legacy_path)==public_id for row in self._csv_rows()):
                    raise RouteError("기존 CSV 행이 변경되었습니다. 목록을 새로 확인하세요.")
                connection.execute("INSERT OR IGNORE INTO csv_cancellations VALUES(?,?)",(public_id,now()))
            else:
                booking=next((b for b in state["bookings"] if b["reservation_id"]==record["raw_id"]),None)
                if not booking or not attached:
                    raise RouteError("신규 원본 예약을 찾을 수 없습니다.")
                booking.update(status="cancelled",cancelled_at=now())
                payload={k:v for k,v in state.items() if k!="revision"}
                connection.execute("UPDATE route_registry.registry SET revision=revision+1,payload=? WHERE singleton=1",(json.dumps(payload,ensure_ascii=False,allow_nan=False),))
