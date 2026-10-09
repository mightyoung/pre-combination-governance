from pathlib import Path

import pytest

from rfb.research.controller import guard_mme_controller_entry


def test_local_scope_needs_no_authorization_file(tmp_path: Path):
    guard_mme_controller_entry(
        tmp_path,
        operation="LOCAL_MME_V2",
        independent_blocks=27,
        dataset_split="MME_v2",
    )


@pytest.mark.parametrize(
    "operation,blocks,split,error",
    [
        ("REMOTE", 27, "MME_v2", "NONLOCAL"),
        ("LOCAL_MME_V2", 26, "MME_v2", "BLOCK_COUNT"),
        ("LOCAL_MME_V2", 27, "D_test", "RUN_CLASS"),
        ("LOCAL_MME_V2", 1, "MME_v2", "BLOCK_COUNT"),
    ],
)
def test_local_scope_still_rejects_wrong_protocol(
    tmp_path: Path, operation, blocks, split, error
):
    with pytest.raises(ValueError, match=error):
        guard_mme_controller_entry(
            tmp_path,
            operation=operation,
            independent_blocks=blocks,
            dataset_split=split,
        )


def test_cli_real_entry_dispatches_without_approval_arguments(tmp_path, monkeypatch):
    from rfb.research import __main__ as cli
    from rfb.research import mme_runner

    received = []

    def capture(config, *, resume):
        received.append((config, resume))
        return {"terminal_state": "SUCCEEDED"}

    monkeypatch.setattr(mme_runner, "run_mme", capture)
    assert cli.main(["mme-run", "--workspace", str(tmp_path), "--smoke"]) == 0
    config, resume = received[0]
    assert config["run_class"] == "D_development"
    assert config["block_limit"] == 1
    assert not resume
    assert "authorization" not in config and "request" not in config


def test_cli_config_cannot_replace_workspace_scope(tmp_path):
    import json
    from rfb.research import __main__ as cli

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"workspace_root": str(tmp_path.parent)}), encoding="utf-8"
    )
    assert (
        cli.main(["mme-run", "--workspace", str(tmp_path), "--config", str(config)])
        == cli.EXIT["invalid"]
    )
