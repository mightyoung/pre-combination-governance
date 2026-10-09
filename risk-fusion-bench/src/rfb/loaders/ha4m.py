# -*- coding: utf-8 -*-
"""HA4M加载器：装配动作骨架序列 → 人流规范观测 + {H}类初始BPA。

数据来源（注册后公开下载）：
  HA4M: Human Action Multi-Modal Monitoring in Manufacturing (Sci Data 2022)
  https://www.scidb.cn/en/detail?dataSetId=c8d743ad2ea549dfa938cea320a38c46
  41名受试者×12类装配动作，Azure Kinect：RGB/深度/IR/点云/骨架(32关节)。
  建议先下骨架数据（小体积），RGB留给VLM实验（M3阶段）。

本加载器消费骨架序列 frames×joints×3（米制），配合区域配置计算三类
可解释人因风险特征（对应元素编码H07区域位置/H10人机距离/H08不安全动作）：
  1) 与危险区/运行设备的最小距离（越近越险）
  2) 手部运动速度峰值（急促动作）
  3) 躯干倾角（弯腰探身姿态）
深度动作识别（ST-GCN分类概率）作为模态内分析层升级项在E3引入；
本基线保证证据可解释、可复现、无训练依赖。
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .base import BaseLoader, CanonicalObs

# Azure Kinect 关节索引（子集）
J_PELVIS, J_NECK, J_HAND_R, J_HAND_L = 0, 3, 15, 8
FPS_DEFAULT = 30.0


@dataclass
class HazardZone:
    center: Tuple[float, float, float]
    radius: float
    zone_id: str = "Z1"


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class HA4MLoader(BaseLoader):
    STREAM = "human"
    PROP_MASK = 2  # {H} 人因风险
    PROCEDURE = "ha4m-skeleton-rules/0.1"

    def __init__(
        self,
        zones: Optional[List[HazardZone]] = None,
        fps: float = FPS_DEFAULT,
        window_s: float = 2.0,
    ):
        self.zones = zones or []
        self.fps = fps
        self.win = int(window_s * fps)
        # 基线统计（正常作业段拟合）
        self.speed_mu = 0.5
        self.speed_sd = 0.3
        self.incline_mu = 15.0
        self.incline_sd = 8.0

    # ---------- 特征 ----------
    def _frame_feats(self, sk: Sequence[Sequence[float]]) -> Tuple[float, float]:
        """单帧：与最近危险区距离、躯干倾角（度）。"""
        pelvis, neck = sk[J_PELVIS], sk[J_NECK]
        dmin = min(
            (_dist(pelvis, z.center) - z.radius for z in self.zones), default=9.9
        )
        torso = [neck[i] - pelvis[i] for i in range(3)]
        vert = math.sqrt(torso[0] ** 2 + torso[2] ** 2)
        incline = math.degrees(math.atan2(vert, abs(torso[1]) + 1e-9))
        return max(0.0, dmin), incline

    def fit_normal(self, frames: Sequence[Sequence[Sequence[float]]]):
        """在正常作业骨架段上拟合速度/倾角基线。"""
        sp, inc = [], []
        for t in range(1, len(frames)):
            v = _dist(frames[t][J_HAND_R], frames[t - 1][J_HAND_R]) * self.fps
            sp.append(v)
            inc.append(self._frame_feats(frames[t])[1])
        n = max(2, len(sp))
        self.speed_mu = sum(sp) / n
        self.speed_sd = max(
            1e-6, math.sqrt(sum((v - self.speed_mu) ** 2 for v in sp) / (n - 1))
        )
        self.incline_mu = sum(inc) / n
        self.incline_sd = max(
            1e-6, math.sqrt(sum((v - self.incline_mu) ** 2 for v in inc) / (n - 1))
        )

    def from_array(
        self,
        frames: Sequence[Sequence[Sequence[float]]],
        worker_id: str = "worker-1",
        t0: float = 0.0,
    ) -> List[CanonicalObs]:
        """骨架序列 → 窗口化观测。value=每窗特征摘要[最小区距, 峰值手速, 峰值倾角]。"""
        obs = []
        for i in range(0, len(frames) - self.win + 1, self.win):
            chunk = frames[i : i + self.win]
            dists, incs, speeds = [], [], []
            for t in range(len(chunk)):
                d, inc = self._frame_feats(chunk[t])
                dists.append(d)
                incs.append(inc)
                if t > 0:
                    speeds.append(
                        _dist(chunk[t][J_HAND_R], chunk[t - 1][J_HAND_R]) * self.fps
                    )
            miss = sum(1 for fr in chunk for j in fr if any(v != v for v in j))
            obs.append(
                CanonicalObs(
                    value=[min(dists), max(speeds) if speeds else 0.0, max(incs)],
                    unit="m,m/s,deg",
                    t_gen=t0 + (i + self.win) / self.fps,
                    feature_of_interest=worker_id,
                    procedure=self.PROCEDURE,
                    quality={
                        "completeness": 1.0 - miss / max(1, len(chunk) * 32),
                        "fps": self.fps,
                    },
                )
            )
        return obs

    def window_score(self, values: Sequence[float]) -> float:
        dmin, vmax, incmax = values[0], values[1], values[2]
        # 区域接近：1m内线性升分（H07/H10）
        s_zone = max(0.0, (1.0 - dmin)) * 3.0
        # 急促动作与异常姿态的z分数（H08）
        s_speed = max(0.0, (vmax - self.speed_mu) / self.speed_sd) * 0.5
        s_pose = max(0.0, (incmax - self.incline_mu) / self.incline_sd) * 0.4
        return s_zone + min(2.0, s_speed) + min(1.5, s_pose)
