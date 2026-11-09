
from datetime import datetime, timedelta


def calculate_drt_schedule(
    tram_departure,
    drt_duration,
    transfer_buffer=5
):
    """
    트램 출발시간 기준 DRT 역산 배차

    tram_departure: 트램 출발시간 (HH:MM)
    drt_duration: DRT 예상 운행시간 (분)
    transfer_buffer: 환승 여유시간 (분)
    """

    tram_time = datetime.strptime(
        tram_departure, "%H:%M"
    )

    drt_arrival = tram_time - timedelta(
        minutes=transfer_buffer
    )

    drt_start = drt_arrival - timedelta(
        minutes=drt_duration
    )

    return {
        "tram_departure": tram_time.strftime("%H:%M"),
        "drt_arrival": drt_arrival.strftime("%H:%M"),
        "drt_start": drt_start.strftime("%H:%M"),
        "transfer_buffer": transfer_buffer
    }
