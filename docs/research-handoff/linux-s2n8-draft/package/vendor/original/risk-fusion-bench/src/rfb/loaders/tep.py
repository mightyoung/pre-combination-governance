# -*- coding: utf-8 -*-
"""TEP加载器：Tennessee Eastman过程数据 → 法/工艺流规范观测 + {P}类初始BPA。

支持两种数据来源（自动识别）：
1. 经典 .dat 格式（d00.dat…d21.dat / d00_te.dat…d21_te.dat）：
   来源 https://web.mit.edu/braatzgroup/links.html 或
   https://github.com/mv-per/tennessee-eastman-dataset （CSV整理版）
   训练文件 480/500 行 × 52 列；测试文件 960 行 × 52 列，故障自第160个采样注入。
2. 通用 CSV/ndarray：行=采样（3分钟间隔），列=52个过程变量（XMEAS1-41 + XMV1-11）。

获取指引（W2执行时）：
  经典版直下无需申请；扩展版 Rieth 2017 在 Harvard Dataverse doi:10.7910/DVN/6C3JR1
  （.RData格式，用 pyreadr 读取，本加载器 from_array() 直接吃转换后的数组）。

偏离评分：在正常段（d00训练数据）上拟合均值/协方差对角，窗口z分数的
上分位数作为偏离度——刻意选择最简单可解释的检测器作为初始证据，
更强的检测器（PCA-T²/SPE、TCN分类器）在E3/E5作为模态内分析层升级项。
"""

from __future__ import annotations
import os
import math
from typing import List, Optional, Sequence

from .base import BaseLoader, CanonicalObs

SAMPLE_INTERVAL_S = 180.0  # TEP采样间隔3分钟
N_VARS = 52
FAULT_ONSET_TEST = 160  # 测试集故障注入点（第160个采样后）


def _read_dat(path: str) -> List[List[float]]:
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.replace(",", " ").split()
            if not parts:
                continue
            try:
                rows.append([float(x) for x in parts])
            except ValueError:
                continue  # 跳过表头
    # d00.dat 的历史怪癖：52行×500列（转置存储），检测并纠正
    if rows and len(rows) == N_VARS and len(rows[0]) > N_VARS:
        rows = [list(col) for col in zip(*rows)]
    return rows


class TEPLoader(BaseLoader):
    STREAM = "process"
    PROP_MASK = 16  # {P} 工艺风险
    PROCEDURE = "tep-zscore-detector/0.1"

    def __init__(self):
        self.mu: Optional[List[float]] = None
        self.sd: Optional[List[float]] = None

    # ---------- 基线拟合 ----------
    def fit_normal(self, rows: Sequence[Sequence[float]]):
        """在正常工况数据（d00）上拟合逐变量均值与标准差。"""
        n = len(rows)
        assert n > 10, "正常段样本过少"
        k = len(rows[0])
        mu = [sum(r[j] for r in rows) / n for j in range(k)]
        sd = [
            max(1e-9, math.sqrt(sum((r[j] - mu[j]) ** 2 for r in rows) / (n - 1)))
            for j in range(k)
        ]
        self.mu, self.sd = mu, sd

    def fit_normal_from_file(self, d00_path: str):
        self.fit_normal(_read_dat(d00_path))

    # ---------- 加载 ----------
    def from_array(
        self,
        rows: Sequence[Sequence[float]],
        window: int = 4,
        unit_id: str = "TEP-unit",
        t0: float = 0.0,
        fault_label: Optional[int] = None,
        simulation_run_id: Optional[str] = None,
    ) -> List[CanonicalObs]:
        """任意来源的TEP数组 → 窗口化规范观测（window个采样=12分钟/窗默认）。"""
        assert self.mu is not None, "先调用 fit_normal()"
        obs = []
        for i in range(0, len(rows) - window + 1, window):
            chunk = rows[i : i + window]
            flat = [v for r in chunk for v in r]
            miss = sum(1 for v in flat if v != v)  # NaN计数
            obs.append(
                CanonicalObs(
                    value=[v for r in chunk for v in r],
                    unit="mixed(temp/pressure/flow)",
                    t_gen=t0 + (i + window) * SAMPLE_INTERVAL_S,
                    feature_of_interest=unit_id,
                    procedure=self.PROCEDURE,
                    quality={
                        "completeness": 1.0 - miss / max(1, len(flat)),
                        "sample_interval_s": SAMPLE_INTERVAL_S,
                    },
                )
            )
        metadata = {}
        if fault_label is not None:
            metadata["fault_label"] = fault_label
        if simulation_run_id is not None:
            metadata["simulation_run_id"] = simulation_run_id
        self._set_scorer_only_sidecar(obs, [metadata for _ in obs])
        return obs

    def load(
        self,
        data_dir: str,
        fault: int = 0,
        split: str = "test",
        window: int = 4,
        simulation_run_id: Optional[str] = None,
    ) -> List[CanonicalObs]:
        """从经典.dat目录加载指定故障场景。fault=0为正常。"""
        name = f"d{fault:02d}" + ("_te" if split == "test" else "") + ".dat"
        rows = _read_dat(os.path.join(data_dir, name))
        if self.mu is None:
            d00 = os.path.join(data_dir, "d00.dat")
            assert os.path.exists(d00), "缺少d00.dat用于基线拟合"
            self.fit_normal_from_file(d00)
        obs = self.from_array(
            rows,
            window=window,
            fault_label=fault,
            simulation_run_id=simulation_run_id,
        )
        source_path = os.path.join(data_dir, name)
        metadata_rows = []
        for observation in obs:
            metadata = dict(self.scorer_only_metadata(observation))
            metadata.update(
                {
                    "source_path": source_path,
                    "source_filename": name,
                    "split": split,
                }
            )
            metadata_rows.append(metadata)
        self._set_scorer_only_sidecar(obs, metadata_rows)
        return obs

    # ---------- 评分 ----------
    def window_score(self, values: Sequence[float]) -> float:
        """窗口偏离度：逐变量z分数绝对值的上四分位均值（抗单变量噪声）。"""
        k = len(self.mu)
        n = len(values) // k
        zs = []
        for i in range(n):
            row = values[i * k : (i + 1) * k]
            zs.extend(abs((row[j] - self.mu[j]) / self.sd[j]) for j in range(k))
        zs.sort(reverse=True)
        top = zs[: max(1, len(zs) // 4)]
        return sum(top) / len(top)
