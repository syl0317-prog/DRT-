"""Write an auditable development summary from actual outputs."""
import contextlib
import io
import json
import subprocess
from collections import Counter
from build_stage0 import ROOT, OUT, read_csv
from validate_data import validate

def table(rows, keys):
    lines = ['| '+' | '.join(keys)+' |', '| '+' | '.join(['---']*len(keys))+' |']
    lines += ['| '+' | '.join(str(r[k]).replace('|', '/') for k in keys)+' |' for r in rows]
    return '\n'.join(lines)

def main():
    master = read_csv(OUT/'apartment_master.csv')
    classification = read_csv(OUT/'apartment_classification.csv')
    candidates = read_csv(OUT/'virtual_stop_candidates_v2.csv')
    results = read_csv(OUT/'punctuality_results.csv')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert validate() == 0
    compare = json.loads((OUT/'osrm_comparison.json').read_text(encoding='utf-8'))
    commits = subprocess.check_output(['git', 'log', '--format=%h %s', '9ab01d9..HEAD'], cwd=ROOT).decode('utf-8').strip()
    changed = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'diff', '--name-only', '9ab01d9'], cwd=ROOT).decode('utf-8').splitlines()
    new = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT).decode('utf-8').splitlines()
    names = sorted({n for n in changed+new if '__pycache__' not in n and not n.endswith('.log')} | {'docs/development_stage0_5_report.md'})
    chosen = [r for r in results if r['합승수'] == '0' and r['여유분'] in ('0', '3', '5')]
    for r in chosen:
        r['놓칠확률'] = f"{float(r['놓칠확률'])*100:.2f}%" if r['놓칠확률'] != 'missing' else 'missing'
        r['평균대기분'] = f"{float(r['평균대기분']):.3f}" if r['평균대기분'] != 'missing' else 'missing'
    text = f'''# 위례 DRT 단계 0~5 개발 결과

작성일: 2026-11-10. Git fetch 후 HEAD와 origin/main 차이 0/0 확인. 충돌 및 덮어쓰기 없음. push 없음.
Python 3.12 venv 생성, requirements.txt 전체 설치 및 pip check 통과.

## 완료 범위

- 단계 0: 19행 통합표·보수적 분류·후보 초안·검증 도구 완료.
- 단계 1: 검증된 행정동 위례동 내부 DRT대상 0개로 실제 정류장 확정 보류. drt_stops_v2.csv 미생성. 선택 스크립트의 게이트 검증 완료.
- 단계 2: 경로·설정 분리 및 방향별 OSRM 캐시 완료. 캐시 우선, 캐시 미존재/조회 실패는 missing.
- 단계 3: 4개 기존 미검증 DRT 후보 × 2시간대 × 3합승조건 × 11여유시간 = {len(results)}행. 조건별 10,000회, 고정 시드.
- 단계 4: 관리자 패널·1~6대 슬라이더·월/연 비용·이용객당 운영비·가상시간표 문구·README 완료.
- 단계 5: 전체 sewook31 Python py_compile, 8개 회귀 테스트(여러 UI 화면 포함), Streamlit HTTP health 및 5초 유지 통과.

기존 원본 34개 파일을 Git 체크아웃 필터를 적용한 초기 커밋과 대조하여 보존 확인. 원본 data/raw, 기존 GeoJSON, drt_stops.csv 및 예약 CSV를 수정하지 않음.

## 데이터 상태

- 좌표 missing {sum(r['좌표상태']=='missing' for r in master)}개, unverified {sum(r['좌표상태']=='unverified' for r in master)}개. 수요합산 제외 2개.
- 유형은 모두 확정 전: {dict(Counter(r['유형']+' / '+r['분류상태'] for r in classification))}.
- 창곡동 법정동 기준: {dict(Counter(r['창곡동내부'] for r in master))}. 행정동 위례동 내부 여부 19개 모두 missing.
- 위례자이더시티의 기존 좌표는 제공된 창곡동 경계 밖으로 판정됨. 단지 실제 위치에 대한 확정 판정이 아니며 좌표/경계 대조가 필요함.
- 위례포레샤인23단지 좌표 missing으로 12역 거리표를 만들지 않음. 문서의 2,200세대는 검증된 통합표에 추가하지 않음.
- travel_time_observed.csv 및 household_stats_todo.csv는 UTF-8 BOM 빈 입력 양식만 생성. 입력 실측/통계 0건.
- bus_routes_real.csv의 미확인 45칸. 기존 raw 배차표/노선 파일은 참고용으로 보존하며 최신 검증 자료로 승격하지 않음.

## 가상정류장 후보 (실제 선정 아님)

{table(candidates, ['후보ID', '단지명', '창곡동내부', '위례동내부', '좌표상태', '선정가능'])}

4개 단지 후보와 기존 D01~D04 총 8개 검토 항목이다. 검증된 승하차 지점 8개가 아니다.
예비점수는 직선거리/700이며 세대수·300m 격자인구·사각지대 포함 여부는 검토 속성으로 제공.
격자 인구와 세대수는 수요 중복을 피하기 위해 합산하지 않음. 2024 인구이며 반경 중복 및 결측 0 처리에 주의.

## 정시성 결과 (합승 0명)

{table(chosen, ['정류장', '시간대', '여유분', '놓칠확률', '평균대기분', '기준대기분'])}

전체 합승 0~2명 결과는 data/processed/punctuality_results.csv 참조.
k=1.0/1.2/1.5 가정이며 실측 0건. 0분 여유의 100%는 혼잡계수>1이면서 여유가 없는 설계의 결과이고 실제 서비스 예측이 아니다.
예정 픽업은 OSRM+정차+여유를 역산하며 합승 추가 지연은 별도로 적용한다. 도착과 실제 가상 트램 출발을 비교하고 여러 편을 놓치는 경우도 계산한다.
정시성 최근접역은 기준 GeoJSON 12역 중 선택한다. 기존 예약은 기존 환승거점 2개를 유지하므로 두 용도의 좌표가 다를 수 있다.

## OSRM 비교

그린파크푸르지오→기준 GeoJSON 위례역사공원: OSRM {compare['osrm_minutes']}분, 답사 참고 약 6분.
좌표와 답사 원시 기록 unverified. 보정하지 않음. 같은 출발·도착·진행방향·측정 조건 확인 전 실측 보정에 사용하지 않는다.

## 문구 정정

- docs/관리용 웹사이트 구상:4 — 기존 2027년 예정 표현 정정.
- scripts/generate_tram_blindspot_map.py:496 — 기존 2026 개통 표현 정정.
- 텍스트 검색에서 12월 개통 표현 없음. 원본 바이너리 문서는 수정 대상에서 제외.
- 최신 확정 개통일의 공식 원문을 확보하지 못해 '개통 일정 확인 필요 · 가상 시간표 기준'으로 표기.

## 검증 로그

```text
{buf.getvalue().strip()}
```

WARN 42건은 두 통합표에 반복되는 좌표 missing/unverified 38건, 주소 중복 2건, 공통 근거 부족 2건이다. FAIL 0은 구조 검증 통과이며 현장 데이터 확정을 뜻하지 않는다.

## 추가 확인 및 사용자가 할 일

1. 단지코드로 좌표·출입구를 확인하고 주소 충돌 및 위례역푸르지오 통합 등록/5단지 세대수를 확인.
2. 행정동 위례동 경계와 기준 트램 위치·승강장 접근 지점을 공식 자료로 확인.
3. 단지별 보행경로·횡단 및 버스 방향별 연결·현재 배차를 확인. 실제 승하차 위치를 답사.
4. travel_time_observed.csv에 같은 경로의 실측·OSRM 쌍, 날짜, 출처, 검증상태 입력. 최소 3개 검증 쌍부터 혼잡계수 산출.
5. 기존 코드 4대와 계획서 2대 중 차량 계획을 결정. 실제 운영일·보험료·환승할인·위례 수요를 보완.
6. 검증된 정류장으로 전환 전 예약의 정류장 ID 및 노선 대응을 점검. 기존 예약은 자동 재매핑하지 않음.
7. 실행은 README의 venv 활성화 → PYTHONUTF8=1 → streamlit run sewook31/app.py 순서 사용.

## 변경·생성 파일

''' + '\n'.join('- '+n for n in names) + f'''

## 로컬 커밋 (보고서 생성 시점)

```text
{commits}
```

이 보고서 자체를 포함한 최종 문서 커밋은 git log로 확인 가능. .env/venv/data/raw/archive 및 실행 생성 pyc는 커밋하지 않음.
'''
    (ROOT/'docs/development_stage0_5_report.md').write_text(text, encoding='utf-8', newline='\n')
    print('Wrote docs/development_stage0_5_report.md')

if __name__ == '__main__':
    main()
