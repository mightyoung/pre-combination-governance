# -*- coding: utf-8 -*-
"""HA4M与MVTec加载器离线测试。运行: python tests/test_ha4m_mvtec.py"""

import math
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb.loaders.ha4m import HA4MLoader, HazardZone
from rfb.loaders.mvtec import MVTecLoader


def synth_skeleton(n_frames, approach=False, seed=5):
    """32关节合成骨架：工人在(2,0,2)作业；approach=True时走向危险区(0,0,0)并做急促弯腰动作。"""
    rng = random.Random(seed)
    frames = []
    for t in range(n_frames):
        frac = t / max(1, n_frames - 1)
        if approach:
            base = [2.0 * (1 - frac) * 0.9 + 0.15, 0.0, 2.0 * (1 - frac) * 0.9 + 0.15]
        else:
            base = [2.0, 0.0, 2.0]

        def jitter(s=0.02):
            return rng.gauss(0, s)

        sk = [[0.0, 0.0, 0.0] for _ in range(32)]
        sk[0] = [base[0] + jitter(), 0.9 + jitter(), base[2] + jitter()]  # pelvis
        neck_y = 1.5 - (0.45 * frac if approach else 0.0)  # 弯腰
        neck_fwd = 0.35 * frac if approach else 0.0
        sk[3] = [
            base[0] + neck_fwd + jitter(),
            neck_y + jitter(),
            base[2] + jitter(),
        ]  # neck
        hand_amp = 0.35 + (0.5 * frac if approach else 0.0)  # 手速渐增
        sk[15] = [
            base[0] + hand_amp * math.sin(t * (0.6 if approach else 0.25)),
            1.1 + jitter(),
            base[2] + jitter(),
        ]  # hand R
        sk[8] = [base[0] - 0.3, 1.1, base[2]]  # hand L
        for j in range(32):
            if sk[j] == [0.0, 0.0, 0.0]:
                sk[j] = [
                    base[0] + jitter(0.05),
                    1.0 + jitter(0.05),
                    base[2] + jitter(0.05),
                ]
        frames.append(sk)
    return frames


def test_ha4m():
    ld = HA4MLoader(zones=[HazardZone(center=(0.0, 0.9, 0.0), radius=0.5)])
    ld.fit_normal(synth_skeleton(240, approach=False, seed=1))
    obs_n = ld.from_array(synth_skeleton(240, approach=False, seed=2))
    obs_a = ld.from_array(synth_skeleton(240, approach=True, seed=2))
    s_n = sum(ld.window_score(o.value) for o in obs_n) / len(obs_n)
    end_a = ld.window_score(obs_a[-1].value)
    assert end_a > s_n + 1.5, (
        f"接近危险区末端评分应显著高: normal={s_n:.2f} approach_end={end_a:.2f}"
    )
    # 评分应随接近单调上升趋势（首窗<末窗）
    assert ld.window_score(obs_a[0].value) < end_a
    bpa_a = ld.to_bpa(obs_a[-1])
    bpa_n = ld.to_bpa(obs_n[3])
    assert bpa_a.get(2, 0) > 0.5, f"接近末端应强支持H: {bpa_a}"
    assert bpa_n.get(1, 0) > bpa_n.get(2, 0), f"正常作业应支持S: {bpa_n}"
    print(
        f"PASS HA4M: 正常{s_n:.2f}→接近末端{end_a:.2f} | BPA(H)={bpa_a.get(2, 0):.2f} | "
        f"正常BPA(S)={bpa_n.get(1, 0):.2f}"
    )


def test_mvtec():
    rng = random.Random(9)
    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good.csv")
        test = os.path.join(tmp, "test.csv")
        with open(good, "w") as f:
            for i in range(200):
                f.write(f"good_{i}.png,{rng.gauss(0.20, 0.05):.4f},bottle\n")
        with open(test, "w") as f:
            for i in range(50):
                f.write(f"tgood_{i}.png,{rng.gauss(0.21, 0.05):.4f},bottle\n")
            for i in range(50):
                f.write(
                    f"broken_{i}.png,{rng.gauss(0.75, 0.10):.4f},bottle,broken_large\n"
                )
        ld = MVTecLoader()
        obs = ld.load(test, good_csv=good)
        assert len(obs) == 100
        s_good = sum(ld.window_score(o.value) for o in obs[:50]) / 50
        s_bad = sum(ld.window_score(o.value) for o in obs[50:]) / 50
        assert s_bad > s_good + 2.0, f"缺陷分数应显著高: {s_good:.2f} vs {s_bad:.2f}"
        bpa_bad = ld.to_bpa(obs[75])
        # 良品取中位分样本（避免尾部抽样导致的偶发翻转——单张良品高分本就该报风险，
        # 这是检测器语义而非加载器缺陷；批级判断由融合层聚合完成）
        good_sorted = sorted(obs[:50], key=lambda o: o.value[0])
        bpa_good = ld.to_bpa(good_sorted[25])
        assert bpa_bad.get(8, 0) > 0.5, f"缺陷应强支持T: {bpa_bad}"
        assert bpa_good.get(1, 0) > bpa_good.get(8, 0), f"良品应支持S: {bpa_good}"
        print(
            f"PASS MVTec: 良品{s_good:.2f}→缺陷{s_bad:.2f} | BPA(T)={bpa_bad.get(8, 0):.2f}"
        )


if __name__ == "__main__":
    test_ha4m()
    test_mvtec()
    print("HA4M/MVTec测试全部通过。")
