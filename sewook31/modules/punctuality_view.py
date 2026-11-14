"""Read-only Streamlit view for precomputed punctuality simulation results."""
from pathlib import Path

import pandas as pd
from modules.session_ui import persistent_ui as st
import streamlit as streamlit

RESULTS = Path(__file__).resolve().parents[2] / "data" / "processed" / "punctuality_main_results.csv"


@streamlit.cache_data(show_spinner=False)
def _load_results(modified_ns):
    return pd.read_csv(RESULTS, encoding="utf-8-sig")


def show_punctuality():
    st.header("정시성 검증")
    try:
        data = _load_results(RESULTS.stat().st_mtime_ns)
    except (OSError, pd.errors.ParserError) as exc:
        st.error(f"정시성 결과 CSV를 읽지 못했습니다: {type(exc).__name__}")
        return
    if data.empty:
        st.warning("계산 결과가 없습니다. scripts/punctuality_calc.py를 실행해 주세요.")
        return

    st.download_button("전체 분석 결과 CSV 다운로드", data.to_csv(index=False).encode("utf-8-sig"),
                       file_name="punctuality_results.csv", mime="text/csv", key="punct_csv")
    segment = st.selectbox("구간 유형", sorted(data["구간유형"].unique()), key="punct_segment")
    period = st.selectbox("시간대", sorted(data["시간대"].unique()), key="punct_period")
    stop = st.selectbox("정류장", sorted(data["정류장"].unique()), key="punct_stop")
    passengers = st.selectbox("합승 인원", sorted(data["합승수"].unique()), key="punct_passengers")
    level = st.selectbox("혼잡 수준", ["min", "mode", "max"], index=1, key="punct_level")
    subset = data[(data["시간대"] == period) & (data["정류장"] == stop)
                  & (data["구간유형"] == segment)
                  & (data["합승수"] == passengers) & (data["혼잡수준"] == level)]
    if subset.empty:
        st.info("선택한 조건의 결과가 없습니다.")
        return

    buffers = sorted(subset["여유분"].unique())
    selected_buffer = st.selectbox("환승 여유시간 b (분)", buffers, key="punct_buffer")
    row = subset[subset["여유분"] == selected_buffer].iloc[0]
    delta = float(row["기준대기분"]) - float(row["평균대기분"])
    delta_text = f"-{delta:.2f}" if delta >= 0 else f"+{abs(delta):.2f}"
    st.info(f"여유 {selected_buffer}분일 때 놓칠 확률 {row['놓칠확률']:.1%}, "
            f"평균 대기 {row['평균대기분']:.2f}분(기준 {row['기준대기분']:.2f}분 대비 {delta_text}분)")

    chart = subset.sort_values("여유분").set_index("여유분")
    st.line_chart(chart[["놓칠확률"]], x_label="여유시간 b (분)", y_label="놓칠 확률",
                  alt="여유시간에 따른 트램 환승 놓침 확률")
    wait_chart = chart[["평균대기분", "기준대기분"]]
    st.line_chart(wait_chart, x_label="여유시간 b (분)", y_label="분",
                  alt="여유시간에 따른 평균 환승 대기와 기준 대기")
    st.caption("혼잡 계수는 위례 진입 간선 12개 구간의 시간대별 속도 기반(평일, 시간 구간 대응은 추정)이고, "
               "단지 내 계수와 합승 지연은 가정값입니다. 실제 운행 데이터가 없어 시뮬레이션 결과이며 "
               "실측 검증은 후속 과제입니다.")
