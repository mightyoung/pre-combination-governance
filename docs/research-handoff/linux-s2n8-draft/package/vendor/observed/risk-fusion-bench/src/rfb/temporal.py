# -*- coding: utf-8 -*-
"""时间折扣递归融合及最小的根级一次性贡献 canary。

该模块仍不是 v20.1 的完整事务运行时；在缺少 replacement/replay ledger 时，
高版本输入必须 fail closed，不能假装完成原子替换。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import dst
from .dst import Mass


class FusionFailClosedError(RuntimeError):
    """Raised when the canary cannot safely commit a fusion transition."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class Evidence:
    """一条 BPA 消息；新增身份字段均置于旧字段之后以保持位置参数兼容。"""

    m: Mass
    t_gen: float
    source_id: str = "?"
    reliability: float = 1.0
    event_id: Optional[str] = None
    root_id: Optional[str] = None
    bundle_version: Optional[int] = None
    view_id: Optional[str] = None


EventFingerprint = Tuple[
    Tuple[Tuple[int, float], ...],
    float,
    str,
    float,
    Optional[str],
    Optional[int],
    Optional[str],
]


@dataclass
class BeliefState:
    """连续信念状态及无事务 ledger 情况下的保守一次性贡献 canary。"""

    gamma: float = 0.05
    t: float = 0.0
    B: Mass = field(default_factory=dst.vacuous)
    history: List[dict] = field(default_factory=list)
    audit: List[dict] = field(default_factory=list)
    frozen: bool = False
    freeze_reason: Optional[str] = None
    _seen_events: Dict[str, EventFingerprint] = field(default_factory=dict, repr=False)
    _root_versions: Dict[str, int] = field(default_factory=dict, repr=False)

    def _temporal_discount(self, m: Mass, dt: float) -> Mass:
        if dt <= 0:
            return m
        return dst.discount(m, math.exp(-self.gamma * dt))

    @staticmethod
    def _event_fingerprint(ev: Evidence) -> EventFingerprint:
        return (
            tuple(sorted(ev.m.items())),
            float(ev.t_gen),
            ev.source_id,
            float(ev.reliability),
            ev.root_id,
            ev.bundle_version,
            ev.view_id,
        )

    def _append_audit(self, status: str, ev: Evidence, **extra):
        record = {
            "status": status,
            "event_id": ev.event_id,
            "root_id": ev.root_id,
            "bundle_version": ev.bundle_version,
            "view_id": ev.view_id,
        }
        record.update(extra)
        self.audit.append(record)

    def _fail_closed(self, reason: str, status: str, ev: Evidence):
        # Belief, time and history are deliberately untouched.  Only the
        # fail-closed control state and append-only audit record are committed.
        self.frozen = True
        self.freeze_reason = reason
        self._append_audit(status, ev, reason=reason)
        raise FusionFailClosedError(reason)

    def _assert_available(self):
        if self.frozen:
            raise FusionFailClosedError(f"STATE_FROZEN:{self.freeze_reason}")

    def step(self, ev: Evidence, t_arrive: Optional[float] = None) -> Mass:
        """Safely process one evidence event without a replacement ledger."""
        self._assert_available()
        fingerprint = self._event_fingerprint(ev)

        if ev.event_id is not None and ev.event_id in self._seen_events:
            if self._seen_events[ev.event_id] == fingerprint:
                self._append_audit("DUPLICATE_AUDIT", ev)
                return self.B
            self._fail_closed("EVENT_ID_EQUIVOCATION", "EVENT_ID_FAIL_CLOSED", ev)

        version = 0 if ev.bundle_version is None else int(ev.bundle_version)
        if ev.root_id is not None and ev.root_id in self._root_versions:
            committed_version = self._root_versions[ev.root_id]
            if version > committed_version:
                self._fail_closed(
                    "HIGHER_VERSION_REQUIRES_TRANSACTION_LEDGER",
                    "HIGHER_VERSION_FAIL_CLOSED",
                    ev,
                )

            if ev.event_id is not None:
                self._seen_events[ev.event_id] = fingerprint
            if version == committed_version:
                self._append_audit("ALTERNATE_VIEW_AUDIT", ev)
            else:
                self._append_audit("STALE_VERSION_AUDIT", ev)
            return self.B

        # Compute the whole candidate transition in local variables.  No
        # belief/time/history mutation occurs until every gate has passed.
        t_now = max(self.t, t_arrive if t_arrive is not None else ev.t_gen)
        predicted_belief = self._temporal_discount(self.B, t_now - self.t)
        candidate_mass = ev.m
        late = t_now - ev.t_gen
        if late > 0:
            candidate_mass = self._temporal_discount(candidate_mass, late)
        candidate_mass = dst.discount(candidate_mass, ev.reliability)

        conflict = dst.conflict_coefficient(predicted_belief, candidate_mass)
        if conflict >= 1.0 - 1e-12:
            self._fail_closed("FULL_CONFLICT", "FULL_CONFLICT_FAIL_CLOSED", ev)

        fused = dst.dempster_combine(predicted_belief, candidate_mass)

        # Atomic commit point for the canary transition.
        self.B = fused
        self.t = t_now
        if ev.event_id is not None:
            self._seen_events[ev.event_id] = fingerprint
        if ev.root_id is not None:
            self._root_versions[ev.root_id] = version
        self._record()
        return self.B

    def coast(self, t_now: float) -> Mass:
        """无证据推进；冻结状态禁止继续演化或恢复服务。"""
        self._assert_available()
        if t_now > self.t:
            self.B = self._temporal_discount(self.B, t_now - self.t)
            self.t = t_now
            self._record()
        return self.B

    def _record(self):
        self.history.append(
            {
                "t": self.t,
                "R": dst.risk_index(self.B),
                "unknown": dst.unknown_mass(self.B),
            }
        )

    def risk(self) -> float:
        return dst.risk_index(self.B)


def risk_velocity(history: List[dict], window: int = 5) -> float:
    """Ṙ(t)：滑动窗最小二乘斜率。"""
    pts = history[-window:]
    n = len(pts)
    if n < 2:
        return 0.0
    tm = sum(p["t"] for p in pts) / n
    rm = sum(p["R"] for p in pts) / n
    num = sum((p["t"] - tm) * (p["R"] - rm) for p in pts)
    den = sum((p["t"] - tm) ** 2 for p in pts)
    return num / den if den > 0 else 0.0


def decide_level(
    B: Mass,
    r: float,
    rdot: float,
    unknown: float,
    th=(0.25, 0.5, 0.75),
    accel_bonus: float = 0.05,
    unknown_guard: float = 0.6,
) -> int:
    """决策函数 g：趋势阈值、加速提前告警及高无知安全保护。"""
    r_eff = r + (accel_bonus if rdot > 0.02 else 0.0)
    if unknown > unknown_guard:
        r_eff = max(r_eff, th[0] + 1e-6)
    if r_eff < th[0]:
        return 0
    if r_eff < th[1]:
        return 1
    if r_eff < th[2]:
        return 2
    return 3
