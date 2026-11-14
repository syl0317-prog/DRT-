# 위례 DRT 통합 복원 결과

최종 실행 파일: `sewook31/app.py`. 현재 브랜치: `feature/drt-simulation`. Git 커밋·푸시는 수행하지 않았다.

## 보존과 복구 출처

- 작업 전 파일·CSV·SQLite 백업: `backups\integration_20261114_010309`. 시작 시 Git 변경 목록도 함께 저장했다.
- `git reset`, `git clean`, 강제 푸시, DB 초기화, 기존 예약 삭제를 수행하지 않았다.
- 두 폴더의 기본 정류장 CSV는 내용이 동일한 6행이었다. CSV를 덮어쓰지 않았다.
- 현재 노선 DB는 R02 초안만 남고 정류장·구간·예약이 0개였다. Git의 병합 전 보관 커밋 `ee68dcc680861bc0ffb5e2254435410773f13718`의 DB에는 V05~V08 4개와 OSRM 3개 구간이 있었다. 초기 CSV 내보내기는 더 이른 빈 초안이므로 복구 근거로 사용하지 않았다.
- 기존 DB에서 R02 객체와 예약 배열을 유지하면서 정류장·구간·방문 순서·계산 결과만 병합했고 revision은 1→2로 증가했다. 원본의 비활성·차량 없음·환승 거점 미지정 상태는 유지했다. 원본 DB와 체크섬은 백업 및 복구 manifest에 남겼다.
- `sewook31` 예약 CSV에는 5건, `drt_system`에는 6건이 있었다. 공통 5건의 모든 필드가 동일함을 확인하고 누락된 실제 예약 `DA75DCD589` 1건만 추가 복원했다. 총 6건을 유지한다.

## 메뉴와 기능

메인 메뉴는 정확히 통합 대시보드 / 예약 관리 / 배차·경로 / 정시·환승 분석 / 운영 시뮬레이션 / 관리·설정의 6개다.

- 예약 관리: 통합 예약, 기존 트램 연계 예약, 신규 독립 노선 예약.
- 배차·경로: 지도·노선 설정, 배차·픽업 계산, 신규 독립 노선.
- 정시·환승 분석: 개별 운행 분석, 기존 정시성 검증.
- 운영 시뮬레이션: 예약 기반 합승, 운영전략 비교.
- 관리·설정: 운영 설정, 실시간 관제, 기존 운행 지도, 도로 혼잡도 분석.
- 기존 대시보드의 GITS 상세 분석·후보 지도도 유지한다.
- 시간표 JSON의 service 구조와 과거 시간대별 구조를 읽는 호환 처리를 추가해 기존 정시성/전략 분석의 TypeError를 수정했다. 시간표 원본은 변경하지 않았다.

## 노선 및 정류장

| 구분 | 실제 저장 상태 | 지도 |
|---|---|---|
| R01 | 기존 D01~D04 및 T01/T02 CSV 기능에 부여한 화면 식별자. 과거 고정 노선 등록 데이터는 발견하지 못함 | 기본 선택 D01→D02→D03→D04→T01의 기존 OSRM 캐시 1.760km, 약 4.993분; 파란색 |
| R02 | V05→V06→V07→V08, 비활성, 차량 없음, 트램 거점 연결 없음 | 복구된 OSRM 3구간 1.3336km, 2.0분; 빨간색 |

R01의 선택 순서는 기존 기능대로 세션 미리보기다. 저장된 고정 사업 노선으로 표시하지 않는다. 지도 체크 선택과 레이어 제어로 두 노선을 각각 숨길 수 있다. 실제 도로 경로가 없을 때는 점선에 임시 연결선 표시를 하고 거리·시간을 미확인으로 남긴다. R02가 비활성이어도 복구된 경로는 지도에서 볼 수 있다.

| ID | 원본 이름 | 위도 | 경도 |
|---|---|---|---|
| V05 | V05 | 37.47327006828548 | 127.15424363783058 |
| V06 | V06 | 37.46998746740596 | 127.15186721982725 |
| V07 | V07 | 37.47005560133381 | 127.14862708064307 |
| V08 | V08 | 37.47104337872609 | 127.14269398900343 |

예약 기본 목록은 D01~D04 + V05~V08의 **DRT 정류장 8개**다. T01/T02는 별도의 트램 환승 거점 2개이며 선택 옵션을 켜면 하차 목록이 10개가 된다. 원래 기억한 추가 2개라는 가정과 달리 Git에 남은 구현은 DRT 4+4개였다. 새 이름이나 좌표는 만들지 않았다.

## 데이터 저장 역할

| 저장소 | 역할 |
|---|---|
| `sewook31/data/drt_stops.csv` | R01 기본 DRT 정류장 4개 및 공통 트램 거점 2개의 원본. 통합 지도·예약·신규 노선 관리가 같은 loader로 읽음 |
| `data/derived/drt_routes/routes.sqlite3` | R02 정류장·방문 순서·환승 연결·전용 차량·활성 여부·OSRM 구간·기존 독립 예약의 트랜잭션 저장소 |
| `data/derived/unified_reservations/reservations.sqlite3` | 신규 날짜 기반 통합 예약, 중복 방지 요청 키, 원본 CSV를 보존하는 취소 overlay |
| `sewook31/data/reservations.csv` | 기존 날짜 미기록 예약 6건 및 기존 팀원 예약 기능. 통합 화면에서 함께 조회하며 원본 형식 유지 |
| `drt_system/data/` 및 `sewook31/modules_backup/` | 이전 구현/원본 참조. 최종 실행 앱은 이 폴더를 별도 운영 저장소로 사용하지 않음 |

R02 데이터는 CSV에 복제하지 않는다. 예약 catalog는 기본 CSV와 R02 등록부를 합쳐 읽는다. 기존 예약은 원래 CSV, R02 예약은 등록부, 신규 요청은 통합 DB에서 원본 출처를 구분해 중복 없이 조회한다.

## 검증

- 기존 `drt_system/tests` 89개 통과. 처음 실패한 기존 시간표 구조 호환 오류를 수정한 뒤 전체 통과.
- 최종 앱 통합 테스트 4개 통과: 실제 복구 데이터·레이어/색상/임시선, 노선 선택·생성·취소·원본 보존, 임시 DB의 R02 배차/정원/시간 충돌/취소 좌석 반환, 최종 앱의 6개 메뉴와 모든 하위 화면·정류장 8개·R01/R02 UI 생성/취소·노선 필터.
- R02 배차 테스트의 차량은 임시 DB에만 만든 `R02-TEST`이다. 운영 DB에 테스트 차량·예약을 넣지 않았다.
- Python 109개 파일 문법 검사 통과 (최종 앱/모듈/백업/테스트 및 이전 앱 모듈).
- Streamlit 서버 `http://127.0.0.1:8521`, `/` 및 `/_stcore/health` HTTP 200.
- 브라우저 도구가 `The browser access host is unavailable`로 실패해 실제 브라우저 화면·배경 타일·팝업·레이어 클릭의 시각적 검증은 미완료. Streamlit AppTest로 위젯 상호작용과 화면 실행, Folium 생성 HTML의 레이어·경로·마커를 검증했다.
- 통합 예약 DB는 백업과 SQL dump 비교로 스키마·행 동일성을 확인했다. SQLite 백업 API로 생성한 백업은 헤더 카운터 때문에 파일 해시가 다를 수 있다.
- 최종 운영 DB: R02 정류장 4, 구간 3, 기존 독립 예약 0. 통합 DB requests 0, csv_cancellations 0; 테스트가 운영 예약을 남기지 않음.

## 남은 설정과 한계

- R02 전용 차량·환승 거점은 원본에서도 없었다. 신규 독립 노선 화면에서 사용자가 지정하고 필요하면 OSRM 재계산 후 활성화해야 자동 운행편 배정이 가능하다. 환승 거점은 선택 사항이다.
- 현재 R02의 신규 신청은 비활성 상태이므로 **배차 검토 필요**로 저장된다. 활성화된 임시 복사 DB에서는 예약완료·정원·시간 충돌을 검증했다.
- R01 날짜 기반 신규 요청도 **배차 검토 필요**로 저장한다. 날짜 없는 기존 차량 예약과 자동 병합하면 중복 운행 위험이 있어 기존 자동 배차와 날짜 기반 요청을 섞지 않는다. 기존 트램 연계 예약/합승 알고리즘은 별도 메뉴에서 계속 사용한다.
- 이용 노선과 다른 정류장 조합, R02 역방향 방문은 서버에서 거절한다. R01/R02 차량을 자동 공유하지 않는다. 임시 테스트에서 같은 차량의 운행 시간 충돌과 정원 초과를 확인했다.
- 복구된 V05~V08은 원본의 연구용 후보이며 OSRM 거리·시간도 실측값이 아니다. 외부 OSRM 재조회는 이번 검증에서 하지 않았다.

## 수정·추가 파일

- `sewook31/app.py`
- `sewook31/modules/combined_routes.py`
- `sewook31/modules/detail_views.py`
- `sewook31/modules/gits_views.py`
- `sewook31/modules/independent_routes.py`
- `sewook31/modules/independent_route_views.py`
- `sewook31/modules/punctuality_sim.py`
- `sewook31/modules/route_views.py`
- `sewook31/modules/settings.py`
- `sewook31/modules/timetable_periods.py`
- `sewook31/modules/unified_reservations.py`
- `sewook31/modules/unified_reservation_views.py`
- `sewook31/data/reservations.csv`
- `drt_system/modules/detail_views.py`
- `drt_system/modules/gits_views.py`
- `drt_system/modules/punctuality_sim.py`
- `drt_system/modules/timetable_periods.py`
- `data/derived/drt_routes/routes.sqlite3`
- `sewook31/tests/test_integrated_runtime.py`
- `docs/integration_restore_report.md`
- `docs/integration_recovery_manifest.json`

## 실행

```powershell
.\venv\Scripts\python.exe -m streamlit run sewook31/app.py
```

테스트:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s sewook31/tests -p "test_*.py" -v
.\venv\Scripts\python.exe -B -m unittest discover -s drt_system/tests -p "test_*.py" -q
```
