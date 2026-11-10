# 위례 DRT 단계 0~5 개발 결과

작성일: 2026-11-10. Git fetch 후 HEAD와 origin/main 차이 0/0 확인. 충돌 및 덮어쓰기 없음. push 없음.
Python 3.12 venv 생성, requirements.txt 전체 설치 및 pip check 통과.

## 완료 범위

- 단계 0: 19행 통합표·보수적 분류·후보 초안·검증 도구 완료.
- 단계 1: 검증된 행정동 위례동 내부 DRT대상 0개로 실제 정류장 확정 보류. drt_stops_v2.csv 미생성. 선택 스크립트의 게이트 검증 완료.
- 단계 2: 경로·설정 분리 및 방향별 OSRM 캐시 완료. 캐시 우선, 캐시 미존재/조회 실패는 missing.
- 단계 3: 4개 기존 미검증 DRT 후보 × 2시간대 × 3합승조건 × 11여유시간 = 264행. 조건별 10,000회, 고정 시드.
- 단계 4: 관리자 패널·1~6대 슬라이더·월/연 비용·이용객당 운영비·가상시간표 문구·README 완료.
- 단계 5: 전체 sewook31 Python py_compile, 8개 회귀 테스트(여러 UI 화면 포함), Streamlit HTTP health 및 5초 유지 통과.

기존 원본 34개 파일을 Git 체크아웃 필터를 적용한 초기 커밋과 대조하여 보존 확인. 원본 data/raw, 기존 GeoJSON, drt_stops.csv 및 예약 CSV를 수정하지 않음.

## 데이터 상태

- 좌표 missing 15개, unverified 4개. 수요합산 제외 2개.
- 유형은 모두 확정 전: {'미확정 / 미확정': 15, 'DRT대상 / 예비': 3, '도보형 / 예비': 1}.
- 창곡동 법정동 기준: {'missing': 15, 'Y': 3, 'N': 1}. 행정동 위례동 내부 여부 19개 모두 missing.
- 위례자이더시티의 기존 좌표는 제공된 창곡동 경계 밖으로 판정됨. 단지 실제 위치에 대한 확정 판정이 아니며 좌표/경계 대조가 필요함.
- 위례포레샤인23단지 좌표 missing으로 12역 거리표를 만들지 않음. 문서의 2,200세대는 검증된 통합표에 추가하지 않음.
- travel_time_observed.csv 및 household_stats_todo.csv는 UTF-8 BOM 빈 입력 양식만 생성. 입력 실측/통계 0건.
- bus_routes_real.csv의 미확인 45칸. 기존 raw 배차표/노선 파일은 참고용으로 보존하며 최신 검증 자료로 승격하지 않음.

## 가상정류장 후보 (실제 선정 아님)

| 후보ID | 단지명 | 창곡동내부 | 위례동내부 | 좌표상태 | 선정가능 |
| --- | --- | --- | --- | --- | --- |
| D01 | 가상정류장 1 | N | missing | unverified | N |
| A10027692 | 위례더힐55 | Y | missing | unverified | N |
| A10027277 | 위례호반써밋에비뉴 | Y | missing | unverified | N |
| A10027595 | 위례센트럴푸르지오 | Y | missing | unverified | N |
| D02 | 가상정류장 2 | N | missing | unverified | N |
| A10023289 | 위례자이더시티 | N | missing | unverified | N |
| D03 | 가상정류장 3 | N | missing | unverified | N |
| D04 | 가상정류장 4 | N | missing | unverified | N |

4개 단지 후보와 기존 D01~D04 총 8개 검토 항목이다. 검증된 승하차 지점 8개가 아니다.
예비점수는 직선거리/700이며 세대수·300m 격자인구·사각지대 포함 여부는 검토 속성으로 제공.
격자 인구와 세대수는 수요 중복을 피하기 위해 합산하지 않음. 2024 인구이며 반경 중복 및 결측 0 처리에 주의.

## 정시성 결과 (합승 0명)

| 정류장 | 시간대 | 여유분 | 놓칠확률 | 평균대기분 | 기준대기분 |
| --- | --- | --- | --- | --- | --- |
| 가상정류장 1 | 출퇴근 | 0 | 100.00% | 9.604 | 5.0 |
| 가상정류장 1 | 출퇴근 | 3 | 0.00% | 2.604 | 5.0 |
| 가상정류장 1 | 출퇴근 | 5 | 0.00% | 4.604 | 5.0 |
| 가상정류장 1 | 평시 | 0 | 100.00% | 14.604 | 7.5 |
| 가상정류장 1 | 평시 | 3 | 0.00% | 2.604 | 7.5 |
| 가상정류장 1 | 평시 | 5 | 0.00% | 4.604 | 7.5 |
| 가상정류장 2 | 출퇴근 | 0 | 100.00% | 9.503 | 5.0 |
| 가상정류장 2 | 출퇴근 | 3 | 0.00% | 2.503 | 5.0 |
| 가상정류장 2 | 출퇴근 | 5 | 0.00% | 4.503 | 5.0 |
| 가상정류장 2 | 평시 | 0 | 100.00% | 14.503 | 7.5 |
| 가상정류장 2 | 평시 | 3 | 0.00% | 2.503 | 7.5 |
| 가상정류장 2 | 평시 | 5 | 0.00% | 4.503 | 7.5 |
| 가상정류장 3 | 출퇴근 | 0 | 100.00% | 9.601 | 5.0 |
| 가상정류장 3 | 출퇴근 | 3 | 0.00% | 2.601 | 5.0 |
| 가상정류장 3 | 출퇴근 | 5 | 0.00% | 4.601 | 5.0 |
| 가상정류장 3 | 평시 | 0 | 100.00% | 14.601 | 7.5 |
| 가상정류장 3 | 평시 | 3 | 0.00% | 2.601 | 7.5 |
| 가상정류장 3 | 평시 | 5 | 0.00% | 4.601 | 7.5 |
| 가상정류장 4 | 출퇴근 | 0 | 100.00% | 9.939 | 5.0 |
| 가상정류장 4 | 출퇴근 | 3 | 0.00% | 2.939 | 5.0 |
| 가상정류장 4 | 출퇴근 | 5 | 0.00% | 4.939 | 5.0 |
| 가상정류장 4 | 평시 | 0 | 100.00% | 14.939 | 7.5 |
| 가상정류장 4 | 평시 | 3 | 0.00% | 2.939 | 7.5 |
| 가상정류장 4 | 평시 | 5 | 0.00% | 4.939 | 7.5 |

전체 합승 0~2명 결과는 data/processed/punctuality_results.csv 참조.
k=1.0/1.2/1.5 가정이며 실측 0건. 0분 여유의 100%는 혼잡계수>1이면서 여유가 없는 설계의 결과이고 실제 서비스 예측이 아니다.
예정 픽업은 OSRM+정차+여유를 역산하며 합승 추가 지연은 별도로 적용한다. 도착과 실제 가상 트램 출발을 비교하고 여러 편을 놓치는 경우도 계산한다.
정시성 최근접역은 기준 GeoJSON 12역 중 선택한다. 기존 예약은 기존 환승거점 2개를 유지하므로 두 용도의 좌표가 다를 수 있다.

## OSRM 비교

그린파크푸르지오→기준 GeoJSON 위례역사공원: OSRM 2.075분, 답사 참고 약 6분.
좌표와 답사 원시 기록 unverified. 보정하지 않음. 같은 출발·도착·진행방향·측정 조건 확인 전 실측 보정에 사용하지 않는다.

## 문구 정정

- docs/관리용 웹사이트 구상:4 — 기존 2027년 예정 표현 정정.
- scripts/generate_tram_blindspot_map.py:496 — 기존 2026 개통 표현 정정.
- 텍스트 검색에서 12월 개통 표현 없음. 원본 바이너리 문서는 수정 대상에서 제외.
- 최신 확정 개통일의 공식 원문을 확보하지 못해 '개통 일정 확인 필요 · 가상 시간표 기준'으로 표기.

## 검증 로그

```text
WARN: LH위례31단지 coordinates missing
WARN: LH위례36단지 coordinates missing
WARN: e편한세상 테라스위례 coordinates missing
WARN: 래미안위례아파트 coordinates missing
WARN: 위례 LH 35단지 coordinates missing
WARN: 위례 래미안이편한세상 coordinates missing
WARN: 위례 아트리버 푸르지오 1단지 coordinates missing
WARN: 위례더힐55 coordinates unverified
WARN: 위례센트럴자이 coordinates missing
WARN: 위례센트럴푸르지오 coordinates unverified
WARN: 위례역 푸르지오 4단지 coordinates missing
WARN: 위례역푸르지오 4,6단지 아파트 coordinates missing
WARN: 위례역푸르지오 4,5,6단지 coordinates missing
WARN: 위례역푸르지오 6단지아파트 coordinates missing
WARN: 위례자이더시티 coordinates unverified
WARN: 위례자이아파트 coordinates missing
WARN: 위례포레스트사랑으로부영 coordinates missing
WARN: 위례호반써밋에비뉴 coordinates unverified
WARN: 힐스테이트위례 coordinates missing
WARN: apartment_master.csv duplicate addresses need review
WARN: LH위례31단지 coordinates missing
WARN: LH위례36단지 coordinates missing
WARN: e편한세상 테라스위례 coordinates missing
WARN: 래미안위례아파트 coordinates missing
WARN: 위례 LH 35단지 coordinates missing
WARN: 위례 래미안이편한세상 coordinates missing
WARN: 위례 아트리버 푸르지오 1단지 coordinates missing
WARN: 위례더힐55 coordinates unverified
WARN: 위례센트럴자이 coordinates missing
WARN: 위례센트럴푸르지오 coordinates unverified
WARN: 위례역 푸르지오 4단지 coordinates missing
WARN: 위례역푸르지오 4,6단지 아파트 coordinates missing
WARN: 위례역푸르지오 4,5,6단지 coordinates missing
WARN: 위례역푸르지오 6단지아파트 coordinates missing
WARN: 위례자이더시티 coordinates unverified
WARN: 위례자이아파트 coordinates missing
WARN: 위례포레스트사랑으로부영 coordinates missing
WARN: 위례호반써밋에비뉴 coordinates unverified
WARN: 힐스테이트위례 coordinates missing
WARN: apartment_classification.csv duplicate addresses need review
WARN: Tram coordinates unverified; legal Changgok boundary is not administrative Wirye boundary
WARN: Walking routes, verified bus alternatives, observed travel times and boarding-site checks missing
PASS=228 / WARN=42 / FAIL=0
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

- .gitignore
- README.md
- data/assumptions/household_stats_todo.csv
- data/assumptions/sim_params.json
- data/assumptions/tram_timetable.json
- data/assumptions/travel_time_observed.csv
- data/processed/apartment_classification.csv
- data/processed/apartment_master.csv
- data/processed/operating_cost_reference.csv
- data/processed/osrm_comparison.json
- data/processed/punctuality_results.csv
- data/processed/stops_with_admin.csv
- data/processed/virtual_stop_candidates_v2.csv
- docs/development_stage0_5_report.md
- docs/관리용 웹사이트 구상
- scripts/build_stage0.py
- scripts/final_checks.py
- scripts/generate_tram_blindspot_map.py
- scripts/refactor_simulation.py
- scripts/run_punctuality.py
- scripts/select_virtual_stops.py
- scripts/test_simulation.py
- scripts/update_project_docs.py
- scripts/validate_data.py
- scripts/write_development_report.py
- sewook31/app.py
- sewook31/data/osrm_cache.json
- sewook31/modules/analysis_views.py
- sewook31/modules/integrated_scheduler.py
- sewook31/modules/map_view.py
- sewook31/modules/operating_costs.py
- sewook31/modules/osrm_cache.py
- sewook31/modules/pickup_scheduler.py
- sewook31/modules/punctuality_sim.py
- sewook31/modules/reservation_manager.py
- sewook31/modules/route_engine.py
- sewook31/modules/settings.py
- sewook31/modules/shared_route.py
- sewook31/modules/spatial.py
- sewook31/modules/tram_scheduler.py

## 로컬 커밋 (보고서 생성 시점)

```text
de60a8f Add seeded punctuality simulation and fleet cost controls
bd886a6 Extract simulation settings and cache directional OSRM routes
b1c41b1 Build conservative apartment drafts and read-only validation
```

이 보고서 자체를 포함한 최종 문서 커밋은 git log로 확인 가능. .env/venv/data/raw/archive 및 실행 생성 pyc는 커밋하지 않음.
