# origin/main 병합 충돌 해결

작업 브랜치: `integration/main-merge`. 병합 커밋과 푸시는 수행하지 않았다.

## 충돌 9개 비교 및 선택

| 파일 | 양쪽 차이와 해결 |
| --- | --- |
| `sewook31/app.py` | HEAD의 98행 통합 라우터와 main의 624행 기존 앱이 충돌. HEAD의 6개 메뉴 및 모듈 연결을 유지. main의 예약·정시성 화면은 이미 해당 모듈로 통합되어 있음. |
| `sewook31/modules/live_control.py` | 관제 알고리즘은 동일하며 마지막 안내문만 다름. HEAD의 가상 시간표 안내 유지. |
| `sewook31/modules/punctuality_view.py` | HEAD의 상태 보존 위젯, 구간 필터, 다운로드, 파일 수정시간 기반 캐시 갱신 유지. main 모델 결과를 별도 CSV로 연결. |
| `scripts/punctuality_calc.py` | HEAD의 별도 출력 경로, 정류장별 평균 그래프, 트램 배차 간격의 정확한 배수 지연 시 대기 0분 처리 유지. main의 계산 모델 자체는 이미 포함됨. |
| `scripts/reproduce_reservation_duplicate.py` | main의 단순 행 수 출력 대신 HEAD의 임시 데이터 및 클릭/재실행 검증 유지. 함수 내부 import도 오프라인 경로 대체값을 사용하도록 테스트 보완. |
| `scripts/test_punctuality_tab.py` | main의 독립 메뉴 접근 대신 HEAD의 통합 메뉴 접근, 6개 메뉴·구간 필터·다운로드 검증 유지. |
| `data/processed/punctuality_results.csv` | HEAD의 기존 모델 264행·8열 유지. main의 구간유형·혼잡수준 포함 모델 1,584행·10열은 `punctuality_main_results.csv`로 보존. |
| `scripts/generate_tram_blindspot_map.py` | 범례 문구만 다름. HEAD의 개통 일정 확인 필요·가상 시간표 안내 유지. |
| `docs/관리용 웹사이트 구상` | 배경의 개통 일정 안내만 다름. HEAD의 시점에 종속되지 않는 안내 유지. |

main에서 추가된 PNG는 계산기의 출력 경로와 일치하도록 `punctuality_main_chart.png`로 보존했다. 서로 다른 계산 모델의 CSV를 합치거나 기존 모델 결과를 덮어쓰지 않았다.

## 런타임 데이터 보존

새 worktree에는 R02 노선 및 통합 예약 SQLite가 없었다. 원본 feature worktree의 `data/derived/drt_routes/routes.sqlite3`와 `data/derived/unified_reservations/reservations.sqlite3`를 현재 worktree에 바이트 그대로 복사했다. 원본은 읽기만 했으며 복사본도 초기화하지 않았다. 두 DB는 로컬 런타임 데이터로 남기고 스테이징하지 않았다.

원본 DB 2개, 복사본 DB 2개, 현재 worktree의 기존 예약 CSV 2개의 SHA-256이 테스트 전후 동일함을 확인했다. R01·R02 및 정류장 구성 파일은 변경하지 않았다.

## 검증

- `python -m unittest discover -s sewook31/tests -v`: 6개 통과. 6개 메뉴와 하위 화면, R01/R02 지도, DRT 8개·트램 2개, 예약·취소·정원·독립 노선, 정시성 계산 검증 포함.
- `python -m unittest discover -s scripts -p test_simulation.py -v`: 8개 통과.
- `python scripts/reproduce_reservation_duplicate.py`: 클릭 1회에 1건 생성, 재실행 시 추가 생성 없음.
- `python scripts/test_punctuality_tab.py`: 그래프 2개, 구간 필터, 다운로드 통과.
- `sewook31` 및 `scripts`의 모든 Python 파일 구문 검사 통과.
- 실제 Streamlit 서버에서 `sewook31/app.py` 기동: health `ok`, HTTP 200. 확인용 서버는 종료함. 화면 실행은 위 AppTest로 별도 검증.

통합 테스트의 기존 예약 수 고정 조건(6건)은 현재 원본 데이터(5건)에 의존하므로, 기존 예약이 존재하고 테스트 전후 내용이 그대로 유지되는지 검증하도록 보완했다. 운영 데이터를 테스트에 맞춰 변경하지 않았다.

외부 실시간 API 연결이나 실운행 결과는 이번 오프라인 회귀 검증의 범위에 포함하지 않는다.
