# 통합 웹 실행 환경·데이터 점검

점검 기준: 2026-11-14, GitHub `main` 커밋 `aaef86f47d72b071faca82ffd23830d9692e832d`. GitHub에서 별도 복제한 사본에서 작업했습니다. 원본 `DRT_main_merge`, 기존 브랜치, 예약 CSV 및 SQLite는 수정하지 않았습니다. 커밋·푸시·병합·스테이징은 하지 않았습니다.

## 1. 이미 GitHub에 포함된 필수 데이터

| 항목 | GitHub main 파일 | 점검 결과 |
|---|---|---|
| R01 정류장·환승 거점 | `sewook31/data/drt_stops.csv` | D01~D04 4개, T01~T02 2개. R01은 고정 노선 파일이 아니라 선택 순서 미리보기 |
| 도로 경로 캐시 | `sewook31/data/osrm_cache.json` | 기본 R01 도로 경로 및 기존 정시성 계산에 사용. 새 방향·순서의 캐시 존재는 별도 조건 |
| 기존 예약·차량 배정 | `sewook31/data/reservations.csv` | 이미 추적됨. 초기화 대상 아님. 실제/가상 출처 확인 필요 |
| 정시성 결과·그래프 | `data/processed/punctuality_main_results.csv`, `punctuality_main_chart.png`, `punctuality_results.csv`, `punctuality_gits_results.csv` | 사전 계산 결과 포함. 웹 차트는 CSV로 렌더링하므로 PNG는 웹 시작 필수는 아님 |
| 정시성 입력 | `data/processed/congestion_by_hour.csv`, `data/assumptions/travel_time_observed.csv`, `data/processed/wirye_tram_official_stations.geojson` | 실측 입력은 검증 상태에 따라 가정값 대체 가능. 실제 운행 검증 완료를 의미하지 않음 |
| 운영 설정 | `data/assumptions/sim_params.json`, `tram_timetable.json`, `congestion_params.json`, `drt_cost_scenarios.json`, `demand_weight_params.json` | 차량·가상 시간표·혼잡·비용 설정 포함 |
| 시뮬레이션·도로 분석 | `data/processed/gits_route_travel_times.csv`, `gits_link_summary.csv`, `gits_time_profiles.csv`, `gits_data_quality.csv`, `drt_strategy_comparison.csv`, `drt_strategy_summary.csv` | 재수집 없이 기존 모형 계산·조회 가능 |
| 지도·도로망 | `data/vworld/wirye_road_links.geojson`, `data/processed/wirye_tram_official_lines.geojson`, `wirye_tram_official_stations.geojson`, `wirye_changgok_boundary.geojson`, `wirye_tram_buffer_700m.geojson`, `wirye_tram_blindspot_700m.geojson`, `wirye_vulnerable_apartments.geojson` | 로컬 형상 데이터 포함. OSM 배경 타일은 외부 네트워크 |

파일별 크기·SHA-256과 기준 main 포함 여부는 `docs/team_runtime_data_manifest.json`에 기록했습니다. `data/raw/`는 현재 ignore 규칙이 있어도 이미 추적된 일부 파일이 존재합니다. 새 실행을 위해 원본 GIS나 raw 데이터를 다시 수집할 필요는 없습니다.

**누락 확인:** GitHub main에는 두 SQLite가 모두 없었습니다. DB 없이 웹은 시작되지만 R02가 없어서 DRT 정류장은 4개만 표시되었습니다. R02와 V05~V08 좌표·도로 형상은 원본 로컬 SQLite에만 있었습니다.

## 2. GitHub에 추가해야 하는 파일

- `data/seeds/drt_routes.json`: 원본 DB를 읽기 전용으로 확인한 뒤 노선·정류장·구간만 추출. bookings는 빈 배열. R02 거리 약 1.3336km, 모형시간 2분, 비활성·차량 미배정 상태 유지.
- `scripts/init_team_runtime.py`: 표준 라이브러리만 사용하여 없는 SQLite만 생성. 기존 파일은 열지 않음. 재실행 시 바이트 보존. 실제 예약·취소 기록을 배포하지 않음.
- `.python-version`: 검증 Python 3.12 명시.
- `sewook31/tests/test_team_runtime.py`: 초기화·예약 보존·오프라인 분석 및 지도 데이터 회귀 검사.
- `docs/team_quickstart.md`, `docs/team_runtime_audit.md`, `docs/team_runtime_data_manifest.json`: 실행 안내·결과·데이터 목록.

이 파일들은 아직 GitHub에 반영되지 않았습니다. 제공한 변경 파일 묶음 또는 패치를 별도 검토한 뒤 반영해야 합니다.

## 3. GitHub에 올리면 안 되는 파일

- `.env`, 실제 API 키, 토큰, 개인정보, 새 실제 예약·취소·배차 내역 및 관련 내보내기 CSV/JSON.
- `data/derived/drt_routes/` 및 `data/derived/unified_reservations/`의 운영 SQLite 전체와 WAL/SHM/journal. routes.sqlite3도 bookings를 함께 저장할 수 있음.
- `.venv/`, `venv/`, `__pycache__/`, `*.pyc`, 로컬 로그 및 이번 테스트 산출 DB.

기존 `sewook31/data/reservations.csv`에는 예약 ID·시각·정류장·승객수·차량이 있습니다. 이름·전화번호 열은 없지만 실제 이동 기록일 수 있으므로 공개 적합성을 확인해야 합니다. 이번 작업은 이미 추적된 예약 CSV를 삭제하거나 변경하지 않았으며, 변경 파일 묶음에도 포함하지 않았습니다. `.gitignore`는 이미 추적된 파일을 제거하지 않습니다. 추적 중인 pyc도 기존 main에 존재하므로 새 산출물을 추가하지 않도록 주의합니다.

문자열 기반 키 점검에서 실제 키로 판단되는 항목은 확인하지 못했으나 전체 Git 이력·바이너리·문서의 개인정보 부재를 보증하는 검사는 아닙니다. 기본 웹은 API 키를 읽지 않습니다.

## 4. 수정한 실행 환경 및 설정 파일

| 파일 | 변경 |
|---|---|
| `requirements.txt` | 기존 고정 목록 유지, folium 0.20.0·streamlit-folium 0.27.4·python-dotenv 1.2.4 고정, 직접 사용하는 branca 0.8.2 및 지도 의존성 xyzservices 2026.9.1 명시 |
| `sewook31/requirements.txt` | 루트 requirements를 참조하여 설치 환경 통일 |
| `.python-version` | Python 3.12 |
| `.gitignore` | 두 로컬 DB 폴더 및 SQLite 부속 파일 제외 |
| `.env.example` | 기본 웹에서는 불필요하다는 설명만 추가. 실제 키 없음 |
| `README.md` | 초기화 포함 설치·실행 명령과 상세 안내 링크 |

`sewook31/app.py` 및 모든 애플리케이션 모듈은 변경하지 않았습니다. 루트 requirements의 기존 다른 서비스·분석용 의존성도 제거하지 않았습니다.

앱 전체 모듈 AST 검사에서 사용하는 외부 패키지는 `streamlit`, `streamlit-folium`, `folium`, `branca`, `altair`, `pandas`, `numpy`, `requests`, `networkx`, `pyproj`, `shapely`입니다. `sqlite3`는 Python 기본 제공입니다. Windows `zoneinfo`의 Asia/Seoul 시간대는 `tzdata`로 제공합니다. 관련 데이터 스크립트용 `Pillow`, `matplotlib`, `geopandas`, `python-dotenv`도 requirements에 포함됩니다. 일부 패키지의 메타데이터 최소 Python은 3.11이지만 실제 검증 조합은 Windows x64 / Python 3.12.0입니다. 다른 Python/OS는 미검증입니다.

## 5. 팀원이 실행할 명령어

프로젝트 루트에서:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/init_team_runtime.py
.\.venv\Scripts\python.exe -m streamlit run sewook31/app.py
```

초기화 결과가 `preserved`이면 기존 DB를 보존한 것입니다. 기존 DB가 초기 seed와 다르더라도 자동 덮어쓰지 않습니다.

## 6. 테스트 결과 및 남은 문제

새 GitHub 복제본 + 변경 파일 + 새 `.venv`에서 검증했습니다. 원본 DB 복사본을 실행 데이터로 사용하지 않고, 배포용 JSON seed에서 초기화했습니다.

| 검사 | 결과 |
|---|---|
| 새 환경 requirements 설치 / `pip check` | 성공 / 의존성 충돌 없음 |
| Streamlit 프로세스·HTTP | health 200 `ok`, 루트 HTTP 200 |
| 통합 회귀 테스트 | `unittest discover -s sewook31/tests -v` 9개 통과 |
| 6개 메뉴 및 하위 화면 | AppTest 예외 없음. 정시성 결과 화면 추가 검증 |
| R01·R02 지도 | 두 노선 레이어·도로 형상·색상 확인. R02 약 1.3336km/2분 유지 |
| DRT 8개 / 트램 2개 | 카탈로그 8/2. T01·T02 각각 선택해 총 10개 ID 확인 |
| 예약 생성·중복 방지·취소 | 임시 DB에서 R01/R02 생성, 동일 request_key 중복 방지, 정원·중첩·취소 후 좌석 해제 검증 |
| 정시성 분석 | 저장 CSV 차트, 직접 입력 시뮬레이션, 확률 범위·시드 재현성·여유시간 증가 효과 검증 |
| 운영 시뮬레이션 | `scripts/test_simulation.py` 8개 통과. 합승 화면·운영전략 계산·비용 배율 회귀 검증 |
| DB 보호 | 예약을 삽입한 테스트 DB 재초기화 후 해시 동일. 원본 두 SQLite SHA-256 동일 |

제한 사항:

- 통합 지도는 R01의 선택된 트램 거점 1개와 8개 DRT 지점으로 9개 마커를 표시합니다. 두 트램 거점 동시 표시는 기존 기능에 없으며 기능을 변경하지 않았습니다. 선택을 바꿔 T01/T02 모두 사용 가능합니다.
- AppTest와 생성된 Folium HTML/형상으로 검증했습니다. 실제 브라우저의 외부 CDN·배경 타일 로딩은 시각적으로 검증하지 않았습니다. 네트워크가 없으면 배경지도까지 동일하게 보장할 수 없습니다.
- 키 없는 기본 분석은 로컬 데이터만 사용합니다. 요청을 차단한 추가 테스트에서도 직접 입력 정시성·저장 차트·전략 비교가 네트워크 호출 없이 실행됩니다. 캐시 없는 도로 경로는 기존 기능대로 missing/미확인 처리합니다.
- R02 비활성·차량 미배정은 보존된 상태입니다. 자동 배차 보장이나 실측 운행 검증 완료를 의미하지 않습니다. 운영전략 C안 등 기존 missing 항목은 유지됩니다.
- 기존 예약 CSV의 실제/가상 여부 확인은 남아 있습니다. 실제 기록일 경우 별도 보관·공개 정책 검토 후 예약 없는 배포 방식으로 전환할 필요가 있습니다. 기존 데이터를 변경하지 말라는 요청에 따라 이번 작업에서는 변경하지 않았습니다.
