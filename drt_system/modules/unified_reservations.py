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
    with closing(sqlite3.connect(path,timeout=5)) as connection:
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
    with closing(sqlite3.connect(path,timeout=5)) as connection:
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
                      longitude=float(row["longitude"]),source="legacy",route_id=None)
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
        return dict(boarding=boarding,trams=trams)

    def _csv_rows(self):
        if not self.legacy_path.exists():
            return []
        with self.legacy_path.open(encoding="utf-8-sig",newline="") as handle:
            return list(csv.DictReader(handle))

    def own_records(self):
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path,timeout=5)) as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM requests ORDER BY rowid")]

    def list_records(self):
        state=self.routes.snapshot(); cancelled=csv_cancellations(self.path); result=[]
        for row in self._csv_rows():
            public=csv_public_id(row,self.legacy_path)
            result.append(dict(public_id=public,raw_id=row["reservation_id"],source="legacy_csv",
                boarding_stop=row["boarding_stop"],destination_stop=row["tram_stop"],requested_at=None,
                time_basis="탑승 희망 날짜·시간은 기존 CSV에 미기록",
                tram_departure=row.get("tram_departure"),passengers=int(row["passengers"]),
                status="예약취소" if public in cancelled else row["status"],route_id="기존 경로 (노선 미지정)",
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
               evidence_provider=None,reference_now=None,tram_departure=None):
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
        initial_route,order=self._ordered_route(initial,origin,destination)
        route_ids={stops[k]["route_id"] for k in (origin,destination)}
        cap=max((v["capacity"] for v in initial_route["vehicles"]),default=int(setting("vehicle_capacity"))) if initial_route else int(setting("vehicle_capacity"))
        if passengers>cap:
            raise RouteError("탑승 인원이 해당 차량 정원을 초과합니다.")
        segments=[s for s in initial["segments"] if initial_route and s["route_id"]==initial_route["route_id"]]
        if initial_route and initial_route["calculation_status"]=="calculated" and len(segments)==len(order)-1:
            evidence=dict(status="verified_model",source="저장된 R02 OSRM 구간 · 실측 아님")
        else:
            evidence=(evidence_provider or path_evidence)([[stops[k]["latitude"],stops[k]["longitude"]] for k in (origin,destination)],allow_network=allow_network)
        if evidence["status"]=="no_route":
            raise RouteError(evidence.get("reason","이동 가능한 경로가 없습니다."))
        if self.routes.snapshot()["revision"]!=initial["revision"]:
            raise RouteError("경로 확인 중 등록부가 변경됐습니다. 다시 신청하세요.")
        request_time=requested_at.astimezone(timezone.utc).isoformat()
        tram_time=tram_departure.astimezone(timezone.utc).isoformat() if tram_departure else None
        fingerprint=digest([origin,destination,request_time,passengers,tram_time])
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
                route_id=route["route_id"] if route else ("기존 경로" if stops[origin]["source"]==stops[destination]["source"]=="legacy" else "노선 간 이동 / 개별 검토"),
                dispatch_status="현재 배차 엔진이 이 조합·날짜 기반 운행을 자동 배차하지 않음",
                simulation_adapter="excluded",research_only=True,path_evidence=evidence,created_at=now(),registry_path=str(self.routes.path.resolve()),
                stop_snapshot={k:copy.deepcopy(stops[k]) for k in (origin,destination)},registry_revision=initial["revision"])
            if evidence["status"]!="verified_model":
                record["dispatch_status"]="이동 경로 미확인; 온라인/현장 및 배차 검토 필요"
            elif route and route["active"] and route["calculation_status"]=="calculated" and route["vehicles"]:
                cancelled={row[0] for row in connection.execute("SELECT public_id FROM csv_cancellations")}
                uncertain_vehicles={row["vehicle_id"] for row in self._csv_rows() if row["status"]=="예약완료" and csv_public_id(row,self.legacy_path) not in cancelled}
                self._assign_r02(connection,state,record,route,order,requested_at,reference_now or datetime.now(timezone.utc),uncertain_vehicles)
                if record["status"]=="예약완료" and tram_departure:
                    booking=record["booking_snapshot"]
                    plan=booking_schedule(booking,booking["dwell_assumption_min"],float(setting("transfer_buffer")))
                    if datetime.fromisoformat(plan["ready_at"])>tram_departure:
                        record.update(status="배차 검토 필요",vehicle_id=None,simulation_adapter="excluded",
                            dispatch_status="입력 가상 트램 출발 전 환승 준비가 어려워 배차 검토 필요")
                        record.pop("booking_snapshot",None)
            elif route:
                record["dispatch_status"]="R02 비활성 또는 별도 차량 미지정; 배차 검토 필요"
            connection.execute("INSERT INTO requests VALUES(?,?,?,?)",(record["public_id"],str(request_key),fingerprint,json.dumps(record,ensure_ascii=False,allow_nan=False)))
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
