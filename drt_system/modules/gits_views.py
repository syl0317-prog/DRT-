from modules.timetable_periods import load_periods
"""Additional Streamlit views, isolated from existing operational pages."""
import json
import pandas as pd
import streamlit as st
from modules.settings import PROJECT_DIR
from modules.strategy_sim import compare

def load(name):
    return pd.read_csv(PROJECT_DIR/'data/processed'/name, encoding='utf-8-sig', keep_default_na=False)

def show_roads():
    st.header('도로 혼잡도 분석')
    st.caption('분석 기준일 2026-11-10 · 엑셀 관측시각 missing · CSV 2026-11-10 00:37 수집')
    st.warning('상대적 저속 구분입니다. 제한속도·평시 기준속도가 없으며, 시간대별 링크 자료와 도로 도형이 부족합니다.')
    f = load('gits_link_summary.csv')
    source = st.selectbox('교통자료 출처', f.source.unique())
    f = f[f.source == source]
    st.dataframe(f.astype(str), hide_index=True)
    st.bar_chart(f.set_index('link_id')[['mean_speed_kmh']])
    st.caption('동일 출처 속도 Q25 이하: 상대적 저속 / 중앙값 이상: 상대적 원활. 도로 등급 차이를 통제하지 않은 탐색 지표입니다.')
    st.dataframe(load('gits_data_quality.csv'), hide_index=True)

def show_strategies():
    st.header('운영전략 비교')
    st.warning('A/B는 차량이 픽업 지점에서 즉시 이용 가능한 단일 운행 가정 실험입니다. 전체 차량 배차 구현은 missing이며 차량 수 효과를 검증하지 않습니다. C안은 구현 보류입니다.')
    timetable = load_periods()
    period = st.selectbox('시간대', list(timetable))
    strategies = st.multiselect('전략', ['A','B','C'], default=['A','B','C'])
    buffer = st.slider('환승 여유시간(분)', 0, 15, 5)
    shared = st.slider('추가 합승 승객 수', 0, 7, 0)
    vehicles = st.session_state.get('vehicle_count', 4)
    st.caption(f'차량 수 {vehicles}: 전체 배차 자료 부족으로 성능 반영 보류. 합승은 기존 1인당 우회시간 가정입니다. 교차로 지연 missing.')
    routes = load('gits_route_travel_times.csv')
    route = st.selectbox('캐시 경로(정류장 명칭 대응 미검증)', routes.route_id)
    f = compare(routes[routes.route_id == route], period, timetable[period]['headway_minutes'], buffer, shared, vehicles)
    f = f[f.strategy.isin(strategies)]
    st.caption('OSRM + 기존 삼각분포 k=(1,1.2,1.5), 동일 시드·10,000회. 실제 GITS 반영률 0%. 시간대 선택은 가상 트램 배차만 변경합니다.')
    st.dataframe(f.astype(str), hide_index=True)
    for label, col in [('환승 실패율','failure_rate'), ('평균 호출 대기시간','call_wait_min'), ('평균 환승 대기시간','transfer_wait_min'), ('95백분위 전체 이동시간','p95_total_time_min')]:
        st.write(label)
        plot = f[['strategy', col]].copy()
        plot[col] = pd.to_numeric(plot[col], errors='coerce')
        if plot[col].notna().any():
            st.bar_chart(plot.set_index('strategy').dropna())
        else:
            st.info('missing')
    st.info('GITS 매칭·예측이 없어 C/B 효과 비교 및 GITS 미반영/반영 차이는 missing입니다. 실제 수요·차고지·공차 경로가 없어 호출 거절률·처리량·전체 운행거리도 missing입니다.')
