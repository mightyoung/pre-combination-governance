# -*- coding: utf-8 -*-
"""调节智能体：可靠性权重与冷启动协议（论文4.4节）。

r_i = min{ r̄_i(k), w1·q + w2·c̃ + w3·κ + w4·(1-u) }
r̄_i(k) = min{ r_cap(k), (a0+s_k)/(a0+b0+k) }   —— 保守Beta先验 + 试用期上限
约束：本模块只含声明的可计算函数，任何生成式模型无权直接改 r_i。
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Calibrator:
    """置信度校准 c̃=φ(c)。骨架实现为温度缩放；正式版在验证集上拟合T，
    或替换为保形预测。离线更新，经变更管理生效（论文4.4镣铐之二）。"""

    temperature: float = 1.5

    def __call__(self, c: float) -> float:
        import math

        c = min(max(c, 1e-6), 1 - 1e-6)
        logit = math.log(c / (1 - c)) / self.temperature
        return 1 / (1 + math.exp(-logit))


@dataclass
class SourceReliability:
    """单个证据源的可靠性账户（含冷启动）。"""

    source_id: str
    a0: float = 1.0  # Beta先验（保守：a0 << b0）
    b0: float = 9.0
    r_probe: float = 0.3  # 试用期硬上限
    probation: int = 50  # 试用期长度（可复核判定次数）
    s: int = 0  # 复核确认正确次数
    f: int = 0  # 复核确认错误次数
    weights: tuple = (0.3, 0.3, 0.2, 0.2)  # w1..w4，验证集上以高风险召回为目标搜索
    calibrator: Calibrator = field(default_factory=Calibrator)

    @property
    def k(self) -> int:
        return self.s + self.f

    def cap(self) -> float:
        beta_mean = (self.a0 + self.s) / (self.a0 + self.b0 + self.k)
        hard = self.r_probe if self.k < self.probation else 1.0
        return min(hard, beta_mean if self.k > 0 else self.a0 / (self.a0 + self.b0))

    def weight(self, q: float, c: float, kappa: float, u: bool) -> float:
        """q:输入质量(来自连接器质量标记) c:原始置信 kappa:采样一致性 u:不确定性标记"""
        w1, w2, w3, w4 = self.weights
        base = w1 * q + w2 * self.calibrator(c) + w3 * kappa + w4 * (0.0 if u else 1.0)
        return max(0.0, min(self.cap(), base))

    def feedback(self, correct: bool):
        """复核回流（PROV-O留痕在正式版实现）。"""
        if correct:
            self.s += 1
        else:
            self.f += 1


def conflict_second_discount(
    r: float, d_bar: float, tau: float = 0.5, rho: float = 0.6, lam: float = 2.0
) -> float:
    """冲突二次折扣：d̄>τ 且 r<ρ 时 r ← r·exp(-λ(d̄-τ))（论文5.1）。"""
    import math

    if d_bar > tau and r < rho:
        return r * math.exp(-lam * (d_bar - tau))
    return r
