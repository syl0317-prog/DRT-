# 팀원 실행 안내

Windows 64비트 Python 3.12에서 검증합니다. 현재 고정 패키지에는 Python 3.11 이상 요구 항목이 있으므로 3.10 이하는 사용할 수 없습니다. 3.11 및 3.13 이상은 이번 실행 검증 대상이 아닙니다.

프로젝트 루트에서 PowerShell로 실행합니다. 가상환경 활성화나 실행 정책 변경은 필요 없습니다.

```powershell
git clone --branch main --single-branch https://github.com/syl0317-prog/DRT-.git
cd DRT-
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/init_team_runtime.py
.\.venv\Scripts\python.exe -m streamlit run sewook31/app.py
```

브라우저에서 http://localhost:8501 을 엽니다. 위 명령은 이 변경 파일들이 main에 반영된 이후 기준입니다. 별도 데이터 수집·GIS 재생성·API 키 입력은 필요 없습니다. 기존 복제본은 루트로 이동하여 설치·초기화·실행 단계만 진행합니다.

macOS/Linux에서는 `python3.12 -m venv .venv` 이후 위 명령의 Python 경로를 `.venv/bin/python`으로 바꿉니다. 해당 OS의 실제 실행은 이번에 검증하지 않았습니다.

## 초기 데이터와 기존 데이터 보호

- `data/seeds/drt_routes.json`은 R02 노선 1개, V05~V08 정류장 4개, 도로 구간 3개만 포함합니다. 예약은 없습니다. 기존 로컬 등록부의 공개 가능한 노선 설정만 분리했습니다.
- R01은 기존 `drt_stops.csv`와 OSRM 캐시를 사용합니다. 기존 D01~D04와 V05~V08을 합쳐 DRT 정류장 8개, T01~T02 트램 거점 2개입니다.
- 초기화는 없는 SQLite만 생성합니다. 이미 있는 파일은 손상 여부와 무관하게 보존합니다. 자동 병합·복구·초기화·예약 삭제는 하지 않습니다. 기존 DB에 R02가 없으면 자동 보충하지 않으므로 먼저 별도 백업 후 수동 점검해야 합니다.
- R02는 기존 상태대로 비활성·차량 미배정입니다. 지도는 표시되며 신규 예약은 배차 검토 필요 상태가 될 수 있습니다. 자동 배차를 위해 임의의 차량을 넣거나 노선을 활성화하지 않습니다.
- 통합 예약 SQLite는 첫 예약 시에도 자동 생성될 수 있지만, R02를 같은 상태로 보려면 초기화 단계가 필요합니다.
- `sewook31/data/reservations.csv`는 이미 main에서 추적되는 기존 예약입니다. 초기화 스크립트는 읽거나 수정하지 않습니다. 개인정보 열은 없지만 실제/가상 출처는 코드만으로 확인할 수 없습니다. 실제 이용 기록이면 공개 적합성 확인이 필요합니다. 새 예약 자료를 이 파일에 포함하여 업로드하지 마세요.

## 네트워크와 환경 변수

기본 웹은 `.env`를 읽거나 API 키를 요구하지 않습니다. `.env.example`은 데이터 재수집용 예시이며 복사할 필요가 없습니다. 공공데이터 수집 스크립트는 `PUBLIC_DATA_SERVICE_KEY` 또는 `DATA_GO_KR_API_KEY`를 사용하고, 별도 주소 수집 도구에는 Kakao 키가 필요할 수 있습니다. GITS 키도 예시로만 두며 기본 웹의 저장 결과 조회에는 사용하지 않습니다.

패키지 최초 설치는 PyPI 접속이 필요합니다. 저장된 CSV·GeoJSON·OSRM 캐시로 기본 계산이 가능합니다. 새 경유 순서·역방향 등 캐시 없는 경로는 오프라인 계산이 불가하고 기존 경고 또는 임시 연결선이 표시됩니다. 온라인 OSRM 조회는 키 없이 외부 서버를 사용하며 가용성을 보장하지 않습니다.

Folium 지도 JavaScript/CSS와 OpenStreetMap 배경 타일은 브라우저가 외부 CDN/타일 서버에서 받습니다. 인터넷이 완전히 끊긴 환경에서 배경지도까지 보장하지 않습니다. 저장된 도로망·정류장 데이터의 존재와 배경 타일 다운로드는 별개입니다.

## 검증 명령

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s sewook31/tests -v
.\.venv\Scripts\python.exe scripts/test_simulation.py
```

초기화 후 실행합니다. 테스트는 임시 예약 저장소를 사용합니다. 전체 점검 내역은 `docs/team_runtime_audit.md`를 참고하세요.
