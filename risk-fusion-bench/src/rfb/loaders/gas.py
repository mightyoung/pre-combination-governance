# -*- coding: utf-8 -*-
"""UCI气体传感漂移加载器：Gas Sensor Array Drift → 环流规范观测 + {E}类初始BPA。

数据来源（免费直下，无需申请）：
  https://archive.ics.uci.edu/dataset/224/gas+sensor+array+drift+dataset
  10个批次 batch1.dat … batch10.dat，libsvm格式：
  "<gas_class>;<concentration> 1:v1 2:v2 ... 128:v128"
  （部分镜像为 "<gas_class> 1:v1 ..."，本加载器两种都能解析）
  6类气体：1乙醇 2乙烯 3氨 4乙醛 5丙酮 6甲苯；128维传感器特征。

环流风险语义：氨/甲苯等有害气体高浓度 → {E}环境风险证据。
偏离评分 = 危害加权的浓度分位数（在batch1正常浓度分布上标定）。
批次间漂移天然提供E10校准实验与Q02校准有效期元素的真实素材。
"""

from __future__ import annotations
import os
from typing import Dict, List, Optional, Sequence, Tuple

from .base import BaseLoader, CanonicalObs

# 气体危害权重（毒性/燃爆倾向的粗粒度序，可在基准规则表中调整并注明依据）
HAZARD_W = {1: 0.4, 2: 0.7, 3: 0.9, 4: 0.6, 5: 0.5, 6: 0.8}


def parse_libsvm_line(line: str) -> Optional[Tuple[int, float, List[float]]]:
    """返回 (gas_class, concentration, features[128])；concentration缺失则为nan。"""
    parts = line.split()
    if not parts:
        return None
    head = parts[0]
    if ";" in head:
        cls_s, conc_s = head.split(";", 1)
        cls, conc = int(float(cls_s)), float(conc_s)
    else:
        cls, conc = int(float(head)), float("nan")
    feats = [0.0] * 128
    for tok in parts[1:]:
        if ":" not in tok:
            continue
        i, v = tok.split(":", 1)
        idx = int(i) - 1
        if 0 <= idx < 128:
            feats[idx] = float(v)
    return cls, conc, feats


class GasLoader(BaseLoader):
    STREAM = "environment"
    PROP_MASK = 32  # {E} 环境风险
    PROCEDURE = "uci-gas-drift-hazard/0.1"

    def __init__(self):
        self.conc_p50: Dict[int, float] = {}
        self.conc_p95: Dict[int, float] = {}

    def fit_baseline(self, samples: Sequence[Tuple[int, float, List[float]]]):
        """在基线批次上按气体类别标定浓度分位数。"""
        by_cls: Dict[int, List[float]] = {}
        for cls, conc, _ in samples:
            if conc == conc:  # 非nan
                by_cls.setdefault(cls, []).append(conc)
        for cls, arr in by_cls.items():
            arr.sort()
            self.conc_p50[cls] = arr[len(arr) // 2]
            self.conc_p95[cls] = arr[min(len(arr) - 1, int(len(arr) * 0.95))]

    def read_batch(self, path: str) -> List[Tuple[int, float, List[float]]]:
        out = []
        with open(path) as f:
            for line in f:
                r = parse_libsvm_line(line)
                if r:
                    out.append(r)
        return out

    def load(
        self,
        data_dir: str,
        batch: int = 2,
        baseline_batch: int = 1,
        area_id: str = "zone-A",
        interval_s: float = 30.0,
    ) -> List[CanonicalObs]:
        if not self.conc_p50:
            self.fit_baseline(
                self.read_batch(os.path.join(data_dir, f"batch{baseline_batch}.dat"))
            )
        samples = self.read_batch(os.path.join(data_dir, f"batch{batch}.dat"))
        obs = []
        for i, (cls, conc, feats) in enumerate(samples):
            missing = 1.0 if conc != conc else 0.0
            obs.append(
                CanonicalObs(
                    value=[float(cls), conc] + feats,
                    unit="class,ppmv,sensor-features",
                    t_gen=i * interval_s,
                    feature_of_interest=area_id,
                    procedure=self.PROCEDURE + f"|batch={batch}",
                    quality={
                        "completeness": 1.0 - 0.5 * missing,
                        "calibration_age_batches": abs(batch - baseline_batch),
                    },
                )
            )
        return obs

    def window_score(self, values: Sequence[float]) -> float:
        """危害加权浓度偏离：p50→0分，p95→约2分（配合base的logistic x0=2）。"""
        cls = int(values[0])
        conc = values[1]
        if conc != conc or cls not in self.conc_p50:
            return 0.0  # 无浓度信息：不制造风险证据（质量标记已降低completeness）
        p50 = self.conc_p50[cls]
        p95 = self.conc_p95.get(cls, p50 * 2 + 1e-9)
        span = max(1e-9, p95 - p50)
        base_score = max(0.0, (conc - p50) / span) * 2.0
        return base_score * HAZARD_W.get(cls, 0.5)
