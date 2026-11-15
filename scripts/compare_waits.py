"""Compare wait time formulas."""
import random

rng = random.Random(42)

# Suppose P = 3.285 (D01), k ~ triangular(1.9, 3.1, 2.5)
# R = P * k + noise + pool
P = 3.285
k_samples = [rng.triangular(1.9, 3.1, 2.5) for _ in range(1000)]
noises = [rng.uniform(-1, 1) for _ in range(1000)]

for b in (0, 2, 5):
    waits_platform = []
    waits_literal = []
    missed_count = 0
    for k, noise in zip(k_samples, noises):
        R = P * k + noise
        lateness = (R - P) - b
        if lateness > 0:
            missed_count += 1
            # Platform wait: next tram arrives at 10, arrived at lateness
            rem = lateness % 10
            wait_plat = 10 - rem if rem > 1e-12 else 10
            # Literal: 10 + lateness
            wait_lit = 10 + lateness
            waits_platform.append(wait_plat)
            waits_literal.append(wait_lit)
        else:
            wait_early = -lateness
            waits_platform.append(wait_early)
            waits_literal.append(wait_early)
    print(f"b={b}: missed={missed_count/1000:.1%}, avg_platform_wait={sum(waits_platform)/1000:.2f}분, avg_literal_wait={sum(waits_literal)/1000:.2f}분")
