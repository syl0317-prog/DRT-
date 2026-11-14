"""One-time migration of existing application sources; source data untouched."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'sewook31'

def main():
    specs = {
        'stops_file': ('drt_stops.csv', '기존 미검증 후보 유지'),
        'vehicle_count': (4, '기존 reservation_manager.py; 구역당 1대/2구역 계획과 다름'),
        'vehicle_capacity': (8, '기존 차량 정원'), 'traffic_factor': (1.2, '기존 혼잡계수'),
        'transfer_buffer': (5, '기존 환승 여유 분'), 'dwell_minutes': (1, '기존 정차 분'),
        'k_min': (1.0, '실측 입력 전 가정값'), 'k_mode': (1.2, '실측 입력 전 가정값'),
        'k_max': (1.5, '실측 입력 전 가정값'), 'detour_per_passenger': (2, '사용자 지정 합승 추가 분'),
        'simulation_runs': (10000, '사용자 지정 조건별 반복'), 'random_seed': (20261110, '재현 가능한 고정 시드'),
        'operating_days_per_year': (365, '연간 비용/이용객 환산 가정; 실제 운영일 확인 필요')}
    params = {k: {'value': v, 'status': 'assumption', 'source': source} for k, (v, source) in specs.items()}
    path = ROOT / 'data/assumptions/sim_params.json'
    if not path.exists():
        path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding='utf-8')
    timetable = {k: {'headway_minutes': v, 'status': 'assumption', 'source': '사용자 지정 가상 배차; 실제 시간표 아님'} for k, v in [('출퇴근', 10), ('평시', 15)]}
    (ROOT / 'data/assumptions/tram_timetable.json').write_text(json.dumps(timetable, ensure_ascii=False, indent=2), encoding='utf-8')
    for p in sorted(BASE.rglob('*.py')):
        if p.name in ('settings.py', 'route_engine.py', 'punctuality_sim.py', 'analysis_views.py', 'operating_costs.py'):
            continue
        text = p.read_text(encoding='utf-8')
        original = text
        if 'drt_stops.csv' in text:
            text = 'from modules.settings import stops_path, setting\n' + text
            text = text.replace('BASE_DIR / "data" / "drt_stops.csv"', 'stops_path()')
            text = text.replace('"data/drt_stops.csv"', 'stops_path()')
            text = re.sub(r'\(\s*Path\(__file__\).resolve\(\).parent\s*/ "data"\s*/ "drt_stops.csv"\s*\)', 'stops_path()', text)
            text = text.replace('STOPS_FILE,', 'stops_path(),')
        if any(t in text for t in ('transfer_buffer=5', 'dwell_minutes=1', 'traffic_factor=1.2', 'boarding_minutes=1')):
            if 'import stops_path, setting' not in text:
                text = 'from modules.settings import setting\n' + text
            for key, old in [('transfer_buffer', '5'), ('dwell_minutes', '1'), ('traffic_factor', '1.2'), ('boarding_minutes', '1')]:
                config = 'dwell_minutes' if key == 'boarding_minutes' else key
                text = text.replace(f'{key}={old}', f'{key}=setting("{config}")')
        if p.name == 'reservation_manager.py':
            text = 'from modules.settings import vehicle_count\n' + text
            text = text.replace('VEHICLE_COUNT = 4', 'VEHICLE_COUNT = setting("vehicle_count")').replace('VEHICLE_CAPACITY = 8', 'VEHICLE_CAPACITY = setting("vehicle_capacity")')
            text = text.replace('range(1, VEHICLE_COUNT + 1)', 'range(1, vehicle_count() + 1)')
            start = text.index('    reservations = load_reservations()', text.index('    return new_reservation, message'))
            end = text.index('\ndef cancel_reservation', start)
            text = text[:start] + '\n' + text[end:]
            first = text.index('\ndef calculate_reservation_pickup(')
            second = text.index('\ndef calculate_reservation_pickup(', first+1)
            text = text[:first] + text[second:]
        if p.name == 'map_view.py':
            start = text.index('    if st.button("선택 위치 저장"):')
            end = text.index('    st.divider()', start)
            text = text[:start] + '    st.info("정류장 원본은 읽기 전용입니다. 변경 위치는 별도 검증이 필요합니다.")\n\n' + text[end:]
        if p.name == 'app.py':
            text = text.replace('"운영 시뮬레이션"\n', '"운영 시뮬레이션",\n        "정시성 검증",\n        "관리자 패널"\n')
            text = text.replace('st.sidebar.title("운영 메뉴")', 'st.sidebar.title("운영 메뉴")\nst.sidebar.slider("차량 수", 1, 6, int(setting("vehicle_count")), key="vehicle_count")\nst.caption("개통 일정 확인 필요 · 가상 시간표 기준 · 기존 정류장 좌표 미검증")')
            text = text.replace('col1.metric("운영 차량", "4대")', 'col1.metric("운영 차량", f"{st.session_state.vehicle_count}대")').replace('max_value=8,', 'max_value=int(setting("vehicle_capacity")),')
            text = text.replace('value=5', 'value=int(setting("transfer_buffer"))').replace('value=1.2', 'value=float(setting("traffic_factor"))')
            text = text.replace('max_value=10,\n            value=1', 'max_value=10,\n            value=int(setting("dwell_minutes"))')
            start = text.index('\n\n            reservation, message = create_reservation(', text.index('            except ValueError as e:'))
            end = text.index('\n        st.divider()', start)
            text = text[:start] + '\n' + text[end:]
            text += '\n\nelif menu == "정시성 검증":\n    from modules.analysis_views import show_punctuality\n    show_punctuality()\n\nelif menu == "관리자 패널":\n    from modules.analysis_views import show_admin\n    show_admin()\n'
        if text != original:
            p.write_text(text, encoding='utf-8')
    (BASE / 'modules/route_engine.py').write_text('"""Cached road routing; unavailable routes return None."""\nfrom modules.osrm_cache import calculate_road_route\n', encoding='utf-8')
    cache = BASE / 'data/osrm_cache.json'
    if not cache.exists():
        cache.write_text('{}\n', encoding='utf-8')

if __name__ == '__main__':
    main()
