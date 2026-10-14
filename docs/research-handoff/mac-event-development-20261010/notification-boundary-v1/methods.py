"""Standalone development methods. Not imported or executed yet.

No old PCG imports, no oracle access, network, subprocess or file operations.
Logical validity parameters are fixed toy settings, not facility thresholds.
"""
from fractions import Fraction as F

FRAME = {"RUN": frozenset({"RUN"}), "STOP": frozenset({"STOP"}),
         "U": frozenset({"RUN", "STOP"}), "EMPTY": frozenset()}


def fuse(masses, normalized):
    state = {FRAME["U"]: F(1)}
    for mass in masses:
        if sum(mass.values()) != 1 or any(v < 0 for v in mass.values()):
            raise ValueError("invalid mass")
        nxt = {}
        for a, av in state.items():
            for b, bv in mass.items():
                key = a & FRAME[b]
                nxt[key] = nxt.get(key, F(0)) + av * bv
        state = nxt
    conflict = state.get(FRAME["EMPTY"], F(0))
    if normalized and conflict == 1:
        return None
    divisor = 1 - conflict if normalized else F(1)
    result = {k: (F(0) if normalized and k == "EMPTY" else state.get(v, F(0)) / divisor)
              for k, v in FRAME.items()}
    result["conflict"] = conflict
    return result


def latest_evidence(prefix, now):
    # Source timestamp may be unchanged while server confirmation remains fresh.
    latest = {}
    for row in prefix:
        if row["target"] != "motion":
            continue
        key = (row["asset"], row["acquisition"], row["target"])
        if key not in latest or (row["source_time"], row["confirmed_time"]) > (
                latest[key]["source_time"], latest[key]["confirmed_time"]):
            latest[key] = row
    return [row for row in latest.values() if row["quality"] == "GOOD"
            and 0 <= now - row["confirmed_time"] <= 2]


def rule_cards(prefix):
    cards, possible = {}, []
    epoch, last_alarm, active, recovered = {}, {}, {}, set()
    # Only already received rows; physical ordering prevents delayed old alarms
    # from being attached to a later episode. No future input is read.
    for _, row in sorted(enumerate(prefix), key=lambda x: (x[1]["source_time"], x[0])):
        asset = row["asset"]
        marker = (asset, row["source_time"])
        if row["recovery"] and row["quality"] == "GOOD" and marker not in recovered and row["source_time"] >= last_alarm.get(asset, -1):
            epoch[asset] = epoch.get(asset, 0) + 1
            recovered.add(marker)
            active.pop(asset, None)
        if not row["alarm"]:
            continue
        if row["relationship"] != "VALID":
            cards[row["id"]] = "uncertain:" + row["id"]
            possible.append(row["id"])
        else:
            key = (row["task"], epoch.get(asset, 0))
            cards[row["id"]] = "task:%s:epoch:%d" % key
            active[asset] = cards[row["id"]]
        last_alarm[asset] = max(last_alarm.get(asset, -1), row["source_time"])
    return cards, possible


def window_cards(prefix, window):
    cards, last = {}, {}
    for arrival, row in enumerate(prefix):
        if not row["alarm"]:
            continue
        key = row["asset"]
        previous = last.get(key)
        card = previous[1] if previous and arrival - previous[0] <= window else "window:" + row["id"]
        cards[row["id"]] = card
        last[key] = (arrival, card)
    return cards


def assess(prefix, method):
    if method not in ("M0", "M1", "M2", "M3"):
        raise ValueError("unknown method")
    now = len(prefix) - 1
    cards, possible = (window_cards(prefix, 2), []) if method == "M0" else rule_cards(prefix)
    evidence = latest_evidence(prefix, now)
    current_time = {}
    for row in prefix:
        if row["target"] == "motion":
            current_time[row["asset"]] = max(current_time.get(row["asset"], -1), row["source_time"])
    evidence = [r for r in evidence if r["source_time"] == current_time[r["asset"]]]
    # Partition by asset and physical time: incompatible targets/times are not contradictions.
    aligned = {}
    for row in evidence:
        aligned.setdefault((row["asset"], row["source_time"]), []).append(row)
    conflict = any({r["value"] for r in rows} == {"RUN", "STOP"} for rows in aligned.values())
    latest_presence = {}
    for row in prefix:
        # Old arrival cannot overwrite later physical presence.
        if row["presence"] is not None and (row["asset"] not in latest_presence or
                row["source_time"] >= latest_presence[row["asset"]][0]):
            latest_presence[row["asset"]] = (row["source_time"], row["presence"])
    running = any(r["value"] == "RUN" and latest_presence.get(r["asset"], (0, False))[1] for r in evidence)
    risk = "CONFLICT_REVIEW" if conflict else "EXPOSURE" if running else "UNKNOWN"
    if running and not conflict and any(r.get("danger_level") == "HIGH" for r in evidence):
        risk = "EXPOSURE_HIGH"
    # STOP is a motion proposition; this code never emits SAFE.
    priority = "FOLLOW_UP" if now >= 2 and any(v[1] for v in latest_presence.values()) else "REVIEW"
    fused = {}
    if method in ("M2", "M3"):
        for key, rows in sorted(aligned.items()):
            masses = [{"RUN": F(4, 5) if r["value"] == "RUN" else F(0),
                       "STOP": F(4, 5) if r["value"] == "STOP" else F(0), "U": F(1, 5)} for r in rows]
            mass = fuse(masses, method == "M2")
            fused["%s@%s" % key] = None if mass is None else {k: str(v) for k, v in mass.items()}
    notify = running or conflict
    return dict(cards=cards, possible=possible, risk=risk, priority=priority,
                notify=notify, fused=fused, independent_evidence=len(evidence),
                role="event rules shared; DS motion fusion diagnostic only")
