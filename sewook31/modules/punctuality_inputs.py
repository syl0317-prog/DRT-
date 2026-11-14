"""Read-only stop and OSRM adapters for the independent research page."""
from datetime import datetime, timezone
import math

import pandas as pd
import requests
from modules.settings import stops_path
from modules.route_engine import calculate_road_route


def load_stops():
    stops = pd.read_csv(stops_path(), dtype={"stop_id": str}, encoding="utf-8-sig")
    required = {"stop_id", "stop_name", "latitude", "longitude", "stop_type"}
    if not required <= set(stops):
        raise ValueError("정류장 파일에 필요한 이름·좌표·유형 필드가 없습니다.")
    if stops.stop_id.isna().any() or stops.stop_id.duplicated().any():
        raise ValueError("정류장 ID가 비어 있거나 중복되어 있습니다.")
    return stops


def route_duration(coordinates, allow_network=False):
    """Reuse existing directional cache; optional live request never writes it."""
    try:
        if len(coordinates) < 2 or any(len(p) != 2 or not all(math.isfinite(float(x)) for x in p)
                or not -90 <= float(p[0]) <= 90 or not -180 <= float(p[1]) <= 180 for p in coordinates):
            raise ValueError("유효한 정류장 좌표가 필요합니다.")
        cached = calculate_road_route(coordinates, allow_network=False)
        if cached and math.isfinite(float(cached["duration_min"])) and float(cached["duration_min"]) > 0:
            return dict(duration_min=float(cached["duration_min"]), source="OSRM 캐시 · 실측 아님",
                        retrieved_at=cached.get("retrieved_at", "missing")), None
        if not allow_network:
            return None, "OSRM 캐시에 이 경로가 없습니다. 온라인 조회를 허용하거나 수동 입력 모드를 선택하세요."
        coords = ";".join(f"{float(lon):.7f},{float(lat):.7f}" for lat, lon in coordinates)
        response = requests.get("https://router.project-osrm.org/route/v1/driving/"+coords,
                                params={"overview": "false", "steps": "false"}, timeout=8)
        response.raise_for_status()
        data = response.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError("OSRM 응답에 경로가 없습니다.")
        duration = float(data["routes"][0]["duration"])/60
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("OSRM 이동시간이 유효하지 않습니다.")
        return dict(duration_min=duration, source="OSRM 온라인 모형 · 실측 아님",
                    retrieved_at=datetime.now(timezone.utc).isoformat()), None
    except (requests.RequestException, ValueError, TypeError, KeyError, OSError) as error:
        return None, f"OSRM 조회 실패: {error}. 수동 입력 모드를 선택하세요."


def resolve_duration(mode, manual_min, coordinates, allow_network=False):
    if mode == "manual":
        duration = float(manual_min)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("수동 이동시간은 유한한 양수여야 합니다.")
        return dict(duration_min=duration, source="사용자 직접 입력 · OSRM 계산값 아님", retrieved_at="해당 없음"), None
    if mode != "osrm":
        raise ValueError("지원하지 않는 이동시간 모드입니다.")
    return route_duration(coordinates, allow_network)
