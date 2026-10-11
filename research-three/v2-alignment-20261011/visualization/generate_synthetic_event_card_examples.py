#!/usr/bin/env python3
"""Run tested event-card APIs on explicit synthetic inputs and render JSON/HTML."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
INPUT_PATH = HERE / "synthetic-event-card-examples-input.json"
DATA_PATH = HERE / "synthetic-event-card-examples.json"
HTML_PATH = HERE / "synthetic-event-card-examples.html"
MANIFEST_PATH = HERE / "synthetic-event-card-examples-manifest.json"
SOURCE_COMMIT = "22b5f0404d27b9c4631def21d96dfef068afc016"
GENERATOR_COMMAND = (
    "python research-three/v2-alignment-20261011/visualization/"
    "generate_synthetic_event_card_examples.py"
)

sys.path.insert(0, str(REPOSITORY / "risk-fusion-bench" / "src"))

from rfb.research.alert_action_experiment import (  # noqa: E402
    ActionIntent,
    ActionKind,
    PolicyMode,
    ReminderActionLedger,
)
from rfb.research.alert_notification_preview import (  # noqa: E402
    build_event_card_preview,
)
from rfb.research.event_card_resolution import (  # noqa: E402
    PendingAssociation,
    resolve_pending_association,
)


IMPLEMENTATION_FILES = (
    "risk-fusion-bench/src/rfb/research/alert_action_experiment.py",
    "risk-fusion-bench/src/rfb/research/alert_notification_preview.py",
    "risk-fusion-bench/src/rfb/research/event_card_resolution.py",
    "risk-fusion-bench/src/rfb/research/alert_governance_v2.py",
)


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _tuple(value: list[str], label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a JSON array of strings")
    return tuple(value)


def action_intent(payload: dict[str, Any], received_at: str) -> ActionIntent:
    return ActionIntent(
        intent_id=payload["intent_id"],
        display_card_id=payload["display_card_id"],
        kind=ActionKind(payload["kind"]),
        risk_stage=payload["risk_stage"],
        received_at=received_at,
        observation_ids=_tuple(payload["observation_ids"], "observation_ids"),
        source_ids=_tuple(payload["source_ids"], "source_ids"),
        candidate_episode_ids=_tuple(
            payload["candidate_episode_ids"], "candidate_episode_ids"
        ),
        association_ids=_tuple(payload["association_ids"], "association_ids"),
        evidence_refs=_tuple(payload["evidence_refs"], "evidence_refs"),
        risk_flags=_tuple(payload["risk_flags"], "risk_flags"),
        risk_basis_ids=_tuple(payload["risk_basis_ids"], "risk_basis_ids"),
        source_times=_tuple(payload["source_times"], "source_times"),
        observed_at_times=_tuple(
            payload["observed_at_times"], "observed_at_times"
        ),
        experiment_batch_id=payload["experiment_batch_id"],
        association_state=payload["association_state"],
        dedup_episode_interval_key=payload["dedup_episode_interval_key"],
        trigger_known_time=payload.get("trigger_known_time"),
        detected_at=payload.get("detected_at"),
    )


def intent_record(intent: ActionIntent) -> dict[str, Any]:
    return {
        "intent_id": intent.intent_id,
        "display_card_id": intent.display_card_id,
        "kind": intent.kind.value,
        "risk_stage": intent.risk_stage,
        "received_at": intent.received_at,
        "observation_ids": list(intent.observation_ids),
        "source_ids": list(intent.source_ids),
        "candidate_episode_ids": list(intent.candidate_episode_ids),
        "association_ids": list(intent.association_ids),
        "evidence_refs": list(intent.evidence_refs),
        "risk_flags": list(intent.risk_flags),
        "risk_basis_ids": list(intent.risk_basis_ids),
        "source_times": list(intent.source_times),
        "observed_at_times": list(intent.observed_at_times),
        "experiment_batch_id": intent.experiment_batch_id,
        "association_state": intent.association_state,
        "dedup_episode_interval_key": intent.dedup_episode_interval_key,
        "trigger_known_time": intent.trigger_known_time,
        "detected_at": intent.detected_at,
        "provenance": "SYNTHETIC_INPUT_TO_TESTED_ACTION_LEDGER",
    }


def decision_record(decision: Any) -> dict[str, Any]:
    return {
        "intent_id": decision.intent_id,
        "status": decision.status.value,
        "notification_id": decision.experiment_notification_id,
        "card_revision": decision.card_revision,
        "decision_reason": decision.decision_reason,
        "simulated_card_update_delay_seconds": (
            decision.simulated_card_update_delay_seconds
        ),
        "actual_visible_at": decision.actual_visible_at,
    }


def run_scenario(
    scenario: dict[str, Any], *, ledger_configuration: dict[str, Any]
) -> dict[str, Any]:
    identity_input = scenario["identity"]
    pending = PendingAssociation(
        association_id=identity_input["association_id"],
        display_card_id=identity_input["display_card_id"],
        candidate_episode_ids=_tuple(
            identity_input["candidate_episode_ids"], "candidate_episode_ids"
        ),
        association_state=identity_input["association_state"],
        pending_at=identity_input["pending_at"],
        evidence_refs=_tuple(identity_input["evidence_refs"], "identity.evidence_refs"),
    )
    ledger = ReminderActionLedger(
        mode=PolicyMode(ledger_configuration["mode"]),
        merge_window_seconds=ledger_configuration["merge_window_seconds"],
    )

    seen_intents: dict[str, ActionIntent] = {}
    run_steps: list[dict[str, Any]] = []
    for action in scenario["actions"]:
        if "intent_ref" in action:
            try:
                base_intent = seen_intents[action["intent_ref"]]
            except KeyError as exc:
                raise ValueError(
                    f"intent_ref must point to an earlier intent: {action['intent_ref']}"
                ) from exc
            intent = action_intent(
                {
                    key: value
                    for key, value in intent_record(base_intent).items()
                    if key not in {"received_at", "provenance"}
                },
                received_at=action["apply_at"],
            )
        else:
            intent = action_intent(action["intent"], received_at=action["apply_at"])
            seen_intents.setdefault(intent.intent_id, intent)

        decision = ledger.apply(intent)
        run_steps.append(
            {
                "label": action["label"],
                "call_received_at": action["apply_at"],
                "intent": intent_record(intent),
                "decision": decision_record(decision),
                "ledger_revision_count_after_call": len(
                    ledger.card_revisions_for(intent.display_card_id)
                ),
                "notification_action_count_after_call": ledger.notification_action_count,
            }
        )

    resolution_input = identity_input.get("resolution")
    identity: PendingAssociation | Any = pending
    if resolution_input is not None:
        identity = resolve_pending_association(
            pending,
            association_state=resolution_input["association_state"],
            identity_evidence_known_at=resolution_input[
                "identity_evidence_known_at"
            ],
            resolved_at=resolution_input["resolved_at"],
            evidence_refs=_tuple(
                resolution_input["evidence_refs"], "resolution.evidence_refs"
            ),
            new_display_card_id=resolution_input.get("new_display_card_id"),
        )
        card_ids = [card.card_id for card in identity.display_cards]
    else:
        card_ids = [pending.display_card_id]

    cards: list[dict[str, Any]] = []
    for card_id in card_ids:
        preview = build_event_card_preview(identity, card_id=card_id, ledger=ledger)
        cards.append({"card_id": card_id, "preview": preview})

    result = {
        "scenario_id": scenario["scenario_id"],
        "title": scenario["title"],
        "purpose": scenario["purpose"],
        "classification": "SYNTHETIC",
        "identity_result_source": (
            "EXTERNALLY_SUPPLIED_SYNTHETIC_SCENARIO"
            if resolution_input is not None
            else "EXTERNALLY_SUPPLIED_PENDING_SCENARIO"
        ),
        "identity_input": identity_input,
        "run_steps": run_steps,
        "cards": cards,
        "ledger_summary": {
            "mode": ledger.mode.value,
            "merge_window_seconds": ledger.merge_window_seconds,
            "parameter_status": ledger_configuration["parameter_status"],
            "notification_action_count": ledger.notification_action_count,
            "duplicate_replay_count": ledger.duplicate_replay_count,
            "coalesced_update_count": ledger.coalesced_update_count,
            "missed_important_update_ids": list(ledger.missed_important_update_ids()),
        },
    }
    verify_scenario(result)
    return result


def verify_scenario(scenario: dict[str, Any]) -> None:
    """Fail generation if the real implementation diverges from the example claims."""
    cards = {row["card_id"]: row["preview"] for row in scenario["cards"]}
    identifier = scenario["scenario_id"]
    if identifier == "repeat_same_alarm":
        card = cards["CARD-REPLAY-A"]
        if scenario["run_steps"][1]["decision"]["status"] != "DUPLICATE_REPLAY_IGNORED":
            raise AssertionError("exact replay did not produce DUPLICATE_REPLAY_IGNORED")
        if card["content_revision_count"] != 1 or card["notification_action_count"] != 1:
            raise AssertionError("exact replay unexpectedly created a revision or action")
        if card["replay_attempt_count"] != 1:
            raise AssertionError("the card preview did not retain the replay attempt")
    elif identifier == "risk_escalation_same_card":
        card = cards["CARD-RISK-A"]
        current = card["current_content"]
        if card["content_revision_count"] != 2 or card["notification_action_count"] != 2:
            raise AssertionError("risk escalation did not remain an independent card update")
        if current["severity"] != "CRITICAL":
            raise AssertionError("single high exposure flag did not map to CRITICAL")
        if current["risk_state"]["risk_stage"] != "ESCALATED":
            raise AssertionError("risk stage did not reach ESCALATED")
        if card["association_state"] != "UNKNOWN_PENDING":
            raise AssertionError("risk escalation changed the unresolved identity state")
    elif identifier == "pending_pair_resolves_same":
        card = cards["CARD-SAME-A"]
        if card["association_state"] != "SAME_CONFIRMED":
            raise AssertionError("externally supplied SAME conclusion was not retained")
        if card["event_episode_ids"] != ["EP-SAME-A", "EP-SAME-B"]:
            raise AssertionError("SAME conclusion did not retain both episode references")
        if card["identity_ledger_alignment"]["temporal_alignment"]["status"] != "ALIGNED":
            raise AssertionError("SAME resolution and action ledger timestamps do not align")
    elif identifier == "pending_pair_resolves_different":
        first = cards["CARD-DIFF-A"]
        second = cards["CARD-DIFF-B"]
        if first["event_episode_ids"] != ["EP-DIFF-A"]:
            raise AssertionError("first DIFFERENT card did not retain only episode A")
        if second["event_episode_ids"] != ["EP-DIFF-B"]:
            raise AssertionError("second DIFFERENT card did not retain only episode B")
        if first["history_link_card_ids"] != ["CARD-DIFF-B"]:
            raise AssertionError("first split card is missing its reciprocal history link")
        if second["history_link_card_ids"] != ["CARD-DIFF-A"]:
            raise AssertionError("second split card is missing its reciprocal history link")
        if any(
            card["identity_ledger_alignment"]["temporal_alignment"]["status"]
            != "ALIGNED"
            for card in (first, second)
        ):
            raise AssertionError("DIFFERENT resolution and action ledger timestamps do not align")
    else:
        raise ValueError(f"unrecognized example scenario: {identifier}")

    for card in cards.values():
        if card["delivery_status"] != "NOT_DELIVERED":
            raise AssertionError("example unexpectedly reports actual delivery")
        if card["emitted_at"] is not None or card["visible_at"] is not None:
            raise AssertionError("example unexpectedly reports an emission or visible receipt")
        if card["business_acceptance"] != "NOT_EVALUATED":
            raise AssertionError("example must not claim business acceptance")


def _evidence_refs(values: list[str]) -> str:
    if not values:
        return '<span class="muted">无</span>'
    return "<br>".join(f"<code>{escape(value)}</code>" for value in values)


def render_revision_row(revision: dict[str, Any]) -> str:
    timing = revision["time_evidence"]
    trace = revision["revision_trace"]
    times = [
        ("source", timing["source_times"]),
        ("observed", timing["observed_at_times"]),
        ("trigger known", [timing["trigger_known_time"]] if timing["trigger_known_time"] else []),
        ("detected", [timing["detected_at"]] if timing["detected_at"] else []),
        ("received", [timing["received_at_processing_time"]]),
    ]
    time_html = "<br>".join(
        f"<b>{escape(label)}</b> " + (", ".join(escape(value) for value in values) if values else "—")
        for label, values in times
    )
    current_risk = revision["risk_state"]
    return (
        "<tr>"
        f"<td>r{escape(str(revision['content_revision']))}<br>{escape(trace['action_kind'])}</td>"
        f"<td>{time_html}</td>"
        f"<td>{escape(', '.join(current_risk['risk_flags']) or '—')}<br>"
        f"stage={escape(current_risk['risk_stage'])}<br>severity={escape(str(revision['severity'] or '待定'))}</td>"
        f"<td>{escape(revision['association_state'])}<br>{_evidence_refs(revision['evidence_refs'])}</td>"
        f"<td>{escape(revision['decision_status'])}<br>{escape(trace['decision_reason'])}<br>"
        f"<span class='badge'>{escape(revision['delivery_status'])}</span></td>"
        "</tr>"
    )


def render_card(card_row: dict[str, Any]) -> str:
    preview = card_row["preview"]
    current = preview["current_content"]
    message = current["user_visible_message"] if current else "尚无卡片内容修订。"
    history_rows = "".join(render_revision_row(row) for row in preview["revision_history"])
    episodes = preview["event_episode_ids"] or preview["candidate_episode_ids"]
    links = preview["history_link_card_ids"]
    return (
        "<section class='card'>"
        f"<div class='card-head'><div><span class='eyebrow'>稳定展示卡</span>"
        f"<h4>{escape(card_row['card_id'])}</h4></div>"
        f"<span class='badge'>{escape(preview['association_state'])}</span></div>"
        f"<p><b>episode：</b>{escape(', '.join(episodes) or '未确认')}<br>"
        f"<b>历史互链：</b>{escape(', '.join(links) or '无')}</p>"
        f"<p class='user-message'>{escape(message)}</p>"
        f"<p class='delivery'>投递：{escape(preview['delivery_status'])} · emitted_at：— · visible_at：—</p>"
        "<div class='table-scroll'><table><thead><tr>"
        "<th>修订 / 动作</th><th>时间证据（UTC）</th><th>风险内容</th>"
        "<th>关联 / 证据引用</th><th>账本结果</th></tr></thead>"
        f"<tbody>{history_rows or '<tr><td colspan="5">暂无修订</td></tr>'}</tbody></table></div>"
        "</section>"
    )


def render_scenario(scenario: dict[str, Any]) -> str:
    step_rows = []
    for step in scenario["run_steps"]:
        intent = step["intent"]
        decision = step["decision"]
        step_rows.append(
            "<tr>"
            f"<td>{escape(step['call_received_at'])}<br>{escape(step['label'])}</td>"
            f"<td><code>{escape(intent['intent_id'])}</code><br>"
            f"trigger={escape(str(intent['trigger_known_time']))}<br>"
            f"detected={escape(str(intent['detected_at']))}<br>"
            f"evidence={_evidence_refs(intent['evidence_refs'])}</td>"
            f"<td>{escape(decision['status'])}<br>{escape(decision['decision_reason'])}<br>"
            f"card revision={escape(str(decision['card_revision']))}</td>"
            "</tr>"
        )
    resolution = scenario["identity_input"].get("resolution")
    if resolution:
        identity_panel = (
            "<div class='identity-panel'>"
            f"<b>外部身份结论：</b>{escape(resolution['association_state'])} · "
            "此标签是合成输入，不由本程序推断。<br>"
            f"<b>证据可用：</b>{escape(resolution['identity_evidence_known_at'])} · "
            f"{_evidence_refs(resolution['evidence_refs'])}<br>"
            f"<b>身份解决：</b>{escape(resolution['resolved_at'])}"
            "</div>"
        )
    else:
        identity = scenario["identity_input"]
        identity_panel = (
            "<div class='identity-panel'>"
            f"<b>外部待确认输入：</b>{escape(identity['association_state'])} · "
            f"pending_at={escape(identity['pending_at'])} · "
            f"episodes={escape(', '.join(identity['candidate_episode_ids']))}<br>"
            f"<b>当前身份依据：</b>{_evidence_refs(identity['evidence_refs'])}"
            "</div>"
        )
    cards = "".join(render_card(card) for card in scenario["cards"])
    summary = scenario["ledger_summary"]
    return (
        "<section class='scenario' id='" + escape(scenario["scenario_id"]) + "'>"
        f"<div class='scenario-title'><div><span class='eyebrow'>{escape(scenario['scenario_id'])}</span>"
        f"<h2>{escape(scenario['title'])}</h2></div>"
        f"<span class='badge'>SYNTHETIC</span></div>"
        f"<p class='muted'>{escape(scenario['purpose'])}</p>"
        f"{identity_panel}"
        "<h3>实际 ledger 调用结果</h3>"
        "<div class='table-scroll'><table><thead><tr><th>调用时间 / 输入</th>"
        "<th>已知时间与输入证据</th><th>被测实现返回</th></tr></thead><tbody>"
        f"{' '.join(step_rows)}</tbody></table></div>"
        f"<p class='ledger-summary'>卡片动作数：{summary['notification_action_count']} · "
        f"精确重放数：{summary['duplicate_replay_count']} · "
        f"卡片内合并更新：{summary['coalesced_update_count']} · "
        "漏掉的重要动作："
        f"{escape(', '.join(summary['missed_important_update_ids']) or '无')}</p>"
        f"<div class='cards'>{cards}</div>"
        "</section>"
    )


def render_html(data: dict[str, Any]) -> str:
    tags = " / ".join(data["scope_tags"])
    scenarios = "\n".join(render_scenario(row) for row in data["scenarios"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>合成事件卡示例</title>
<style>
:root {{ color-scheme: light; --ink:#172434; --muted:#526477; --line:#d8e0e9; --paper:#f4f7fb; --blue:#1d5686; --teal:#11675f; --amber:#945400; --pale:#fff7e9; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:14px/1.55 system-ui,"Noto Sans CJK SC","Microsoft YaHei",sans-serif; }}
main {{ max-width:1320px; margin:auto; padding:26px 20px 48px; }}
h1 {{ margin:0 0 8px; font-size:27px; }} h2 {{ margin:0; font-size:20px; }} h3 {{ margin:20px 0 8px; font-size:15px; }} h4 {{ margin:2px 0; font:600 16px ui-monospace,monospace; }}
p {{ margin:8px 0; }} code {{ font:12px ui-monospace,monospace; overflow-wrap:anywhere; }}
.muted {{ color:var(--muted); }} .eyebrow {{ display:block; color:var(--muted); font-size:11px; letter-spacing:.06em; text-transform:uppercase; }}
.banner {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; padding:12px 14px; border:1px solid #e8c58f; border-left:5px solid var(--amber); border-radius:8px; background:var(--pale); }}
.badge {{ display:inline-block; padding:3px 8px; border-radius:999px; color:#15594f; background:#def3ec; font-size:11px; font-weight:750; white-space:nowrap; }}
.scope {{ margin:12px 0 22px; color:var(--muted); font-size:12px; }}
.scenario {{ margin:22px 0; padding:18px; border:1px solid var(--line); border-radius:12px; background:#fff; box-shadow:0 2px 9px #152d4610; }}
.scenario-title,.card-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; }}
.identity-panel {{ margin:12px 0; padding:10px 12px; border-left:3px solid var(--blue); background:#f0f6fb; font-size:13px; overflow-wrap:anywhere; }}
.table-scroll {{ overflow:auto; }} table {{ width:100%; border-collapse:collapse; font-size:12px; }} th,td {{ padding:8px 9px; border-bottom:1px solid #e6edf3; text-align:left; vertical-align:top; min-width:120px; }} th {{ background:#f3f6f9; color:#34475b; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:12px; margin-top:14px; }}
.card {{ min-width:0; padding:13px; border:1px solid #cbd7e3; border-radius:9px; background:#fbfdff; }}
.card p {{ font-size:12px; overflow-wrap:anywhere; }} .user-message {{ padding:10px; background:#f0f5fa; border-radius:7px; }}
.delivery {{ color:var(--amber); font-weight:700; }} .ledger-summary {{ color:var(--muted); font-size:12px; }}
.footnote {{ margin-top:28px; padding:14px; border:1px solid var(--line); border-radius:8px; background:#fff; font-size:12px; color:var(--muted); }}
@media(max-width:650px) {{ main {{ padding:18px 12px 34px; }} h1 {{ font-size:22px; }} .scenario {{ padding:13px; }} .cards {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body><main>
<h1>事件卡示例：重复报警、风险升级与身份分叉</h1>
<p class="muted">由合成输入驱动的本地软件展示。每个时间与身份标签都明确保留来源；HTML 不连接网络或投递系统。</p>
<div class="banner"><span class="badge">SYNTHETIC</span><span class="badge">EXTERNALLY_SUPPLIED identity</span><span class="badge">NOT_DELIVERED</span><span class="badge">C0 / I0 / M0</span><span>任何 SAME / DIFFERENT 结论均是示例输入，不是本程序的真值推断。</span></div>
<p class="scope">发送与用户可见时间均未产生：<code>emitted_at=null</code>、<code>visible_at=null</code>。业务验收、身份真值评分和真实投递均未执行。提醒严重级别只呈现已有单风险标记映射；合成实验窗口仍未冻结。</p>
{scenarios}
<footer class="footnote"><b>解释范围：</b>卡片及 ledger 结果由已测试的纯软件实现生成；`synthetic://` 引用仅为示例标识。合成时间上的处理接收/检测字段不代表真实端到端延迟或实际用户可见性。重复场景展示精确 intent 重放，风险升级展示独立保护动作，身份场景展示外部给定证据时间与解决时间。原 Mac 试验与实机状态未参与本示例。</footer>
</main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    args = parser.parse_args()
    input_bytes = args.input.read_bytes()
    input_data = json.loads(input_bytes)
    if input_data.get("classification") != "SYNTHETIC":
        raise ValueError("input classification must be SYNTHETIC")
    if input_data.get("delivery_status") != "NOT_DELIVERED":
        raise ValueError("input must keep delivery_status NOT_DELIVERED")

    input_sha = sha256(input_bytes).hexdigest()
    generator_sha = file_sha256(Path(__file__).resolve())
    implementation_sha = {
        relative: file_sha256(REPOSITORY / relative)
        for relative in IMPLEMENTATION_FILES
    }
    configuration = input_data["ledger_configuration"]
    scenarios = [
        run_scenario(row, ledger_configuration=configuration)
        for row in input_data["scenarios"]
    ]
    output_data = {
        "format_version": "1.0",
        "classification": "SYNTHETIC",
        "scope_tags": input_data["scope_tags"],
        "identity_result_source": input_data["identity_input_provenance"],
        "delivery_status": "NOT_DELIVERED",
        "emitted_at": None,
        "visible_at": None,
        "business_acceptance": "NOT_EVALUATED",
        "identity_truth": "NOT_EVALUATED",
        "execution_boundary": {
            "in_memory_ledger_only": True,
            "model_or_network_service_called": False,
            "delivery_adapter_called": False,
            "actual_delivery": "NOT_RUN",
            "old_1464_trial_rerun": False,
            "mac_device_validation": "NOT_RUN",
        },
        "provenance": {
            "input_file": args.input.resolve().relative_to(REPOSITORY).as_posix(),
            "input_sha256": input_sha,
            "generator_file": Path(__file__).resolve().relative_to(REPOSITORY).as_posix(),
            "generator_sha256": generator_sha,
            "tested_implementation_base_commit": SOURCE_COMMIT,
            "implementation_files_sha256": implementation_sha,
            "generation_command": GENERATOR_COMMAND,
        },
        "ledger_configuration": configuration,
        "scenarios": scenarios,
    }
    DATA_PATH.write_text(stable_json(output_data), encoding="utf-8")
    HTML_PATH.write_text(render_html(output_data), encoding="utf-8")

    manifest = {
        "classification": "SYNTHETIC",
        "scope_tags": input_data["scope_tags"],
        "delivery_status": "NOT_DELIVERED",
        "business_acceptance": "NOT_EVALUATED",
        "source_commit": SOURCE_COMMIT,
        "command": GENERATOR_COMMAND,
        "input": {
            "path": args.input.resolve().relative_to(REPOSITORY).as_posix(),
            "sha256": input_sha,
        },
        "generator": {
            "path": Path(__file__).resolve().relative_to(REPOSITORY).as_posix(),
            "sha256": generator_sha,
        },
        "tested_implementation_sha256": implementation_sha,
        "outputs": {
            DATA_PATH.name: file_sha256(DATA_PATH),
            HTML_PATH.name: file_sha256(HTML_PATH),
        },
        "manifest_self_hash": "OMITTED_BY_DESIGN",
    }
    MANIFEST_PATH.write_text(stable_json(manifest), encoding="utf-8")
    print(stable_json({"manifest": MANIFEST_PATH.name, **manifest}), end="")


if __name__ == "__main__":
    main()
