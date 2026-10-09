# -*- coding: utf-8 -*-
"""加载器离线测试：用合成fixture模拟TEP与UCI气体数据格式，不依赖真实下载。
运行: python tests/test_loaders.py
"""

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rfb.loaders.tep import TEPLoader, _read_dat, N_VARS
from rfb.loaders.gas import GasLoader, parse_libsvm_line


def make_tep_fixture(tmp):
    """合成d00（正常）与d01_te（第160采样后注入均值漂移故障）。"""
    rng = random.Random(7)

    def rows(n, shift=0.0, onset=0):
        out = []
        for i in range(n):
            s = shift if i >= onset else 0.0
            out.append(
                [
                    rng.gauss(10 + j * 0.1 + (s if j < 8 else 0), 1.0)
                    for j in range(N_VARS)
                ]
            )
        return out

    with open(os.path.join(tmp, "d00.dat"), "w") as f:
        for r in rows(480):
            f.write(" ".join(f"{v:.5f}" for v in r) + "\n")
    with open(os.path.join(tmp, "d01_te.dat"), "w") as f:
        for r in rows(960, shift=6.0, onset=160):
            f.write(" ".join(f"{v:.5f}" for v in r) + "\n")


def test_tep():
    with tempfile.TemporaryDirectory() as tmp:
        make_tep_fixture(tmp)
        ld = TEPLoader()
        obs = ld.load(tmp, fault=1, split="test", window=4)
        assert len(obs) == 240, f"窗口数 {len(obs)}"
        # 故障前窗口（前160采样=前40窗）应低偏离/支持S；故障后应高偏离/支持{P}
        pre = [ld.window_score(o.value) for o in obs[:35]]
        post = [ld.window_score(o.value) for o in obs[45:]]
        assert sum(pre) / len(pre) < 2.0 < sum(post) / len(post), (
            f"pre={sum(pre) / len(pre):.2f} post={sum(post) / len(post):.2f}"
        )
        bpa_pre = ld.to_bpa(obs[10])
        bpa_post = ld.to_bpa(obs[100])
        assert bpa_pre.get(1, 0) > bpa_pre.get(16, 0), "故障前应支持S"
        assert bpa_post.get(16, 0) > 0.5, f"故障后应强支持P: {bpa_post}"
        assert abs(sum(bpa_post.values()) - 1) < 1e-9
        # 转置怪癖测试
        with open(os.path.join(tmp, "t.dat"), "w") as f:
            for j in range(N_VARS):
                f.write(" ".join("1.0" for _ in range(500)) + "\n")
        assert len(_read_dat(os.path.join(tmp, "t.dat"))) == 500
        print(
            f"PASS TEP: 240窗 | 故障前评分{sum(pre) / len(pre):.2f}→后{sum(post) / len(post):.2f} | "
            f"故障后BPA(P)={bpa_post.get(16, 0):.2f}"
        )


def make_gas_fixture(tmp):
    rng = random.Random(11)

    def batch(path, conc_scale):
        with open(path, "w") as f:
            for _ in range(300):
                cls = rng.randint(1, 6)
                conc = rng.uniform(10, 100) * conc_scale
                feats = " ".join(f"{i + 1}:{rng.gauss(0, 1):.4f}" for i in range(128))
                f.write(f"{cls};{conc:.2f} {feats}\n")

    batch(os.path.join(tmp, "batch1.dat"), 1.0)  # 基线
    batch(os.path.join(tmp, "batch2.dat"), 3.0)  # 浓度整体抬升（模拟危险积聚）


def test_gas():
    with tempfile.TemporaryDirectory() as tmp:
        make_gas_fixture(tmp)
        ld = GasLoader()
        obs1 = ld.load(tmp, batch=1)
        obs2 = ld.load(tmp, batch=2)
        s1 = sum(ld.window_score(o.value) for o in obs1) / len(obs1)
        s2 = sum(ld.window_score(o.value) for o in obs2) / len(obs2)
        assert s2 > s1 + 0.5, f"高浓度批次评分应显著更高: {s1:.2f} vs {s2:.2f}"
        high = max(obs2, key=lambda o: ld.window_score(o.value))
        bpa = ld.to_bpa(high)
        assert bpa.get(32, 0) > 0.4, f"高浓度应支持E: {bpa}"
        # 解析健壮性：无浓度格式
        r = parse_libsvm_line("3 1:0.5 2:0.7")
        assert r[0] == 3 and r[1] != r[1]
        print(
            f"PASS GAS: 基线评分{s1:.2f}→漂移批次{s2:.2f} | 峰值BPA(E)={bpa.get(32, 0):.2f}"
        )


def test_bpa_feeds_fusion():
    """端到端衔接：加载器BPA能直接进入融合核心。"""
    with tempfile.TemporaryDirectory() as tmp:
        make_tep_fixture(tmp)
        ld = TEPLoader()
        obs = ld.load(tmp, fault=1, split="test", window=4)
        from rfb.temporal import BeliefState, Evidence

        bs = BeliefState(gamma=0.001)  # TEP窗间隔720s，遗忘率对应调低
        for o in obs[::10]:
            bs.step(Evidence(m=ld.to_bpa(o), t_gen=o.t_gen, reliability=0.8))
        assert bs.risk() > 0.4, f"故障场景末端风险指数应升高: {bs.risk():.2f}"
        print(f"PASS 端到端: TEP故障流 → 融合核心 → 末端R={bs.risk():.2f}")


if __name__ == "__main__":
    test_tep()
    test_gas()
    test_bpa_feeds_fusion()
    print("加载器测试全部通过。")
