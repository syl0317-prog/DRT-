
import requests


def calculate_road_route(coordinates):
    """
    coordinates: [[latitude, longitude], ...]
    정류장 방문 순서대로 도로 경로 계산
    """

    if len(coordinates) < 2:
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
            return None

        route = data["routes"][0]

        # GeoJSON은 경도, 위도 순서
        road_coordinates = [
            [lat, lon]
            for lon, lat in route["geometry"]["coordinates"]
        ]

        return {
            "coordinates": road_coordinates,
            "distance_km": route["distance"] / 1000,
            "duration_min": route["duration"] / 60
        }

    except (requests.RequestException, ValueError, KeyError):
        return None
