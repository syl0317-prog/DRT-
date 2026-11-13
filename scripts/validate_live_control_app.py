"""Headless Streamlit smoke check for the live-control tab."""
from pathlib import Path
import sys
from datetime import date, datetime, time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))
from streamlit.testing.v1 import AppTest  # noqa: E402


def main():
    app = ROOT / "sewook31" / "app.py"
    run = AppTest.from_file(str(app), default_timeout=30).run()
    assert not run.exception, run.exception
    menu = next(w for w in run.radio if w.label == "메뉴 선택")
    menu.set_value("실시간 관제").run()
    assert not run.exception, run.exception
    captions = [x.value for x in run.caption]
    dataframes = list(run.dataframe)
    assert any("시뮬레이션 예약 기반(가상)" in x for x in captions)
    assert dataframes, "차량 표가 표시되지 않았습니다."

    preset = next(w for w in run.selectbox if w.key == "live_preset")
    assert next(w for w in run.slider if w.key == "live_time_평일 출근 07~09시").value == datetime.combine(
        date.today(), time(7, 0))
    preset.set_value("평일 퇴근 17~19시").run()
    assert next(w for w in run.slider if w.key == "live_time_평일 퇴근 17~19시").value == datetime.combine(
        date.today(), time(17, 0))
    preset = next(w for w in run.selectbox if w.key == "live_preset")
    preset.set_value("평일 낮 호출형").run()
    lunch_slider = next(w for w in run.slider if w.key == "live_time_평일 낮 호출형")
    assert lunch_slider.value == datetime.combine(date.today(), time(12, 0))
    lunch_slider.set_value(datetime.combine(date.today(), time(13, 5))).run()
    assert next(w for w in run.slider if w.key == "live_time_평일 낮 호출형").value == datetime.combine(
        date.today(), time(13, 5))
    next(w for w in run.selectbox if w.key == "live_preset").set_value("주말").run()
    weekend_slider = next(w for w in run.slider if w.key == "live_time_주말")
    assert weekend_slider.value == datetime.combine(date.today(), time(12, 0))

    rendered_text = "\n".join([x.value for x in run.caption] + [x.value for x in run.warning]
                              + [x.value for x in run.error] + [x.value for x in run.info])
    for frame in run.dataframe:
        if isinstance(getattr(frame, "value", None), pd.DataFrame):
            rendered_text += "\n" + frame.value.to_string()
            for _, row in frame.value.iterrows():
                row_dash = ["운행 번호", "연결 예정 트램 시각", "설계 여유", "혼잡 반영 후 여유", "지연(분)"]
                if str(row["차량 번호"]).startswith("TR-"):
                    assert row["탑승 인원"] == "-"
                    assert all(row[name] == "-" for name in row_dash)
                elif row["상태"] == "대기" or row["운행 번호"] == "-":
                    assert all(row[name] == "-" for name in row_dash)
                if pd.isna(row["탑승 인원"]) or row["탑승 인원"] == "missing":
                    assert row["탑승 인원"] == "미집계"
    assert "missing" not in rendered_text.lower(), rendered_text
    playback = next(w for w in run.radio if w.label == "표시 방식")
    playback.set_value("지도 자동 재생").run()
    assert not run.exception, run.exception
    print("AppTest: 앱 표시, 프리셋 시각 초기화, 슬라이더 유지, missing 비노출, 자동 재생 정상")
    assert any("지도 자동 재생용 위치" in x for x in [c.value for c in run.caption])
    print(f"표: {len(list(run.dataframe))}개; 자동 재생 지도 렌더: 정상")
    print("UI warnings:", [x.value for x in run.warning])


if __name__ == "__main__":
    main()
