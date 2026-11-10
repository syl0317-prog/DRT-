"""Build conservative draft datasets without changing source data."""
import csv
import json
import math
from pathlib import Path
from collections import Counter
from difflib import get_close_matches

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'processed'


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def geo(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def distance(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [*a, *b])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def in_ring(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:]+ring[:1]):
        cross = (x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        if abs(cross) < 1e-12 and min(a[0], b[0]) <= x <= max(a[0], b[0]) and min(a[1], b[1]) <= y <= max(a[1], b[1]):
            return 'boundary'
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def contains(point, geometry):
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    for polygon in polygons:
        tests = [in_ring(point, ring) for ring in polygon]
        if 'boundary' in tests:
            return 'boundary'
        if tests[0] and not any(tests[1:]):
            return 'Y'
    return 'N'


def build():
    households = read_csv(ROOT / 'data/assumptions/apartment_households.csv')
    apartments = {f['properties']['name']: f for f in geo('wirye_vulnerable_apartments.geojson')['features']}
    stations = geo('wirye_tram_official_stations.geojson')['features']
    boundary = geo('wirye_changgok_boundary.geojson')['features'][0]['geometry']
    blind = geo('wirye_tram_blindspot_700m.geojson')['features'][0]['geometry']
    grids = read_csv(OUT / 'wirye_grid_population.csv')
    codes = Counter(r['단지코드'] for r in households)
    master = []
    for r in households:
        name = r['단지명']
        match = apartments.get(name)
        point = match['geometry']['coordinates'] if match else None
        station = min(stations, key=lambda s: distance(point, s['geometry']['coordinates'])) if point else None
        master.append({
            '단지코드': r['단지코드'], '단지명': name, '세대수': r['세대수'], '도로명주소': r['도로명주소'],
            '수요합산': 'Y' if r['모델반영'] == 'Y' and codes[r['단지코드']] == 1 else 'N',
            '보류사유': r['비고'] or 'missing', '경도': point[0] if point else 'missing', '위도': point[1] if point else 'missing',
            '좌표상태': 'unverified' if point else 'missing',
            '좌표출처': 'data/processed/wirye_vulnerable_apartments.geojson' if point else 'missing',
            '유사명검토': ' | '.join(get_close_matches(name, apartments, n=3, cutoff=.45)) if not match else 'missing',
            '행정구역': '창곡동(법정동)' if point and contains(point, boundary) == 'Y' else 'missing',
            '창곡동내부': contains(point, boundary) if point else 'missing',
            '위례동내부': 'missing', '경계기준': '법정동 창곡동 41131108; 행정동 위례동과 동일시하지 않음',
            '최근접트램번호': station['properties']['station_no'] if station else 'missing',
            '최근접트램정거장': station['properties']['station_name'] if station else 'missing',
            '직선거리_m': round(distance(point, station['geometry']['coordinates']), 2) if station else 'missing',
            '트램좌표출처': 'data/processed/wirye_tram_official_stations.geojson', '트램좌표상태': 'unverified',
            '출처': r['출처'], '확인일': r['확인일'],
        })
    write_csv(OUT / 'apartment_master.csv', master)
    classification = []
    for r in master:
        d = r['직선거리_m']
        classification.append({**r, '유형': '미확정' if d == 'missing' else ('DRT대상' if d > 700 else '도보형'),
            '분류상태': '미확정' if d == 'missing' else '예비',
            '분류근거': '좌표 missing' if d == 'missing' else '직선거리 700m 팀 가정; 보행 및 버스 대안 미검증',
            '도보거리_m': 'missing', '버스접근성': 'missing'})
    write_csv(OUT / 'apartment_classification.csv', classification)
    candidates = []
    def candidate(cid, name, point, households_value, source, eligible='N'):
        pop = sum(int(g['인구']) for g in grids if distance(point, [float(g['중심_경도']), float(g['중심_위도'])]) <= 300)
        station = min(stations, key=lambda s: distance(point, s['geometry']['coordinates']))
        d = distance(point, station['geometry']['coordinates'])
        candidates.append({'후보ID': cid, '단지명': name, '경도': point[0], '위도': point[1], '세대수': households_value,
            '창곡동내부': contains(point, boundary), '위례동내부': 'missing', '사각지대내부': contains(point, blind),
            '300m격자인구': pop, '직선거리_m': round(d, 2), '좌표상태': 'unverified', '선정가능': eligible,
            '점수': round(d/700, 4), '점수근거': '거리/700 예비순위; 세대수와 격자인구는 중복 방지를 위해 합산하지 않음',
            '출처': source, '검토사유': '좌표·보행·버스·승하차 위치 미검증; 격자인구는 2024년 자료, 반경 중복 가능'})
    for r in master:
        if r['경도'] != 'missing' and r['수요합산'] == 'Y':
            candidate(r['단지코드'], r['단지명'], [r['경도'], r['위도']], r['세대수'], r['좌표출처'])
    stops = read_csv(ROOT / 'sewook31/data/drt_stops.csv')
    admin = []
    for r in stops:
        point = [float(r['longitude']), float(r['latitude'])]
        admin.append({**r, '창곡동내부': contains(point, boundary), '위례동내부': 'missing', '좌표상태': 'unverified', '경계기준': '법정동 창곡동'})
        if r['stop_type'] == 'drt':
            candidate(r['stop_id'], r['stop_name'], point, 'missing', 'sewook31/data/drt_stops.csv')
    write_csv(OUT / 'stops_with_admin.csv', admin)
    write_csv(OUT / 'virtual_stop_candidates_v2.csv', sorted(candidates, key=lambda r: r['점수'], reverse=True))
    print(f'master={len(master)}, coordinates={sum(r["경도"] != "missing" for r in master)}, candidates={len(candidates)}, confirmed_DRT=0')


if __name__ == '__main__':
    build()
