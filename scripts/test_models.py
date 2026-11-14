"""Test simulation under user model definitions."""
import random
import csv

rng = random.Random(42)

# OSRM times to T01
stops = {
    "D01": 2.285,
    "D02": 2.095,
    "D03": 1.470,
    "D04": 0.100,
}
dwell = 1.0

# Distributions for complex k
# (a) min 1.9, mode 2.5, max 3.1
# (b) min 1.0, mode 1.1, max 1.2

def run_test(k_dist, wait_formula="platform"):
    results = {}
    rng = random.Random(42)
    for stop_id in ("D01", "D02"):
        P = stops[stop_id] + dwell
        for passengers in (0, 1, 2):
            for b in (0, 1, 2, 3, 5, 8):
                missed = 0
                waits = 0.0
                for _ in range(10_000):
                    k = rng.triangular(*k_dist)
                    noise = rng.uniform(-1.0, 1.0)
                    pool = sum(rng.expovariate(0.5) for _ in range(passengers)) if passengers > 0 else 0.0
                    R = P * k + noise + pool
                    # lateness relative to tram depart
                    lateness = (R - P) - b
                    if lateness > 1e-12:
                        missed += 1
                        if wait_formula == "platform":
                            rem = lateness % 10.0
                            w = (10.0 - rem) if rem > 1e-12 else 10.0
                        else: # literal: 10 + lateness
                            w = 10.0 + lateness
                        waits += w
                    else:
                        waits += -lateness
                results[(stop_id, passengers, b)] = (missed / 10000.0, waits / 10000.0)
    return results

print("=== (a) Platform Wait (10 - rem) ===")
res_a_plat = run_test((1.9, 3.1, 2.5), "platform")
for stop in ("D01", "D02"):
    for p in (0, 2):
        print(f"{stop} pool={p}: " + " | ".join(f"b={b}:{res_a_plat[(stop, p, b)][0]:.1%}/{res_a_plat[(stop, p, b)][1]:.2f}m" for b in (0, 2, 5, 8)))

print("\n=== (a) Literal Wait (10 + lateness) ===")
res_a_lit = run_test((1.9, 3.1, 2.5), "literal")
for stop in ("D01", "D02"):
    for p in (0, 2):
        print(f"{stop} pool={p}: " + " | ".join(f"b={b}:{res_a_lit[(stop, p, b)][0]:.1%}/{res_a_lit[(stop, p, b)][1]:.2f}m" for b in (0, 2, 5, 8)))

print("\n=== (b) Platform Wait (10 - rem) ===")
res_b_plat = run_test((1.0, 1.2, 1.1), "platform")
for stop in ("D01", "D02"):
    for p in (0, 2):
        print(f"{stop} pool={p}: " + " | ".join(f"b={b}:{res_b_plat[(stop, p, b)][0]:.1%}/{res_b_plat[(stop, p, b)][1]:.2f}m" for b in (0, 2, 5, 8)))

print("\n=== (b) Literal Wait (10 + lateness) ===")
res_b_lit = run_test((1.0, 1.2, 1.1), "literal")
for stop in ("D01", "D02"):
    for p in (0, 2):
        print(f"{stop} pool={p}: " + " | ".join(f"b={b}:{res_b_lit[(stop, p, b)][0]:.1%}/{res_b_lit[(stop, p, b)][1]:.2f}m" for b in (0, 2, 5, 8)))
