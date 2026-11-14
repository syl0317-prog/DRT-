"""Preload OSRM routes and save reproducible, explicitly provisional results."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sewook31'))
from modules.punctuality_sim import calibrate, generate, save_results
from modules.route_engine import calculate_road_route

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', action='store_true')
    args = parser.parse_args()
    calibrate(persist=True)
    frame = generate(allow_network=args.network)
    save_results(frame)
    apartments = json.loads((ROOT / 'data/processed/wirye_vulnerable_apartments.geojson').read_text(encoding='utf-8'))['features']
    stations = json.loads((ROOT / 'data/processed/wirye_tram_official_stations.geojson').read_text(encoding='utf-8'))['features']
    apt = next(f for f in apartments if f['properties']['name'] == '위례그린파크푸르지오')
    station = next(f for f in stations if f['properties']['station_no'] == '108')
    route = calculate_road_route([apt['geometry']['coordinates'][::-1], station['geometry']['coordinates'][::-1]], allow_network=args.network)
    comparison = {'route': '위례그린파크푸르지오 → 위례역사공원', 'osrm_minutes': route['duration_min'] if route else 'missing',
        'field_reference_minutes': 6, 'field_reference_status': 'unverified', 'field_reference_source': '사용자 답사 약 6분 참고값; 날짜·경로·원시기록 missing',
        'coordinate_status': 'unverified', 'note': '정거장 GeoJSON 108 기준. 보정하지 않음. 혼잡계수 실측 보정에 사용하지 않음.'}
    (ROOT / 'data/processed/osrm_comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(comparison, ensure_ascii=False))
    print(frame[(frame['여유분'].isin([0, 3, 5])) & (frame['합승수'] == 0)].drop(columns='가정').to_string(index=False))

if __name__ == '__main__':
    main()
