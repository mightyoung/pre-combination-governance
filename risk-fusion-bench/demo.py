# -*- coding: utf-8 -*-
"""端到端玩具演示：场景生成 → 递归融合 → 连续风险轨迹 → 预警提前量。
同时对比对抗语义证据在 有/无 可靠性折扣下的污染程度（E9的雏形）。
运行: python demo.py
"""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from rfb import dst
from rfb.temporal import BeliefState, Evidence, risk_velocity, decide_level
from rfb.reliability import SourceReliability
from rfb.benchmark.generator import Scenario, lead_time


def run(adversarial_rate: float, use_reliability: bool) -> dict:
    sc = Scenario(seed=42)
    evs = sc.emit(adversarial_rate=adversarial_rate)
    bs = BeliefState(gamma=0.04)
    # 调节智能体：语义源(试用期后)与传感源的可靠性账户
    accounts = {}
    for ev in evs:
        sid = ev.source_id.replace("_ADV", "")
        if sid not in accounts:
            acc = SourceReliability(source_id=sid)
            acc.s, acc.f = (
                (60, 5) if not sid.startswith("llm") else (40, 10)
            )  # 模拟历史
            accounts[sid] = acc
        if use_reliability:
            # 语义源置信度偏高（过度自信），一致性中等
            c = 0.85 if sid.startswith("llm") else 0.75
            kappa = 0.7 if sid.startswith("llm") else 0.9
            ev.reliability = accounts[sid].weight(q=0.9, c=c, kappa=kappa, u=False)
        else:
            ev.reliability = 1.0  # 对照：满权重接入
        bs.step(ev)
    lt = lead_time(bs.history, sc.truth)
    # 轨迹RMSE
    import math

    err = [(h["R"] - sc.truth(h["t"])) ** 2 for h in bs.history]
    rmse = math.sqrt(sum(err) / len(err))
    final_level = decide_level(
        bs.B, bs.risk(), risk_velocity(bs.history), dst.unknown_mass(bs.B)
    )
    return {
        "lead_time": lt,
        "rmse": rmse,
        "final_R": bs.risk(),
        "final_level": final_level,
    }


if __name__ == "__main__":
    print("=== 干净场景（无对抗证据）===")
    r = run(0.0, True)
    print(
        f"预警提前量: {r['lead_time']:.1f}s | 轨迹RMSE: {r['rmse']:.3f} | 末端R: {r['final_R']:.2f} | 等级: {r['final_level']}"
    )

    print("\n=== 30%对抗语义证据，有可靠性折扣 ===")
    a = run(0.3, True)
    print(f"预警提前量: {a['lead_time']:.1f}s | 轨迹RMSE: {a['rmse']:.3f}")

    print("\n=== 30%对抗语义证据，无折扣（满权重）===")
    b = run(0.3, False)
    print(f"预警提前量: {b['lead_time']:.1f}s | 轨迹RMSE: {b['rmse']:.3f}")

    print(
        f"\n结论雏形（E9）：折扣使对抗场景RMSE {b['rmse']:.3f} → {a['rmse']:.3f}"
        f"（降低 {100 * (b['rmse'] - a['rmse']) / b['rmse']:.0f}%）"
    )
