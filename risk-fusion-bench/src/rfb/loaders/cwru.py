# -*- coding: utf-8 -*-
"""CWRU轴承加载器：凯斯西储轴承振动数据 → 机流规范观测 + {M}类初始BPA。

数据来源（免费直下，无需申请）：
  https://engineering.case.edu/bearingdatacenter/download-data-file
  .mat格式，字段名形如 X097_DE_time（驱动端）/ X097_FE_time（风扇端）。
  正常：97-100.mat；故障：内圈/外圈/滚动体 × 0.007/0.014/0.021英寸 × 多工况。
  采样率12kHz（部分48kHz）。XJTU-SY到货后经 from_array() 平替（全寿命退化，
  更适合E15连续趋势——CWRU为分类式故障，先行支撑E1—E5b）。

特征与评分：窗口内计算 RMS、峭度、峰值因子、包络峰值比 四个经典指标，
在正常数据上拟合基线，马氏化z分数均值为偏离度。刻意保持无学习检测器，
深度模型（如一维CNN）作为模态内分析层升级项在E3引入。
"""

from __future__ import annotations
import math
import os
from typing import List, Optional, Sequence

from .base import BaseLoader, CanonicalObs

FS_DEFAULT = 12000.0
WINDOW = 2048  # 约0.17s/窗


def _features(x: Sequence[float]) -> List[float]:
    n = len(x)
    mu = sum(x) / n
    xc = [v - mu for v in x]
    rms = math.sqrt(sum(v * v for v in xc) / n)
    rms = max(rms, 1e-12)
    kurt = (sum(v**4 for v in xc) / n) / (rms**4)  # 峭度（正常≈3，冲击故障↑）
    peak = max(abs(v) for v in xc)
    crest = peak / rms  # 峰值因子
    # 简化包络指标：整流信号的峰均比（避免依赖scipy hilbert）
    env = [abs(v) for v in xc]
    env_pm = max(env) / (sum(env) / n + 1e-12)
    return [rms, kurt, crest, env_pm]


def read_mat_signal(path: str, channel: str = "DE") -> List[float]:
    """读取CWRU .mat文件中的时域信号（需scipy；无scipy环境请用from_array）。"""
    from scipy.io import loadmat  # 延迟导入

    d = loadmat(path)
    keys = [k for k in d.keys() if k.endswith(f"_{channel}_time")]
    assert keys, f"{path} 中未找到 *_{channel}_time 字段，可用: {list(d.keys())}"
    return [float(v) for v in d[keys[0]].ravel()]


class CWRULoader(BaseLoader):
    STREAM = "machine"
    PROP_MASK = 4  # {M} 设备风险
    PROCEDURE = "cwru-vib-stats/0.1"

    def __init__(self, fs: float = FS_DEFAULT, window: int = WINDOW):
        self.fs = fs
        self.window = window
        self.mu: Optional[List[float]] = None
        self.sd: Optional[List[float]] = None

    def _windows(self, signal: Sequence[float]) -> List[List[float]]:
        w = self.window
        return [list(signal[i : i + w]) for i in range(0, len(signal) - w + 1, w)]

    def fit_normal(self, normal_signal: Sequence[float]):
        """在正常轴承信号上拟合四特征基线。"""
        feats = [_features(w) for w in self._windows(normal_signal)]
        assert len(feats) > 10, "正常信号过短"
        k = 4
        self.mu = [sum(f[j] for f in feats) / len(feats) for j in range(k)]
        self.sd = [
            max(
                1e-9,
                math.sqrt(
                    sum((f[j] - self.mu[j]) ** 2 for f in feats) / (len(feats) - 1)
                ),
            )
            for j in range(k)
        ]

    def from_array(
        self,
        signal: Sequence[float],
        device_id: str = "bearing-1",
        t0: float = 0.0,
        label: str = "",
    ) -> List[CanonicalObs]:
        assert self.mu is not None, "先调用 fit_normal()"
        obs = []
        dt = self.window / self.fs
        for i, w in enumerate(self._windows(signal)):
            obs.append(
                CanonicalObs(
                    value=w,
                    unit="g(accel)",
                    t_gen=t0 + (i + 1) * dt,
                    feature_of_interest=device_id,
                    procedure=self.PROCEDURE,
                    quality={"completeness": 1.0, "fs_hz": self.fs},
                )
            )
        metadata = {"label": label} if label else {}
        self._set_scorer_only_sidecar(obs, [metadata for _ in obs])
        return obs

    def load(
        self,
        normal_mat: str,
        target_mat: str,
        channel: str = "DE",
        device_id: str = "bearing-1",
    ) -> List[CanonicalObs]:
        self.fit_normal(read_mat_signal(normal_mat, channel))
        label = os.path.basename(target_mat)
        obs = self.from_array(
            read_mat_signal(target_mat, channel), device_id=device_id, label=label
        )
        metadata_rows = []
        for observation in obs:
            metadata = dict(self.scorer_only_metadata(observation))
            metadata.update(
                {
                    "source_path": target_mat,
                    "source_filename": label,
                    "normal_source_path": normal_mat,
                    "normal_source_filename": os.path.basename(normal_mat),
                    "channel": channel,
                }
            )
            metadata_rows.append(metadata)
        self._set_scorer_only_sidecar(obs, metadata_rows)
        return obs

    def window_score(self, values: Sequence[float]) -> float:
        f = _features(values)
        zs = [abs((f[j] - self.mu[j]) / self.sd[j]) for j in range(4)]
        # 峭度与峰值因子对轴承冲击故障最敏感，加权平均
        wgt = [0.2, 0.35, 0.25, 0.2]
        return sum(z * w for z, w in zip(zs, wgt)) / sum(wgt) * 0.8
