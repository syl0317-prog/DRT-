
import json
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OSRM_CACHE = BASE_DIR / "data" / "osrm_cache.json"
_FAILED_ROUTES = set()


def _cache_key(coordinates):
    return ";".join(f"{float(lat):.6f},{float(lon):.6f}" for lat, lon in coordinates)


def _load_cache():
    try:
        return json.loads(OSRM_CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    OSRM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OSRM_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def calculate_road_route(coordinates):
    """
    coordinates: [[latitude, longitude], ...]
    정류장 방문 순서대로 도로 경로 계산
    """

    if len(coordinates) < 2:
        return None

    key = _cache_key(coordinates)
    cached = _load_cache().get(key)
    if cached and cached.get("coordinates") and cached.get("duration_min") is not None:
        result = dict(cached)
        result["source"] = "osrm_cache"
        return result
    if key in _FAILED_ROUTES:
        return None

    # OSRM은 경도, 위도 순서로 요청
    coordinate_string = ";".join(
        f"{lon},{lat}" for lat, lon in coordinates
    )

    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{coordinate_string}"
    )

    try:
        response = requests.get(
            url,
            params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "false"
            },
            timeout=15
        )
        response.raise_for_status()

        data = response.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            _FAILED_ROUTES.add(key)
            return None

        route = data["routes"][0]

        # GeoJSON은 경도, 위도 순서
        road_coordinates = [
            [lat, lon]
            for lon, lat in route["geometry"]["coordinates"]
        ]

        result = {
            "coordinates": road_coordinates,
            "distance_km": route["distance"] / 1000,
            "duration_min": route["duration"] / 60,
            "source": "osrm_live"
        }
        cache = _load_cache()
        cache[key] = result
        _save_cache(cache)
        return result

    except (requests.RequestException, ValueError, KeyError):
        _FAILED_ROUTES.add(key)
        return None
