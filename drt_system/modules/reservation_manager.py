from modules.settings import vehicle_count
from modules.settings import stops_path, setting

from pathlib import Path
from datetime import datetime
from uuid import uuid4
from datetime import timedelta
from modules.route_engine import calculate_road_route

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
RESERVATION_FILE = BASE_DIR / "data" / "reservations.csv"

VEHICLE_COUNT = setting("vehicle_count")
VEHICLE_CAPACITY = setting("vehicle_capacity")

COLUMNS = [
    "reservation_id",
    "created_at",
    "vehicle_id",
    "boarding_stop",
    "tram_stop",
    "tram_departure",
    "passengers",
    "status"
]


def load_reservations():
    if not RESERVATION_FILE.exists():
        return pd.DataFrame(columns=COLUMNS)

    return pd.read_csv(
        RESERVATION_FILE,
        dtype={
            "reservation_id": str,
            "vehicle_id": str,
            "boarding_stop": str,
            "tram_stop": str,
            "tram_departure": str
        },
        encoding="utf-8-sig"
    )


def get_vehicle_status(tram_stop, tram_departure):
    reservations = load_reservations()

    vehicles = []

    for i in range(1, vehicle_count() + 1):
        vehicle_id = f"V{i:02d}"

        assigned = reservations[
            (reservations["vehicle_id"] == vehicle_id)
            & (reservations["tram_stop"] == tram_stop)
            & (reservations["tram_departure"] == tram_departure)
            & (reservations["status"] == "예약완료")
        ]

        occupied = int(
            pd.to_numeric(
                assigned["passengers"],
                errors="coerce"
            ).fillna(0).sum()
        )

        vehicles.append({
            "차량 ID": vehicle_id,
            "정원": VEHICLE_CAPACITY,
            "예약 인원": occupied,
            "잔여 좌석": VEHICLE_CAPACITY - occupied
        })

    return pd.DataFrame(vehicles)



def create_reservation(
    boarding_stop,
    tram_stop,
    tram_departure,
    passengers
):
    """
    합승 우선 차량 자동 배정 알고리즘

    1. 동일 트램 출발편의 기존 차량 우선
    2. 잔여 좌석이 충분한 차량 선택
    3. 기존 차량이 없으면 미배정 차량 선택
    4. 예약 결과 CSV 저장
    """

    reservations = load_reservations()

    passengers = int(passengers)

    if passengers < 1 or passengers > VEHICLE_CAPACITY:
        return None, "탑승 인원이 차량 정원을 초과했습니다."

    # 동일 트램 정거장 + 출발시간의 기존 예약
    same_trip = reservations[
        (reservations["tram_stop"] == tram_stop)
        & (reservations["tram_departure"] == tram_departure)
        & (reservations["status"] == "예약완료")
    ].copy()

    # 차량별 좌석 현황
    vehicle_status = get_vehicle_status(
        tram_stop,
        tram_departure
    )

    # 동일 출발편에 이미 배정된 차량
    used_vehicle_ids = set(
        same_trip["vehicle_id"].dropna().tolist()
    )

    # 1순위: 기존 합승 차량 중 잔여 좌석 충분한 차량
    existing_vehicles = vehicle_status[
        (vehicle_status["차량 ID"].isin(used_vehicle_ids))
        & (vehicle_status["잔여 좌석"] >= passengers)
    ].copy()

    if not existing_vehicles.empty:

        # 기존 차량 중 잔여 좌석이 가장 적으면서
        # 신규 승객까지 수용 가능한 차량 선택
        selected = existing_vehicles.sort_values(
            ["잔여 좌석", "차량 ID"],
            ascending=[True, True]
        ).iloc[0]

        assignment_type = "기존 차량 합승"

    else:

        # 2순위: 해당 출발편에 아직 사용하지 않은 차량
        unused_vehicles = vehicle_status[
            (~vehicle_status["차량 ID"].isin(used_vehicle_ids))
            & (vehicle_status["잔여 좌석"] >= passengers)
        ].copy()

        if unused_vehicles.empty:
            return None, "예약 가능한 차량이 없습니다."

        selected = unused_vehicles.sort_values(
            "차량 ID"
        ).iloc[0]

        assignment_type = "신규 차량 배정"

    vehicle_id = selected["차량 ID"]

    new_reservation = {
        "reservation_id": uuid4().hex[:10].upper(),
        "created_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "vehicle_id": vehicle_id,
        "boarding_stop": boarding_stop,
        "tram_stop": tram_stop,
        "tram_departure": tram_departure,
        "passengers": passengers,
        "status": "예약완료"
    }

    # 기존 예약 데이터에 신규 예약 추가
    reservations = pd.concat(
        [
            reservations,
            pd.DataFrame([new_reservation])
        ],
        ignore_index=True
    )

    RESERVATION_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    reservations.to_csv(
        RESERVATION_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    message = (
        f"예약 완료! {vehicle_id} 차량에 배정되었습니다. "
        f"배정 방식: {assignment_type}"
    )

    return new_reservation, message



def cancel_reservation(reservation_id):
    reservations = load_reservations()

    mask = (
        (reservations["reservation_id"] == reservation_id)
        & (reservations["status"] == "예약완료")
    )

    if not mask.any():
        return False

    reservations.loc[mask, "status"] = "예약취소"

    reservations.to_csv(
        RESERVATION_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    return True

def calculate_reservation_pickup(
    boarding_stop,
    tram_stop,
    tram_departure,
    transfer_buffer=setting("transfer_buffer"),
    traffic_factor=setting("traffic_factor"),
    boarding_minutes=setting("dwell_minutes")
):
    """
    예약 승객의 예상 DRT 탑승시간 계산
    """

    from datetime import datetime, timedelta
    from modules.route_engine import calculate_road_route

    stops_file = stops_path()

    stops = pd.read_csv(
        stops_file,
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    stop_lookup = stops.set_index("stop_id")

    coordinates = []

    for stop_id in [boarding_stop, tram_stop]:

        if stop_id not in stop_lookup.index:
            raise ValueError(
                f"정류장을 찾을 수 없습니다: {stop_id}"
            )

        row = stop_lookup.loc[stop_id]

        if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
            raise ValueError(
                f"정류장 좌표가 없습니다: {stop_id}"
            )

        coordinates.append([
            float(row["latitude"]),
            float(row["longitude"])
        ])

    road_route = calculate_road_route(coordinates)

    if road_route is None:
        raise ValueError("도로 경로 계산에 실패했습니다.")

    driving_minutes = (
        road_route["duration_min"] * traffic_factor
    )

    tram_time = datetime.strptime(
        tram_departure, "%H:%M"
    )

    drt_arrival = tram_time - timedelta(
        minutes=transfer_buffer
    )

    pickup_time = drt_arrival - timedelta(
        minutes=driving_minutes + boarding_minutes
    )

    return {
        "pickup_time": pickup_time.strftime("%H:%M"),
        "drt_arrival": drt_arrival.strftime("%H:%M"),
        "tram_departure": tram_departure,
        "distance_km": road_route["distance_km"],
        "driving_minutes": round(driving_minutes, 1)
    }
