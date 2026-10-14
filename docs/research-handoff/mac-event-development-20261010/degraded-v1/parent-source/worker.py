"""Prepared worker; do not execute until fresh isolation qualification exists.

Read public input from stdin; no filesystem writes or oracle reads.
120 counted method invocations. Future launcher must enforce qualification,
CPU/wall/output protection and consumed-once authorization externally.
"""
import json
import sys
import methods


def run(public):
    if len(public["traces"]) != 6 or any(len(t["rows"]) != 5 for t in public["traces"]):
        raise ValueError("fixed scope required")
    output, count = [], 0
    for trace in public["traces"]:
        previous = {}
        for n in range(1, 6):
            for method in ("M0", "M1", "M2", "M3"):
                count += 1
                if count > 120:
                    raise RuntimeError("method budget")
                result = methods.assess(trace["rows"][:n], method)
                old = previous.get(method, {})
                new_card = bool(set(result["cards"].values()) - set(old.get("cards", {}).values()))
                changed_risk = result["risk"] != old.get("risk")
                reasons = []
                if result["notify"] and (new_card or changed_risk):
                    reasons.append("new_card_or_risk_state_change")
                if result["priority"] == "FOLLOW_UP" and old.get("priority") != "FOLLOW_UP":
                    reasons.append("handling_follow_up_only")
                result["notification_reasons"] = reasons
                previous[method] = result
                output.append(dict(trace=trace["id"], prefix=n, method=method, result=result))
    return dict(status="DEVELOPMENT_ONLY", method_invocations=count, rows=output)


if __name__ == "__main__":
    # Gate closed until a separate launcher is built and qualified. No naked CLI.
    raise SystemExit("BLOCKED: static preparation; no qualified launcher for this version")
