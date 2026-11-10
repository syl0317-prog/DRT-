"""Read-only validation. WARN denotes incomplete evidence, FAIL structural defects."""
import sys
import math
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
    counts = Counter(level for level, _ in results)
    for level, message in results:
        if level != 'PASS':
            print(level + ': ' + message)
    print(' / '.join(f'{level}={counts[level]}' for level in ('PASS', 'WARN', 'FAIL')))
    return counts['FAIL']


if __name__ == '__main__':
    sys.exit(bool(validate()))
