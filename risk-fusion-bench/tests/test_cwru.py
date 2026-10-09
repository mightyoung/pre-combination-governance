# -*- coding: utf-8 -*-
"""CWRU加载器离线测试：合成振动信号（正常=平稳噪声+转频正弦；故障=叠加周期冲击）。
运行: python tests/test_cwru.py
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb.loaders.cwru import CWRULoader
from rfb.temporal import BeliefState, Evidence

FS = 12000.0


def synth(n_sec=6.0, fault=False, seed=3):
    rng = random.Random(seed)
    n = int(n_sec * FS)
    sig = []
    for i in range(n):
        t = i / FS
        v = 0.3 * math.sin(2 * math.pi * 29.95 * t) + rng.gauss(0, 0.08)  # 转频+噪声
        if fault and (i % 111) < 3:  # 内圈故障特征频率量级的周期冲击
            v += rng.uniform(1.2, 2.2) * (1 if rng.random() > 0.5 else -1)
        sig.append(v)
    return sig


def test_cwru():
    ld = CWRULoader()
    ld.fit_normal(synth(fault=False, seed=1))
    normal_obs = ld.from_array(synth(fault=False, seed=2), label="normal")
    fault_obs = ld.from_array(synth(fault=True, seed=2), label="IR007-synth")
    s_n = sum(ld.window_score(o.value) for o in normal_obs) / len(normal_obs)
    s_f = sum(ld.window_score(o.value) for o in fault_obs) / len(fault_obs)
    assert s_f > s_n + 1.5, f"故障评分应显著高: normal={s_n:.2f} fault={s_f:.2f}"
    bpa_n = ld.to_bpa(normal_obs[5])
    bpa_f = ld.to_bpa(fault_obs[5])
    assert bpa_n.get(1, 0) > bpa_n.get(4, 0), f"正常应支持S: {bpa_n}"
    assert bpa_f.get(4, 0) > 0.5, f"故障应强支持M: {bpa_f}"
    assert abs(sum(bpa_f.values()) - 1) < 1e-9
    print(
        f"PASS CWRU: 正常评分{s_n:.2f}→故障{s_f:.2f} | 故障BPA(M)={bpa_f.get(4, 0):.2f} | "
        f"正常BPA(S)={bpa_n.get(1, 0):.2f}"
    )

    # 端到端：退化剧本（正常→轻微→严重冲击）喂给融合核心，验证R(t)单调抬升
    bs = BeliefState(gamma=0.5)  # 振动窗0.17s，遗忘率相应调高
    phases = [synth(2.0, fault=False, seed=4), synth(2.0, fault=True, seed=5)]
    t0, risks = 0.0, []
    for ph, sig in enumerate(phases):
        for o in ld.from_array(sig, t0=t0)[::4]:
            bs.step(Evidence(m=ld.to_bpa(o), t_gen=o.t_gen, reliability=0.85))
        t0 = bs.t + 0.2
        risks.append(bs.risk())
    assert risks[1] > risks[0] + 0.2, f"退化后风险应抬升: {risks}"
    print(f"PASS 端到端: 正常段R={risks[0]:.2f} → 故障段R={risks[1]:.2f}")


if __name__ == "__main__":
    test_cwru()
    print("CWRU测试全部通过。")
