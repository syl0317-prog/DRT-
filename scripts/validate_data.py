"""Read-only validation. WARN denotes incomplete evidence, FAIL structural defects."""
import sys
import math
import json
from collections import Counter
from build_stage0 import ROOT, OUT, read_csv


def validate():
    results = []
    def check(ok, message, level='FAIL'):
        results.append(('PASS' if ok else level, message))
    for filename in ('apartment_master.csv', 'apartment_classification.csv', 'virtual_stop_candidates_v2.csv', 'stops_with_admin.csv'):
        path = OUT / filename
        check(path.exists(), filename + ' exists')
        if not path.exists():
            continue
        rows = read_csv(path)
        check(bool(rows), filename + ' nonempty')
        if filename.startswith('apartment_'):
            required = {'단지코드', '단지명', '세대수', '경도', '위도', '좌표상태', '출처', '수요합산', '창곡동내부', '위례동내부', '트램좌표상태'}
            check(required <= set(rows[0]), filename + ' required columns')
            if not required <= set(rows[0]):
                continue
            check(len({r['단지코드'] for r in rows}) == len(rows), filename + ' unique apartment codes')
            for r in rows:
                name = r['단지명']
                try:
                    valid = float(r['세대수']) > 0 and float(r['세대수']).is_integer()
                except ValueError:
                    valid = False
                check(valid, name + ' households positive integer')
                check(r['출처'] not in ('', 'missing'), name + ' household source')
                check(r['좌표상태'] in ('missing', 'unverified', 'verified'), name + ' coordinate status')
                if 'missing' in (r['경도'], r['위도']):
                    check(r['경도'] == r['위도'] == 'missing' and r['좌표상태'] == 'missing', name + ' missing coordinates consistent')
                    check(False, name + ' coordinates missing', 'WARN')
                else:
                    try:
                        valid = math.isfinite(float(r['위도'])) and 33 <= float(r['위도']) <= 39 and 124 <= float(r['경도']) <= 132
                    except ValueError:
                        valid = False
                    check(valid, name + ' coordinate range')
                    check(r['좌표상태'] == 'verified', name + ' coordinates unverified', 'WARN')
                if filename == 'apartment_classification.csv':
                    check(r['분류상태'] in ('확정', '예비', '미확정'), name + ' classification status')
                    check(r['분류상태'] != '확정' or (r['좌표상태'] == r['트램좌표상태'] == 'verified'), name + ' confirmed classification evidence')
            address_counts = Counter(r['도로명주소'] for r in rows)
            check(not any(v > 1 for v in address_counts.values()), filename + ' duplicate addresses need review', 'WARN')
            check(all(r['수요합산'] == 'N' for r in rows if '통합' in r['보류사유'] or '이중계산' in r['보류사유']), filename + ' held registrations excluded')
        else:
            required = {'좌표상태', '창곡동내부', '위례동내부'}
            check(required <= set(rows[0]), filename + ' required status columns')
            lat, lon = ('latitude', 'longitude') if filename == 'stops_with_admin.csv' else ('위도', '경도')
            check(all(33 <= float(r[lat]) <= 39 and 124 <= float(r[lon]) <= 132 for r in rows), filename + ' coordinate range')
    check(False, 'Tram coordinates unverified; legal Changgok boundary is not administrative Wirye boundary', 'WARN')
    check(False, 'Walking routes, verified bus alternatives, observed travel times and boarding-site checks missing', 'WARN')
    params_path = ROOT/'data/assumptions/sim_params.json'
    if params_path.exists():
        params = json.loads(params_path.read_text(encoding='utf-8'))
        required = {'stops_file', 'vehicle_count', 'vehicle_capacity', 'traffic_factor', 'transfer_buffer', 'dwell_minutes', 'k_min', 'k_mode', 'k_max', 'simulation_runs', 'random_seed', 'detour_per_passenger'}
        check(required <= set(params), 'simulation required settings')
        for key, spec in params.items():
            check({'value', 'status', 'source'} <= set(spec) and spec.get('status') in ('assumption', 'sourced') and bool(spec.get('source')), key+' annotated setting')
        check(1 <= params['vehicle_count']['value'] <= 6 and params['vehicle_capacity']['value'] > 0, 'fleet setting range')
        check(0 < params['k_min']['value'] <= params['k_mode']['value'] <= params['k_max']['value'], 'triangular factor order')
        check((ROOT/'sewook31/data'/params['stops_file']['value']).is_file(), 'configured stops exist')
        table = json.loads((ROOT/'data/assumptions/tram_timetable.json').read_text(encoding='utf-8'))
        check(all(s['headway_minutes'] > 0 and s['status'] == 'assumption' and s['source'] for s in table.values()), 'virtual timetable annotated')
        results_path = OUT/'punctuality_results.csv'
        if results_path.exists():
            simulation = read_csv(results_path)
            stops = read_csv(ROOT/'sewook31/data'/params['stops_file']['value'])
            expected = sum(s['stop_type'] == 'drt' for s in stops)*len(table)*3*11
            check(len(simulation) == expected, 'configured candidate simulation combinations')
            valid = True
            for r in simulation:
                if r['놓칠확률'] == 'missing':
                    valid &= r['평균대기분'] == 'missing'
                else:
                    valid &= 0 <= float(r['놓칠확률']) <= 1 and math.isfinite(float(r['평균대기분'])) and float(r['평균대기분']) >= 0
                valid &= bool(r['가정'])
            check(valid, 'simulation ranges/missing consistency/assumptions')
    counts = Counter(level for level, _ in results)
    for level, message in results:
        if level != 'PASS':
            print(level + ': ' + message)
    print(' / '.join(f'{level}={counts[level]}' for level in ('PASS', 'WARN', 'FAIL')))
    return counts['FAIL']


if __name__ == '__main__':
    sys.exit(bool(validate()))
