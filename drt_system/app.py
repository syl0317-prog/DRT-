"""Six-menu presentation router. Operational algorithms stay in their modules."""
import streamlit as st
from modules.settings import setting
from modules.session_ui import persistent_ui, scope

MENUS = ["통합 대시보드", "예약 관리", "배차·경로", "정시·환승 분석", "운영 시뮬레이션", "관리·설정"]

st.set_page_config(page_title="위례 DRT 통합 운영", page_icon="🚌", layout="wide")
st.markdown("""<style>
.stApp {background:#f7f9fc;}
[data-testid="stMetric"] {background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;}
[data-testid="stSidebar"] {background:#edf2f8;}
.block-container {padding-top:2rem;padding-bottom:3rem;}
</style>""", unsafe_allow_html=True)
st.title("위례 DRT 통합 운영 시스템")
st.caption("저장된 예약·경로 운영 도구와 연구용 시뮬레이션을 한곳에서 확인합니다.")
with st.sidebar:
    st.title("운영 메뉴")
    menu = persistent_ui.radio("메뉴 선택", MENUS, key="main_menu")
    persistent_ui.slider("차량 수", 1, 6, int(setting("vehicle_count")), key="vehicle_count")
    st.caption("현재 세션 설정 · 실제 운행 차량 수가 아닙니다.")

if menu == "통합 대시보드":
    from modules.dashboard_views import show_dashboard
    show_dashboard()
elif menu == "예약 관리":
    from modules.unified_reservation_views import show_unified_reservations
    with scope("unified_reservations"):
        show_unified_reservations()
elif menu == "배차·경로":
    selected = persistent_ui.radio("배차·경로 작업", ["지도·노선 설정", "배차·픽업 계산", "신규 독립 노선"],
                                   horizontal=True, key="route_section")
    if selected == "지도·노선 설정":
        from modules.route_views import show_drt_map
        with scope("route_map"):
            show_drt_map()
    elif selected == "배차·픽업 계산":
        from modules.operational_views import show_dispatch
        with scope("dispatch"):
            show_dispatch()
    else:
        from modules.independent_route_views import show_route_management
        with scope("new_route_management"):
            show_route_management()
elif menu == "정시·환승 분석":
    selected = persistent_ui.radio("정시·환승 분석 방식", ["개별 운행 분석", "기존 정시성 검증"],
                                   horizontal=True, key="punctuality_section")
    if selected == "개별 운행 분석":
        from modules.punctuality_views import show_punctuality_analysis
        with scope("punctuality"):
            show_punctuality_analysis()
    else:
        from modules.detail_views import show_punctuality
        with scope("legacy_punctuality"):
            show_punctuality()
elif menu == "운영 시뮬레이션":
    st.caption("연구·가정 기반 계산이며 실제 운행 결과가 아닙니다.")
    selected = persistent_ui.radio("운영 시뮬레이션 방식", ["예약 기반 합승", "운영전략 비교"],
                                   horizontal=True, key="simulation_section")
    if selected == "예약 기반 합승":
        from modules.unified_reservation_views import show_simulation_compatibility
        show_simulation_compatibility()
        from modules.operational_views import show_shared
        with scope("shared"):
            show_shared()
    else:
        from modules.detail_views import show_strategies
        with scope("strategies"):
            show_strategies()
else:
    from modules.detail_views import show_admin
    with scope("admin"):
        show_admin()
