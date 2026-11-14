"""Directional OSRM cache. Missing routes are never approximated."""
import json
import math
import os
import threading
from datetime import datetime, timezone
import requests
from modules.settings import BASE_DIR

CACHE_FILE = BASE_DIR / 'data' / 'osrm_cache.json'
LOCK = threading.Lock()

def calculate_road_route(coordinates, allow_network=True):
    if len(coordinates) < 2:
        return None
    try:
        if not all(math.isfinite(float(x)) for p in coordinates for x in p):
            return None
        key = 'driving|' + ';'.join(f'{float(lon):.7f},{float(lat):.7f}' for lat, lon in coordinates)
    except (ValueError, TypeError):
        return None
    with LOCK:
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cache = {}
        if key in cache:
            return {**cache[key], 'cache_hit': True}
    if not allow_network:
        return None
    try:
        response = requests.get('https://router.project-osrm.org/route/v1/driving/' + key.split('|')[1],
            params={'overview': 'full', 'geometries': 'geojson', 'steps': 'false'}, timeout=8)
        response.raise_for_status()
        data = response.json()
        if data.get('code') != 'Ok' or not data.get('routes'):
            return None
        route = data['routes'][0]
        result = {'coordinates': [[lat, lon] for lon, lat in route['geometry']['coordinates']],
            'distance_km': route['distance']/1000, 'duration_min': route['duration']/60,
            'source': 'OSRM driving model; not observed', 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        if not (math.isfinite(result['duration_min']) and result['duration_min'] > 0 and result['distance_km'] >= 0):
            return None
        with LOCK:
            try:
                cache = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                cache = {}
            cache[key] = result
            temp = CACHE_FILE.with_suffix('.tmp')
            temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, CACHE_FILE)
        return {**result, 'cache_hit': False}
    except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
        return None
