#!/usr/bin/env python3
"""Run one deterministic synthetic alert lifecycle and render standalone HTML."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
sys.path.insert(0, str(REPOSITORY / "risk-fusion-bench" / "src"))

from rfb.research.alert_governance import (  # noqa: E402
    AlertLedger,
    CandidateEvent,
    DeliveryStatus,
    RelationDecision,
)


SCENARIO_ID = "SYNTH-V2-ALIGN-001"


def _card_row(card: Any) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "candidate_ids": list(card.candidate_ids),
        "identity_status": card.status,
        "alert_stage": card.alert_level,
        "merged_into_card_id": card.merged_into_card_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "latest_alert_id": card.latest_alert_id,
    }


def _alert_row(alert: Any) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "display_card_id": alert.card_id,
        "revision": alert.revision,
        "candidate_ids": list(alert.candidate_ids),
        "source_ids": list(alert.source_ids),
        "alert_stage": alert.alert_level,
        "identity_status": alert.verification_state,
        "risk_flags": alert.risk_flag,
        "visible_text": alert.visible_text,
        "rationale": alert.rationale,
        "reason_codes": list(alert.reason_codes),
        "evidence_refs": list(alert.evidence_refs),
        "event_time": alert.event_time,
        "observed_at": alert.observed_at,
        "software_emitted_at": alert.alerted_at,
        "delivery_status": alert.delivery_status.value,
        "delivered_at": alert.delivered_at,
    }


def _step(
    ledger: AlertLedger,
    *,
    at: str,
    action: str,
    evidence_refs: tuple[str, ...],
    before_alert_count: int,
    association_id: str | None = None,
) -> dict[str, Any]:
    association = ledger.association(association_id) if association_id else None
    return {
        "at": at,
        "action": action,
        "evidence_refs": list(evidence_refs),
        "new_alert_ids": [
            alert.alert_id for alert in ledger.alerts[before_alert_count:]
        ],
        "association": (
            {
                "association_id": association.association_id,
                "status": association.status,
                "canonical_card_id": association.canonical_card_id,
                "history": [transition.to_status for transition in association.history],
            }
            if association
            else None
        ),
        "cards": [_card_row(card) for card in ledger.cards],
    }


def run_scenario() -> dict[str, Any]:
    ledger = AlertLedger(delivery_status=DeliveryStatus.SIMULATED)
    timeline: list[dict[str, Any]] = []

    candidate_a = CandidateEvent(
        candidate_id="synthetic-observation-a",
        event_time="2026-10-11T08:00:00Z",
        observed_at="2026-10-11T08:00:01Z",
        summary="合成观测 A：风险暴露信号",
        source_id="synthetic-sensor-A",
        evidence_refs=("synthetic://v2-alignment/observation-A",),
        risk_flag="EXPOSURE",
    )
    candidate_b = CandidateEvent(
        candidate_id="synthetic-observation-b",
        event_time="2026-10-11T08:00:02Z",
        observed_at="2026-10-11T08:00:04Z",
        summary="合成观测 B：风险暴露信号",
        source_id="synthetic-sensor-B",
        evidence_refs=("synthetic://v2-alignment/observation-B",),
        risk_flag="EXPOSURE",
    )

    before = len(ledger.alerts)
    card_a = ledger.add_candidate(
        candidate_a, alerted_at="2026-10-11T08:00:03Z"
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:03Z",
            action="收到候选 A；生成首条待核实风险提醒",
            evidence_refs=candidate_a.evidence_refs,
            before_alert_count=before,
        )
    )

    before = len(ledger.alerts)
    card_b = ledger.add_candidate(
        candidate_b, alerted_at="2026-10-11T08:00:05Z"
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:05Z",
            action="收到候选 B；保留第二张独立稳定卡",
            evidence_refs=candidate_b.evidence_refs,
            before_alert_count=before,
        )
    )

    conflict_refs = ("synthetic://v2-alignment/ambiguous-identity-evidence",)
    before = len(ledger.alerts)
    association = ledger.propose_association(
        candidate_a.candidate_id,
        candidate_b.candidate_id,
        at="2026-10-11T08:00:06Z",
        rationale="合成证据对两条观测是否属于同一物理事件存在冲突；身份待核。",
        evidence_refs=conflict_refs,
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:06Z",
            action="关联出现冲突；状态 PENDING，两张卡不合并",
            evidence_refs=conflict_refs,
            before_alert_count=before,
            association_id=association.association_id,
        )
    )

    risk_refs = ("synthetic://v2-alignment/risk-review-evidence-ref",)
    before = len(ledger.alerts)
    ledger.confirm_risk_alert(
        card_a.card_id,
        at="2026-10-11T08:00:07Z",
        rationale="合成审核证据确认风险条件；事件身份仍待核。",
        evidence_refs=risk_refs,
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:07Z",
            action="风险证据确认；提醒阶段 CONFIRMED，身份仍待核",
            evidence_refs=risk_refs,
            before_alert_count=before,
            association_id=association.association_id,
        )
    )

    same_refs = ("synthetic://v2-alignment/identity-review-same",)
    before = len(ledger.alerts)
    ledger.resolve_association(
        association.association_id,
        decision=RelationDecision.SAME_EVENT,
        at="2026-10-11T08:00:08Z",
        evidence_refs=same_refs,
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:08Z",
            action="身份复核暂确认 SAME；当前实现合并到最早稳定卡",
            evidence_refs=same_refs,
            before_alert_count=before,
            association_id=association.association_id,
        )
    )

    escalation_refs = ("synthetic://v2-alignment/risk-escalation",)
    before = len(ledger.alerts)
    ledger.escalate_card(
        card_a.card_id,
        at="2026-10-11T08:00:09Z",
        rationale="合成复核证据显示风险加重，独立升级提醒。",
        evidence_refs=escalation_refs,
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:09Z",
            action="风险加重；提醒阶段 ESCALATED",
            evidence_refs=escalation_refs,
            before_alert_count=before,
            association_id=association.association_id,
        )
    )

    split_refs = ("synthetic://v2-alignment/contradictory-identity-evidence",)
    before = len(ledger.alerts)
    ledger.split_association(
        association.association_id,
        at="2026-10-11T08:00:10Z",
        rationale="后续合成证据与 SAME 决定矛盾；分拆并保留历史卡 ID。",
        evidence_refs=split_refs,
    )
    timeline.append(
        _step(
            ledger,
            at="2026-10-11T08:00:10Z",
            action="矛盾证据支持分拆；恢复两个原始卡 ID",
            evidence_refs=split_refs,
            before_alert_count=before,
            association_id=association.association_id,
        )
    )

    return {
        "scenario_id": SCENARIO_ID,
        "classification": "SYNTHETIC_DEVELOPMENT_TEST_ONLY",
        "source_commits": {
            "comparison_implementation": "214197c0370dfd60d23786884bb7ff785d8a0092",
            "v2_public_spec": "cc6d59b88bda73381fc09d9091a224ab4155891e",
        },
        "execution_boundary": {
            "software_ledger_only": True,
            "model_service_called": False,
            "delivery_adapter_called": False,
            "delivery_status": "SIMULATED",
            "delivered_at": None,
            "visible_at": None,
            "frozen_1464_trial_rerun": False,
            "mac_device_or_cleanup_validation": "NOT_RUN",
            "independent_ground_truth": "NOT_PROVIDED",
        },
        "synthetic_inputs": [
            {
                "candidate_id": candidate.candidate_id,
                "source_id": candidate.source_id,
                "risk_flag": candidate.risk_flag,
                "event_time": candidate.event_time,
                "observed_at": candidate.observed_at,
                "evidence_refs": list(candidate.evidence_refs),
            }
            for candidate in (candidate_a, candidate_b)
        ],
        "timeline": timeline,
        "associations": [
            {
                "association_id": row.association_id,
                "candidate_ids": list(row.candidate_ids),
                "status": row.status,
                "canonical_card_id": row.canonical_card_id,
                "evidence_refs": list(row.evidence_refs),
                "history": [
                    {
                        "status": transition.to_status,
                        "at": transition.at,
                        "evidence_refs": list(transition.evidence_refs),
                    }
                    for transition in row.history
                ],
            }
            for row in ledger.associations
        ],
        "final_cards": [_card_row(card) for card in ledger.cards],
        "notifications": [_alert_row(alert) for alert in ledger.alerts],
    }


def _short(value: str | None) -> str:
    return f"{value[:16]}…" if value else "—"


def render_html(data: dict[str, Any]) -> str:
    snapshot_by_time = {row["at"]: row for row in data["timeline"]}
    cards = data["final_cards"]
    start_cards = data["timeline"][1]["cards"]
    merged_cards = snapshot_by_time["2026-10-11T08:00:08Z"]["cards"]
    split_cards = data["timeline"][-1]["cards"]

    def card_box(card: dict[str, Any], *, alias: bool = False) -> str:
        title = "歷史別名" if alias else "穩定展示卡"
        return (
            '<div class="card-box">'
            f'<div class="card-title">{title}</div>'
            f'<div class="card-id">{html.escape(_short(card["card_id"]))}</div>'
            f'<div>身份：{html.escape(card["identity_status"])}</div>'
            f'<div>提醒：{html.escape(card["alert_stage"])}</div>'
            f'<div>候选：{html.escape(", ".join(card["candidate_ids"]))}</div>'
            '</div>'
        )

    start_html = "".join(card_box(card) for card in start_cards)
    merged_html = "".join(
        card_box(card, alias=bool(card["merged_into_card_id"]))
        for card in merged_cards
    )
    split_html = "".join(card_box(card) for card in split_cards)

    timeline_html = []
    for row in data["timeline"]:
        status = row["association"]["status"] if row["association"] else "—"
        refs = " · ".join(row["evidence_refs"])
        alerts = "、".join(_short(alert_id) for alert_id in row["new_alert_ids"])
        timeline_html.append(
            '<article class="timeline-item">'
            '<span class="dot"></span>'
            f'<div class="time">{html.escape(row["at"].split("T", 1)[1].replace("Z", " UTC"))}</div>'
            f'<div class="action">{html.escape(row["action"])}</div>'
            f'<div class="meta">关联：{html.escape(status)} · 新提醒：{html.escape(alerts or "无")}</div>'
            f'<div class="evidence">证据：{html.escape(refs or "无")}</div>'
            '</article>'
        )

    notification_rows = []
    for alert in data["notifications"]:
        notification_rows.append(
            "<tr>"
            f'<td>{html.escape(_short(alert["alert_id"]))}</td>'
            f'<td>{html.escape(_short(alert["display_card_id"]))}</td>'
            f'<td>{html.escape(alert["alert_stage"])}</td>'
            f'<td>{html.escape(alert["identity_status"])}</td>'
            f'<td><span class="badge">{html.escape(alert["delivery_status"])}</span></td>'
            '<td>未记录（无真实回执）</td>'
            "</tr>"
        )

    cards_caption = f"最终 {len(cards)} 张原始稳定卡；分拆关系的 canonical_card_id 为空"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>合成事件卡演变时间线</title>
<style>
:root {{ color-scheme: light; --ink:#182230; --muted:#536273; --line:#d6dee8; --blue:#245b8f; --teal:#17786d; --amber:#a85c00; --red:#a3372d; --paper:#f7f9fc; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:28px 24px 44px; }}
h1 {{ margin:0 0 8px; font-size:28px; }} h2 {{ margin:28px 0 12px; font-size:20px; }}
.banner {{ display:flex; align-items:center; gap:12px; padding:14px 16px; border:1px solid #e3ad68; border-left:6px solid var(--amber); border-radius:9px; background:#fff5e8; font-weight:650; }}
.banner b {{ color:#8d4600; }} .sub {{ color:var(--muted); margin:0 0 18px; }}
.overview {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:18px 0; }}
.overview div {{ padding:13px 15px; background:#fff; border:1px solid var(--line); border-radius:9px; }}
.overview strong {{ display:block; font-size:12px; color:var(--muted); text-transform:uppercase; }}
.cards-evolution {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }}
.stage {{ border:1px solid var(--line); border-radius:11px; background:#fff; padding:15px; min-height:188px; }}
.stage h3 {{ margin:0 0 6px; font-size:16px; }} .stage p {{ margin:0 0 12px; color:var(--muted); font-size:13px; }}
.card-box {{ border:1px solid #cad6e3; border-radius:8px; padding:10px 11px; margin:8px 0; background:#f9fbfd; font-size:12px; overflow-wrap:anywhere; }}
.card-title {{ font-weight:700; color:var(--blue); }} .card-id {{ font-family:ui-monospace,monospace; color:#314a62; }}
.timeline {{ position:relative; margin-left:6px; padding-left:26px; border-left:2px solid var(--line); }}
.timeline-item {{ position:relative; margin:0 0 18px; padding:0 0 3px 6px; }}
.dot {{ position:absolute; width:12px; height:12px; left:-33px; top:6px; border-radius:50%; background:var(--teal); border:2px solid white; box-shadow:0 0 0 1px var(--teal); }}
.time {{ color:var(--blue); font-weight:700; font-variant-numeric:tabular-nums; }} .action {{ font-weight:650; }}
.meta,.evidence {{ font-size:12px; color:var(--muted); overflow-wrap:anywhere; }} .evidence {{ font-family:ui-monospace,monospace; }}
.table-wrap {{ overflow-x:auto; background:#fff; border:1px solid var(--line); border-radius:9px; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }} th,td {{ text-align:left; padding:9px 10px; border-bottom:1px solid #e7edf3; vertical-align:top; }} th {{ color:#344456; background:#f1f5f9; }}
.badge {{ display:inline-block; padding:2px 7px; border-radius:999px; color:#0d6259; background:#e3f5f1; font-weight:700; }}
.caveat {{ padding:14px 16px; border:1px solid #e4b1ac; border-radius:9px; background:#fff3f1; }}
code {{ font-family:ui-monospace,monospace; }}
@media(max-width:800px) {{ .overview,.cards-evolution {{ grid-template-columns:1fr; }} main {{ padding:20px 14px; }} h1 {{ font-size:23px; }} }}
</style>
</head>
<body><main>
<h1>合成事件：提醒与事件卡演变</h1>
<p class="sub">场景 {html.escape(data['scenario_id'])} · 当前 V1.2 纯软件账本输出 · 时间为合成测试时钟</p>
<div class="banner"><span>⚠</span><span><b>合成开发测试</b>：通知状态为 SIMULATED；没有外部投递、真实展示或 delivered_at 回执。</span></div>
<div class="overview">
  <div><strong>身份历史</strong>PENDING → CONFIRMED_SAME_EVENT → SPLIT_TO_DISTINCT</div>
  <div><strong>风险提醒阶段</strong>PRECAUTIONARY → CONFIRMED → ESCALATED</div>
  <div><strong>交付边界</strong>SIMULATED · visible_at 未知 · delivered_at 未记录</div>
</div>
<h2>展示卡演变</h2>
<div class="cards-evolution">
  <section class="stage"><h3>① 待核：两张卡</h3><p>身份关联尚未确认；各自保留候选与来源。</p>{start_html}</section>
  <section class="stage"><h3>② 暂确认 SAME：合并视图</h3><p>当前实现将 SAME 组件指向最早稳定卡；此设计与 V2 的“展示卡不等于物理事件”仍有差距。</p>{merged_html}</section>
  <section class="stage"><h3>③ 矛盾证据后拆分</h3><p>原始卡 ID 恢复；提醒阶段仍为 ESCALATED。</p>{split_html}<p>{html.escape(cards_caption)}</p></section>
</div>
<h2>事件时间线与证据引用</h2>
<div class="timeline">{''.join(timeline_html)}</div>
<h2>本次账本生成的通知记录</h2>
<div class="table-wrap"><table><thead><tr><th>通知修订</th><th>稳定卡</th><th>提醒阶段</th><th>身份状态</th><th>记录状态</th><th>真实展示回执</th></tr></thead><tbody>{''.join(notification_rows)}</tbody></table></div>
<h2>具体失败/未知</h2>
<div class="caveat"><b>V2 对齐尚未通过。</b>当前记录有 alerted_at，但没有 trigger_known_time、detected_at 或 visible_at；公开 V2 也未冻结真实毫秒 SLO。图中的“确认/升级/拆分”只表示本地合成状态转换，evidence_refs 是合成引用而非独立合格真值。该运行不能证明用户已看到提醒、物理事件判断正确、旧 1,464 检查通过或 Mac 清理资格通过。</div>
<p class="sub">数据文件与生成脚本随本 HTML 一起提供，可离线打开和复核。没有外部字体、脚本或网络依赖。</p>
</main></body></html>"""


def main() -> None:
    data = run_scenario()
    data_path = HERE / "synthetic-event-data.json"
    html_path = HERE / "synthetic-event-timeline.html"
    data_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(render_html(data), encoding="utf-8")
    print(
        json.dumps(
            {
                "scenario_id": data["scenario_id"],
                "classification": data["classification"],
                "notification_count": len(data["notifications"]),
                "final_association_status": data["associations"][0]["status"],
                "final_card_count": len(data["final_cards"]),
                "delivery_statuses": sorted(
                    {item["delivery_status"] for item in data["notifications"]}
                ),
                "delivered_at_values": sorted(
                    {str(item["delivered_at"]) for item in data["notifications"]}
                ),
                "data_path": str(data_path),
                "html_path": str(html_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
