<<<<<<< Updated upstream
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
    selected = persistent_ui.radio("예약 업무", ["통합 예약", "기존 트램 연계 예약", "신규 독립 노선 예약"], horizontal=True, key="booking_section")
    if selected == "통합 예약":
        with scope("unified_reservations"):
            show_unified_reservations()
    elif selected == "기존 트램 연계 예약":
        from modules.operational_views import show_reservations
        with scope("legacy_reservations"):
            show_reservations()
    else:
        from modules.independent_route_views import show_new_route_reservations
        with scope("independent_reservations"):
            show_new_route_reservations()
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
    selected = persistent_ui.radio("정시·환승 분석 방식", ["개별 운행 분석", "기존 정시성 검증", "정시성 계산·검증 결과"],
                                   horizontal=True, key="punctuality_section")
    if selected == "개별 운행 분석":
        from modules.punctuality_views import show_punctuality_analysis
        with scope("punctuality"):
            show_punctuality_analysis()
    elif selected == "정시성 계산·검증 결과":
        from modules.punctuality_view import show_punctuality
        with scope("main_punctuality"):
            show_punctuality()
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
    selected = persistent_ui.radio("관리 업무", ["운영 설정", "실시간 관제", "기존 운행 지도", "도로 혼잡도 분석"], horizontal=True, key="admin_section")
    with scope("admin_" + selected):
        if selected == "운영 설정":
            from modules.detail_views import show_admin
            show_admin()
        elif selected == "실시간 관제":
            from modules.live_control import show_live_control
            show_live_control()
        elif selected == "기존 운행 지도":
            from modules.map_view import show_drt_map
            show_drt_map()
        else:
            from modules.detail_views import show_roads
            show_roads()
=======
from modules.map_view import show_drt_map
from modules.tram_scheduler import calculate_drt_schedule
import streamlit as st
from modules.pickup_scheduler import calculate_pickup_schedule
from pathlib import Path
import pandas as pd
from modules.reservation_manager import (
    load_reservations,
    get_vehicle_status,
    create_reservation,
    cancel_reservation
)
from modules.reservation_manager import (
    load_reservations,
    get_vehicle_status,
    create_reservation,
    cancel_reservation,
    calculate_reservation_pickup
)
from modules.shared_route import get_shared_route
from modules.live_control import show_live_control
from modules.access_priority_view import show_access_priority
from modules.punctuality_view import show_punctuality

from modules.integrated_scheduler import calculate_integrated_schedule
from modules.pickup_scheduler import calculate_pickup_schedule

st.set_page_config(
    page_title="위례형 DRT 운영 시스템",
    page_icon="🚌",
    layout="wide"
)

st.title("🚌 위례형 DRT 통합 운영 시스템")
st.caption("트램 환승 연계 기반 역산형 DRT 운영 시뮬레이션")

st.sidebar.title("운영 메뉴")

menu = st.sidebar.radio(
    "메뉴 선택",
    [
        "운영 대시보드",
        "DRT 운행 지도",
        "예약 관리",
        "트램 환승 관리",
        "운영 시뮬레이션",
        "이용객 유형 구분",
        "정시성 검증",
        "실시간 관제"
    ]
)

if menu == "운영 대시보드":
    st.header("운영 현황")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("운영 차량", "4대")
    col2.metric("운영 권역", "2개")
    col3.metric("예약 인원", "0명")
    col4.metric("환승 성공률", "미산출")

    st.info("DRT 운영 시뮬레이션 시스템 초기 화면입니다.")

elif menu == "DRT 운행 지도":
    st.header("🗺️ 위례동 DRT 운행 지도")

    st.write(
        "위례동의 트램 정거장과 "
        "DRT 운행 권역을 확인하는 지도입니다."
    )

    show_drt_map()

elif menu == "예약 관리":

    st.header("🚌 DRT 승객 예약 관리")

    st.write(
        "탑승 정류장과 환승 트램역을 선택하여 "
        "DRT 탑승을 예약할 수 있습니다."
    )

    stops_file = (
        Path(__file__).resolve().parent
        / "data"
        / "drt_stops.csv"
    )

    stops = pd.read_csv(
        stops_file,
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    drt_stops = stops[
        (stops["stop_type"] == "drt")
        & stops["latitude"].notna()
        & stops["longitude"].notna()
    ]

    tram_stops = stops[
        (stops["stop_type"] == "tram")
        & stops["latitude"].notna()
        & stops["longitude"].notna()
    ]

    stop_names = dict(
        zip(stops["stop_id"], stops["stop_name"])
    )

    if drt_stops.empty or tram_stops.empty:
        st.warning(
            "먼저 DRT 정류장과 트램 정거장의 "
            "좌표를 등록해 주세요."
        )

    else:

        st.subheader("신규 예약")

        boarding_stop = st.selectbox(
            "탑승 정류장",
            drt_stops["stop_id"].tolist(),
            format_func=lambda x: f"{x} - {stop_names[x]}"
        )

        tram_stop = st.selectbox(
            "환승 트램 정거장",
            tram_stops["stop_id"].tolist(),
            format_func=lambda x: f"{x} - {stop_names[x]}"
        )

        tram_time = st.time_input(
            "희망 트램 출발시간",
            key="reservation_tram_time"
        )

        passengers = st.number_input(
            "탑승 인원",
            min_value=1,
            max_value=8,
            value=1
        )

        tram_departure = tram_time.strftime("%H:%M")

        st.subheader("차량별 좌석 현황")

        vehicle_status = get_vehicle_status(
            tram_stop,
            tram_departure
        )

        st.dataframe(
            vehicle_status,
            use_container_width=True,
            hide_index=True
        )


        if st.button("예약하기"):

            try:
                with st.spinner("탑승 예정시간 계산 중..."):

                    pickup = calculate_reservation_pickup(
                        boarding_stop=boarding_stop,
                        tram_stop=tram_stop,
                        tram_departure=tram_departure,
                        transfer_buffer=5,
                        traffic_factor=1.2
                    )

                reservation, message = create_reservation(
                    boarding_stop=boarding_stop,
                    tram_stop=tram_stop,
                    tram_departure=tram_departure,
                    passengers=int(passengers)
                )

                if reservation:

                    st.success(message)

                    st.subheader("예약 및 탑승 안내")

                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "DRT 탑승 예정시간",
                        pickup["pickup_time"]
                    )

                    col2.metric(
                        "트램 정거장 도착",
                        pickup["drt_arrival"]
                    )

                    col3.metric(
                        "트램 출발시간",
                        pickup["tram_departure"]
                    )

                    st.info(
                        f"예약번호: {reservation['reservation_id']} / "
                        f"배정 차량: {reservation['vehicle_id']}"
                    )

                    st.write(
                        f"예상 이동거리: "
                        f"{pickup['distance_km']:.2f} km"
                    )

                    st.write(
                        f"예상 주행시간: "
                        f"{pickup['driving_minutes']:.1f}분"
                    )

                else:
                    st.error(message)

            except ValueError as e:
                st.error(str(e))
        st.divider()

        st.subheader("전체 예약 내역")

        reservations = load_reservations()

        if reservations.empty:
            st.info("등록된 예약이 없습니다.")

        else:
            st.dataframe(
                reservations,
                use_container_width=True,
                hide_index=True
            )

            active = reservations[
                reservations["status"] == "예약완료"
            ]

            if not active.empty:

                cancel_id = st.selectbox(
                    "취소할 예약번호",
                    active["reservation_id"].tolist()
                )

                if st.button("선택 예약 취소"):

                    if cancel_reservation(cancel_id):
                        st.success("예약이 취소되었습니다.")
                        st.rerun()
                    else:
                        st.error("예약 취소에 실패했습니다.")




elif menu == "트램 환승 관리":

    st.header("🚊 트램 연계 DRT 자동 배차")

    st.write(
        "도로 기반 운행시간을 계산하고, "
        "트램 출발시간에 맞춰 DRT 배차 및 "
        "정류장별 픽업시간을 산출합니다."
    )

    stops_file = (
        Path(__file__).resolve().parent
        / "data"
        / "drt_stops.csv"
    )

    stops = pd.read_csv(
        stops_file,
        dtype={"stop_id": str},
        encoding="utf-8-sig"
    )

    valid_stops = stops.dropna(
        subset=["latitude", "longitude"]
    )

    drt_stops = valid_stops[
        valid_stops["stop_type"] == "drt"
    ]

    tram_stops = valid_stops[
        valid_stops["stop_type"] == "tram"
    ]

    stop_names = dict(
        zip(stops["stop_id"], stops["stop_name"])
    )

    if drt_stops.empty or tram_stops.empty:
        st.warning(
            "DRT 정류장과 트램 정거장 좌표를 "
            "먼저 등록해 주세요."
        )

    else:

        
        st.subheader("DRT 정류장 방문 순서 설정")

        available_ids = drt_stops["stop_id"].tolist()

        stop_count = st.number_input(
            "경유할 정류장 수",
            min_value=1,
            max_value=len(available_ids),
            value=len(available_ids),
            step=1
        )

        route_stop_ids = []
        remaining_ids = available_ids.copy()

        for i in range(int(stop_count)):

            selected_id = st.selectbox(
                f"{i + 1}번째 방문 정류장",
                remaining_ids,
                format_func=lambda x: (
                    f"{x} - {stop_names[x]}"
                ),
                key=f"route_order_{i}"
            )

            route_stop_ids.append(selected_id)
            remaining_ids.remove(selected_id)

        st.write(
            "현재 방문 순서: "
            + " → ".join(route_stop_ids)
        )


        tram_stop_id = st.selectbox(
            "환승할 트램 정거장",
            tram_stops["stop_id"].tolist(),
            format_func=lambda x: f"{x} - {stop_names[x]}"
        )

        tram_time = st.time_input(
            "트램 출발시간"
        )

        transfer_buffer = st.number_input(
            "환승 여유시간 (분)",
            min_value=1,
            max_value=30,
            value=5
        )

        dwell_minutes = st.number_input(
            "정류장당 정차시간 (분)",
            min_value=0,
            max_value=10,
            value=1
        )

        traffic_factor = st.number_input(
            "교통 혼잡 보정계수",
            min_value=1.0,
            max_value=3.0,
            value=1.2,
            step=0.1
        )

        st.caption(
            "혼잡 보정계수와 정차시간은 "
            "시뮬레이션을 위한 가정값입니다."
        )

        if st.button("자동 배차 및 픽업시간 계산"):

            if not route_stop_ids:
                st.warning(
                    "DRT 경유 정류장을 하나 이상 선택해 주세요."
                )

            else:

                try:
                    with st.spinner("도로 경로 및 배차시간 계산 중..."):

                        result = calculate_integrated_schedule(
                            route_stop_ids=route_stop_ids,
                            tram_stop_id=tram_stop_id,
                            tram_departure=tram_time.strftime("%H:%M"),
                            transfer_buffer=transfer_buffer,
                            dwell_minutes=dwell_minutes,
                            traffic_factor=traffic_factor
                        )

                        pickup_result = calculate_pickup_schedule(
                            route_stop_ids=route_stop_ids,
                            tram_stop_id=tram_stop_id,
                            tram_departure=tram_time.strftime("%H:%M"),
                            transfer_buffer=transfer_buffer,
                            dwell_minutes=dwell_minutes,
                            traffic_factor=traffic_factor
                        )

                    st.success("자동 배차 계산 완료")

                    st.subheader("배차 계산 결과")

                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "DRT 출발시간",
                        pickup_result["drt_start"]
                    )

                    col2.metric(
                        "DRT 도착시간",
                        pickup_result["drt_arrival"]
                    )

                    col3.metric(
                        "트램 출발시간",
                        pickup_result["tram_departure"]
                    )

                    st.divider()

                    st.subheader("도로 기반 운행 분석")

                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "전체 운행거리",
                        f"{result['distance_km']:.2f} km"
                    )

                    col2.metric(
                        "기본 주행시간",
                        f"{result['base_duration']:.1f} 분"
                    )

                    col3.metric(
                        "보정 후 운행시간",
                        f"{pickup_result['total_duration']} 분"
                    )

                    st.divider()

                    st.subheader("🚌 정류장별 픽업 예정시간")

                    st.dataframe(
                        pickup_result["pickup_table"],
                        use_container_width=True,
                        hide_index=True
                    )

                    st.info(
                        f"DRT 출발: {pickup_result['drt_start']} / "
                        f"트램 정거장 도착: {pickup_result['drt_arrival']} / "
                        f"트램 출발: {pickup_result['tram_departure']}"
                    )

                    st.subheader("노선 방문 순서")

                    for i, stop_id in enumerate(
                        result["route_ids"], start=1
                    ):
                        st.write(
                            f"{i}. {stop_names[stop_id]}"
                        )

                except ValueError as e:
                    st.error(str(e))




elif menu == "운영 시뮬레이션":

    st.header("🚌 차량별 DRT 합승 노선 시뮬레이션")

    st.write(
        "예약 데이터를 기반으로 차량별 합승 노선을 "
        "구성하고 픽업 예정시간을 계산합니다."
    )

    reservations = load_reservations()

    active = reservations[
        reservations["status"] == "예약완료"
    ].copy()

    if active.empty:
        st.info(
            "예약된 승객이 없습니다. "
            "먼저 예약 관리 메뉴에서 예약을 생성해 주세요."
        )

    else:
        # 같은 차량·트램역·출발시간을 하나의 운행으로 묶기
        trips = active[
            ["vehicle_id", "tram_stop", "tram_departure"]
        ].drop_duplicates()

        trip_options = [
            tuple(row)
            for row in trips.itertuples(index=False, name=None)
        ]

        selected_trip = st.selectbox(
            "시뮬레이션할 차량 및 트램 출발편",
            trip_options,
            format_func=lambda x: (
                f"{x[0]} / {x[1]} / 트램 {x[2]}"
            )
        )

        vehicle_id, tram_stop, tram_departure = selected_trip

        transfer_buffer = st.number_input(
            "환승 여유시간 (분)",
            min_value=1,
            max_value=30,
            value=5,
            key="shared_transfer_buffer"
        )

        dwell_minutes = st.number_input(
            "정류장당 정차시간 (분)",
            min_value=0,
            max_value=10,
            value=1,
            key="shared_dwell_minutes"
        )

        traffic_factor = st.number_input(
            "교통 혼잡 보정계수",
            min_value=1.0,
            max_value=3.0,
            value=1.2,
            step=0.1,
            key="shared_traffic_factor"
        )

        if st.button("합승 노선 계산"):

            try:
                with st.spinner("합승 노선 계산 중..."):
                    result = get_shared_route(
                        vehicle_id=vehicle_id,
                        tram_stop=tram_stop,
                        tram_departure=tram_departure,
                        transfer_buffer=transfer_buffer,
                        dwell_minutes=dwell_minutes,
                        traffic_factor=traffic_factor
                    )

                st.success("합승 노선 계산 완료")

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "예약 건수",
                    result["reservation_count"]
                )

                col2.metric(
                    "탑승 인원",
                    f"{result['passenger_count']}명"
                )

                col3.metric(
                    "예상 운행시간",
                    f"{result['total_duration']}분"
                )

                st.divider()

                st.subheader("차량 운행 일정")

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "DRT 출발",
                    result["drt_start"]
                )

                col2.metric(
                    "트램역 도착",
                    result["drt_arrival"]
                )

                col3.metric(
                    "트램 출발",
                    result["tram_departure"]
                )

                st.subheader("정류장별 합승 픽업시간")

                st.dataframe(
                    result["pickup_table"],
                    use_container_width=True,
                    hide_index=True
                )

                st.caption(
                    "현재는 정류장 ID 순서로 방문하며, "
                    "도로 기반 예상 이동시간을 사용합니다."
                )

            except ValueError as e:
                st.error(str(e))


elif menu == "이용객 유형 구분":
    show_access_priority()

elif menu == "정시성 검증":
    show_punctuality()

elif menu == "실시간 관제":
    show_live_control()
>>>>>>> Stashed changes
