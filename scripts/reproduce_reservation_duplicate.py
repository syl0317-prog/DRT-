"""Assert one legacy click creates one row; all writes stay in temporary files."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))

def fake_route(coordinates, **kwargs):
    return dict(duration_min=5, distance_km=1, coordinates=coordinates,
                source="TEST FIXTURE", retrieved_at="test", cache_hit=True)

with ExitStack() as stack:
    temp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    csv = temp / "reservations.csv"
    from modules.reservation_manager import COLUMNS
    pd.DataFrame(columns=COLUMNS).to_csv(csv, index=False, encoding="utf-8-sig")
    stack.enter_context(patch("modules.reservation_manager.RESERVATION_FILE", csv))
    stack.enter_context(patch("modules.unified_reservations.DATABASE", temp / "unified.sqlite3"))
    for module in ("reservation_manager", "integrated_scheduler", "pickup_scheduler"):
        stack.enter_context(patch(f"modules.{module}.calculate_road_route", side_effect=fake_route))
    app = AppTest.from_file(str(ROOT / "sewook31/app.py"), default_timeout=60).run()
    assert not app.exception, app.exception
    app.sidebar.radio(key="main_menu").set_value("예약 관리").run()
    app.radio(key="booking_section").set_value("기존 트램 연계 예약").run()
    assert not app.exception, app.exception
    next(b for b in app.button if b.label == "예약하기").click().run()
    assert not app.exception, app.exception
    assert len(pd.read_csv(csv)) == 1, "One click must create exactly one reservation"
    app.run()
    assert not app.exception, app.exception
    assert len(pd.read_csv(csv)) == 1, "A rerun must not create another reservation"
    print("PASS: one legacy click = one row; rerun = zero additional rows")
