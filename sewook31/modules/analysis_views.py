"""Analysis views keep missing routes and assumptions visible."""
import altair as alt
import pandas as pd
import streamlit as st
from modules.settings import setting
from modules.punctuality_sim import calibrate, generate, save_results
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
        st.altair_chart(alt.layer(probability, alt.layer(waits, benchmark)).resolve_scale(y='independent'), use_container_width=True)
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
