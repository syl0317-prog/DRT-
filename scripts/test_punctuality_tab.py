"""Small AppTest smoke check for the punctuality tab."""
from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))

app = AppTest.from_file(str(ROOT / "sewook31" / "app.py"), default_timeout=30).run()
assert not app.exception, [e.message for e in app.exception]
app.sidebar.radio(key="main_menu").set_value("정시·환승 분석").run()
assert len(app.sidebar.radio(key="main_menu").options) == 6
app.radio(key="punctuality_section").set_value("정시성 계산·검증 결과").run()
assert not app.exception, [e.message for e in app.exception]
assert any("정시성 검증" in str(element.value) for element in app.get("header"))
charts = app.get("vega_lite_chart") + app.get("line_chart")
assert len(charts) >= 2, f"Expected two charts, found {len(charts)}"
print("AppTest OK: 정시성 검증 탭, 그래프 2개")

for segment in app.selectbox(key="punct_segment").options:
    app.selectbox(key="punct_segment").set_value(segment).run()
    assert not app.exception, [e.message for e in app.exception]
assert len(app.get("download_button")) == 1
