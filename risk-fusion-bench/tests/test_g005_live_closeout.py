from copy import deepcopy

import pytest

from rfb.live_closeout import CloseoutBlocked, FULL_PANEL, LiveCloseoutRehearsal


def proofs():
    return {
        "capacity": {
            "status": "PASS",
            "peak_bytes": 10_000_000,
            "planning_peak_bytes": 9_000_000,
            "subbudget_borrowing": False,
            "max_sampling_interval_seconds": 30,
        },
        "durable_result": {
            "status": "PASS",
            "sealed": True,
            "contains_raw_dataset": False,
            "truth_isolation": "PASS",
            "complete_rows": 14,
            "manifest_hash": "a" * 64,
            "merkle_root": "b" * 64,
        },
        "archives": {
            "A": {
                "storage_identity": "archive-a",
                "failure_domain": "host-a",
                "missing": 0,
                "unexpected": 0,
                "mismatch": 0,
                "readback_status": "PASS",
                "contains_raw_dataset": False,
            },
            "B": {
                "storage_identity": "archive-b",
                "failure_domain": "host-b",
                "missing": 0,
                "unexpected": 0,
                "mismatch": 0,
                "readback_status": "PASS",
                "contains_raw_dataset": False,
            },
        },
        "regeneration": {
            "status": "PASS",
            "sample_plan_frozen_before_execution": True,
            "sample_count": 2,
            "replacement_sampling": False,
            "payload_commitments_match": True,
            "full_panel_replay_match": True,
        },
        "purge": {
            "status": "PASS",
            "approval_artifact_status": "ISSUED",
            "ds_stat_used_as_authorization": False,
            "ledger_states": [
                "APPROVAL_RECORDED",
                "CLAIMED",
                "PURGE_INTENT",
                "COMMITTED",
            ],
            "ephemeral_files_remaining": 0,
            "open_deleted_bytes": 0,
            "unexplained_space_delta": 0,
            "archive_a_reread": "PASS",
            "archive_b_reread": "PASS",
        },
    }


def rehearsal():
    return LiveCloseoutRehearsal(
        segment_id="seg-1",
        bundle_ids=["b1", "b2"],
        method_ids=FULL_PANEL,
        active_failure_domain="active",
    )


def test_complete_closeout_seals_reconciled_live_evidence():
    out = rehearsal().seal(proofs())
    assert out["classification"] == "LIVE_CLOSEOUT_REHEARSAL"
    assert out["contains_development_evidence"] is True
    assert out["terminal_state"] == "RECONCILED"
    assert out["bundle_count"] == 2
    assert len(out["gates"]) == 5
    assert out["sealed_body"]["state_trace"][-1] == "RECONCILED"


def test_single_bundle_and_split_panel_are_rejected():
    with pytest.raises(CloseoutBlocked, match=">=2"):
        LiveCloseoutRehearsal(
            segment_id="s",
            bundle_ids=["b1"],
            method_ids=FULL_PANEL,
            active_failure_domain="a",
        )
    with pytest.raises(CloseoutBlocked, match="panel"):
        LiveCloseoutRehearsal(
            segment_id="s",
            bundle_ids=["b1", "b2"],
            method_ids=FULL_PANEL[:-1],
            active_failure_domain="a",
        )


@pytest.mark.parametrize(
    ("domain", "mutate"),
    [
        ("capacity", lambda x: x["capacity"].update(peak_bytes=25_000_000_001)),
        ("durable", lambda x: x["durable_result"].update(contains_raw_dataset=True)),
        ("archive", lambda x: x["archives"]["B"].update(storage_identity="archive-a")),
        ("regen", lambda x: x["regeneration"].update(sample_count=1)),
        ("purge", lambda x: x["purge"].update(ephemeral_files_remaining=1)),
    ],
)
def test_each_failed_domain_blocks(domain, mutate):
    item = proofs()
    mutate(item)
    with pytest.raises(CloseoutBlocked):
        rehearsal().seal(item)


def test_ds_stat_cannot_be_purge_authorization():
    item = proofs()
    item["purge"]["ds_stat_used_as_authorization"] = True
    with pytest.raises(CloseoutBlocked, match="DS/STAT"):
        rehearsal().seal(item)


def test_incomplete_purge_ledger_and_same_failure_domain_block():
    item = proofs()
    item["purge"]["ledger_states"] = ["APPROVAL_RECORDED", "COMMITTED"]
    with pytest.raises(CloseoutBlocked, match="ledger"):
        rehearsal().seal(item)
    item = proofs()
    item["archives"]["B"]["failure_domain"] = "host-a"
    with pytest.raises(CloseoutBlocked, match="failure"):
        rehearsal().seal(item)


def test_seal_detects_proof_tampering_by_hash_change():
    out = rehearsal().seal(proofs())
    changed = deepcopy(out["sealed_body"])
    changed["proofs"]["capacity"]["peak_bytes"] += 1
    from rfb.live_gate import canonical_hash

    assert canonical_hash(changed) != out["sealed_evidence_hash"]
