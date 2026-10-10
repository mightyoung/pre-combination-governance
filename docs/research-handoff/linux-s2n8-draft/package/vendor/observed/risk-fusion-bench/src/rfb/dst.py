# -*- coding: utf-8 -*-
"""D-S证据理论核心：BPA表示、折扣、组合、冲突度量、Pignistic变换。

辨识框架 Θ = {S, H, M, T, P, E}（安全/人因/设备/物料/工艺/环境）。
焦元用位掩码int表示：S=1, H=2, M=4, T=8, P=16, E=32；Θ=63。
BPA用 dict[int, float] 表示，键为焦元掩码，值为质量，和为1。
"""

from __future__ import annotations
import math
from typing import Dict

SINGLETONS = {"S": 1, "H": 2, "M": 4, "T": 8, "P": 16, "E": 32}
NAMES = {v: k for k, v in SINGLETONS.items()}
THETA = 63  # 全集掩码
N = 6  # 单命题数

Mass = Dict[int, float]


def vacuous() -> Mass:
    """空证据（完全无知）：m(Θ)=1，Dempster组合的单位元。"""
    return {THETA: 1.0}


def normalize(m: Mass, eps: float = 1e-12) -> Mass:
    m = {a: v for a, v in m.items() if v > eps and a != 0}
    s = sum(m.values())
    if s <= 0:
        return vacuous()
    return {a: v / s for a, v in m.items()}


def discount(m: Mass, r: float) -> Mass:
    """Shafer可靠性折扣：m_r(A)=r·m(A) (A⊂Θ)，m_r(Θ)=1-r+r·m(Θ)。

    这是命题1（有界影响）的机制载体：r→0 时退化为空证据。
    """
    assert 0.0 <= r <= 1.0
    out: Mass = {}
    for a, v in m.items():
        out[a] = out.get(a, 0.0) + r * v
    out[THETA] = out.get(THETA, 0.0) + (1.0 - r)
    return normalize(out)


def dempster_combine(m1: Mass, m2: Mass) -> Mass:
    """经典Dempster组合（归一化冲突）。"""
    acc: Mass = {}
    conflict = 0.0
    for a, va in m1.items():
        for b, vb in m2.items():
            c = a & b
            w = va * vb
            if c == 0:
                conflict += w
            else:
                acc[c] = acc.get(c, 0.0) + w
    if conflict >= 1.0 - 1e-12:
        return vacuous()  # 完全冲突：回退为无知（保守）
    k = 1.0 / (1.0 - conflict)
    return normalize({a: v * k for a, v in acc.items()})


def conflict_coefficient(m1: Mass, m2: Mass) -> float:
    """冲突系数K。"""
    return sum(va * vb for a, va in m1.items() for b, vb in m2.items() if a & b == 0)


def weighted_average_combine(masses: list, weights: list) -> Mass:
    """基于可信度加权平均证据的改进组合（Murphy/邓勇路线）：
    先按权重平均得到 m̄，再自组合 n-1 次。可交换、解析性好——见论文5.1选型论证。
    """
    n = len(masses)
    assert n >= 1 and len(weights) == n
    ws = sum(weights)
    wn = [w / ws for w in weights] if ws > 0 else [1.0 / n] * n
    avg: Mass = {}
    for m, w in zip(masses, wn):
        for a, v in m.items():
            avg[a] = avg.get(a, 0.0) + w * v
    avg = normalize(avg)
    out = avg
    for _ in range(n - 1):
        out = dempster_combine(out, avg)
    return out


def _popcount(x: int) -> int:
    return bin(x).count("1")


def jousselme_distance(m1: Mass, m2: Mass) -> float:
    """Jousselme证据距离 d=sqrt(0.5 (m1-m2)^T D (m1-m2))，D(A,B)=|A∩B|/|A∪B|。"""
    keys = sorted(set(m1) | set(m2))
    diff = [m1.get(a, 0.0) - m2.get(a, 0.0) for a in keys]
    acc = 0.0
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            inter = _popcount(a & b)
            union = _popcount(a | b)
            if union:
                acc += diff[i] * diff[j] * inter / union
    return math.sqrt(max(0.0, 0.5 * acc))


def belief(m: Mass, a: int) -> float:
    """Bel(A) = Σ_{B⊆A} m(B)。"""
    return sum(v for b, v in m.items() if b & ~a == 0)


def plausibility(m: Mass, a: int) -> float:
    return sum(v for b, v in m.items() if b & a != 0)


def pignistic(m: Mass) -> Dict[int, float]:
    """Pignistic概率 BetP(θ) = Σ_{A∋θ} m(A)/|A|。"""
    out = {s: 0.0 for s in SINGLETONS.values()}
    for a, v in m.items():
        k = _popcount(a)
        if k == 0:
            continue
        for s in out:
            if a & s:
                out[s] += v / k
    return out


def unknown_mass(m: Mass) -> float:
    return m.get(THETA, 0.0)


# 严重度权向量 w(θ)：安全=0，各风险类型可按场景调整
DEFAULT_SEVERITY = {1: 0.0, 2: 1.0, 4: 0.8, 8: 0.7, 16: 0.85, 32: 0.75}


def risk_index(m: Mass, severity: Dict[int, float] = None) -> float:
    """连续风险指数 R = Σ BetP(θ)·w(θ)，归一化到[0,1]。"""
    sev = severity or DEFAULT_SEVERITY
    bp = pignistic(m)
    wmax = max(sev.values()) or 1.0
    return sum(bp[s] * sev[s] for s in bp) / wmax
