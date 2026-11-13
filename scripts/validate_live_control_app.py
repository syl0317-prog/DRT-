"""Headless Streamlit smoke check for the live-control tab."""
from pathlib import Path
import sys

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
    playback = next(w for w in run.radio if w.label == "표시 방식")
    playback.set_value("지도 자동 재생").run()
    assert not run.exception, run.exception
    print("AppTest: 앱 import 및 실시간 관제 전환 정상")
    assert any("지도 자동 재생용 위치" in x for x in [c.value for c in run.caption])
    print(f"표: {len(list(run.dataframe))}개; 자동 재생 지도 렌더: 정상")
    print("UI warnings:", [x.value for x in run.warning])


if __name__ == "__main__":
    main()
