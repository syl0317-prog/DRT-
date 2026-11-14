"""Run the requested D01/D02 punctuality comparison without changing legacy outputs."""
from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOPS = ROOT / "sewook31" / "data" / "drt_stops.csv"
CACHE = ROOT / "sewook31" / "data" / "osrm_cache.json"
OUT = ROOT / "data" / "processed" / "punctuality_results_v3.csv"
REPS = 100_000
HEADWAY = 10.0
BUFFERS = (0, 1, 2, 3, 5, 8)
K_MODELS = {
    "a_assumption": (1.9, 2.5, 3.1),
    "b_uncalibrated": (1.0, 1.1, 1.2),
}
CORRIDOR_K = (1.11, 1.33, 4.41)


def haversine_m(a: dict, b: dict) -> float:
    lat1, lon1 = map(math.radians, (float(a["latitude"]), float(a["longitude"])))
    lat2, lon2 = map(math.radians, (float(b["latitude"]), float(b["longitude"])))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def main() -> None:
    with STOPS.open(encoding="utf-8-sig", newline="") as f:
        all_stops = list(csv.DictReader(f))
    trams = [s for s in all_stops if s["stop_type"] == "tram"]
    homes = [s for s in all_stops if s["stop_id"] in {"D01", "D02"}]
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    routes = {}
    for home in homes:
        tram = min(trams, key=lambda t: haversine_m(home, t))
        a = f"{float(home['latitude']):.6f},{float(home['longitude']):.6f}"
        b = f"{float(tram['latitude']):.6f},{float(tram['longitude']):.6f}"
        route = cache.get(f"{a};{b}") or cache.get(f"{b};{a}")
        if not route or route.get("duration_min") is None:
            raise ValueError(f"OSRM cache route missing: {home['stop_id']} -> {tram['stop_id']}")
        routes[home["stop_id"]] = (home, tram, float(route["duration_min"]) + 1.0)

    # Pair each case's random draws across k models to make comparisons stable.
    rows = []
    for stop_id, (home, tram, p_min) in routes.items():
        for segment, k_triplet in (("단지내", None), ("간선연계", CORRIDOR_K)):
            for passengers in (0, 1, 2):
                samples = {}
                for model_name in K_MODELS:
                    samples[model_name] = [[] for _ in BUFFERS]
                for model_idx, (model_name, k_triplet_model) in enumerate(K_MODELS.items()):
                    lo, mode, hi = k_triplet_model if segment == "단지내" else k_triplet
                    rng = random.Random(20261115 + (0 if stop_id == "D01" else 10_000)
                                        + (0 if segment == "단지내" else 1_000)
                                        + passengers * 100 + model_idx * 10_000_000)
                    for _ in range(REPS):
                        k = rng.triangular(lo, hi, mode)
                        noise = rng.uniform(-1.0, 1.0)
                        pooling = sum(rng.expovariate(0.5) for _ in range(passengers))
                        actual = p_min * k + noise + pooling
                        # start = tram_departure - b - P, hence lateness = R - P - b.
                        for idx, b in enumerate(BUFFERS):
                            late = actual - p_min - b
                            missed = late > 0.0
                            wait = HEADWAY + late if missed else -late
                            samples[model_name][idx].append((missed, wait))
                for model_name in K_MODELS:
                    for idx, b in enumerate(BUFFERS):
                        case = samples[model_name][idx]
                        miss_p = sum(m for m, _ in case) / REPS
                        avg_wait = sum(w for _, w in case) / REPS
                        rows.append({
                            "stop_id": stop_id, "stop_name": home["stop_name"],
                            "tram_stop_id": tram["stop_id"], "tram_stop_name": tram["stop_name"],
                            "period": "출근", "segment": segment, "k_model": model_name,
                            "k_min": (K_MODELS[model_name][0] if segment == "단지내" else CORRIDOR_K[0]),
                            "k_mode": (K_MODELS[model_name][1] if segment == "단지내" else CORRIDOR_K[1]),
                            "k_max": (K_MODELS[model_name][2] if segment == "단지내" else CORRIDOR_K[2]),
                            "passengers": passengers, "buffer_min": b,
                            "planned_P_min_including_dwell": p_min,
                            "miss_probability": miss_p, "mean_wait_min": avg_wait,
                            "random_arrival_baseline_wait_min": 5.0,
                        })
    fields = list(rows[0])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {OUT}")
    with OUT.open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")
    for key, (home, tram, p) in routes.items():
        print(f"ROUTE {key} -> {tram['stop_id']} {tram['stop_name']}; P={p:.3f} min incl. 1-min dwell")
    print("MIN_B <=5% (observed on requested buffers)")
    for stop_id in routes:
        for segment in ("단지내", "간선연계"):
            for model in K_MODELS:
                for passengers in (0, 1, 2):
                    subset = [r for r in rows if r["stop_id"] == stop_id and r["segment"] == segment
                              and r["k_model"] == model and r["passengers"] == passengers
                              and r["miss_probability"] <= 0.05]
                    print(stop_id, segment, model, passengers,
                          min((r["buffer_min"] for r in subset), default="not reached"))


if __name__ == "__main__":
    main()
