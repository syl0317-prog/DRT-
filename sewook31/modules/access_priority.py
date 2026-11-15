"""Shared, deterministic apartment access classification and ranking."""
from __future__ import annotations

from copy import deepcopy

NAME = "\ub2e8\uc9c0\uba85"
HOUSEHOLDS = "\uc138\ub300\uc218"
INSIDE = "\uc704\ub840\ub3d9\ub0b4\ubd80"
MODEL = "\ubaa8\ub378\ubc18\uc601"
TRAM_WALK = "\ud2b8\ub7a8\ub3c4\ubcf4\ucd94\uc815_m"
BUS_WALK = "\ubc84\uc2a4\ub3c4\ubcf4\ucd94\uc815_m"
ACCESS = "\uc811\uadfc\uac70\ub9ac_m"
TYPE = "\uc720\ud615"
TYPE_STATUS = "\uc720\ud615_status"
RANK = "\uc6b0\uc120\uc21c\uc704"
RANK_KIND = "\uc6b0\uc120\uc21c\uc704\uad6c\ubd84"
SERVICE = "\uc11c\ube44\uc2a4\ub300\uc0c1"
CUM_HH = "\ub204\uc801\uc138\ub300\uc218"


def _number(value):
    if value in (None, "", "missing", "\ubbf8\uc9d1\uacc4"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_and_rank(rows, tram_walk_threshold_m, bus_walk_threshold_m,
                      service_stop_count, max_service_stops=8):
    """Classify rows and rank eligible apartments by access distance.

    Rows with unknown boundary or access measurements keep an unknown status.
    """
    count = max(1, min(int(service_stop_count), int(max_service_stops)))
    classified = []
    for source in rows:
        row = deepcopy(source)
        tram = _number(row.get(TRAM_WALK))
        bus = _number(row.get(BUS_WALK))
        inside = str(row.get(INSIDE, "")).strip().upper()
        row[TYPE] = "\ubbf8\uc9d1\uacc4"
        row[TYPE_STATUS] = "missing"
        row[RANK] = ""
        row[RANK_KIND] = ""
        row[SERVICE] = "N"
        row[CUM_HH] = ""
        if inside == "N":
            row[TYPE] = "\ud0c0 \uc9c0\uc790\uccb4 \ud611\uc758 \ud544\uc694"
            row[TYPE_STATUS] = "sourced"
        elif inside == "Y":
            if tram is not None and tram <= float(tram_walk_threshold_m):
                row[TYPE], row[TYPE_STATUS] = "\ub3c4\ubcf4\ud615", "assumption"
            elif bus is not None and bus <= float(bus_walk_threshold_m):
                row[TYPE], row[TYPE_STATUS] = "\ubc84\uc2a4\ud615", "assumption"
            elif tram is not None and bus is not None:
                row[TYPE], row[TYPE_STATUS] = "DRT\ub300\uc0c1", "assumption"
        classified.append(row)

    eligible = [r for r in classified if r.get(INSIDE) == "Y"
                and str(r.get(MODEL, "")).strip() != "\ubcf4\ub958"]

    def key(row):
        d, hh = _number(row.get(ACCESS)), _number(row.get(HOUSEHOLDS))
        return (-(d if d is not None else float("-inf")),
                -(hh if hh is not None else -1), str(row.get(NAME, "")))

    drt = sorted((r for r in eligible if r[TYPE] == "DRT\ub300\uc0c1"), key=key)
    buses = sorted((r for r in eligible if r[TYPE] == "\ubc84\uc2a4\ud615"), key=key)
    supplement = buses[:max(0, count - len(drt))]
    sequence = drt + supplement
    cumulative = 0
    for i, row in enumerate(sequence, 1):
        row[RANK] = i
        row[RANK_KIND] = "\ubcf4\ucda9(\uae30\uc900 \uc774\ub0b4)" if row in supplement else "DRT\ub300\uc0c1"
        row[SERVICE] = "Y" if i <= count else "N"
        hh = _number(row.get(HOUSEHOLDS))
        if hh is not None:
            cumulative += int(hh)
            row[CUM_HH] = cumulative

    summary = {"analysis_count": sum(r.get(INSIDE) == "Y" for r in classified),
               "types": {}, "service_stop_count": count,
               "drt_target_households": 0, "service_households": 0,
               "served_drt_target_households": 0, "service_coverage_ratio": None,
               "eligible_drt_candidates": len(drt), "supplement_count": len(supplement)}
    for row in classified:
        group = summary["types"].setdefault(row[TYPE], {"count": 0, "households": 0})
        group["count"] += 1
        hh = _number(row.get(HOUSEHOLDS))
        if hh is not None:
            group["households"] += int(hh)
            if row.get(INSIDE) == "Y" and row[TYPE] == "DRT\ub300\uc0c1":
                summary["drt_target_households"] += int(hh)
            if row.get(SERVICE) == "Y":
                summary["service_households"] += int(hh)
                if row[TYPE] == "DRT\ub300\uc0c1":
                    summary["served_drt_target_households"] += int(hh)
    denom = summary["drt_target_households"]
    if denom:
        summary["service_coverage_ratio"] = summary["served_drt_target_households"] / denom
    rank_names = {str(r.get(NAME, "")) for r in sequence}
    classified.sort(key=lambda r: (0 if str(r.get(NAME, "")) in rank_names else 1,
                                   int(r[RANK]) if r.get(RANK) not in (None, "") else 999999,
                                   str(r.get(NAME, ""))))
    return classified, summary
