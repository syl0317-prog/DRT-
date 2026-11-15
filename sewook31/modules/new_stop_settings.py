"""Atomic, versioned candidate coordinates; isolated from operational stores."""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from modules.settings import PROJECT_DIR

SETTINGS_FILE = PROJECT_DIR / 'data/derived/new_route_settings/locations.json'
STOP_IDS = ('R03-S01', 'R03-S02', 'R04-S01', 'R04-S02', 'R03-BOKJEONG', 'R04-BOKJEONG')
SOURCE = '사용자 지정 후보 좌표'



def _replace_with_retry(source, target, attempts=10):
    """Atomic replace; Windows/OneDrive can briefly lock the target while syncing."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))

def coordinates(latitude, longitude):
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise ValueError
        lat, lon = float(latitude), float(longitude)
        # This editor is scoped to Wirye, preventing swapped/remote clicks.
        if not (math.isfinite(lat) and math.isfinite(lon) and 37.40 <= lat <= 37.55 and 127.05 <= lon <= 127.22):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError('위례 주변 범위의 유효한 위도·경도가 필요합니다 (위도 37.40~37.55, 경도 127.05~127.22).') from None
    return lat, lon


def clicked_point(event):
    point = (event or {}).get('last_clicked')
    if not point:
        return None
    lat, lon = coordinates(point.get('lat'), point.get('lng'))
    return dict(latitude=lat, longitude=lon)


def empty():
    return dict(version=2, revision=0, stops={}, roads={})


def validate(data):
    if not isinstance(data, dict) or data.get('version') not in (1, 2) or type(data.get('revision')) is not int or data['revision'] < 0:
        raise ValueError('신규 정류장 설정 형식/버전을 확인하세요. 원본을 자동 초기화하지 않습니다.')
    if not isinstance(data.get('stops'), dict) or not isinstance(data.get('roads'), dict):
        raise ValueError('정류장 및 도로 설정 형식이 잘못되었습니다.')
    if set(data['stops']) - (set(STOP_IDS) | {'BOKJEONG'}) or set(data['roads']) - {'R03', 'R04'}:
        raise ValueError('설정에 지원하지 않는 정류장/노선 ID가 있습니다.')
    for row in data['stops'].values():
        if not isinstance(row, dict):
            raise ValueError('정류장 좌표 기록 형식이 잘못되었습니다.')
        coordinates(row.get('latitude'), row.get('longitude'))
        if row.get('source') != SOURCE or not row.get('updated_at'):
            raise ValueError('저장 좌표의 후보 출처 및 수정 시각이 필요합니다.')
    for road in data['roads'].values():
        from modules.sequential_routes import valid_road
        if not isinstance(road, dict) or not valid_road(road) or not road.get('coordinate_signature'):
            raise ValueError('저장 도로 경로 근거가 올바르지 않습니다.')
    return data


def migrate(data):
    """Pure v1→v2 projection; preserve the legacy point and all road evidence."""
    data = copy.deepcopy(validate(data))
    if data['version'] == 1:
        legacy = data['stops'].get('BOKJEONG')
        if legacy:
            for rid in ('R03', 'R04'):
                data['stops'].setdefault(rid+'-BOKJEONG', dict(copy.deepcopy(legacy), inherited_from='BOKJEONG'))
        data['version'] = 2
    return validate(data)


def load(path=None):
    path = Path(path or SETTINGS_FILE)
    if not path.exists():
        return empty()
    try:
        return migrate(json.loads(path.read_text(encoding='utf-8')))
    except (TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError('신규 정류장 설정이 손상되었습니다. 백업을 확인하세요.') from error


def load_for_display():
    """Isolate invalid road evidence on read, without weakening save validation."""
    try:
        return load()
    except ValueError:
        data = json.loads(Path(SETTINGS_FILE).read_text(encoding='utf-8'))
        roads = data.get('roads')
        if not isinstance(roads, dict):
            raise ValueError('신규 정류장 도로 설정 형식이 잘못되었습니다.')
        data['roads'] = {}
        validate(data)  # Bad stop coordinates/schema must still be rejected.
        valid = {}
        for rid, road in roads.items():
            candidate = dict(data, roads={rid: road})
            try:
                validate(candidate)
            except ValueError:
                continue
            valid[rid] = road
        return migrate(dict(data, roads=valid))


@contextmanager
def edit(expected_revision, path=None):
    path = Path(path or SETTINGS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('다른 저장이 진행 중입니다. 잠시 후 다시 시도하세요. 지속되면 저장 잠금 파일을 관리자에게 확인하세요.') from None
    temp = None
    try:
        os.close(fd)
        data = load(path)
        if data['revision'] != expected_revision:
            raise ValueError('설정이 다른 화면에서 변경됐습니다. 새로고침 후 다시 선택하세요.')
        original = path.read_bytes() if path.exists() else None
        yield data
        data['revision'] += 1
        payload = json.dumps(validate(data), ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        # Validate the exact serialized artifact before any replacement.
        validate(json.loads(payload))
        if original is not None:
            backups = path.parent / 'backups'
            backups.mkdir(exist_ok=True)
            backup = backups / (path.stem + '.' + uuid4().hex + '.json')
            with backup.open('xb') as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            if backup.read_bytes() != original:
                raise OSError('백업 무결성 확인 실패. 저장을 중단했습니다.')
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.locations_', suffix='.tmp', delete=False) as handle:
            temp = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError('저장 도중 설정 파일이 변경되었습니다. 새로고침하세요.')
        _replace_with_retry(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
        lock.unlink()


def migrate_file(path=None):
    """Persist migration via the same lock/backup/atomic replacement workflow."""
    path = Path(path or SETTINGS_FILE)
    if not path.exists():
        return load(path)
    raw = validate(json.loads(path.read_text(encoding='utf-8')))
    if raw['version'] == 1:
        with edit(raw['revision'], path):
            pass
    return load(path)


def save_stop(stop_id, latitude, longitude, expected_revision, path=None):
    if stop_id not in STOP_IDS:
        raise ValueError('R03/R04 및 복정역 후보만 수정할 수 있습니다.')
    lat, lon = coordinates(latitude, longitude)
    with edit(expected_revision, path) as data:
        data['stops'][stop_id] = dict(latitude=lat, longitude=lon, source=SOURCE,
            updated_at=datetime.now(timezone.utc).isoformat(), access_status='검증 필요')
        affected = (stop_id[:3],)
        for rid in affected:
            data['roads'].pop(rid, None)


def route_points(route_id, data):
    if route_id not in ('R03', 'R04'):
        raise ValueError('신규 노선만 조회할 수 있습니다.')
    ids = [route_id+'-S01', route_id+'-S02', route_id+'-BOKJEONG']
    if not all(sid in data['stops'] for sid in ids):
        raise ValueError('승차 정류장 2개와 복정역 하차 후보를 모두 저장한 뒤 조회하세요.')
    return [[data['stops'][sid]['latitude'], data['stops'][sid]['longitude']] for sid in ids]


def point_signature(points):
    return hashlib.sha256(json.dumps(points, sort_keys=True).encode()).hexdigest()


def checked_road(road, points):
    from modules.sequential_routes import geometry_check
    if not road or 'osrm' not in str(road.get('source', '')).lower():
        raise ValueError('OSRM 차량 경로를 확인하지 못했습니다. 검증 필요 상태를 유지합니다.')
    stops = [dict(stop_id=str(i), latitude=p[0], longitude=p[1]) for i, p in enumerate(points)]
    checked = geometry_check(road, stops)
    if not checked:
        raise ValueError('경로의 정류장 접근 거리 또는 방문 순서가 맞지 않습니다. 검증 필요 상태를 유지합니다.')
    return dict(copy.deepcopy(road),
                distance_km=float(road['distance_km']), duration_min=float(road['duration_min']),
                coordinates=[[float(a), float(b)] for a, b in road['coordinates']],
                coordinate_signature=point_signature(points),
                snap_distances_m=checked['snap_distances_m'], status='OSRM 도로 모형 확인 · 차량 접근·정차 검증 필요')


def query_road(route_id, expected_revision, path=None, router=None):
    from modules.route_engine import calculate_road_route
    data = load(path)
    if data['revision'] != expected_revision:
        raise ValueError('설정이 변경됐습니다. 다시 조회하세요.')
    points = route_points(route_id, data)
    # Explicit user action; existing router never writes its source cache.
    road = (router or calculate_road_route)(points, allow_network=True)
    try:
        checked = checked_road(road, points)
    except ValueError:
        # Do not continue presenting a previous successful result after failure.
        with edit(expected_revision, path) as current:
            current['roads'].pop(route_id, None)
        raise
    with edit(expected_revision, path) as current:
        current['roads'][route_id] = checked
    return checked
