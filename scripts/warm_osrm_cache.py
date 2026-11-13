"""Prime the OSRM route cache for the four live-control demo presets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "sewook31"
sys.path.insert(0, str(APP_DIR))

from modules.route_engine import OSRM_CACHE
from modules.vehicle_positions import SimulatedProvider


def main():
    result = SimulatedProvider.warm_demo_cache()
    try:
        cache = json.loads(OSRM_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    print(f"OSRM 캐시 항목: {len(cache)} ({OSRM_CACHE})")
    for preset, details in result.items():
        print(f"{preset}: DRT 일정 {details['drt_routes']}건")
        for warning in details["warnings"]:
            print(f"  경고: {warning}")


if __name__ == "__main__":
    main()
