## 통합 웹 팀원 실행 (Python 3.12)

별도 데이터 수집이나 API 키 없이 실행하려면 [팀원 실행 안내](docs/team_quickstart.md)를 따르세요. 최초 실행 전 예약 없는 R02 초기 데이터를 생성합니다. 기존 SQLite는 보존합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/init_team_runtime.py
.\.venv\Scripts\python.exe -m streamlit run sewook31/app.py
```

[실행 환경·데이터 점검 결과](docs/team_runtime_audit.md)

---



# 위례신도시 대중교통 사각지대 분석 및 수요응답형 버스(DRT) 운영 최적화

본 프로젝트는 위례선 도시철도(트램) 개통 계획을 반영하여 대중교통 서비스 취약 구역을 진단하고, 이를 해소하기 위한 최적의 수요응답형 교통수단(DRT: Demand Responsive Transport) 경로 및 운영 모델을 구축하는 캡스톤디자인 연구 과제입니다.

---

## 📁 프로젝트 폴더 구조

```text
캡스톤DRT프로젝트/
├── sewook31/             # ★ 통합 Streamlit 웹 앱 (실행: streamlit run sewook31/app.py)
│   ├── app.py            #   메뉴 라우터
│   ├── modules/          #   정시성·예약·노선·GITS·관제 등 기능 모듈
│   ├── data/             #   정류장 CSV, OSRM 캐시, 예약 CSV
│   └── tests/            #   통합 테스트 (pytest sewook31/tests)
├── scripts/              # 데이터 수집·전처리·정시성 계산·검증 스크립트
│   └── diagnostics/      #   노선 분석 및 네트워크 진단
├── data/
│   ├── raw/              # 원천 데이터 (대부분 .gitignore 대상)
│   ├── processed/        # 전처리·분석 결과 (GeoJSON, CSV)
│   ├── assumptions/      # 시뮬레이션 가정값 (sim_params.json 등)
│   └── derived/          # 실행 중 생성되는 SQLite·검증 결과 (일부 .gitignore)
├── docs/                 # 보고서, 계획서, 팀원 실행 안내
├── archive/              # 로컬 보관용 (.gitignore 대상, 예전 drt_system 앱 등)
├── requirements.txt      # 패키지 의존성 (Python 3.12)
└── README.md
```

> 예전 앱 `drt_system/`과 일회성 점검 스크립트는 2026-11-15에 저장소에서 정리했습니다. git 기록(커밋 `db40f94` 이전)에서 복원할 수 있습니다.

---

## 개발 환경 설정

```bash
# 1. 가상환경 생성 (Python 3.12 권장)
py -3.12 -m venv .venv

# 2. 가상환경 활성화 (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 3. 필수 패키지 설치
pip install -r requirements.txt
```


## DRT 앱 실행 (프로젝트 루트 / PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
streamlit run sewook31/app.py
```

가상환경 미활성화 상태에서는 `.\.venv\Scripts\python.exe -m streamlit run sewook31/app.py`를 사용합니다.
Python 실행은 프로젝트 venv만 사용합니다. 파일은 UTF-8, CSV 저장은 utf-8-sig입니다.
패키지 설치: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

개통 일정 확인 필요. 앱은 출퇴근 10분/평시 15분 가상 시간표를 사용합니다.
2026-11-10 공식 자료 검색에서 최신 확정 개통일의 공식 원문을 확보하지 못하여 일정을 확정하지 않았습니다.

### 데이터와 검증

법정동 창곡동 경계만 사용하며 행정동 위례동 또는 위례신도시 전체와 동일시하지 않습니다.
아파트는 단지코드로 식별하고 정확한 이름 일치만 좌표 연결합니다. 좌표/트램 위치는 unverified입니다.
직선거리 700m는 예비 분류 기준이며 실제 보행 접근성과 버스 대안이 확인되기 전에는 확정 유형이 아닙니다.
검증된 DRT대상이 3개 미만이므로 신규 실제 정류장은 확정하지 않았습니다. 기존 D01~D04는 미검증 시뮬레이션 후보입니다.

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe scripts/build_stage0.py
.\.venv\Scripts\python.exe scripts/validate_data.py
.\.venv\Scripts\python.exe scripts/run_punctuality.py --network
.\.venv\Scripts\python.exe scripts/test_simulation.py
```

`refactor_simulation.py`와 `update_project_docs.py`는 최초 마이그레이션용이며 반복 실행하지 않습니다.
`data/assumptions/sim_params.json`의 각 항목은 value/status/source를 가집니다.
stops_file의 value는 sewook31/data 내부 CSV 파일명입니다. 기존 파일은 drt_stops.csv입니다.
vehicle_count 기본 4대는 기존 코드 기준입니다. 2구역×1대 계획과 차이가 있어 팀 결정이 필요합니다.
왼쪽 차량 슬라이더는 현재 세션의 배차·비용에 함께 적용되며 파일 기본값은 바꾸지 않습니다.

OSRM은 방향과 전체 경유 좌표가 같은 경로의 캐시를 먼저 사용합니다. 캐시와 네트워크 결과가 모두 없으면 missing입니다.
OSRM 시간은 자동차 경로 모델값이며 실측값이 아닙니다. 인터넷 없이도 앱이 열리며 캐시 없는 경로만 계산 불가입니다.
정시성 화면의 온라인 조회는 기본 꺼져 있습니다. OSRM 조회 후 CSV를 저장하려면 결과 저장 버튼을 누릅니다.

정시성은 조건별 10,000회, 고정 난수 시드로 수행합니다. 목표 트램 출발=0,
예정 픽업=−(OSRM시간+정차시간+여유시간), 실제 도착=예정 픽업+OSRM시간×k+정차시간+합승수×우회시간입니다.
도착≤0이면 목표편을 타고, 도착>0이면 ceil(도착/배차간격)의 다음 출발편을 탑니다. 여러 편을 놓치는 경우도 반영합니다.
혼잡 및 합승 우회를 예정 픽업에 미리 보정하지 않는 민감도 비교입니다. 이 계산에는 역내 이동시간이 없어 현장 검증이 필요합니다.
비교 기준은 무작위 도착의 평균 대기 H/2입니다. 같은 시드로 여유시간별 공통 난수를 사용합니다.

실측 입력 양식은 data/assumptions/travel_time_observed.csv입니다.
실측소요분/OSRM소요분이 양수이고 검증상태=verified, 출처가 있는 최소 3건을 사용합니다.
k는 비율 최소·최빈·최대입니다. 유일한 표본최빈값이 없으면 삼각분포 적률식 `3×평균−최소−최대`를 범위 내로 제한해 최빈값을 추정합니다. 미달 시 1.0/1.2/1.5 가정입니다.
비교용 약 6분 답사 참고값은 검증된 실측 입력으로 자동 전환하지 않습니다.

운영비 low/base는 보험료 미반영 팀 가정, high는 다른 지역 지자체 예산 참고값입니다.
대당 하루 43~72명은 타 지역 사례이며 위례 수요 예측이 아닙니다. 연 365일 및 연비용/12 월 환산은 가정입니다.
요금 차감값은 환승할인·실제 수입이 반영되지 않은 참고치입니다.
