"""Five-menu operating workspace; research tools retain their own scopes."""
import streamlit as st
from modules.settings import setting
from modules.session_ui import persistent_ui, scope

MENUS = ['통합 대시보드', '예약 및 배차 관리', '노선 및 운영 관리', '시뮬레이션 및 정시성 분석', '데이터 및 시스템 관리']
st.set_page_config(page_title='위례 DRT 통합 운영', page_icon='🚐', layout='wide')
st.markdown('''<style>
.stApp {background:#f7f9fc;}
[data-testid="stMetric"] {background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;}
[data-testid="stSidebar"] {background:#edf2f8;}
.block-container {padding-top:1rem;padding-bottom:1.5rem;max-width:1600px;}
h1 {font-size:1.9rem;margin-bottom:.2rem;}
</style>''', unsafe_allow_html=True)
st.title('위례 DRT 통합 운영 시스템')
st.caption('R01 → 위례별역 · R02 → 위례역사공원역')
with st.sidebar:
    st.title('운영 메뉴')
    # Old saved navigation values must not leave the radio without a valid choice.
    if st.session_state.get('main_menu') not in MENUS:
        st.session_state['main_menu'] = MENUS[0]
        st.session_state.setdefault('ui_saved_values', {})['main_menu'] = MENUS[0]
    menu = persistent_ui.radio('메뉴 선택', MENUS, key='main_menu')
    with st.expander('연구용 설정'):
        persistent_ui.slider('연구용 차량 수', 1, 6, int(setting('vehicle_count')), key='vehicle_count')
        st.caption('시뮬레이션 전용 · 실제 차량 수와 별개')

if menu == MENUS[0]:
    from modules.dashboard_views import show_dashboard
    show_dashboard()
elif menu == MENUS[1]:
    from modules.unified_reservation_views import show_booking_form, show_reservation_list, show_simulation_compatibility
    from modules.combined_routes import show_combined_map
    left, right = st.columns([1, 1.2],gap='medium')
    with left, scope('unified_reservations'):
        show_booking_form()
    with right, scope('booking_map'):
        show_combined_map(height=430,compact=True)
    from modules.fixed_dispatch_views import show_dispatch_board
    listing,dispatch = st.columns([1.25,1],gap='medium')
    with listing,scope('unified_reservations'):
        show_reservation_list()
    with dispatch,scope('fixed_dispatch_board'):
        show_dispatch_board(compact=True)
    with st.expander('기존 CSV·연구용 계산 도구'):
        compatibility,legacy=st.tabs(['시뮬레이션 적용 범위','기존 픽업 계산'])
        with compatibility:
            show_simulation_compatibility()
        with legacy:
            from modules.operational_views import show_dispatch
            with scope('dispatch'):
                show_dispatch()
elif menu == MENUS[2]:
    operation_options=['통합 노선 지도', '차량·운행편 등록', '운영 설정', '연구·관제 도구']
    saved_operation=st.session_state.get('operations_section',st.session_state.get('ui_saved_values',{}).get('operations_section'))
    if saved_operation is not None and saved_operation not in operation_options:
        st.session_state.pop('operations_section',None)
        st.session_state.setdefault('ui_saved_values',{}).pop('operations_section',None)
        st.caption('연구 등록부는 데이터 및 시스템 관리에서 확인하세요.')
    selected = persistent_ui.radio('노선 운영 업무', operation_options, horizontal=True, key='operations_section')
    with scope('operations_' + selected):
        if selected == '통합 노선 지도':
            from modules.combined_routes import show_combined_map
            show_combined_map()
        elif selected == '차량·운행편 등록':
            from modules.fixed_dispatch_views import show_fixed_operations
            show_fixed_operations()
        elif selected == '운영 설정':
            from modules.detail_views import show_admin
            show_admin()
        else:
            st.info('연구·시뮬레이션 전용 · 실제 차량 및 운영 배차와 구분됩니다.')
            tool=persistent_ui.radio('연구 도구',['기존 경유지 비교','관제 모형'],horizontal=True,key='research_tool')
            if tool=='기존 경유지 비교':
                from modules.route_views import show_legacy_route_settings
                show_legacy_route_settings()
            else:
                from modules.live_control import show_live_control
                show_live_control()
elif menu == MENUS[3]:
    selected = persistent_ui.radio('분석 도구', ['개별 운행 분석', '기존 정시성 검증', '정시성 계산·검증 결과', '예약 기반 합승', '운영전략 비교'], horizontal=True, key='analysis_section')
    st.caption('가정과 저장 자료에 근거한 연구 결과이며 실제 운행 실적이 아닙니다.')
    with scope('analysis_' + selected):
        if selected == '개별 운행 분석':
            from modules.punctuality_views import show_punctuality_analysis
            show_punctuality_analysis()
        elif selected == '기존 정시성 검증':
            from modules.detail_views import show_punctuality
            show_punctuality()
        elif selected == '정시성 계산·검증 결과':
            from modules.punctuality_view import show_punctuality
            show_punctuality()
        elif selected == '예약 기반 합승':
            from modules.unified_reservation_views import show_simulation_compatibility
            from modules.operational_views import show_shared
            show_simulation_compatibility(); show_shared()
        else:
            from modules.detail_views import show_strategies
            show_strategies()
else:
    from modules.system_views import show_system
    show_system()
    with st.expander('도로 혼잡도 및 GITS 상세 분석'):
        from modules.detail_views import show_roads
        with scope('system_roads'):
            show_roads()
