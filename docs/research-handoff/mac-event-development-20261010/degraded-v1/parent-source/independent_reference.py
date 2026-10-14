"""Static independent reference preparation; no import of methods.py.

Not executed. Independent fusion uses Cartesian-product enumeration rather
than the iterative implementation. It does not establish full oracle
independence: the mass semantics remain a common mathematical contract.
"""
from fractions import Fraction as F
from itertools import product


def ds_reference(readings, normalized):
    frames = ({"RUN"}, {"STOP"}, {"RUN", "STOP"})
    masses = [(F(4, 5), F(0), F(1, 5)) if value == "RUN"
              else (F(0), F(4, 5), F(1, 5)) for value in readings]
    total = {"RUN": F(0), "STOP": F(0), "U": F(0), "EMPTY": F(0)}
    for choices in product(range(3), repeat=len(masses)):
        intersection, weight = {"RUN", "STOP"}, F(1)
        for i, choice in enumerate(choices):
            intersection &= frames[choice]
            weight *= masses[i][choice]
        target = "EMPTY" if not intersection else "U" if len(intersection) == 2 else next(iter(intersection))
        total[target] += weight
    conflict = total["EMPTY"]
    if normalized:
        if conflict == 1:
            return None
        for key in ("RUN", "STOP", "U"):
            total[key] /= 1 - conflict
        total["EMPTY"] = F(0)
    total["conflict"] = conflict
    return {k: str(v) for k, v in total.items()}


def event_errors(cards, uncertain_ids, physical_episodes):
    """One physical-reference evaluation per prefix. Include coverage denominators."""
    ids = sorted(set(cards) & set(physical_episodes))
    uncertain = set(uncertain_ids)
    merged = split = decided = rejected = total = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            total += 1
            if a in uncertain or b in uncertain:
                rejected += 1
                continue
            decided += 1
            same_truth = physical_episodes[a] == physical_episodes[b]
            same_output = cards[a] == cards[b]
            merged += int(same_output and not same_truth)
            split += int(same_truth and not same_output)
    return dict(false_merge=merged, false_split=split, decided_pairs=decided,
                rejected_pairs=rejected, total_pairs=total)


# Hand-authored terminal equivalence classes, independent of method code.
# Card labels themselves are arbitrary; compare equality relations only.
TERMINAL_REFERENCE = {
    "T1": {"M0": [["a", "b", "d"]], "M1": [["a", "b", "d"]]},
    "T2": {"M0": [["a"], ["d", "e"]], "M1": [["a"], ["d", "e"]]},
    "T3": {"M0": [["a", "b"], ["c", "d", "e"]], "M1": [["a", "b", "c", "d"], ["e"]]},
    "T4": {"M0": [["a", "c"], ["b", "d", "e"]], "M1": [["a", "c"], ["b", "d", "e"]]},
    "T5": {"M0": [["a"], ["d"]], "M1": [["a", "d"]]},
    "T6": {"M0": [["a", "c", "d"]], "M1": [["a"], ["c", "d"]]},
}


def check_terminal(cards, expected):
    output = {frozenset(k for k, v in cards.items() if v == label) for label in set(cards.values())}
    return output == {frozenset(group) for group in expected}
