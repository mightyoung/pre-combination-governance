# -*- coding: utf-8 -*-
"""数值验证命题1（有界影响）与命题2（指数遗忘）——论文附录A/B的实验佐证。
运行: python -m tests.test_props （在 risk-fusion-bench 目录下, 需 src 在 PYTHONPATH）
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb import dst
from rfb.temporal import BeliefState, Evidence


def test_prop1_bounded_influence():
    """|Bel(m0 ⊕ m_s^r)(A) - Bel(m0)(A)| ≤ C·r，且随r单调收缩、r=0不变。"""
    m0 = {2: 0.5, 4: 0.2, dst.THETA: 0.3}  # 现有组合：支持{H}
    m_adv = {16: 0.9, dst.THETA: 0.1}  # 对抗语义证据：强推{P}
    base = dst.belief(m0, 2)
    prev_dev = 1e9
    print("r      |ΔBel({H})|   |Δ|/r")
    for r in [1.0, 0.8, 0.6, 0.4, 0.2, 0.1, 0.05, 0.0]:
        fused = dst.dempster_combine(m0, dst.discount(m_adv, r))
        dev = abs(dst.belief(fused, 2) - base)
        ratio = dev / r if r > 0 else 0.0
        print(f"{r:4.2f}   {dev:10.4f}   {ratio:8.4f}")
        assert dev <= prev_dev + 1e-9, "扰动未随r单调收缩"
        prev_dev = dev
    assert prev_dev < 1e-12, "r=0 时组合应不变（空证据是单位元）"
    print("PASS 命题1：扰动随r单调收缩，r=0不变\n")


def test_prop2_exponential_forgetting():
    """错误证据并入后，其对信念状态的残余影响随时间指数衰减。"""
    gamma = 0.05
    bs_clean = BeliefState(gamma=gamma)
    bs_dirty = BeliefState(gamma=gamma)
    # 共同证据流
    for t in range(0, 10):
        ev = Evidence(m={1: 0.5, dst.THETA: 0.5}, t_gen=float(t))
        bs_clean.step(ev)
        bs_dirty.step(ev)
    # t=10 注入错误证据（仅dirty）
    bs_dirty.step(Evidence(m={16: 0.9, dst.THETA: 0.1}, t_gen=10.0))
    bs_clean.coast(10.0)
    print("t      影响|ΔR|      e^{-γ(t-10)}")
    prev = 1e9
    for t in range(11, 101, 10):
        ev = Evidence(m={1: 0.5, dst.THETA: 0.5}, t_gen=float(t))
        bs_clean.step(ev)
        bs_dirty.step(ev)
        d = abs(bs_dirty.risk() - bs_clean.risk())
        bound = math.exp(-gamma * (t - 10))
        print(f"{t:4d}   {d:10.5f}   {bound:10.5f}")
        assert d <= prev + 1e-9, "影响未衰减"
        prev = d
    assert prev < 0.02, "100单位时间后残余影响应接近0"
    print("PASS 命题2：错误证据影响指数消退\n")


def test_late_evidence_discounted():
    """迟到证据"折扣到当下"：同一证据迟到越久，扰动越小。"""

    def run(late: float) -> float:
        bs = BeliefState(gamma=0.05)
        for t in range(0, 20):
            bs.step(Evidence(m={1: 0.5, dst.THETA: 0.5}, t_gen=float(t)))
        r_before = bs.risk()
        bs.step(Evidence(m={16: 0.9, dst.THETA: 0.1}, t_gen=19.0 - late), t_arrive=19.5)
        return abs(bs.risk() - r_before)

    print("迟到Δ    扰动|ΔR|")
    prev = 1e9
    for late in [0.0, 5.0, 20.0, 60.0]:
        d = run(late)
        print(f"{late:5.0f}   {d:10.5f}")
        assert d <= prev + 1e-9
        prev = d
    print("PASS 迟到证据：延迟越久影响越小\n")


if __name__ == "__main__":
    test_prop1_bounded_influence()
    test_prop2_exponential_forgetting()
    test_late_evidence_discounted()
    print("全部数值验证通过。")
