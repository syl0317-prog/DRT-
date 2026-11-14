# main 기능 통합 결과

- 작업 브랜치: `feature/drt-simulation`. 검토 대상: `d516ee5..ee7927d` (`origin/main`).
- 커밋·푸시·브랜치 이동·DB 초기화를 수행하지 않았다. main 전체 병합 대신 기능별로 통합했다.
- 백업: `backups/main_integration_20261114_220144/`. 소스·데이터 286개, SHA-256 manifest, HEAD, 작업 상태, staged/unstaged binary diff 보관. 기존의 미추적 예약·노선 DB와 수동 백업도 포함한다. 가상환경과 캐시는 백업 대상에서 제외했다.
- 기존 데이터 파일 97개를 백업 manifest와 비교했으며 변경된 파일은 0개다. 기존 로컬 예약 CSV, 노선 및 통합 예약 SQLite DB, OSRM 캐시, 이전 분석 결과를 보존했다.

## 통합 내용

기존 6개 메뉴를 유지하고 `정시·환승 분석 → 정시성 계산·검증 결과`에 main의 `punctuality_view.py`를 연결했다. 구간 유형·시간대·정류장·합승수·혼잡 수준·여유시간별 놓침 확률과 대기시간 그래프 2개, 전체 결과 CSV 다운로드를 제공한다. CSV 갱신 시 캐시를 새로 읽는다.

기존 `punctuality_results.csv`는 형식과 용도가 달라 유지했다. main 분석의 출력은 `punctuality_main_results.csv`와 `punctuality_main_chart.png`로 분리했다. `venv/Scripts/python.exe scripts/punctuality_calc.py`로 재계산 가능하다. 계산은 로컬 OSRM 캐시만 사용한다. PNG는 정류장별 선을 이어 붙이는 대신 여유시간별 평균을 그리도록 수정했고, 정확히 다음 트램 시각에 도착할 때의 대기시간을 0으로 처리했다.

main의 예약 중복 수정은 `sewook31/app.py` 예약 버튼 블록 뒤의 중복 `create_reservation()` 호출 제거다. feature에서는 해당 화면이 `operational_views.py`로 분리됐고 이미 단일 호출이므로 운영 코드의 추가 삭제는 필요하지 않았다. 임시 CSV에서 한 번 클릭 시 1건, rerun 시 추가 0건을 검증했다. 통합 예약의 같은 요청 키 재시도도 동일 ID·단일 저장임을 R01/R02 모두 검증했다.

main의 `live_control.py` 변경은 안내 한 줄이며 운행 로직 변경은 없었다. 기존 운행 로직을 유지하면서 가상 시간표 기반이라는 안내를 반영했다. docs와 사각지대 지도 생성기의 개통 문구 변경은 현재 통합 웹 기능과 무관하며 상대 날짜 표현을 포함하므로 그대로 복사하지 않았다.

## 수정·추가 파일

수정:
- `sewook31/app.py`
- `sewook31/modules/live_control.py`
- `sewook31/tests/test_integrated_runtime.py`
- `scripts/test_simulation.py`
- `scripts/validate_live_control_app.py`

추가:
- `sewook31/modules/punctuality_view.py`
- `sewook31/tests/test_main_punctuality.py`
- `scripts/punctuality_calc.py`
- `scripts/reproduce_reservation_duplicate.py`
- `scripts/test_punctuality_tab.py`
- `data/processed/punctuality_main_results.csv`
- `data/processed/punctuality_main_chart.png`
- 이 보고서

작업 전부터 존재하던 데이터·pyc 변경과 미추적 파일은 사용자 변경으로 구분하며 삭제하지 않았다.

## 검증

- `python -m unittest discover -s sewook31/tests -v`: 6개 통과. 6개 메뉴, 전체 하위 화면, R01·R02 동시 지도, DRT 8개·트램 2개, 예약·취소·정원·중복 키·기존 데이터 보존, 새 계산의 재현성·확률 범위·단조성·PNG 출력 검증.
- `python -m unittest discover -s drt_system/tests -v`: 89개 통과.
- `python scripts/test_simulation.py`: 8개 통과. 이전 메뉴명을 현재 6개 메뉴로 수정 후 재실행했다. 문법 검사는 임시 디렉터리에 pyc를 생성하도록 변경했다.
- `python scripts/test_punctuality_tab.py`: 통과. 새 메뉴 진입·두 구간 유형·그래프 2개·다운로드 검증.
- `python scripts/reproduce_reservation_duplicate.py`: 통과. 실제 데이터 대신 임시 CSV와 DB 사용, 외부 경로 조회는 fixture로 대체.
- `python scripts/validate_live_control_app.py`: 통과. 프리셋 시각·슬라이더 유지·표·자동 재생 검증.
- 새 계산 스크립트 실제 실행 완료. 모든 시나리오에서 여유시간 증가 시 놓침 확률 비증가 확인.
- 실제 `streamlit run sewook31/app.py` 서버 시작 및 `/_stcore/health` 응답 `ok` 확인. 검증용 서버는 종료했다. AppTest에서 화면 코드 실행 예외 없음.
- 변경한 tracked 소스의 `git diff --check` 통과. 전체 검사에는 작업 전 예약 CSV의 기존 공백이 나타나며 해당 데이터는 수정하지 않았다.

로그와 데이터 보존 검사: `backups/`. PowerShell이 stderr 경고를 NativeCommandError로 기록한 실행도 있어 각 로그의 unittest 최종 결과를 확인했다. 새 화면·예약 중복 검사는 subprocess 반환 코드 0을 별도로 확인했다.

## 남은 제약

새 main 분석은 기존 CSV 정류장과 캐시 경로 기반의 연구용 시뮬레이션이며, 신규 R02 실측 검증은 포함하지 않는다. 캐시에 없는 경로는 계산에서 제외된다. 기존 관제의 주말·혼잡 데이터 가정 경고 및 Streamlit `use_container_width` 폐기 예정 경고는 남아 있다. 이번 범위의 기능·테스트 실패는 없다.
