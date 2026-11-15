"""Candidate-only R03/R04 overlay. Never writes to source registries."""
import copy
from modules.settings import PROJECT_DIR

NAMES = {'R03': '위례 북서부 → 복정역', 'R04': '위례 중서부 → 복정역'}
DESTINATION = 'BOKJEONG'
DESTINATIONS = {'R03': 'R03-BOKJEONG', 'R04': 'R04-BOKJEONG'}
STOPS = [
    dict(stop_id='R03-S01', name='위례포레샤인 23단지 인근', route_id='R03', position=1,
         address='위례순환로 477 주변', source='사용자 최종 설계안 · 네이버 지도 표시 위치 미수신'),
    dict(stop_id='R03-S02', name='서울송례초등학교 인근', route_id='R03', position=2,
         address=None, source='사용자 최종 설계안 · GITS 송례초교사거리는 도로 구간명만 확인'),
    dict(stop_id='R04-S01', name='위례중앙푸르지오 인근', route_id='R04', position=1,
         address=None, source='사용자 최종 설계안 · GIS 107 중심광장 좌표는 도로변 승차 위치가 아님'),
    dict(stop_id='R04-S02', name='위례센트럴자이 인근', route_id='R04', position=2,
         address='위례광장로 97 주변', source='data/processed/apartment_master.csv A10026944'),
]


def boarding_stops():
    """Return all boarding candidates; route filtering belongs to callers."""
    from modules.new_stop_settings import load_for_display
    return _boarding_stops(load_for_display())


def _boarding_stops(settings):
    """Build candidates from one already-loaded settings snapshot."""
    stops = [dict(copy.deepcopy(s), latitude=None, longitude=None, stop_type='drt',
                 coordinate_status='검증 필요 · 도로변 좌표 미확정',
                 access_status='검증 필요 · 차량 접근·정차·진입 방향 미확인',
                 destination_stop_id=DESTINATIONS[s['route_id']]) for s in STOPS]
    for stop in stops:
        apply_candidate(stop, settings)
    return stops


def apply_candidate(stop, settings):
    candidate = settings['stops'].get(stop['stop_id'])
    if candidate:
        stop.update(latitude=candidate['latitude'], longitude=candidate['longitude'],
                    source=candidate['source'], updated_at=candidate['updated_at'],
                    coordinate_status='사용자 지정 후보 좌표 · 검증 필요')
        if candidate.get('inherited_from'):
            stop['coordinate_status'] = '기존 공통 복정역에서 복사한 초기 후보 · 검증 필요'
    return stop


def destination_stop():
    """Legacy common point, retained for read-only compatibility."""
    from modules.new_stop_settings import load_for_display
    return _destination_stop(load_for_display())


def destination_stops():
    from modules.new_stop_settings import load_for_display
    settings = load_for_display()
    return [_destination_stop(settings, rid) for rid in DESTINATIONS]


def _destination_stop(settings, route_id=None):
    # Existing station 112 is a reference location, not a verified roadside bay.
    import json
    path = PROJECT_DIR / 'data/processed/wirye_tram_official_stations.geojson'
    features = json.loads(path.read_text(encoding='utf-8'))['features']
    station = next(f for f in features if f['properties']['station_no'] == '112')
    lon, lat = station['geometry']['coordinates']
    sid = DESTINATIONS[route_id] if route_id else DESTINATION
    return apply_candidate(dict(stop_id=sid, name='복정역', latitude=lat, longitude=lon,
                stop_type='destination', source=str(path.relative_to(PROJECT_DIR)),
                coordinate_status='기존 GIS 역 기준점 · 승하차 위치 검증 필요',
                access_status='검증 필요 · 하차 지점 차량 접근·회차 미확인'), settings)


def plans():
    import hashlib, json
    from modules.new_stop_settings import load_for_display, route_points, checked_road
    settings = load_for_display()
    result = []
    for rid, name in NAMES.items():
        stops = [s for s in _boarding_stops(settings) if s['route_id'] == rid] + [_destination_stop(settings, rid)]
        order = [s['stop_id'] for s in stops]
        road = settings['roads'].get(rid)
        if road:
            try:
                points = route_points(rid, settings)
                verified = checked_road(road, points)
                if verified['coordinate_signature'] != road['coordinate_signature']:
                    road = None
            except ValueError:
                road = None
        signature = hashlib.sha256(json.dumps([stops, road], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result.append(dict(route_id=rid, name=name, order=order, stops=stops, paths=[],
            estimated_paths=[], access=[], temporary=True, road_complete=False,
            signature=signature, segments=[], evidence=[], distance_km=None, duration_min=None,
            active=False, vehicles=[], test_geometry=False,
            road_candidates=['위례터널 인근 · 경유 도로 후보(승차 정류장 아님)'] if rid == 'R04' else [],
            geometry_note=' → '.join(order) + ' · 도로변 좌표 미확정 · 도로 연결 검증 필요 · 운행 검증 대기'))
        # Road model confirmation does not authorize dispatch/stop access.
        result[-1].update(paths=[road['coordinates']] if road else [],
            road_model_complete=bool(road),
            distance_km=road['distance_km'] if road else None,
            duration_min=road['duration_min'] if road else None,
            evidence=[road] if road else [],
            geometry_note=' → '.join(order) + (' · OSRM 도로 모형 확인 · 차량 접근·정차 검증 필요' if road else ' · 좌표/도로 연결 검증 필요 · 운행 검증 대기'))
        from modules.new_route_display import display_geometry
        result[-1].update(display_geometry(rid, stops, road))
    return result


def show_validation():
    import streamlit as st
    import pandas as pd
    st.caption('신규 후보 노선 · 기존 R01/R02 원본과 별도 · R03 진한 파랑 / R04 초록')
    for plan in plans():
        st.write(f"{plan['route_id']} — {plan['name']}")
        st.dataframe(pd.DataFrame([{'순서': i, '정류장': s['stop_id'], '이름': s['name'],
            '위도': s['latitude'], '경도': s['longitude'], '좌표 상태': s['coordinate_status'],
            '차량 접근': s['access_status'],
            '근거': s['source']} for i, s in enumerate(plan['stops'], 1)]), hide_index=True)
        if plan['road_model_complete']:
            st.info(f"OSRM 도로 모형: {plan['distance_km']:.2f} km · {plan['duration_min']:.1f}분 · 실측 아님")
        else:
            st.warning('경로 확인 필요 · 저장 OSRM 도로 연결 미확인 · 거리/시간 산출 불가')
        st.warning('차량 접근·정차·회차 검증 필요 · 배차 확정 불가')
        st.caption('정시성 시뮬레이션: OSRM 도로 모형 기준으로 지원(시뮬레이션 및 정시성 분석 메뉴) · 차량 접근·정차 검증 필요')
        for candidate in plan['road_candidates']:
            st.caption(candidate + ' · 통행 방향·고속도로 진입·회차 검증 필요')
