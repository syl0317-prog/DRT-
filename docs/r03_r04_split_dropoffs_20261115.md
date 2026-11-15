# R03·R04 하차 지점 분리 및 R04 지도 표시 수정

> 후속 요청으로 R04 시각화 직선은 제거됐으며 현재는 전체 OSRM 도로 형상을 표시합니다. 하차 지점 분리는 유지합니다. 최신 결과는 [최종 지도·예약 점검 보고서](final_routes_booking_validation_20261115.md)를 확인하세요. 아래 직선 관련 내용은 이전 작업 기록입니다.

## 사용자 화면

- `노선 및 운영 관리 → 신규 정류장 위치 설정`에서 R03을 선택하면 `R03-S01`, `R03-S02`, `R03-BOKJEONG`을 선택한다.
- R04는 `R04-S01`, `R04-S02`, `R04-BOKJEONG`을 선택한다.
- 두 하차 지점의 표시 이름은 모두 **복정역**이다. 각각 지도 클릭으로 저장·수정한다.
- 한 노선의 하차 후보를 수정하면 해당 노선의 저장 OSRM 결과만 무효화한다. 반대 노선의 좌표와 OSRM 결과는 유지한다.
- 기존 공통 복정역 좌표는 양쪽의 초기 후보로 복사했다. 실제 위치가 같다는 검증 결과가 아니므로 운영자가 각 노선의 차량 접근 방향에 맞게 별도로 지정해야 한다.

## JSON 호환 및 실제 이관

`locations.json`을 version 1에서 2로 이관한다. 읽기 시에는 원본을 수정하지 않는 v2 투영을 지원하고, 위치 설정 화면을 열거나 저장 시 기존 잠금·revision·백업·원자적 교체 절차로 v2를 기록한다. `migrate_file()`을 여러 번 호출해도 이미 v2인 파일을 다시 쓰지 않는다.

- 기존 `BOKJEONG` 항목은 삭제하지 않고 읽기 전용 과거 후보로 남긴다. 신규 UI에서는 이 항목을 수정하지 않는다.
- 초기 후보 복사본은 `inherited_from: BOKJEONG`으로 구분한다. 개별 지도를 클릭해 저장하면 사용자 지정 후보로 갱신한다.
- 이미 존재하는 노선별 하차 좌표는 공통 좌표로 덮어쓰지 않는다.
- 기존 승차 좌표, 공통 좌표, 수정 시각, 추가 메타데이터와 두 노선의 전체 OSRM 형상·거리·시간을 보존한다.
- 기존 공통 목적지 예약은 원본 DB를 이관하거나 덮어쓰지 않는다. 과거 하차 기록임을 표시하고 조회·취소·배차 재검토가 가능하다. 신규 예약은 각 노선의 하차 ID를 사용하며 공통 ID나 반대 노선 하차 ID는 거절한다.

이 작업에서 실제 `data/derived/new_route_settings/locations.json`의 v1 revision 10을 v2로 이관했다. 기존 파일의 원본 바이트와 동일한 백업:

`data/derived/new_route_settings/backups/locations.02ba47ea97f3486f84a5064de2b91fdb.json`

이관 전후 기존 stop 항목 전체와 roads 객체의 동등성을 확인했다. 실제 저장 데이터의 두 OSRM 도로 모형이 계속 유효하며, R03은 도로선 1개, R04는 표시용 도로 뒷구간 1개와 시각화 직선 1개로 구성됨을 확인했다. 새 경로 조회나 임의 좌표 생성은 수행하지 않았다.

## R04 표시용 직선과 실제 OSRM 결과의 분리

- 기본 지도: S01→S02는 초록 직선으로 표시한다. 범례와 tooltip은 **시각화용 직선 · 실제 차량 운행 경로 아님**을 명시한다.
- S01→S02의 굽은 OSRM 앞구간은 기본 지도 표시에서 제외한다.
- S02→R04-BOKJEONG은 기존 전체 OSRM 형상에서 S02의 도로 투영 위치 이후 부분을 잘라 표시한다. 새 도로 경로를 생성하지 않는다. 정류장이 도로에서 떨어져 있을 수 있으므로 차량 접근 검증은 별도다.
- 원래 전체 경로는 `paths` 및 저장 JSON의 `roads`에 그대로 두고 `display_paths`/`visualization_paths`만 별도로 만든다. 거리·시간은 전체 OSRM 결과를 그대로 사용한다. 직선 길이를 거리나 이동시간으로 환산하지 않는다.
- 좌표만 있고 OSRM 결과가 없더라도 시각화 직선은 표시할 수 있다. 이때 도로 뒷구간과 거리·시간은 표시하지 않는다.
- 실제 도로 검증·운행편 등록·배차 확정 조건 및 정시성 계산 로직은 변경하지 않는다. 신규 노선의 차량 접근·정차 검증은 계속 필요하다.

지도 렌더링을 공통 helper로 연결해 대시보드, 예약 지도, 통합 노선 지도, 위치 설정 지도에서 같은 표시 방식을 사용한다. 표시/숨김 레이어는 도로선과 직선을 함께 제어한다. 데이터·시스템 및 운영 화면에는 공통 노선 계획을 통해 분리된 목적지와 좌표가 반영된다.

## 변경 파일

신규:

- `sewook31/modules/new_route_display.py`
- `sewook31/tests/test_split_dropoffs.py`
- `docs/r03_r04_split_dropoffs_20261115.md`

수정:

- `sewook31/modules/new_stop_settings.py`
- `sewook31/modules/new_routes.py`
- `sewook31/modules/new_stop_views.py`
- `sewook31/modules/fixed_routes.py`
- `sewook31/modules/unified_reservations.py`
- `sewook31/modules/reservation_audit.py`
- `sewook31/modules/combined_routes.py`
- `sewook31/modules/dashboard_ui.py`
- `sewook31/tests/test_new_routes.py`
- `sewook31/tests/test_new_stop_settings.py`
- `sewook31/tests/test_operations_ui.py`
- `sewook31/tests/test_integrated_runtime.py`
- `sewook31/tests/test_sequential_dispatch.py`
- `sewook31/tests/test_team_runtime.py`
- `docs/new_stop_location_editor_20261115.md`

테스트의 목적지·카탈로그 기대값을 갱신했다. 사용자에게 실제 저장 좌표가 있는 환경에서도 테스트가 원본을 읽거나 이관하지 않도록 임시 위치 설정으로 격리했다. 앱의 위치 설정 메뉴를 실제 app.py AppTest로 실행해 양쪽 노선의 세 지점, 지도 클릭 저장·수정 및 재실행 후 좌표를 확인한다.

## 검증 범위와 보호

최종 전체 실행: `.venv/Scripts/python.exe -B -m unittest discover -s sewook31/tests -v` — **55개 테스트 모두 통과**.

- v1→v2 데이터 보존, 원본 바이트 백업, 반복 이관, 혼합 설정의 기존 분리 좌표 보호.
- 양방향 독립 좌표 수정 및 상대 노선의 좌표·경로 유지.
- 새 Python 프로세스 및 새 Streamlit AppTest 세션에서 좌표 유지.
- R04의 정확히 두 점인 직선, 기존 OSRM S02 이후 구간만 지도에 표시, 전체 OSRM 형상·거리·시간 보존.
- 이전 공통 목적지 예약 조회·재검토·취소 및 신규 목적지 오입력 거절.
- R01/R02 예약·정원·동시 예약·순차 승차·충돌·취소 후 재배차 회귀 검증.
- Python 문법 검사와 `git diff --check` 통과. 원본 운영 입력 및 정시성 모듈 10개 파일의 작업 전후 SHA-256 일치.

브라우저 시각 조작은 이번 작업에서 수행하지 않았다. 실제 웹에서 두 노선의 복정역 선택이 분리되는지, R04의 직선·OSRM 뒷구간·범례가 보이는지 수동 확인할 수 있다. 서버가 이전 모듈을 계속 표시하면 동일 프로젝트의 `sewook31/app.py`로 한 번 재시작한다.

브랜치 `fix/integrated-drt-operations` 유지. 운영 SQLite/CSV와 정시성 계산 코드, stash는 변경하지 않았으며 commit/push/main 병합을 실행하지 않았다.
