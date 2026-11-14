"""Reproduce one reservation click against a disposable app copy."""
from __future__ import annotations

import csv
import shutil
import sys
import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


with tempfile.TemporaryDirectory(prefix="drt_reservation_repro_", dir=ROOT) as temp:
    copy_root = Path(temp) / "sewook31"
    shutil.copytree(ROOT / "sewook31", copy_root, ignore=shutil.ignore_patterns("__pycache__"))
    sys.path.insert(0, str(copy_root))
    reservation_file = copy_root / "data" / "reservations.csv"
    before = row_count(reservation_file)
    app = AppTest.from_file(str(copy_root / "app.py"), default_timeout=30).run()
    assert not app.exception, [e.message for e in app.exception]
    app.radio[0].set_value("예약 관리").run()
    assert not app.exception, [e.message for e in app.exception]
    button = next(b for b in app.button if "예약하기" in b.label)
    button.click().run()
    assert not app.exception, [e.message for e in app.exception]
    after = row_count(reservation_file)
    print(f"임시 앱 복사본 예약 행: {before} -> {after} (증가 {after - before}건)")
