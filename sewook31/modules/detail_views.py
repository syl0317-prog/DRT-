from modules.timetable_periods import load_periods
# Legacy presentation screens, retained together; original modules remain untouched.
"""Analysis views keep missing routes and assumptions visible."""
import altair as alt
import pandas as pd
from modules.session_ui import persistent_ui as st
from modules.settings import setting
from modules.punctuality_sim import calibrate, generate as original_generate, save_results
from modules.operating_costs import cost_table

def show_punctuality():
    st.header('정시성 검증')
    k, n, status, source = calibrate()
    st.caption(source)
    cols = st.columns(3)
    limits = [cols[i].slider(label, 0.1, max(5.0, float(k[2])), float(k[i]), .05, key='k_'+str(i)) for i, label in enumerate(('혼잡계수 최소', '혼잡계수 최빈', '혼잡계수 최대'))]
    if not limits[0] <= limits[1] <= limits[2]:
        st.error('최소 ≤ 최빈 ≤ 최대를 만족해야 합니다.')
        return
    st.caption('예정 픽업=트램 출발−(OSRM+정차+여유). 합승 우회는 추가 지연으로 비교합니다. 정시성 분석은 기준 GeoJSON 12개 중 직선 최근접역을 사용합니다. 기존 예약의 환승거점 2개와 별도입니다.')
    frame = generate(limits, allow_network=st.checkbox('캐시 없는 경로 OSRM 조회', value=False))
    if frame.empty:
        st.warning('정류장 missing')
        return
    stop = st.selectbox('정류장', frame['정류장'].unique())
    period = st.selectbox('시간대', frame['시간대'].unique())
    shared = st.selectbox('합승 승객 수', [0, 1, 2])
    selected = frame[(frame['정류장'] == stop) & (frame['시간대'] == period) & (frame['합승수'] == shared)].copy()
    valid = selected[pd.to_numeric(selected['놓칠확률'], errors='coerce').notna()].copy()
    if valid.empty:
        st.warning('계산 불가: OSRM missing. 캐시가 없으면 인터넷 없이 이동시간을 생성하지 않습니다.')
    else:
        valid['놓칠확률'] = pd.to_numeric(valid['놓칠확률'])
        valid['평균대기분'] = pd.to_numeric(valid['평균대기분'])
        base = alt.Chart(valid).encode(x=alt.X('여유분:Q', title='여유시간 (분)'))
        probability = base.mark_line(color='#dc2626', point=True).encode(y=alt.Y('놓칠확률:Q', scale=alt.Scale(domain=[0, 1]), title='놓칠 확률'))
        waits = base.mark_line(color='#2563eb', point=True).encode(y=alt.Y('평균대기분:Q', title='대기시간 (분)'))
        benchmark = base.mark_line(color='#64748b', strokeDash=[6, 4]).encode(y='기준대기분:Q')
        st.altair_chart(alt.layer(probability, alt.layer(waits, benchmark)).resolve_scale(y='independent'), width="stretch")
        st.caption('빨강: 놓칠 확률 / 파랑: 평균 대기 / 회색 점선: 무작위 도착 H/2')
    st.dataframe(selected, hide_index=True)
    if st.button('현재 전체 조건 결과 CSV 저장'):
        save_results(frame)
        st.success('data/processed/punctuality_results.csv 저장')
    st.caption(f'실측 {n}건 반영' if status == 'sourced' else '가정 기반 시뮬레이션이며 실측 입력 후 재계산됨')

def show_admin():
    st.header('관리자 패널')
    st.caption('차량 수는 왼쪽 1~6대 슬라이더를 사용합니다. 기본값 4대는 기존 코드 기준이며, 2구역×1대 계획과 다릅니다. 변경은 현재 세션에 적용됩니다.')
    from modules.reservation_manager import load_reservations
    reservations = load_reservations()
    active_ids = set(reservations.loc[reservations['status'] == '예약완료', 'vehicle_id'])
    available_ids = {f'V{i:02d}' for i in range(1, st.session_state.get('vehicle_count', setting('vehicle_count'))+1)}
    if active_ids - available_ids:
        st.warning('차량 수 축소로 현재 범위 밖의 기존 예약 차량이 있습니다. 예약은 보존되며 자동 재배정되지 않습니다.')
    st.dataframe(cost_table(st.session_state.get('vehicle_count', setting('vehicle_count'))), hide_index=True)
    st.caption('대당 하루 43~72명은 타 지역 사례 참고값입니다. 위례 실수요가 아닙니다. high는 지자체 예산 참고값으로 low/base 원가와 산정 범위가 다릅니다.')
    st.info('개통 일정 확인 필요. 이 시스템은 가상 시간표 기준으로 설계되었습니다.')

"""Additional Streamlit views, isolated from existing operational pages."""
import json
import pandas as pd
from modules.session_ui import persistent_ui as st
from modules.settings import PROJECT_DIR
from modules.strategy_sim import compare as original_compare

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


# UI result retention: original algorithms are called only for new visible conditions.
from modules.session_ui import matching_result, remember_result
from modules.settings import PROJECT_DIR
import hashlib


def input_versions():
    names = [PROJECT_DIR/'data/assumptions/sim_params.json',
             PROJECT_DIR/'data/assumptions/tram_timetable.json',
             PROJECT_DIR/'data/assumptions/travel_time_observed.csv',
             PROJECT_DIR/'data/processed/wirye_tram_official_stations.geojson',
             PROJECT_DIR/'drt_system/data/osrm_cache.json']
    from modules.settings import stops_path
    names.append(stops_path())
    return {str(p.relative_to(PROJECT_DIR)): hashlib.sha256(p.read_bytes()).hexdigest() for p in names if p.exists()}


def generate(k, allow_network=False):
    inputs = dict(k=k, allow_network=allow_network, sources=input_versions())
    saved = matching_result('legacy_punctuality_execution', inputs)
    if saved:
        return saved['value'].copy()
    value = original_generate(k, allow_network=allow_network)
    # Network may have added derived cache entries: identify the actual source snapshot.
    inputs['sources'] = input_versions()
    remember_result('legacy_punctuality_execution', inputs, value, 'Existing triangular-factor model; virtual timetable; not measured')
    return value


def compare(routes, period, headway, buffer, shared, vehicles):
    inputs = dict(routes=routes.to_dict('records'), period=period, headway=headway,
                  buffer=buffer, shared=shared, vehicles=vehicles, sources=input_versions())
    saved = matching_result('strategy_execution', inputs)
    if saved:
        return saved['value'].copy()
    value = original_compare(routes, period, headway, buffer, shared, vehicles)
    remember_result('strategy_execution', inputs, value, 'Existing isolated-trip strategy model; GITS 0%; not measured')
    return value
