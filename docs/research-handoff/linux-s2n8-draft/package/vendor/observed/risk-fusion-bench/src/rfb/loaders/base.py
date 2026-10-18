# -*- coding: utf-8 -*-
"""加载器基类：把异构数据源统一为规范观测元组流 + 初始BPA（论文7.2节语义接入层的参考实现）。

每条规范观测 (CanonicalObs) 对应论文的 SOSA 风格六元组：
  ⟨观测值, 单位, 生成时刻, 特征兴趣对象, 观测程序, 质量标记⟩
每个加载器同时实现 to_bpa()：把一个观测窗口映射为该流的初始BPA，
供模态智能体/场景装配器消费。
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@dataclass
class CanonicalObs:
    value: Sequence[float]  # 观测值向量（窗口内）
    unit: str  # 单位（多变量时为逗号分隔或 "mixed"）
    t_gen: float  # 生成时刻（相对秒）
    feature_of_interest: str  # 业务实体：设备/区域/流ID
    procedure: str  # 传感器/模型/版本（审计用）
    quality: Dict[str, float] = field(default_factory=dict)  # 缺失率/延迟/时钟偏差等


@dataclass(frozen=True)
class ScorerOnlyRecord:
    """Scorer-only metadata aligned to the loader's latest returned batch."""

    observation_index: int
    metadata: Mapping[str, Any]


_EMPTY_SCORER_METADATA: Mapping[str, Any] = MappingProxyType({})


def logistic(x: float, k: float = 1.0, x0: float = 0.0) -> float:
    return 1.0 / (1.0 + math.exp(-k * (x - x0)))


def deviation_to_bpa(
    score: float,
    prop_mask: int,
    safe_mask: int = 1,
    theta: int = 63,
    k: float = 2.0,
    x0: float = 2.0,
    max_commit: float = 0.85,
) -> Dict[int, float]:
    """把标准化偏离分数映射为该流的初始BPA。

    score: 偏离度（z分数量级，0=正常）。
    映射原则（论文5.1）：证据永不满额承诺——至少保留 1-max_commit 的质量给 Θ，
    正常时把质量给安全命题 S 而非 Θ（"证据主动支持安全"，见论文3章建模辩护）。
    """
    p_anom = logistic(score, k=k, x0=x0)  # 偏离越大越支持风险命题
    commit = max_commit
    m_risk = commit * p_anom
    m_safe = commit * (1.0 - p_anom)
    m_theta = 1.0 - m_risk - m_safe
    out = {}
    if m_risk > 1e-9:
        out[prop_mask] = m_risk
    if m_safe > 1e-9:
        out[safe_mask] = m_safe
    out[theta] = out.get(theta, 0.0) + m_theta
    s = sum(out.values())
    return {a: v / s for a, v in out.items()}


class BaseLoader:
    """加载器契约：子类实现 load() 与 window_score()。"""

    STREAM = "?"  # 流名
    PROP_MASK = 63  # 支持的主命题掩码（子类覆盖）
    PROCEDURE = "base/0"

    def load(self, *a, **kw) -> List[CanonicalObs]:
        raise NotImplementedError

    def _set_scorer_only_sidecar(
        self,
        observations: Sequence[CanonicalObs],
        metadata_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        """Publish scorer-only metadata for the most recently returned batch."""
        if len(observations) != len(metadata_rows):
            raise ValueError("sidecar metadata must align one-to-one with observations")
        records = []
        by_observation_id = {}
        for index, (observation, metadata) in enumerate(
            zip(observations, metadata_rows)
        ):
            frozen = MappingProxyType(dict(metadata))
            records.append(ScorerOnlyRecord(index, frozen))
            by_observation_id[id(observation)] = frozen
        self._scorer_only_records = tuple(records)
        self._scorer_only_by_observation_id = by_observation_id

    def scorer_only_sidecar(self) -> Tuple[ScorerOnlyRecord, ...]:
        """Return the explicit scorer-only sidecar for the last loaded batch."""
        return getattr(self, "_scorer_only_records", ())

    def scorer_only_metadata(self, observation: CanonicalObs) -> Mapping[str, Any]:
        """Return scorer-only metadata associated with one observation."""
        return getattr(self, "_scorer_only_by_observation_id", {}).get(
            id(observation), _EMPTY_SCORER_METADATA
        )

    def window_score(self, values) -> float:
        raise NotImplementedError

    def to_bpa(self, obs: CanonicalObs) -> Dict[int, float]:
        score = self.window_score(obs.value)
        bpa = deviation_to_bpa(score, self.PROP_MASK)
        # 质量差的观测：向Θ再折扣（连接器层质量标记直接生效，供调节智能体复核）
        q = obs.quality.get("completeness", 1.0)
        if q < 1.0:
            bpa = {a: v * q for a, v in bpa.items()}
            bpa[63] = bpa.get(63, 0.0) + (1.0 - q)
        return bpa
