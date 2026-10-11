#!/usr/bin/env python3
"""Run a synthetic idempotency-layer counterexample and render standalone HTML."""

from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

from rfb.research.alert_governance import AlertLedger, CandidateEvent, DeliveryStatus


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def observation(
    candidate_id: str,
    source_id: str,
    evidence_ref: str,
    *,
    observed_at: str = "2026-10-11T08:00:01Z",
) -> CandidateEvent:
    return CandidateEvent(
        candidate_id=candidate_id,
        event_time="2026-10-11T08:00:00Z",
        observed_at=observed_at,
        summary=f"Synthetic observation {candidate_id}",
        source_id=source_id,
        evidence_refs=(evidence_ref,),
        risk_flag="EXPOSURE",
    )


def build_result() -> dict:
    ledger = AlertLedger(delivery_status=DeliveryStatus.SIMULATED)
    original = observation("obs-a", "device-a", "synthetic://obs/a")
    first_card = ledger.add_candidate(original, alerted_at="2026-10-11T08:00:03Z")
    observations_before_replay = {
        "candidate_ids": list(first_card.candidate_ids),
        "card_count": len(ledger.cards),
        "alert_count": len(ledger.alerts),
        "evidence_refs": list(ledger.alerts[0].evidence_refs),
        "observed_at": ledger.alerts[0].observed_at,
    }
    ledger.add_candidate(original, alerted_at="2026-10-11T09:00:00Z")
    observations_after_replay = {
        "candidate_ids": list(ledger.card_for("obs-a").candidate_ids),
        "card_count": len(ledger.cards),
        "alert_count": len(ledger.alerts),
        "evidence_refs": list(ledger.alerts[0].evidence_refs),
        "observed_at": ledger.alerts[0].observed_at,
    }

    stale_replay = observation(
        "obs-a",
        "device-a",
        "synthetic://obs/a",
        observed_at="2026-10-11T09:00:00Z",
    )
    stale_replay_status = "REJECTED"
    stale_replay_error = ""
    try:
        ledger.add_candidate(stale_replay, alerted_at="2026-10-11T09:00:01Z")
    except ValueError as exc:
        stale_replay_error = str(exc)
    else:
        stale_replay_status = "ACCEPTED_UNEXPECTEDLY"

    complementary = observation(
        "obs-b",
        "device-b",
        "synthetic://obs/b-complementary",
        observed_at="2026-10-11T08:00:02Z",
    )
    ledger.add_candidate(complementary, alerted_at="2026-10-11T08:00:04Z")
    pending = ledger.propose_association(
        "obs-a",
        "obs-b",
        at="2026-10-11T08:00:05Z",
        rationale="Synthetic observations may describe the same event.",
        evidence_refs=("synthetic://match/a-b",),
    )
    complementary_sources = sorted(
        alert.source_ids[0]
        for alert in ledger.alerts
        if "CANDIDATE_RISK_FLAG" in alert.reason_codes
    )
    complementary_refs = sorted(
        alert.evidence_refs[0]
        for alert in ledger.alerts
        if "CANDIDATE_RISK_FLAG" in alert.reason_codes
    )

    match_ledger = AlertLedger(delivery_status=DeliveryStatus.SIMULATED)
    cards = {}
    for second, candidate_id in enumerate(("match-a", "match-b", "match-c"), start=3):
        cards[candidate_id] = match_ledger.add_candidate(
            observation(
                candidate_id,
                f"device-{candidate_id[-1]}",
                f"synthetic://obs/{candidate_id}",
            ),
            alerted_at=f"2026-10-11T08:00:{second:02d}Z",
        )
    first_match = match_ledger.propose_association(
        "match-a",
        "match-b",
        at="2026-10-11T08:00:06Z",
        rationale="Synthetic overlap A-B.",
        evidence_refs=("synthetic://match/a-b",),
    )
    match_alerts_before_replay = len(match_ledger.alerts)
    match_ledger.propose_association(
        "match-b",
        "match-a",
        at="2026-10-11T08:00:08Z",
        rationale="Synthetic replay A-B.",
        evidence_refs=("synthetic://match/a-b",),
    )
    match_alerts_after_replay = len(match_ledger.alerts)
    associations_after_same_pair_replay = len(match_ledger.associations)
    second_match = match_ledger.propose_association(
        "match-a",
        "match-c",
        at="2026-10-11T08:00:09Z",
        rationale="Synthetic overlap A-C.",
        evidence_refs=("synthetic://match/a-c",),
    )
    actions_on_a = [
        alert
        for alert in match_ledger.alerts
        if alert.card_id == cards["match-a"].card_id
        and alert.reason_codes == ("IDENTITY_LINK_PENDING",)
    ]

    history = json.loads(
        (ROOT / "research-three/alert-governance-v1/historical-baseline.json").read_text()
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    return {
        "scenario_id": "SYNTH-IDEMPOTENCY-LAYERS-001",
        "classification": "SYNTHETIC_CHARACTERIZATION_ONLY",
        "source_commit": head,
        "execution_boundary": {
            "model_service_called": False,
            "delivery_adapter_called": False,
            "delivery_status": "SIMULATED",
            "delivered_at": None,
            "independent_source_qualification": "NOT_EVALUATED",
            "key_interval_or_credibility_threshold_frozen": False,
            "old_1464_trial_rerun": False,
        },
        "observation_layer": {
            "exact_replay_input_observations": 2,
            "before": observations_before_replay,
            "after": observations_after_replay,
            "idempotent_for_exact_candidate_record": observations_before_replay
            == observations_after_replay,
            "stale_replay": {
                "candidate_id": stale_replay.candidate_id,
                "old_observed_at": original.observed_at,
                "replayed_observed_at": stale_replay.observed_at,
                "status": stale_replay_status,
                "error": stale_replay_error,
                "ledger_observed_at_after_rejection": ledger.alerts[0].observed_at,
                "validity_field_exists_in_candidate_contract": False,
            },
            "complementary_device_observations": {
                "association_status": pending.status,
                "candidate_ids_retained": sorted(
                    candidate_id for card in ledger.cards for candidate_id in card.candidate_ids
                ),
                "distinct_display_card_count_while_pending": len(ledger.cards),
                "source_ids_retained": complementary_sources,
                "evidence_refs_retained": complementary_refs,
                "source_ids_prove_trustworthy_independence": False,
            },
        },
        "match_layer": {
            "same_pair_association_id": first_match.association_id,
            "same_pair_replay_association_count": associations_after_same_pair_replay,
            "association_count_after_overlapping_pair": len(match_ledger.associations),
            "alerts_before_same_pair_replay": match_alerts_before_replay,
            "alerts_after_same_pair_replay": match_alerts_after_replay,
            "same_pair_replay_emitted_new_alert": match_alerts_after_replay
            != match_alerts_before_replay,
            "overlapping_pairs": [
                ["match-a", "match-b"],
                ["match-a", "match-c"],
            ],
            "second_association_id": second_match.association_id,
            "same_card_pending_action_count_after_overlap": len(actions_on_a),
            "action_reason_codes": [list(alert.reason_codes) for alert in actions_on_a],
            "action_evidence_refs": [list(alert.evidence_refs) for alert in actions_on_a],
        },
        "action_layer": {
            "status": "NO_ACTION_LEVEL_DEDUP_POLICY_IN_CURRENT_LEDGER",
            "same_match_replay_is_suppressed": match_alerts_after_replay
            == match_alerts_before_replay,
            "overlapping_distinct_matches_repeat_same_action_class": len(actions_on_a) > 1,
            "episode_interval_key_defined": False,
            "conclusion": "Input replay idempotency does not establish match or notification-action idempotency.",
        },
        "historical_baseline": {
            "checks_executed": history["checks_executed"],
            "round_status": history["round_status"],
            "method_records": history["method_records"],
            "method_records_are_independent_samples": history[
                "method_records_are_independent_samples"
            ],
            "failure_summary": history["failure_summary"],
            "rerun_this_time": False,
        },
    }


def render_html(result: dict) -> str:
    obs = result["observation_layer"]
    match = result["match_layer"]
    stale = obs["stale_replay"]
    comp = obs["complementary_device_observations"]
    baseline = result["historical_baseline"]

    def pill(value: str, cls: str = "") -> str:
        return f'<span class="pill {cls}">{html.escape(value)}</span>'

    rows = [
        ("精确观测重放", "观测层", "1 个 candidate 原样再到达", "candidate/card/evidence/alert 计数不变"),
        (
            "旧记录刷新时间",
            "观测层",
            f"同一 candidate_id 把 observed_at 从 {stale['old_observed_at']} 改成 {stale['replayed_observed_at']}",
            f"{stale['status']}；旧 observed_at 保留。当前 CandidateEvent 没有 validity 字段。",
        ),
        (
            "互补设备观测",
            "观测层 → 匹配层",
            f"{', '.join(comp['source_ids_retained'])} 的两个不同 candidate",
            f"{comp['association_status']}；仍保留 {comp['distinct_display_card_count_while_pending']} 张卡和两个节点",
        ),
        (
            "同一匹配对重放",
            "匹配层",
            "A-B 同一 association 再提议一次",
            f"alert 数 {match['alerts_before_same_pair_replay']} → {match['alerts_after_same_pair_replay']}；没有新动作",
        ),
        (
            "重叠匹配对",
            "匹配层 → 动作层",
            "A-B 与 A-C 是不同 association，但都触达卡 A",
            f"卡 A 收到 {match['same_card_pending_action_count_after_overlap']} 条同类待核提醒更新；动作层无独立去重策略",
        ),
    ]
    table_rows = "\n".join(
        "<tr>"
        + "".join(f"<td>{html.escape(value)}</td>" for value in row)
        + "</tr>"
        for row in rows
    )
    evidence_list = "".join(
        f"<li>{html.escape(ref)}</li>"
        for ref in comp["evidence_refs_retained"]
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>合成去重分层反例</title><style>
:root{{--ink:#182b3c;--muted:#52667a;--line:#d9e2ec;--blue:#eaf3fb;--green:#e8f5ee;--amber:#fff3da;--red:#fce8e6;--paper:#f7f9fc}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:32px 22px 48px}}h1{{font-size:30px;line-height:1.15;margin:8px 0}}h2{{font-size:20px;margin:0 0 12px}}p{{margin:8px 0;color:var(--muted)}}
.eyebrow{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#2563a5;font-weight:700}}.sub{{font-size:15px;max-width:850px}}
.layers{{display:grid;grid-template-columns:1fr 22px 1fr 22px 1fr;gap:8px;margin:22px 0}}
.layer,.panel{{background:white;border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 2px 8px #14283b0b}}
.layer{{min-height:120px}}.layer b{{display:block;font-size:17px;margin:4px 0}}.layer.obs{{border-top:5px solid #4386c6}}.layer.match{{border-top:5px solid #d9941e}}.layer.action{{border-top:5px solid #bb4d47}}
.arrow{{color:#8ba0b3;font-size:22px;text-align:center;padding-top:25px}}.grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:14px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px 9px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}}th{{background:#f0f5fa;color:#354b60;font-size:12px}}
.pill{{display:inline-block;border-radius:99px;padding:2px 8px;font-size:12px;background:var(--blue);color:#24527a;font-weight:700}}.fail{{background:var(--red);color:#8c2925}}.pass{{background:var(--green);color:#256342}}.unknown{{background:var(--amber);color:#82530a}}
.callout{{border-left:4px solid #d9941e;background:var(--amber);padding:12px 14px;border-radius:8px;margin:14px 0}}.danger{{border-left-color:#b8443e;background:var(--red)}}
.code{{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}.footer{{font-size:13px;border-top:1px solid var(--line);padding-top:14px;margin-top:18px}}
@media(max-width:760px){{.layers,.grid{{grid-template-columns:1fr}}.arrow{{padding:0;transform:rotate(90deg)}}main{{padding:20px 14px}}table{{font-size:13px}}th,td{{padding:8px 6px}}}}
</style></head><body><main>
<div class="eyebrow">合成字符化 · {html.escape(result['scenario_id'])}</div>
<h1>输入去重，不等于动作去重</h1>
<p class="sub">同一原始观测重放可在观测层幂等；不同观测仍须保留；匹配关系有自己的 ID；多个不同关系还可能触发同一卡片的重复提醒动作。以下只刻画本地软件 ledger。</p>
<div class="layers">
 <section class="layer obs"><span class="pill pass">现有边界可测</span><b>① 观测层</b><p>同一 candidate_id 与相同内容重放不增记录；更改旧 observed_at 会被拒绝。</p></section>
 <div class="arrow">→</div>
 <section class="layer match"><span class="pill unknown">匹配关系单独计</span><b>② 匹配层</b><p>同一 A-B 关系重放不新发；A-B 与 A-C 是不同关系，不能只按输入去重抹掉。</p></section>
 <div class="arrow">→</div>
 <section class="layer action"><span class="pill fail">当前未保证</span><b>③ 通知动作层</b><p>两个不同待核关系都触达卡 A 时，会产生两次同类更新；当前没有 action-level dedup key。</p></section>
</div>
<section class="panel"><h2>受控反例对照</h2><table><thead><tr><th>扰动</th><th>层</th><th>合成输入</th><th>实际 ledger 结果</th></tr></thead><tbody>{table_rows}</tbody></table></section>
<div class="grid" style="margin-top:14px">
 <section class="panel"><h2>互补观测没有被事件级去重删除</h2><p>两个 source_id / candidate_id 不同，处于待核关系时仍保留两个节点和展示卡。这里仅证明 source_id 与内容可追溯；不据此声称来源可信或统计独立。</p><ul class="code">{evidence_list}</ul><p>关系状态：{pill(comp['association_status'])} · 候选节点数：{len(comp['candidate_ids_retained'])}</p></section>
 <section class="panel"><h2>旧失败记录保持不变</h2><p>{baseline['checks_executed']:,} 项检查 · {pill(baseline['round_status'], 'fail')} · {baseline['method_records']} 条方法记录（非独立样本）</p><p>{html.escape(baseline['failure_summary'])}</p><p>本次未重跑旧试验。</p></section>
</div>
<div class="callout danger"><b>受控边界：</b> stale replay 状态 {pill(stale['status'], 'pass')}；old observed_at={html.escape(stale['ledger_observed_at_after_rejection'])}，没有被改成现在。CandidateEvent 没有 validity 字段，因此本例只能证明时间不被刷新，不能声称已验证 validity/TTL。</div>
<div class="callout"><b>未冻结决策：</b>不同匹配对产生的同类提醒是否应合并成一次卡片更新，取决于 action key 与 episode interval 规则。本例不选 key、不定窗口，也不评价模型调用节省、用户负担效果或真实投递。</div>
<p class="footer">本文件无外部资源依赖。证据引用为 synthetic:// 占位；通知状态 SIMULATED，delivered_at=null。模型服务、投递适配器和 Mac 测试均未运行。</p>
</main></body></html>"""


def main() -> None:
    result = build_result()
    data_path = OUT / "idempotency-layers-data.json"
    html_path = OUT / "idempotency-layers-comparison.html"
    data_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    html_path.write_text(render_html(result))
    print(
        json.dumps(
            {
                "scenario_id": result["scenario_id"],
                "classification": result["classification"],
                "exact_replay_idempotent": result["observation_layer"][
                    "idempotent_for_exact_candidate_record"
                ],
                "stale_replay": result["observation_layer"]["stale_replay"]["status"],
                "independent_source_nodes_retained": len(
                    result["observation_layer"]["complementary_device_observations"][
                        "candidate_ids_retained"
                    ]
                ),
                "same_match_replay_new_action": result["match_layer"][
                    "same_pair_replay_emitted_new_alert"
                ],
                "overlap_actions_on_card_a": result["match_layer"][
                    "same_card_pending_action_count_after_overlap"
                ],
                "historical_status": result["historical_baseline"]["round_status"],
                "data_path": str(data_path),
                "html_path": str(html_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
