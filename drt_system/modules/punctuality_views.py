"""Independent Streamlit research dashboard; never changes reservations or dispatch."""
from dataclasses import asdict
from datetime import datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

import altair as alt
import numpy as np
import pandas as pd
from modules.session_ui import persistent_ui as st, matching_result, remember_result
from modules.punctuality_inputs import load_stops, resolve_duration
from modules.punctuality_simulation import DelayModel, evaluate_timing, simulate

KST = ZoneInfo("Asia/Seoul")
SCENARIOS = ["A — 기본 운행", "B — 일반 혼잡", "C — 심한 혼잡"]


def show_punctuality_analysis():
    st.header("정시성 및 트램 환승 분석")
    st.warning("연구용 시뮬레이션 · 실제 운행 측정 결과가 아닙니다. 예약·배차·경로 비용에 반영하지 않습니다.")
    st.caption("확률은 입력한 지연 분포와 혼잡 시나리오에 조건부입니다. GITS는 검증 완료 링크가 없어 계산에 사용하지 않습니다.")
    try:
        stops = load_stops()
    except (OSError, ValueError) as error:
        st.error(f"정류장 데이터 로딩 실패: {error}")
        return
    if len(stops) < 2:
        st.error("출발·도착 선택에 필요한 정류장이 부족합니다.")
        return
    records = stops.set_index("stop_id")
    departures = stops.loc[stops.stop_type == "drt", "stop_id"].tolist() or stops.stop_id.tolist()
    destinations = stops.stop_id.tolist()
    default_destination = next((i for i, key in enumerate(destinations) if records.loc[key, "stop_type"] == "tram"), 0)
    label = lambda key: f"{records.loc[key, 'stop_name']} ({key})"
    left, right = st.columns(2)
    with left:
        origin = st.selectbox("DRT 출발 정류장", departures, format_func=label, key="pa_origin")
    with right:
        destination = st.selectbox("DRT 도착 정류장", destinations, index=default_destination, format_func=label, key="pa_destination")
    st.caption("정류장: 기존 drt_stops.csv · 후보 좌표의 현장 검증은 별도 필요. 날짜와 익일 여부를 직접 지정합니다.")
    if records.loc[destination, "stop_type"] != "tram":
        st.info("도착지가 트램 정류장이 아닙니다. 입력 보행시간에 실제 환승 거점까지의 이동을 포함하세요.")

    cols = st.columns(3)
    with cols[0]:
        day = st.date_input("DRT 출발 날짜 (한국시간)", datetime.now(KST).date(), key="pa_day")
        start_clock = st.time_input("DRT 출발시간", time(8), key="pa_start")
    with cols[1]:
        target_offset = st.number_input("목표 도착 날짜: 출발일 이후 일수", 0, 7, 0, key="pa_target_day")
        target_clock = st.time_input("목표 도착시간", time(8, 25), key="pa_target")
    with cols[2]:
        tram_offset = st.number_input("트램 출발 날짜: 출발일 이후 일수", 0, 7, 0, key="pa_tram_day")
        tram_clock = st.time_input("가상 트램 출발시간", time(8, 30), key="pa_tram")
    st.caption("현재 실제 운행 시간표는 연결되어 있지 않습니다. 트램 시각은 사용자가 지정한 가상 시간표입니다.")

    mode_label = st.radio("기준 이동시간 출처", ["OSRM 캐시/온라인 조회", "직접 입력"], key="pa_mode", horizontal=True)
    online = st.checkbox("캐시가 없으면 OSRM 온라인 조회 허용", value=False, key="pa_online", disabled=mode_label == "직접 입력")
    manual = st.number_input("수동 기준 이동시간 (분)", min_value=.1, max_value=1440., value=15., key="pa_manual")
    st.caption("OSRM은 실시간 혼잡·정차·합승을 보장하지 않는 경로 모형입니다. 조회 실패 시 직접 입력을 선택하세요. 기존 캐시는 읽기만 합니다.")
    cols = st.columns(4)
    with cols[0]:
        walk = st.number_input("환승 보행시간 (분)", 0., 120., 3., key="pa_walk")
    with cols[1]:
        buffer = st.number_input("추가 환승 여유시간 (분)", 0., 120., 2., key="pa_buffer")
    with cols[2]:
        tolerance = st.number_input("정시 허용 오차 (분)", 0., 120., 0., key="pa_tolerance")
    with cols[3]:
        single_delay = st.number_input("단일 계산 추가 지연 / 고정분포 지연 (분)", 0., 240., 5., key="pa_single_delay")
    cols = st.columns(3)
    with cols[0]:
        selected = st.selectbox("상세 표시 시나리오", SCENARIOS, key="pa_scenario")
    with cols[1]:
        general = st.number_input("B 일반 혼잡 증가율 (%) · 가정", 0., 500., 20., key="pa_general")
    with cols[2]:
        severe = st.number_input("C 심한 혼잡 증가율 (%) · 가정", 0., 1000., 50., key="pa_severe")
    st.caption("A=증가율 0%, B=20%, C=50%는 연구용 기본 예시입니다. 실제 위례 혼잡도로 해석하지 않습니다.")
    distribution = st.selectbox("지연시간 분포", ["고정 지연", "균등분포", "절단 정규분포"], index=1, key="pa_distribution")
    minimum, maximum, mean, std = 0., 10., 5., 2.
    if distribution != "고정 지연":
        cols = st.columns(2)
        with cols[0]:
            minimum = st.number_input("최소 지연 (분)", 0., 240., 0., key="pa_minimum")
        with cols[1]:
            maximum = st.number_input("최대 지연 (분)", 0., 240., 10., key="pa_maximum")
    if distribution == "절단 정규분포":
        cols = st.columns(2)
        with cols[0]:
            mean = st.number_input("절단 전 정규분포 평균 (분)", 0., 240., 5., key="pa_mean")
        with cols[1]:
            std = st.number_input("절단 전 정규분포 표준편차 (분)", .01, 120., 2., key="pa_std")
        st.caption("최소~최대 범위로 조건화한 정규분포입니다. 입력 평균·표준편차는 절단 후 표본 통계와 다를 수 있습니다.")
    cols = st.columns(2)
    with cols[0]:
        runs = st.number_input("시뮬레이션 반복 횟수", 1, 100000, 1000, key="pa_runs")
    with cols[1]:
        seed = st.number_input("난수 시드", 0, 2147483647, 20261113, key="pa_seed")
    coordinates = [[records.loc[key, "latitude"], records.loc[key, "longitude"]] for key in (origin, destination)]
    inputs = dict(origin=origin, destination=destination, coordinates=coordinates, day=day, start_clock=start_clock,
                  target_offset=target_offset, target_clock=target_clock, tram_offset=tram_offset,
                  tram_clock=tram_clock, mode=mode_label, online=online, manual=manual, walk=walk,
                  buffer=buffer, tolerance=tolerance, single_delay=single_delay, selected=selected,
                  general=general, severe=severe, distribution=distribution, minimum=minimum,
                  maximum=maximum, mean=mean, std=std, runs=runs, seed=seed)
    requested = st.button("연구용 시뮬레이션 실행", key="pa_run", type="primary")
    saved = matching_result("punctuality_execution", inputs)
    if not requested and saved is None:
        st.info("입력을 설정한 뒤 실행하세요. 현재 입력과 다른 이전 결과는 대시보드에서 실행 당시 조건과 함께 확인할 수 있습니다.")
        return
    if origin == destination:
        st.error("출발 정류장과 도착 정류장을 다르게 선택하세요.")
        return
    try:
        route, error = (resolve_duration("manual" if mode_label == "직접 입력" else "osrm", manual, coordinates, online)
                        if requested else (saved["value"]["route"], None))
        if error:
            st.error(error)
            return
        departure = datetime.combine(day, start_clock, KST)
        target = datetime.combine(day+timedelta(days=int(target_offset)), target_clock, KST)
        tram = datetime.combine(day+timedelta(days=int(tram_offset)), tram_clock, KST)
        model = DelayModel(kind={"고정 지연": "fixed", "균등분포": "uniform", "절단 정규분포": "truncated_normal"}[distribution],
                           fixed=single_delay, minimum=minimum, maximum=maximum, mean=mean, std=std)
        if requested:
            result = simulate(departure, route["duration_min"], target, tram, model, int(runs), int(seed), general, severe,
                              tolerance_min=tolerance, walk_min=walk, buffer_min=buffer)
            saved = remember_result("punctuality_execution", inputs, dict(route=route, result=result), route["source"])
        else:
            result = saved["value"]["result"]
        summary = pd.DataFrame(result["summary"])
        detail = result["summary"][SCENARIOS.index(selected)]
        timing = evaluate_timing(departure, detail["travel_min"], target, tram, single_delay, tolerance, walk, buffer)
    except (ValueError, OverflowError) as error:
        st.error(f"분석 입력 오류: {error}")
        return

    st.subheader(f"예측 결과 — {selected} · 연구용 시뮬레이션")
    cols = st.columns(4)
    cols[0].metric("DRT 예상 도착 (추가 지연 전)", timing["expected_arrival"].strftime("%m-%d %H:%M:%S"))
    cols[1].metric("예측 정시 도착률", f"{detail['on_time_pct']:.1f}%")
    cols[2].metric("예측 트램 환승 성공률", f"{detail['transfer_success_pct']:.1f}%")
    cols[3].metric("예측 트램 환승 실패 확률", f"{detail['transfer_failure_pct']:.1f}%")
    st.caption(f"기준 이동시간 {route['duration_min']:.3f}분 · {route['source']} · 조회 시각 {route['retrieved_at']}")
    st.subheader("단일 지연 가정의 시간 흐름 · 실제 운행기록 아님")
    st.write(f"정시 도착: {'성공' if timing['on_time'] else '실패'} / 환승: {'성공' if timing['transfer_success'] else '실패'}")
    st.write(f"목표 대비 여유 {timing['target_margin_min']:.2f}분 · 환승 잔여 {timing['transfer_margin_min']:.2f}분 · 실패 초과 {timing['transfer_excess_min']:.2f}분")
    timeline = pd.DataFrame([
        {"단계": label, "시각": timing[key].isoformat(), "출발 후 분": (timing[key]-departure).total_seconds()/60}
        for label, key in [("DRT 출발", "departure"), ("추가 지연 전 도착", "expected_arrival"),
                           ("지연 반영 도착", "delayed_arrival"), ("탑승 준비 완료", "ready_at"),
                           ("목표 도착", "target"), ("가상 트램 출발", "tram_departure")]])
    chart = alt.Chart(timeline).mark_point(size=160).encode(
        x=alt.X("출발 후 분:Q", title="DRT 출발 이후 경과 분 (날짜 포함 계산)"),
        y=alt.Y("단계:N", sort=timeline["단계"].tolist()), color="단계:N", tooltip=["단계", "시각", "출발 후 분"])
    st.altair_chart(chart, width="stretch")
    st.dataframe(timeline, hide_index=True)
    st.caption(f"단일 계산 추가 지연 {single_delay:.2f}분 · 보행+환승 여유 {walk+buffer:.2f}분 · 정시 허용 오차 {tolerance:.2f}분. 위 확률은 단일 결과가 아닌 전체 반복에서 계산합니다.")

    cols = st.columns(2)
    with cols[0]:
        st.subheader("시뮬레이션 정시 도착률 비교")
        st.altair_chart(alt.Chart(summary).mark_bar().encode(x=alt.X("scenario:N", title="가정 시나리오"),
            y=alt.Y("on_time_pct:Q", title="예측 정시 도착률 (%)", scale=alt.Scale(domain=[0, 100])), tooltip=["scenario", "on_time_pct"]), width="stretch")
    with cols[1]:
        st.subheader("시뮬레이션 환승 실패 확률 비교")
        st.altair_chart(alt.Chart(summary).mark_bar(color="#ef8a17").encode(x=alt.X("scenario:N", title="가정 시나리오"),
            y=alt.Y("transfer_failure_pct:Q", title="예측 환승 실패 확률 (%)", scale=alt.Scale(domain=[0, 100])), tooltip=["scenario", "transfer_failure_pct"]), width="stretch")
    st.subheader("가상 추가 지연시간 분포")
    counts, edges = np.histogram(result["samples"][selected]["delay_min"], bins=30)
    histogram = pd.DataFrame({"구간 시작(분)": edges[:-1], "구간 끝(분)": edges[1:], "횟수": counts})
    st.altair_chart(alt.Chart(histogram).mark_bar().encode(x=alt.X("구간 시작(분):Q", bin="binned"),
                    x2="구간 끝(분):Q", y="횟수:Q", tooltip=list(histogram.columns)), width="stretch")
    labels = {"scenario": "연구용 시나리오", "increase_pct": "이동시간 증가율(%)", "travel_min": "혼잡 반영 이동시간(분)",
              "mean_delay_min": "평균 추가 지연(분)", "mean_elapsed_min": "평균 총 소요시간(분)",
              "mean_extra_vs_base_min": "기준 대비 평균 도착 지연(분)", "mean_target_lateness_min": "목표 대비 평균 초과(분)",
              "on_time_pct": "예측 정시 도착률(%)", "transfer_success_pct": "예측 환승 성공률(%)",
              "transfer_failure_pct": "예측 환승 실패 확률(%)", "runs": "반복 횟수", "result_type": "결과 유형"}
    st.subheader("시나리오별 분석표 · 시뮬레이션 결과")
    st.dataframe(summary.rename(columns=labels), hide_index=True)
    metadata = dict(result_type="research_simulation", origin=origin, destination=destination, coordinates=coordinates,
                    departure=departure.isoformat(), target=target.isoformat(), tram=tram.isoformat(),
                    tram_source="사용자 지정 가상 시각 · 실제 시간표 아님", route=route,
                    delay_model=asdict(model), runs=int(runs), seed=int(seed),
                    general_increase_pct=general, severe_increase_pct=severe,
                    walk_min=walk, buffer_min=buffer, tolerance_min=tolerance, single_delay_min=single_delay,
                    gits_applied=False, operational_dispatch_applied=False)
    st.session_state["punctuality_dashboard"] = dict(metadata=metadata, summary=result["summary"],
        selected=selected, created_at=saved["created_at"], origin_name=label(origin), destination_name=label(destination))
    with st.expander("데이터 출처와 시뮬레이션 가정", expanded=True):
        st.json(metadata)
        st.caption("세 시나리오에 동일한 지연 표본을 사용해 혼잡 가정의 효과를 비교합니다. 표본 평균은 설정 평균과 다를 수 있습니다. 정차·합승 추가시간은 별도로 모형화하지 않으며 필요한 경우 지연 가정에 포함하세요.")
    st.download_button("시뮬레이션 요약 CSV 다운로드", summary.rename(columns=labels).to_csv(index=False).encode("utf-8-sig"),
                       "punctuality_simulation_summary.csv", "text/csv")
    st.download_button("입력 가정 JSON 다운로드", json.dumps(metadata, ensure_ascii=False, indent=2),
                       "punctuality_simulation_assumptions.json", "application/json")
