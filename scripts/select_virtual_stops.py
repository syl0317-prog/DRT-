"""Create actual stops only after apartment, administrative and boarding-site verification."""
from build_stage0 import ROOT, OUT, read_csv, write_csv

def select():
    rows = read_csv(OUT/'apartment_classification.csv')
    candidates = {r['후보ID']: r for r in read_csv(OUT/'virtual_stop_candidates_v2.csv')}
    eligible = [r for r in rows if r['분류상태'] == '확정' and r['유형'] == 'DRT대상'
        and r['위례동내부'] == 'Y' and r['좌표상태'] == 'verified' and r['수요합산'] == 'Y'
        and candidates.get(r['단지코드'], {}).get('승하차검증') == 'verified']
    if len(eligible) < 3:
        print(f'Stage 1 HOLD: verified eligible={len(eligible)} (<3); original stops retained; v2 not generated')
        return
    eligible.sort(key=lambda r: float(candidates[r['단지코드']]['점수']), reverse=True)
    original = read_csv(ROOT/'sewook31/data/drt_stops.csv')
    stops = [r for r in original if r['stop_type'] == 'tram']
    assert len(stops) == 2
    for i, r in enumerate(eligible[:8], 1):
        stops.append({'stop_id': f'D{i:02d}', 'stop_name': r['단지명'], 'stop_type': 'drt',
            'zone': r['행정구역'], 'latitude': r['위도'], 'longitude': r['경도']})
    write_csv(ROOT/'sewook31/data/drt_stops_v2.csv', stops)
    print(f'Stage 1 generated {len(stops)-2} verified DRT stops; change stops_file only after reservation ID migration review')

if __name__ == '__main__':
    select()
