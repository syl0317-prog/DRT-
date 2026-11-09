
import math
from datetime import datetime, timedelta

import pandas as pd

from modules.route_engine import calculate_road_route


def calculate_pickup_schedule(
    route_stop_ids,
    tram_stop_id,
    tram_departure,
    transfer_buffer=5,
    dwell_minutes=1,
    traffic_factor=1.2
):
    """
    정류장별 DRT 픽업 예정시간 계산

    - 정류장 사이의 도로 이동시간을 각각 계산
    - 교통 혼잡 및 승하차 시간을 반영
    - 트램 출발시간에서 역산
    """

    stops = pd.read_csv(
        "data/drt_stops.csv",
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    stop_lookup = stops.set_index("stop_id")

    route_ids = route_stop_ids + [tram_stop_id]

    if len(route_stop_ids) == 0:
        raise ValueError("DRT 정류장을 선택해 주세요.")

    coordinates = []

    for stop_id in route_ids:

        if stop_id not in stop_lookup.index:
            raise ValueError(
                f"정류장이 존재하지 않습니다: {stop_id}"
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

    # 정류장 사이 도로 이동시간 계산
    segment_minutes = []

    for i in range(len(coordinates) - 1):

        segment = calculate_road_route(
            [coordinates[i], coordinates[i + 1]]
        )

        if segment is None:
            raise ValueError(
                f"{route_ids[i]} → {route_ids[i + 1]} "
                "도로 경로 계산 실패"
            )

        travel_minutes = (
            segment["duration_min"] * traffic_factor
        )

        segment_minutes.append(travel_minutes)

    # 첫 정류장 탑승부터 마지막 정류장 출발까지
    # DRT 정류장마다 정차시간 반영
    total_minutes = (
        sum(segment_minutes)
        + len(route_stop_ids) * dwell_minutes
    )

    # 트램 출발 전 환승 여유 확보
    tram_time = datetime.strptime(
        tram_departure, "%H:%M"
    )

    drt_arrival = tram_time - timedelta(
        minutes=transfer_buffer
    )

    drt_start = drt_arrival - timedelta(
        minutes=math.ceil(total_minutes)
    )

    # 정류장별 도착 및 탑승시간
    current_time = drt_start
    pickup_rows = []

    for i, stop_id in enumerate(route_stop_ids):

        stop_name = stop_lookup.loc[
            stop_id, "stop_name"
        ]

        pickup_rows.append({
            "정류장 ID": stop_id,
            "정류장명": stop_name,
            "탑승 예정시간": current_time.strftime("%H:%M")
        })

        # 승객 승하차 시간
        current_time += timedelta(
            minutes=dwell_minutes
        )

        # 다음 정류장까지 이동
        current_time += timedelta(
            minutes=segment_minutes[i]
        )

    pickup_rows.append({
        "정류장 ID": tram_stop_id,
        "정류장명": stop_lookup.loc[
            tram_stop_id, "stop_name"
        ],
        "탑승 예정시간": drt_arrival.strftime("%H:%M")
    })

    return {
        "drt_start": drt_start.strftime("%H:%M"),
        "drt_arrival": drt_arrival.strftime("%H:%M"),
        "tram_departure": tram_departure,
        "total_duration": math.ceil(total_minutes),
        "pickup_table": pd.DataFrame(pickup_rows)
    }
