
import math
from pathlib import Path

import pandas as pd

from modules.route_engine import calculate_road_route
from modules.tram_scheduler import calculate_drt_schedule


BASE_DIR = Path(__file__).resolve().parent.parent
STOPS_FILE = BASE_DIR / "data" / "drt_stops.csv"


def calculate_integrated_schedule(
    route_stop_ids,
    tram_stop_id,
    tram_departure,
    transfer_buffer=5,
    dwell_minutes=1,
    traffic_factor=1.2
):
    # 정류장 데이터 불러오기
    stops = pd.read_csv(
        STOPS_FILE,
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    stop_lookup = stops.set_index("stop_id")
    route_ids = route_stop_ids + [tram_stop_id]

    coordinates = []

    for stop_id in route_ids:
        if stop_id not in stop_lookup.index:
            raise ValueError(f"정류장이 없습니다: {stop_id}")

        stop = stop_lookup.loc[stop_id]

        if pd.isna(stop["latitude"]) or pd.isna(stop["longitude"]):
            raise ValueError(f"좌표가 없습니다: {stop_id}")

        coordinates.append([
            float(stop["latitude"]),
            float(stop["longitude"])
        ])

    # 실제 도로 경로 계산
    road_route = calculate_road_route(coordinates)

    if road_route is None:
        raise ValueError("도로 경로 계산에 실패했습니다.")

    driving_minutes = (
        road_route["duration_min"] * traffic_factor
    )

    stop_minutes = len(route_stop_ids) * dwell_minutes

    total_duration = math.ceil(
        driving_minutes + stop_minutes
    )

    schedule = calculate_drt_schedule(
        tram_departure=tram_departure,
        drt_duration=total_duration,
        transfer_buffer=transfer_buffer
    )

    return {
        "route_ids": route_ids,
        "distance_km": road_route["distance_km"],
        "base_duration": road_route["duration_min"],
        "driving_duration": driving_minutes,
        "stop_duration": stop_minutes,
        "total_duration": total_duration,
        "schedule": schedule
    }
