"""Create missing team databases only. Existing files are never opened or changed.

Uses only Python's standard library; no API, network or original database needed.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def publish_missing(path, build):
    path = Path(path)
    if path.exists():
        return "preserved"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory) / "initial.sqlite3"
        with closing(sqlite3.connect(temporary)) as connection:
            with connection:
                build(connection)
        # Exclusive creation also protects an existing file created concurrently.
        try:
            with path.open("xb") as destination:
                destination.write(temporary.read_bytes())
        except FileExistsError:
            return "preserved"
    return "created"


def initialize(root=ROOT):
    root = Path(root)
    seed = json.loads((root / "data/seeds/drt_routes.json").read_text(encoding="utf-8"))
    if set(seed) != {"routes", "stops", "segments", "bookings"} or seed["bookings"]:
        raise ValueError("Expected route-only seed without bookings")
    if [r["route_id"] for r in seed["routes"]] != ["R02"]:
        raise ValueError("Expected R02 configuration")
    if any(r["active"] or r["vehicles"] for r in seed["routes"]):
        raise ValueError("Seed must not activate routes or allocate vehicles")

    def routes(connection):
        connection.execute("CREATE TABLE registry(singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)")
        connection.execute("INSERT INTO registry VALUES(1,0,?)", (json.dumps(seed, ensure_ascii=False),))

    def reservations(connection):
        connection.execute("CREATE TABLE requests(public_id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, signature TEXT NOT NULL, payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE csv_cancellations(public_id TEXT PRIMARY KEY, cancelled_at TEXT NOT NULL)")

    result = {}
    for relative, builder in (("data/derived/drt_routes/routes.sqlite3", routes),
                              ("data/derived/unified_reservations/reservations.sqlite3", reservations)):
        result[relative] = publish_missing(root / relative, builder)
    return result


if __name__ == "__main__":
    for name, status in initialize().items():
        print(f"{status}: {name}")
