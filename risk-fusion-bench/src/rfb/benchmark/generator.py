# -*- coding: utf-8 -*-
"""半合成基准的玩具版场景生成器（论文6章的最小可用实现）。

状态机驱动 正常→偏离→退化→耦合→失控 的连续演化，输出：
- 连续风险真值轨迹 R*(t)
- 各证据源的异步BPA消息流（含噪声、延迟、乱序、语义幻觉注入）
正式版TODO：接入HA4M/XJTU-SY/TEP/MVTec-AD真实片段替换合成信号，
按元素编码（H07/E05/N02…）组织变量，见README路线图M2。
"""

from __future__ import annotations
import hashlib
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .. import dst
from ..temporal import Evidence

PHASES = ["normal", "deviation", "degradation", "coupled", "critical"]
PHASE_RISK = {
    "normal": 0.05,
    "deviation": 0.25,
    "degradation": 0.45,
    "coupled": 0.70,
    "critical": 0.92,
}


def _derive_substream_seed(seed: int, stream: str) -> int:
    """Derive stable, disjoint PRNG seeds from a user-visible seed."""
    payload = f"rfb-scenario-v2|{stream}|{int(seed)}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


@dataclass
class Scenario:
    seed: int = 0
    duration: float = 300.0  # 秒
    dt_truth: float = 1.0
    phase_bounds: List[float] = field(default_factory=lambda: [120, 180, 230, 270])
    # Added after the legacy fields so Scenario(seed, duration) remains valid.
    physical_seed: Optional[int] = None
    noise_seed: Optional[int] = None
    _physical_phase_bounds: List[float] = field(init=False, repr=False)
    _physical_phase_risk: Dict[str, float] = field(init=False, repr=False)

    def __post_init__(self):
        """Freeze one physical trajectory independently of observation noise."""
        self.physical_seed = (
            self.seed if self.physical_seed is None else int(self.physical_seed)
        )
        self.noise_seed = self.seed if self.noise_seed is None else int(self.noise_seed)

        if self.duration <= 0 or self.dt_truth <= 0:
            raise ValueError("duration and dt_truth must be positive")
        if len(self.phase_bounds) != len(PHASES) - 1:
            raise ValueError(f"phase_bounds must contain {len(PHASES) - 1} entries")
        if any(b <= 0 or b >= self.duration for b in self.phase_bounds):
            raise ValueError("phase_bounds must lie strictly inside (0, duration)")
        if any(a >= b for a, b in zip(self.phase_bounds, self.phase_bounds[1:])):
            raise ValueError("phase_bounds must be strictly increasing")

        physical_rng = random.Random(
            _derive_substream_seed(self.physical_seed, "physical")
        )

        # Treat the public phase bounds as nominal durations. The physical
        # substream perturbs each duration and renormalizes the full trajectory
        # to the requested total duration, preserving ordered positive phases.
        nominal_edges = [0.0, *map(float, self.phase_bounds), float(self.duration)]
        nominal_durations = [
            nominal_edges[i + 1] - nominal_edges[i] for i in range(len(PHASES))
        ]
        perturbed = [
            width * physical_rng.uniform(0.85, 1.15) for width in nominal_durations
        ]
        scale = self.duration / sum(perturbed)
        actual_durations = [width * scale for width in perturbed]
        running = 0.0
        self._physical_phase_bounds = []
        for width in actual_durations[:-1]:
            running += width
            self._physical_phase_bounds.append(running)

        # A trajectory-level gain and offset vary physical severity while
        # retaining the monotone ordering of the nominal phase risks.
        risk_gain = physical_rng.uniform(0.92, 1.08)
        risk_offset = physical_rng.uniform(-0.02, 0.02)
        self._physical_phase_risk = {
            phase: min(0.99, max(0.01, PHASE_RISK[phase] * risk_gain + risk_offset))
            for phase in PHASES
        }

    def phase_at(self, t: float) -> str:
        for i, b in enumerate(self._physical_phase_bounds):
            if t < b:
                return PHASES[i]
        return PHASES[-1]

    def truth(self, t: float) -> float:
        """R*(t)：相内线性插值的连续真值轨迹。"""
        ph = self.phase_at(t)
        i = PHASES.index(ph)
        lo = ([0.0] + self._physical_phase_bounds)[i]
        hi = (self._physical_phase_bounds + [self.duration])[i]
        r0 = self._physical_phase_risk[ph]
        r1 = self._physical_phase_risk[PHASES[min(i + 1, 4)]]
        frac = (t - lo) / max(1e-9, hi - lo)
        return r0 + (r1 - r0) * frac * 0.6  # 相内向下一相渐进

    def emit(self, adversarial_rate: float = 0.0) -> List[Evidence]:
        """生成异步证据流。adversarial_rate: 语义源幻觉注入比例（E9压力测试）。"""
        rng = random.Random(_derive_substream_seed(self.noise_seed, "noise"))
        evs: List[Evidence] = []
        # 五个流智能体：不同节拍
        sources = [
            ("human_T5", 5.0, 2),  # (源, 周期s, 主命题掩码H)
            ("machine_T1", 2.0, 4),
            ("material_T5", 10.0, 8),
            ("process_T3", 3.0, 16),
            ("env_T3", 8.0, 32),
        ]
        for sid, period, prop in sources:
            t = rng.uniform(0, period)
            while t < self.duration:
                rstar = self.truth(t)
                # 越接近失控，该流越可能报异常（简化耦合：coupled后人/机/工艺同时异常）
                p_anom = min(0.95, rstar + rng.gauss(0, 0.05))
                if rng.random() < p_anom:
                    m = {prop: 0.5 + 0.3 * rstar, dst.THETA: 0.5 - 0.3 * rstar}
                else:
                    m = {1: 0.6, dst.THETA: 0.4}  # 支持安全S
                evs.append(Evidence(m=dst.normalize(m), t_gen=t, source_id=sid))
                t += period * rng.uniform(0.8, 1.2)
        # LLM跨流语义智能体：低频，支持复合焦元；可注入幻觉
        t = 15.0
        while t < self.duration:
            rstar = self.truth(t)
            hallucinate = rng.random() < adversarial_rate
            if hallucinate:
                m = (
                    {2 | 16: 0.85, dst.THETA: 0.15}
                    if rstar < 0.3
                    else {1: 0.85, dst.THETA: 0.15}
                )
            elif rstar > 0.5:
                m = {2 | 16: 0.45, 4: 0.15, dst.THETA: 0.40}  # 支持{H,P}耦合
            else:
                m = {1: 0.4, dst.THETA: 0.6}
            # 台账/语义证据可能迟到（乱序注入）
            evs.append(
                Evidence(
                    m=dst.normalize(m),
                    t_gen=t,
                    source_id="llm_T7" + ("_ADV" if hallucinate else ""),
                )
            )
            t += 20.0 * rng.uniform(0.7, 1.3)
        evs.sort(key=lambda e: e.t_gen)
        return evs


def lead_time(history, truth_fn, theta_w: float = 0.6, level3_r: float = 0.75):
    """预警提前量：R(t)首次越过θ_w 到 R*(t)首次达Level3 的时间差。"""
    t_warn = next((h["t"] for h in history if h["R"] > theta_w), None)
    t_star, t = None, 0.0
    while t < 10000:
        if truth_fn(t) >= level3_r:
            t_star = t
            break
        t += 0.5
    if t_warn is None or t_star is None:
        return None
    return t_star - t_warn
