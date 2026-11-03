# 🚌 위례신도시 대중교통 사각지대 분석 및 수요응답형 버스(DRT) 운영 최적화

본 프로젝트는 위례선 도시철도(트램) 개통 계획을 반영하여 대중교통 서비스 취약 구역을 진단하고, 이를 해소하기 위한 최적의 수요응답형 교통수단(DRT: Demand Responsive Transport) 경로 및 운영 모델을 구축하는 캡스톤디자인 연구 과제입니다.

---

## 📁 프로젝트 폴더 구조

```text
캡스톤DRT프로젝트/
├── archive/              # 로컬 보관용 대용량 원본 아카이브 (.gitignore 대상)
│   └── data.zip
├── data/
│   ├── raw/              # 원천 데이터 (공공데이터, 공간 SHP 등, .gitignore 대상)
│   │   ├── LSMD_ADM_SECT_UMD_경기/
│   │   ├── LSMD_ADM_SECT_UMD_서울/
│   │   ├── [2026-09-14]NODELINKDATA/
│   │   ├── _census_reqdoc_1791098813447/
│   │   ├── _grid_border_grid_2025_grid_다사_grid_다사 (1)/
│   │   ├── 소상공인시장진흥공단_상가(상권)정보_20260630/
│   │   ├── 국토교통부_전국 버스정류장 위치정보_20251031 (1).csv
│   │   ├── 위례_호반써밋_버스정류소.xlsx
│   │   └── 위례 정류장 데이터/
│   ├── processed/        # 분석 및 시각화용 전처리 데이터 (GeoJSON)
│   │   ├── wirye_changgok_boundary.geojson
│   │   ├── wirye_tram_official_stations.geojson
│   │   ├── wirye_tram_official_lines.geojson
│   │   ├── wirye_tram_buffer_700m.geojson
│   │   ├── wirye_tram_blindspot_700m.geojson
│   │   └── wirye_vulnerable_apartments.geojson
│   └── README.md         # 데이터 명세 및 출처 가이드
├── docs/                 # 프로젝트 보고서, 계획서 및 분석 문서
│   ├── 캡스톤디자인 계획서(이시원, 장세욱, 신유림).hwpx
│   ├── 대시보드_500m_실행안내.md
│   ├── 네트워크_진단_한국어요약.txt
│   └── 진단결과_한국어요약.txt
├── scripts/              # 데이터 수집, 가공 및 GIS 전처리 스크립트
│   ├── apartment_coordinates.py       # 아파트 주소-좌표 변환
│   ├── bus_data.py                    # 수정구 버스 노선/정류장 데이터 수집
│   ├── build_official_tram_gis.py     # 위례 트램 공식 노선/정거장 GeoJSON 생성
│   ├── generate_tram_blindspot_map.py # 사각지대 분석 버퍼 및 시각화 생성
│   ├── read_tram_docs.py              # 트램 관련 보고서 추출 유틸리티
│   ├── wirye_bus_stations.py          # 버스정류소 데이터 추출
│   ├── wirye_bus_stops.py             # 500m 반경 버스정류소 접근성 분석
│   └── diagnostics/                   # 노선 분석 및 네트워크 진단 스크립트
│       ├── diagnose_api_network_10013.py
│       ├── diagnose_tram_105_106.py
│       ├── wirye_integrated_analysis.py
│       ├── wirye_route_analysis.py
│       └── wirye_route_excel.py
├── web/                  # 신규 웹 애플리케이션 개발 공간 (빈 폴더 준비 완료)
├── requirements.txt      # 프로젝트 파이썬 패키지 의존성
├── .gitignore            # Git 버전 관리 제외 규칙
└── README.md             # 프로젝트 개요 및 구조 안내 (본 파일)
```

---

## 🛠️ 개발 환경 설정

```bash
# 1. 가상환경 생성 (Python 3.11+ 권장)
python -m venv venv

# 2. 가상환경 활성화 (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# 3. 필수 패키지 설치
pip install -r requirements.txt
```
