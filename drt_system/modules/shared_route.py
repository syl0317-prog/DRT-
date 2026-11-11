from modules.settings import stops_path, setting

from pathlib import Path

import pandas as pd

from modules.reservation_manager import load_reservations
from modules.pickup_scheduler import calculate_pickup_schedule


BASE_DIR = Path(__file__).resolve().parent.parent
STOPS_FILE = stops_path()


def get_shared_route(
    vehicle_id,
    tram_stop,
    tram_departure,
    transfer_buffer=setting("transfer_buffer"),
    dwell_minutes=setting("dwell_minutes"),
    traffic_factor=setting("traffic_factor")
):
    """
    같은 차량, 트램 정거장, 출발시간의 예약을
    하나의 합승 노선으로 구성한다.

    현재 버전은 정류장 ID 순서로 방문한다.
    """

    reservations = load_reservations()

    assigned = reservations[
        (reservations["vehicle_id"] == vehicle_id)
        & (reservations["tram_stop"] == tram_stop)
        & (reservations["tram_departure"] == tram_departure)
        & (reservations["status"] == "예약완료")
    ].copy()

    if assigned.empty:
        raise ValueError("해당 차량의 예약 내역이 없습니다.")

    stops = pd.read_csv(
        stops_path(),
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    stop_names = dict(
        zip(stops["stop_id"], stops["stop_name"])
    )

    # 동일 정류장 예약을 하나로 묶기
    demand = (
        assigned.groupby("boarding_stop")["passengers"]
        .sum()
        .reset_index()
    )

    # 임시 방문 순서: 정류장 ID 기준
    route_stop_ids = sorted(
        demand["boarding_stop"].tolist()
    )

    # 기존 픽업 스케줄러 재사용
    schedule = calculate_pickup_schedule(
        route_stop_ids=route_stop_ids,
        tram_stop_id=tram_stop,
        tram_departure=tram_departure,
        transfer_buffer=transfer_buffer,
        dwell_minutes=dwell_minutes,
        traffic_factor=traffic_factor
    )

    pickup_table = schedule["pickup_table"].copy()

    demand_map = dict(
        zip(demand["boarding_stop"], demand["passengers"])
    )

    pickup_table["탑승 인원"] = pickup_table[
        "정류장 ID"
    ].map(demand_map).fillna(0).astype(int)

    pickup_table["정류장명"] = pickup_table[
        "정류장 ID"
    ].map(stop_names)

    return {
        "vehicle_id": vehicle_id,
        "tram_stop": tram_stop,
        "tram_departure": tram_departure,
        "reservation_count": len(assigned),
        "passenger_count": int(
            pd.to_numeric(
                assigned["passengers"],
                errors="coerce"
            ).fillna(0).sum()
        ),
        "route_stop_ids": route_stop_ids,
        "pickup_table": pickup_table,
        "drt_start": schedule["drt_start"],
        "drt_arrival": schedule["drt_arrival"],
        "total_duration": schedule["total_duration"]
    }
