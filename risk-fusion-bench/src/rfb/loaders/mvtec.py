# -*- coding: utf-8 -*-
"""MVTec-AD加载器：工业品视觉缺陷 → 料流规范观测 + {T}类初始BPA。

数据来源（研究用途注册免费下载）：
  https://www.mvtec.com/company/research/datasets/mvtec-ad
  15类工业品，train/good 正常图 + test/{good,defect...} 测试图。

设计决策：本加载器不内置视觉模型——异常分数由任意现成检测器产出
（推荐 anomalib 库的 PatchCore/EfficientAD，两行命令出全量分数CSV），
加载器消费 (image_id, anomaly_score, category, defect_type) 记录，
在train/good分数分布上标定基线后映射为{T}证据。
这样保持核心库零深度学习依赖，检测器可插拔（模态内分析层的契约体现）。

分数CSV格式: image_path,score[,category,defect_type]  （无表头亦可）
"""

from __future__ import annotations
import csv
import os
from typing import List, Optional, Sequence, Tuple

from .base import BaseLoader, CanonicalObs


def _read_score_records(path: str) -> List[Tuple[str, float, str, str]]:
    out = []
    with open(path) as f:
        for row in csv.reader(f):
            if not row or row[0].strip().lower() in ("image_path", "path", "image"):
                continue
            img = row[0].strip()
            try:
                score = float(row[1])
            except (IndexError, ValueError):
                continue
            cat = row[2].strip() if len(row) > 2 else "unknown"
            defect_type = row[3].strip() if len(row) > 3 else ""
            out.append((img, score, cat, defect_type))
    return out


def read_scores_csv(path: str) -> List[Tuple[str, float, str]]:
    """Preserve the legacy three-column parser view; loader output is isolated."""
    return [(img, score, cat) for img, score, cat, _ in _read_score_records(path)]


class MVTecLoader(BaseLoader):
    STREAM = "material"
    PROP_MASK = 8  # {T} 物料风险
    PROCEDURE = "mvtec-pluggable-detector/0.1"

    def __init__(self, detector_name: str = "patchcore"):
        self.detector = detector_name
        self.p50: Optional[float] = None
        self.p95: Optional[float] = None

    def fit_baseline(self, good_scores: Sequence[float]):
        """在train/good（或test/good）分数上标定分位数基线。"""
        arr = sorted(good_scores)
        assert len(arr) >= 10, "正常分数样本过少"
        self.p50 = arr[len(arr) // 2]
        self.p95 = arr[min(len(arr) - 1, int(len(arr) * 0.95))]

    def load(
        self,
        scores_csv: str,
        good_csv: Optional[str] = None,
        batch_id: str = "lot-1",
        interval_s: float = 5.0,
    ) -> List[CanonicalObs]:
        if good_csv and self.p50 is None:
            self.fit_baseline([s for _, s, _ in read_scores_csv(good_csv)])
        assert self.p50 is not None, "先提供good分数标定基线"
        rows = _read_score_records(scores_csv)
        obs = []
        metadata_rows = []
        for i, (img, score, cat, defect_type) in enumerate(rows):
            obs.append(
                CanonicalObs(
                    value=[score],
                    unit="anomaly-score",
                    t_gen=i * interval_s,
                    feature_of_interest=batch_id,
                    procedure=f"{self.PROCEDURE}|{self.detector}",
                    quality={"completeness": 1.0},
                )
            )
            metadata = {
                "source_path": img,
                "source_filename": os.path.basename(img),
                "category": cat,
            }
            if defect_type:
                metadata["defect_type"] = defect_type
            metadata_rows.append(metadata)
        self._set_scorer_only_sidecar(obs, metadata_rows)
        return obs

    def window_score(self, values: Sequence[float]) -> float:
        score = values[0]
        span = max(1e-9, self.p95 - self.p50)
        return max(0.0, (score - self.p50) / span) * 2.0
