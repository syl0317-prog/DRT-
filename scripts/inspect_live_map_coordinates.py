"""Report coordinates of every point layer used on the live-control map."""
from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sewook31"))
from modules.vehicle_positions import SimulatedProvider  # noqa: E402

LAT_RANGE = (37.46, 37.50)
LON_RANGE = (127.12, 127.16)


def report(label, points):
    print(f"{label}: count={len(points)}")
    if not points:
        print("  coordinates=missing")
        return
    lats = [p[1] for p in points]
    lons = [p[2] for p in points]
    print(f"  lat_min={min(lats):.8f}, lat_max={max(lats):.8f}, "
          f"lon_min={min(lons):.8f}, lon_max={max(lons):.8f}")
    outside = [p for p in points if not (LAT_RANGE[0] <= p[1] <= LAT_RANGE[1]
                                         and LON_RANGE[0] <= p[2] <= LON_RANGE[1])]
    print(f"  outside_wirye_range={len(outside)} (lat {LAT_RANGE[0]}–{LAT_RANGE[1]}, "
          f"lon {LON_RANGE[0]}–{LON_RANGE[1]})")
    for name, lat, lon in outside:
        print(f"    {name}: lat={lat:.8f}, lon={lon:.8f}")


def main():
    today = date.today()
    provider = SimulatedProvider(scenario="평일 출근 07~09시", service_date=today)
    tram_stations = []
    for feature in provider.get_station_features():
        props = feature.get("properties", {})
        if props.get("lat") is not None and props.get("lon") is not None:
            tram_stations.append((f"{props.get('station_no')} {props.get('station_name')}",
                                  float(props["lat"]), float(props["lon"])))
    virtual_stops = [(f"{sid} {row.get('stop_name')}", float(row["latitude"]), float(row["longitude"]))
                     for sid, row in provider.drt_stop_ids.items()]
    transfer_stops = [(f"{sid} {row.get('stop_name')}", float(row["latitude"]), float(row["longitude"]))
                      for sid, row in provider.tram_stop_ids.items()]
    at = datetime.combine(today, time(7, 0))
    positions = provider.get_positions(at)
    drt_vehicles = [(p["vehicle_id"], float(p["lat"]), float(p["lon"])) for p in positions
                    if str(p.get("vehicle_id", "")).startswith("V")
                    and p.get("lat") is not None and p.get("lon") is not None]
    tram_vehicles = [(p["vehicle_id"], float(p["lat"]), float(p["lon"])) for p in positions
                     if str(p.get("vehicle_id", "")).startswith("TR-")
                     and p.get("lat") is not None and p.get("lon") is not None]
    print(f"Coordinate check timestamp={at.isoformat(timespec='seconds')}")
    report("트램 정거장", tram_stations)
    report("가상정류장", virtual_stops)
    report("환승 정류장 마커", transfer_stops)
    report("DRT 차량", drt_vehicles)
    report("트램 차량", tram_vehicles)
    report("전체 지도 점", tram_stations + virtual_stops + transfer_stops + drt_vehicles + tram_vehicles)


if __name__ == "__main__":
    main()
