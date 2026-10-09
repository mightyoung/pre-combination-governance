import copy
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfb.contracts.canonical_json import CanonicalJsonError, canonical_bytes, sha256_hex  # noqa: E402
from rfb.contracts.failure_codes import (  # noqa: E402
    FAILURE_CODE_REGISTRY,
    FailureCode,
    PRIMARY_ORDER,
    enumerate_failure_codes,
    primary_failure_code,
)
import rfb.contracts.package_validator as package_validator_module  # noqa: E402
from rfb.contracts.package_validator import (  # noqa: E402
    REQUIRED_BINDINGS,
    validate_and_commit_package,
)
from rfb.contracts.schema_versions import CompatibilityRegistry, parse_semantic_version  # noqa: E402
from rfb.contracts.schemas import SCHEMA_DEFINITIONS, validate_schema  # noqa: E402


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "contracts" / "static_schema_fixtures.json"
)


def fixtures():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def manifest_fixture():
    return copy.deepcopy(fixtures()["NormativeReleaseManifest"]["positive"])


def write_artifact(tmp_path, name="artifact.txt", content=b"stage1-artifact"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path, sha256_hex(content)


def package_index(
    tmp_path,
    *,
    artifact_id="artifact-a",
    path="artifact.txt",
    sha256=None,
    schema_name=None,
    schema_version=None,
):
    """Build a complete closed package index and mutate the returned manifest.

    The older one-file helper encoded the defect that a partial package could
    validate. Stage-1 now requires manifest-to-artifact closure for every
    normative hash binding.
    """

    manifest = manifest_fixture()
    artifacts = []
    for idx, binding_key in enumerate(REQUIRED_BINDINGS):
        rel_path = path if idx == 0 else f"artifacts/{binding_key}.bin"
        artifact_path = tmp_path / rel_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if idx == 0 and artifact_path.exists():
            content = artifact_path.read_bytes()
        else:
            content = f"{binding_key}:stage1".encode("utf-8")
            artifact_path.write_bytes(content)
        digest = sha256 if idx == 0 and sha256 is not None else sha256_hex(content)
        manifest[binding_key] = digest
        descriptor = {
            "artifact_id": artifact_id if idx == 0 else binding_key,
            "binding_key": binding_key,
            "path": rel_path,
            "sha256": digest,
        }
        companion = binding_key.removesuffix("_sha256") + "_version"
        if companion in manifest:
            descriptor["artifact_version"] = manifest[companion]
        if idx == 0 and schema_name is not None:
            descriptor["schema_name"] = schema_name
            descriptor["schema_version"] = schema_version or "1.0.0"
        artifacts.append(descriptor)
    manifest["dependency_edges"] = [{"from": manifest["release_id"], "to": artifact_id}]
    return manifest, {
        "schema_version": "1.0.0",
        "release_id": manifest["release_id"],
        "artifacts": artifacts,
    }


def install_schema_content(
    root,
    manifest,
    index,
    schema_name,
    content,
    *,
    descriptor_version="1.0.0",
    descriptor_index=0,
):
    path = root / index["artifacts"][descriptor_index]["path"]
    payload = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    path.write_bytes(payload)
    digest = sha256_hex(payload)
    binding_key = index["artifacts"][descriptor_index]["binding_key"]
    manifest[binding_key] = digest
    index["artifacts"][descriptor_index].update(
        sha256=digest,
        schema_name=schema_name,
        schema_version=descriptor_version,
    )


def test_canonical_json_golden_vectors_and_source_newline_equivalence():
    value = {"中": [True, None], "a": "x", "é": 1}
    golden = b'{"a":"x","\xc3\xa9":1,"\xe4\xb8\xad":[true,null]}'
    assert canonical_bytes(value) == golden
    assert (
        sha256_hex(golden)
        == "39c94d233511ca8a0ca3dba8ca9046533eb890aca561bcf0d869bfed41782ada"
    )
    assert not canonical_bytes(value).startswith(b"\xef\xbb\xbf")
    assert not canonical_bytes(value).endswith(b"\n")

    lf = '{"z": [1, 2], "a": {"b": true}}\n'
    crlf = lf.replace("\n", "\r\n")
    assert canonical_bytes(json.loads(lf)) == canonical_bytes(json.loads(crlf))


@pytest.mark.parametrize(
    "bad", [{1: "x"}, {"x": math.nan}, {"x": math.inf}, {"x": object()}]
)
def test_canonical_json_rejects_non_json_inputs(bad):
    with pytest.raises(CanonicalJsonError):
        canonical_bytes(bad)


def test_canonical_json_rejects_cyclic_dict_and_list_as_typed_error():
    cyclic_dict = {}
    cyclic_dict["self"] = cyclic_dict
    cyclic_list = []
    cyclic_list.append(cyclic_list)

    with pytest.raises(CanonicalJsonError):
        canonical_bytes(cyclic_dict)
    with pytest.raises(CanonicalJsonError):
        canonical_bytes(cyclic_list)


def test_semantic_version_exact_by_default_and_explicit_registry_only():
    assert str(parse_semantic_version("1.2.3")) == "1.2.3"
    for bad in ["1.2", "01.2.3", "1.2.3-alpha", 123]:
        with pytest.raises(ValueError):
            parse_semantic_version(bad)

    registry = CompatibilityRegistry()
    assert registry.is_compatible("RootIdentity", "1.0.0", "1.0.0")
    assert not registry.is_compatible("RootIdentity", "1.0.0", "0.9.0")
    assert not registry.is_compatible("RootIdentity", "1.0.0", "2.0.0")
    explicit = registry.with_reference("RootIdentity", "1.0.0", "0.9.0")
    assert explicit.is_compatible("RootIdentity", "1.0.0", "0.9.0")


def test_all_nine_static_schema_fixtures_have_positive_and_negative_cases():
    data = fixtures()
    assert set(data) == set(SCHEMA_DEFINITIONS)
    for schema_name, cases in data.items():
        assert validate_schema(schema_name, cases["positive"]).valid, schema_name
        assert not validate_schema(schema_name, cases["negative"]).valid, schema_name


def test_closed_schema_missing_required_and_unknown_field_cases():
    root = fixtures()["RootIdentity"]["positive"]
    missing = copy.deepcopy(root)
    missing.pop("credential_subject")
    unknown = copy.deepcopy(root)
    unknown["surprise"] = "closed"
    assert not validate_schema("RootIdentity", missing).valid
    assert not validate_schema("RootIdentity", unknown).valid


def test_pending_hash_spelling_is_exact():
    manifest = manifest_fixture()
    manifest["main_sha256"] = "PENDING-HASH"
    result = validate_schema("NormativeReleaseManifest", manifest)
    assert result.valid
    assert "$.main_sha256" in result.pending_hash_paths

    manifest["main_sha256"] = "PENDING_HASH"
    assert not validate_schema("NormativeReleaseManifest", manifest).valid


def test_failure_code_registry_is_immutable_enumerable_duplicate_free_and_ordered():
    codes = enumerate_failure_codes()
    assert len(codes) == len(set(codes))
    assert "FILE_MISSING" in FAILURE_CODE_REGISTRY
    with pytest.raises(TypeError):
        FAILURE_CODE_REGISTRY["NEW"] = FailureCode.FILE_MISSING  # type: ignore[index]
    assert (
        primary_failure_code([FailureCode.HASH_MISMATCH, FailureCode.FILE_MISSING])
        == FailureCode.FILE_MISSING
    )
    assert (
        FailureCode.PACKAGE_CONSISTENCY_INVALID.value == "PACKAGE_CONSISTENCY_INVALID"
    )


def test_package_validator_success_atomic_receipt_and_repeat_target(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "new-parent" / "receipt"
    result = validate_and_commit_package(
        package_root=tmp_path,
        manifest=manifest,
        index=index,
        output_dir=target,
    )
    assert result.success
    assert result.confirmation_eligible
    assert result.receipt_path == str(target / "validation_receipt.json")
    receipt = (target / "validation_receipt.json").read_bytes()
    assert b"formal_experiment_artifact" in receipt
    assert not receipt.endswith(b"\n")

    repeat = validate_and_commit_package(
        package_root=tmp_path,
        manifest=manifest,
        index=index,
        output_dir=target,
    )
    assert not repeat.success
    assert repeat.primary_code == FailureCode.OUTPUT_ALREADY_EXISTS


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (
            lambda tmp, manifest, index: index["artifacts"][0].update(
                path="missing.txt"
            ),
            FailureCode.FILE_MISSING,
        ),
        (
            lambda tmp, manifest, index: (
                tmp / index["artifacts"][0]["path"]
            ).write_bytes(b"tampered"),
            FailureCode.HASH_MISMATCH,
        ),
        (
            lambda tmp, manifest, index: index["artifacts"][0].update(
                artifact_version="old-label"
            ),
            FailureCode.STALE_VERSION_REFERENCE,
        ),
        (
            lambda tmp, manifest, index: index["artifacts"][0].update(
                schema_name="UnknownSchema", schema_version="1.0.0"
            ),
            FailureCode.SCHEMA_INCOMPATIBLE,
        ),
        (
            lambda tmp, manifest, index: manifest.update(
                dependency_edges=[{"from": "rel-001", "to": "missing"}]
            ),
            FailureCode.MISSING_DEPENDENCY_ENDPOINT,
        ),
        (
            lambda tmp, manifest, index: manifest.update(
                dependency_edges=[{"from": "artifact-a", "to": "artifact-a"}]
            ),
            FailureCode.DEPENDENCY_CYCLE,
        ),
        (
            lambda tmp, manifest, index: manifest.pop("release_id"),
            FailureCode.MANIFEST_SCHEMA_INVALID,
        ),
    ],
)
def test_package_validator_distinct_reason_codes_and_failure_tree_unchanged(
    tmp_path, mutate, expected
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    mutate(tmp_path, manifest, index)
    absent_parent = tmp_path / "absent-parent"
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    result = validate_and_commit_package(
        package_root=tmp_path,
        manifest=manifest,
        index=index,
        output_dir=absent_parent / "receipt",
    )
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert not result.success
    assert result.primary_code == expected
    assert before == after
    assert not absent_parent.exists()


def test_package_validator_multi_node_cycle(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][1]["artifact_id"] = "artifact-b"
    manifest["dependency_edges"] = [
        {"from": "artifact-a", "to": "artifact-b"},
        {"from": "artifact-b", "to": "artifact-a"},
    ]
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.DEPENDENCY_CYCLE


def test_pending_hash_design_vs_confirmation_behavior(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    manifest["main_sha256"] = "PENDING-HASH"
    index["artifacts"][0]["sha256"] = "PENDING-HASH"

    design_target = tmp_path / "design-receipt"
    design = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=design_target
    )
    assert design.success
    assert not design.confirmation_eligible
    assert (design_target / "validation_receipt.json").is_file()

    confirm_target = tmp_path / "confirm-parent" / "receipt"
    confirmation = validate_and_commit_package(
        package_root=tmp_path,
        manifest=manifest,
        index=index,
        output_dir=confirm_target,
        mode="confirmation",
    )
    assert not confirmation.success
    assert confirmation.primary_code == FailureCode.CONFIRMATION_PENDING_HASH
    assert not confirm_target.parent.exists()

    missing = copy.deepcopy(index)
    missing["artifacts"][0]["path"] = "missing-pending.txt"
    pending_missing = validate_and_commit_package(
        package_root=tmp_path,
        manifest=manifest,
        index=missing,
        output_dir=tmp_path / "missing-out",
    )
    assert not pending_missing.success
    assert pending_missing.primary_code == FailureCode.FILE_MISSING
    assert not (tmp_path / "missing-out").exists()


@pytest.mark.parametrize(
    "package_root,rel_path,output_parts",
    [
        ("D_test", "artifact.txt", ("safe", "receipt")),
        ("safe", "D_test/artifact.txt", ("safe", "receipt")),
        ("safe", "artifact.txt", ("D_TEST", "receipt")),
        ("safe", "nested/d_Test/artifact.txt", ("safe", "receipt")),
    ],
)
def test_package_validator_rejects_d_test_variants_before_creating_parents(
    tmp_path, package_root, rel_path, output_parts
):
    build_root = tmp_path / "pkg"
    write_artifact(build_root)
    manifest, index = package_index(build_root)
    root = tmp_path / package_root
    if package_root.casefold() != "d_test":
        root = build_root
        index["artifacts"][0]["path"] = rel_path
    output = tmp_path.joinpath(*output_parts)
    result = validate_and_commit_package(
        package_root=root, manifest=manifest, index=index, output_dir=output
    )
    assert not result.success
    assert result.primary_code == FailureCode.D_TEST_FORBIDDEN
    if output_parts[0].casefold() == "d_test":
        assert not output.exists()


# --- phase1 repair regression tests (handoff-authoritative) ---

AUTHORITATIVE_MANIFEST_FIELDS = {
    "schema_version",
    "release_id",
    "main_version",
    "main_sha256",
    "S1_version",
    "S1_sha256",
    "S2_version",
    "S2_sha256",
    "experiment_version",
    "experiment_sha256",
    "ClaimRegister_sha256",
    "SafetyArtifactIR_schema_version",
    "SafetyArtifactIR_schema_sha256",
    "SafetyArtifactIR_sha256",
    "compiler_version",
    "compiler_sha256",
    "failure_code_registry_sha256",
    "RootIdentityManifest_schema_sha256",
    "AcquisitionManifest_schema_sha256",
    "Eventifier_version",
    "Eventifier_sha256",
    "SourceAdapterRegistry_sha256",
    "RootLevelMapperRegistry_sha256",
    "CouplingFamilyRegistry_sha256",
    "SetwiseEligibilityGenerator_version",
    "SetwiseEligibilityGenerator_sha256",
    "OperationalSafetyArtifact_sha256",
    "MethodRegistry_sha256",
    "ArmFrameMatrix_sha256",
    "SeedManifest_sha256",
    "AllocationManifest_sha256",
    "TestManifest_sha256",
    "analysis_container_sha256",
    "dependency_edges",
}

AUTHORITATIVE_ROOT_IDENTITY_FIELDS = {
    "schema_version",
    "credential_subject",
    "acquisition_uuid",
    "root_epoch",
    "root_type",
    "TTL_policy_id",
    "acquisition_manifest_hash",
    "signature",
}

AUTHORITATIVE_ACQUISITION_FIELDS = {
    "schema_version",
    "acquisition_uuid",
    "root_epoch",
    "Eventifier_id",
    "Eventifier_version",
    "Eventifier_sha256",
    "trusted_clock_domain",
    "t_start",
    "t_end",
    "causal_boundary_id",
    "causal_boundary_sha256",
    "raw_acquisition_identity",
    "segmentation_evidence_sha256",
    "signature",
}


def test_authoritative_s2_field_names_are_exact_and_aliases_closed():
    assert (
        set(SCHEMA_DEFINITIONS["NormativeReleaseManifest"])
        == AUTHORITATIVE_MANIFEST_FIELDS
    )
    manifest = manifest_fixture()
    assert set(manifest) == AUTHORITATIVE_MANIFEST_FIELDS
    for bad_alias in [
        "failure_registry_sha256",
        "RootIdentity_schema_sha256",
        "SourceAdapter_registry_sha256",
        "Seed_manifest_sha256",
    ]:
        bad = manifest_fixture()
        bad[bad_alias] = (
            bad.pop(next(iter(AUTHORITATIVE_MANIFEST_FIELDS - {bad_alias})))
            if bad_alias not in bad
            else bad[bad_alias]
        )
        assert not validate_schema("NormativeReleaseManifest", bad).valid


def test_authoritative_root_identity_and_acquisition_minimum_bindings():
    assert set(SCHEMA_DEFINITIONS["RootIdentity"]) == AUTHORITATIVE_ROOT_IDENTITY_FIELDS
    assert set(SCHEMA_DEFINITIONS["Acquisition"]) == AUTHORITATIVE_ACQUISITION_FIELDS
    data = fixtures()
    assert set(data["RootIdentity"]["positive"]) == AUTHORITATIVE_ROOT_IDENTITY_FIELDS
    assert set(data["Acquisition"]["positive"]) == AUTHORITATIVE_ACQUISITION_FIELDS


def test_normative_release_labels_are_exact_not_three_part_semver():
    manifest = manifest_fixture()
    manifest.update(
        {
            "main_version": "v21",
            "S1_version": "v20.1",
            "S2_version": "v20.1",
            "experiment_version": "v6.8",
            "compiler_version": "compiler-freeze-2026-07-16",
            "Eventifier_version": "eventifier-v1",
            "SetwiseEligibilityGenerator_version": "generator-v1",
        }
    )
    assert validate_schema("NormativeReleaseManifest", manifest).valid
    manifest["schema_version"] = "v1"
    assert not validate_schema("NormativeReleaseManifest", manifest).valid


def test_pending_hash_only_in_hash_fields_not_ids_versions_paths_or_edges():
    manifest = manifest_fixture()
    manifest["release_id"] = "PENDING-HASH"
    assert not validate_schema("NormativeReleaseManifest", manifest).valid
    manifest = manifest_fixture()
    manifest["main_version"] = "PENDING-HASH"
    assert not validate_schema("NormativeReleaseManifest", manifest).valid
    manifest = manifest_fixture()
    manifest["dependency_edges"] = [{"from": "PENDING-HASH", "to": "artifact-a"}]
    assert not validate_schema("NormativeReleaseManifest", manifest).valid


def test_closed_index_descriptor_and_manifest_binding_closure(tmp_path):
    manifest = manifest_fixture()
    root = tmp_path / "pkg"
    root.mkdir()
    artifacts = []
    for binding_key, value in manifest.items():
        if binding_key.endswith("_sha256"):
            payload = json.dumps({"binding": binding_key}, sort_keys=True).encode()
            rel = f"artifacts/{binding_key}.json"
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            digest = sha256_hex(payload)
            manifest[binding_key] = digest
            descriptor = {
                "artifact_id": binding_key,
                "binding_key": binding_key,
                "path": rel,
                "sha256": digest,
            }
            companion = binding_key.removesuffix("_sha256") + "_version"
            if companion in manifest:
                descriptor["artifact_version"] = manifest[companion]
            artifacts.append(descriptor)
    manifest["dependency_edges"] = []
    index = {
        "schema_version": "1.0.0",
        "release_id": manifest["release_id"],
        "artifacts": artifacts,
    }
    out = tmp_path / "receipt"
    result = validate_and_commit_package(
        package_root=root, manifest=manifest, index=index, output_dir=out
    )
    assert result.success, result.failures
    assert result.confirmation_eligible

    missing = copy.deepcopy(index)
    missing["artifacts"] = missing["artifacts"][:-1]
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=missing
        ).primary_code
        == FailureCode.PACKAGE_CONSISTENCY_INVALID
    )

    duplicate = copy.deepcopy(index)
    duplicate["artifacts"].append(copy.deepcopy(duplicate["artifacts"][0]))
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=duplicate
        ).primary_code
        == FailureCode.PACKAGE_CONSISTENCY_INVALID
    )

    unknown = copy.deepcopy(index)
    unknown["artifacts"][0]["binding_key"] = "unknown_sha256"
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=unknown
        ).primary_code
        == FailureCode.PACKAGE_CONSISTENCY_INVALID
    )

    mismatch = copy.deepcopy(index)
    mismatch["release_id"] = "other-release"
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=mismatch
        ).primary_code
        == FailureCode.PACKAGE_CONSISTENCY_INVALID
    )

    stale = copy.deepcopy(index)
    for descriptor in stale["artifacts"]:
        if descriptor.get("artifact_version"):
            descriptor["artifact_version"] = "stale"
            break
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=stale
        ).primary_code
        == FailureCode.STALE_VERSION_REFERENCE
    )

    closed = copy.deepcopy(index)
    closed["extra"] = True
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=closed
        ).primary_code
        == FailureCode.MANIFEST_SCHEMA_INVALID
    )


def test_schema_descriptor_content_is_parsed_and_validated(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    schema_doc = fixtures()["RootIdentity"]["positive"]
    p = root / "root.json"
    p.write_text(json.dumps(schema_doc), encoding="utf-8")
    manifest = manifest_fixture()
    manifest["RootIdentityManifest_schema_sha256"] = sha256_hex(p.read_bytes())
    index = {
        "schema_version": "1.0.0",
        "release_id": manifest["release_id"],
        "artifacts": [
            {
                "artifact_id": "root-schema",
                "binding_key": "RootIdentityManifest_schema_sha256",
                "path": "root.json",
                "sha256": manifest["RootIdentityManifest_schema_sha256"],
                "schema_name": "RootIdentity",
                "schema_version": "1.0.0",
            }
        ],
    }
    # Missing the other required manifest bindings must fail closed, not validate a one-file package.
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=index
        ).primary_code
        == FailureCode.PACKAGE_CONSISTENCY_INVALID
    )

    # With all bindings present, invalid schema content is a typed manifest/schema failure.
    artifacts = []
    for binding_key, value in manifest.items():
        if not binding_key.endswith("_sha256"):
            continue
        rel = f"{binding_key}.json"
        content = (
            b"{}"
            if binding_key == "RootIdentityManifest_schema_sha256"
            else binding_key.encode()
        )
        (root / rel).write_bytes(content)
        manifest[binding_key] = sha256_hex(content)
        descriptor = {
            "artifact_id": binding_key,
            "binding_key": binding_key,
            "path": rel,
            "sha256": manifest[binding_key],
        }
        if binding_key == "RootIdentityManifest_schema_sha256":
            descriptor.update(schema_name="RootIdentity", schema_version="1.0.0")
        companion = binding_key.removesuffix("_sha256") + "_version"
        if companion in manifest:
            descriptor["artifact_version"] = manifest[companion]
        artifacts.append(descriptor)
    manifest["dependency_edges"] = []
    full_index = {
        "schema_version": "1.0.0",
        "release_id": manifest["release_id"],
        "artifacts": artifacts,
    }
    assert (
        validate_and_commit_package(
            package_root=root, manifest=manifest, index=full_index
        ).primary_code
        == FailureCode.MANIFEST_SCHEMA_INVALID
    )


def test_path_safety_rejects_absolute_traversal_symlink_escape_and_dtest_before_io(
    tmp_path, monkeypatch
):
    manifest = manifest_fixture()
    root = tmp_path / "pkg"
    root.mkdir()
    unsafe_indices = [
        {
            "schema_version": "1.0.0",
            "release_id": manifest["release_id"],
            "artifacts": [
                {
                    "artifact_id": "x",
                    "binding_key": "main_sha256",
                    "path": "/abs/file",
                    "sha256": "0" * 64,
                }
            ],
        },
        {
            "schema_version": "1.0.0",
            "release_id": manifest["release_id"],
            "artifacts": [
                {
                    "artifact_id": "x",
                    "binding_key": "main_sha256",
                    "path": "C:\\abs\\file",
                    "sha256": "0" * 64,
                }
            ],
        },
        {
            "schema_version": "1.0.0",
            "release_id": manifest["release_id"],
            "artifacts": [
                {
                    "artifact_id": "x",
                    "binding_key": "main_sha256",
                    "path": "..\\escape",
                    "sha256": "0" * 64,
                }
            ],
        },
        {
            "schema_version": "1.0.0",
            "release_id": manifest["release_id"],
            "artifacts": [
                {
                    "artifact_id": "x",
                    "binding_key": "main_sha256",
                    "path": "safe\\D_Test\\file",
                    "sha256": "0" * 64,
                }
            ],
        },
    ]

    def boom(*args, **kwargs):
        raise AssertionError("file hash/read must not be called for unsafe descriptor")

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    for index in unsafe_indices:
        result = validate_and_commit_package(
            package_root=root, manifest=manifest, index=index
        )
        assert not result.success
        assert result.primary_code in {
            FailureCode.D_TEST_FORBIDDEN,
            FailureCode.MANIFEST_SCHEMA_INVALID,
        }


def test_canonical_json_rejects_non_json_sequences_lone_surrogates_and_nested_nonfinite():
    class CustomSeq:
        def __len__(self):
            return 1

        def __getitem__(self, idx):
            if idx == 0:
                return "x"
            raise IndexError

    for bad in [
        (1, 2),
        range(2),
        CustomSeq(),
        b"bytes",
        bytearray(b"x"),
        {"x": [1, float("nan")]},
        {"\ud800": "x"},
        {"x": "\udfff"},
    ]:
        with pytest.raises(CanonicalJsonError):
            canonical_bytes(bad)
    richer = {"\u00e9": 1, "\u4e2d": 2, "a": 3, "\u20ac": 4}
    assert (
        canonical_bytes(richer)
        == b'{"a":3,"\xc3\xa9":1,"\xe2\x82\xac":4,"\xe4\xb8\xad":2}'
    )


def test_malformed_unhashable_dependency_edge_returns_typed_failure(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    manifest["dependency_edges"] = [{"from": ["artifact-a"], "to": "artifact-a"}]
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


def test_actual_concurrent_receipt_target_has_one_success_and_one_already_exists(
    tmp_path,
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "concurrent" / "receipt"

    def run_once():
        return validate_and_commit_package(
            package_root=tmp_path, manifest=manifest, index=index, output_dir=target
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_once(), range(2)))

    assert sorted(result.success for result in results) == [False, True]
    assert [result.primary_code for result in results if not result.success] == [
        FailureCode.OUTPUT_ALREADY_EXISTS
    ]
    assert (target / "validation_receipt.json").is_file()
    assert not list(target.parent.glob("*.staging-*"))


def test_preexisting_empty_receipt_target_is_not_clobbered_and_leaves_no_staging(
    tmp_path,
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "preexisting" / "receipt"
    target.mkdir(parents=True)

    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=target
    )

    assert not result.success
    assert result.primary_code == FailureCode.OUTPUT_ALREADY_EXISTS
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert not list(target.parent.glob("*.staging-*"))


def test_commit_window_empty_target_competitor_is_not_clobbered_under_posix_replace_semantics(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "race" / "receipt"
    original_write = package_validator_module._write_receipt_staging
    original_rename = Path.rename

    def write_then_compete(staging, receipt):
        original_write(staging, receipt)
        target.mkdir()

    def simulate_posix_directory_replace(self, replacement):
        replacement = Path(replacement)
        if (
            self.name.startswith(f".{target.name}.staging-")
            and replacement == target
            and target.is_dir()
        ):
            target.rmdir()
        return original_rename(self, replacement)

    monkeypatch.setattr(
        package_validator_module, "_write_receipt_staging", write_then_compete
    )
    monkeypatch.setattr(Path, "rename", simulate_posix_directory_replace)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=target
    )

    assert not result.success
    assert result.primary_code == FailureCode.OUTPUT_ALREADY_EXISTS
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert not list(target.parent.glob("*.staging-*"))


def test_publish_after_claim_failure_cleans_only_owned_empty_claim_and_staging(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "publish-fail" / "receipt"
    original_replace = Path.replace

    def fail_publish_with_foreign_content(self, replacement):
        replacement = Path(replacement)
        if (
            self.name == "validation_receipt.json"
            and replacement == target / "validation_receipt.json"
        ):
            (target / "foreign.txt").write_text("competitor", encoding="utf-8")
            raise OSError("injected publish failure")
        return original_replace(self, replacement)

    monkeypatch.setattr(Path, "replace", fail_publish_with_foreign_content)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=target
    )

    assert not result.success
    assert result.primary_code == FailureCode.PACKAGE_CONSISTENCY_INVALID
    assert (target / "foreign.txt").read_text(encoding="utf-8") == "competitor"
    assert not (target / "validation_receipt.json").exists()
    assert not list(target.parent.glob("*.staging-*"))


def test_commit_failure_cleanup_resolve_error_returns_original_failure_without_deleting_sentinel(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "unsafe-cleanup" / "parent" / "receipt"
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    original_resolve = Path.resolve
    cleanup_started = {"value": False}

    def fail_after_staging(staging, receipt):
        staging.mkdir()
        (staging / "partial.tmp").write_text("partial", encoding="utf-8")
        cleanup_started["value"] = True
        raise OSError("injected write failure before commit")

    def resolve_spy(self, *args, **kwargs):
        if cleanup_started["value"] and self == tmp_path:
            raise RuntimeError("injected cleanup boundary resolution failure")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(
        package_validator_module, "_write_receipt_staging", fail_after_staging
    )
    monkeypatch.setattr(Path, "resolve", resolve_spy)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=target
    )

    assert not result.success
    assert result.primary_code == FailureCode.PACKAGE_CONSISTENCY_INVALID
    assert not (target / "validation_receipt.json").exists()
    assert sentinel.is_dir()
    assert (tmp_path / "unsafe-cleanup").is_dir()


def test_post_publish_staging_rmdir_failure_still_returns_success_and_cleans_staging(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "post-publish-cleanup" / "receipt"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    original_rmdir = Path.rmdir

    def rmdir_spy(self, *args, **kwargs):
        if self.name.startswith(f".{target.name}.staging-"):
            raise OSError("injected staging cleanup failure after publish")
        return original_rmdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "rmdir", rmdir_spy)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=target
    )

    assert result.success
    assert result.receipt_path == str(target / "validation_receipt.json")
    receipt = (target / "validation_receipt.json").read_bytes()
    assert b"formal_experiment_artifact" in receipt
    assert not receipt.endswith(b"\n")
    assert not list(target.parent.glob("*.staging-*"))
    assert unrelated.is_dir()


def test_injected_receipt_write_failure_cleans_new_parent_and_staging(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    target = tmp_path / "new" / "parent" / "receipt"

    def fail_after_staging(staging, receipt):
        staging.mkdir()
        (staging / "partial.tmp").write_text("partial", encoding="utf-8")
        raise OSError("injected write failure")

    monkeypatch.setattr(
        package_validator_module, "_write_receipt_staging", fail_after_staging
    )
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=target
    )
    assert not result.success
    assert result.primary_code == FailureCode.PACKAGE_CONSISTENCY_INVALID
    assert not (tmp_path / "new").exists()
    assert not list(tmp_path.rglob("*.staging-*"))


def test_symlink_escape_rejected_before_hashing(tmp_path, monkeypatch):
    root = tmp_path / "pkg"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = root / "link.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable on this Windows surface: {exc}")

    manifest, index = package_index(root)
    index["artifacts"][0]["path"] = "link.txt"

    def boom(*args, **kwargs):
        raise AssertionError("escaped symlink must be rejected before hashing")

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=root, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


# --- stage1 hardening adversarial audit regressions ---


def test_non_dict_manifest_or_index_returns_typed_failure_without_output(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    bad_manifest = validate_and_commit_package(
        package_root=tmp_path, manifest=[], index=index, output_dir=out1
    )  # type: ignore[arg-type]
    bad_index = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=[], output_dir=out2
    )  # type: ignore[arg-type]
    assert not bad_manifest.success
    assert bad_manifest.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID
    assert not out1.exists()
    assert not bad_index.success
    assert bad_index.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID
    assert not out2.exists()


def test_package_preflight_blocks_artifact_io_for_manifest_index_conflict(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][0]["sha256"] = "f" * 64

    def boom(*args, **kwargs):
        raise AssertionError(
            "artifact filesystem I/O must not run after preflight conflict"
        )

    monkeypatch.setattr(Path, "is_file", boom)
    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.PACKAGE_CONSISTENCY_INVALID
    assert {failure.code for failure in result.failures} == {
        FailureCode.PACKAGE_CONSISTENCY_INVALID
    }


def test_package_preflight_blocks_whole_package_io_for_unsafe_traversal(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][-1]["path"] = "..\\escape.bin"

    def boom(*args, **kwargs):
        raise AssertionError("no artifact is_file/open/hash after any unsafe path")

    monkeypatch.setattr(Path, "is_file", boom)
    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


@pytest.mark.parametrize(
    "rel_path",
    [
        "D_test/file.bin",
        "safe\\D_TEST\\file.bin",
        "C:\\safe\\D_test\\file.bin",
        "\\\\server\\share\\D_test\\file.bin",
        "/var/tmp/D_Test/file.bin",
    ],
)
def test_dtest_precedence_across_mixed_absolute_descriptor_paths(
    tmp_path, rel_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][0]["path"] = rel_path

    def boom(*args, **kwargs):
        raise AssertionError(
            "D_test descriptor rejection must happen before artifact I/O"
        )

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.D_TEST_FORBIDDEN


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest, index: index.update(schema_version="PENDING-HASH"),
        lambda manifest, index: index.update(release_id="PENDING_HASH"),
        lambda manifest, index: index["artifacts"][0].update(
            artifact_id="PENDING-HASH"
        ),
        lambda manifest, index: index["artifacts"][0].update(
            binding_key="PENDING-HASH"
        ),
        lambda manifest, index: index["artifacts"][0].update(path="PENDING-HASH"),
        lambda manifest, index: index["artifacts"][0].update(
            artifact_version="PENDING-HASH"
        ),
        lambda manifest, index: index["artifacts"][0].update(
            schema_name="PENDING-HASH", schema_version="1.0.0"
        ),
        lambda manifest, index: index["artifacts"][0].update(
            schema_name="RootIdentity", schema_version="PENDING-HASH"
        ),
        lambda manifest, index: manifest.update(
            dependency_edges=[{"from": "PENDING-HASH", "to": "artifact-a"}]
        ),
    ],
)
def test_pending_markers_rejected_in_all_non_hash_index_descriptor_and_edge_strings(
    tmp_path, mutate, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    mutate(manifest, index)

    def boom(*args, **kwargs):
        raise AssertionError("invalid string marker must fail before artifact I/O")

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


@pytest.mark.parametrize("bad_hash", ["A" * 64, "PENDING_HASH", "short"])
def test_descriptor_sha256_is_lowercase_hex_or_exact_pending_only(
    tmp_path, bad_hash, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][0]["sha256"] = bad_hash

    def boom(*args, **kwargs):
        raise AssertionError(
            "malformed descriptor sha256 must fail before artifact I/O"
        )

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


def test_lone_surrogate_rejected_in_schema_and_index_before_artifact_io(
    tmp_path, monkeypatch
):
    schema_obj = fixtures()["RootIdentity"]["positive"]
    schema_obj["credential_subject"] = "\ud800"
    assert not validate_schema("RootIdentity", schema_obj).valid

    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][0]["artifact_id"] = "\udfff"

    def boom(*args, **kwargs):
        raise AssertionError("lone surrogate must fail before artifact I/O")

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


def test_dag_endpoints_are_release_plus_artifact_ids_not_binding_aliases(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    manifest["dependency_edges"] = [
        {"from": manifest["release_id"], "to": "main_sha256"}
    ]
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MISSING_DEPENDENCY_ENDPOINT


def test_artifact_id_release_id_collision_is_rejected(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["artifacts"][0]["artifact_id"] = manifest["release_id"]
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.PACKAGE_CONSISTENCY_INVALID


def test_schema_content_version_must_equal_descriptor_version(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    content = fixtures()["RootIdentity"]["positive"]
    content["schema_version"] = "0.9.0"
    install_schema_content(
        tmp_path, manifest, index, "RootIdentity", content, descriptor_version="1.0.0"
    )
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID


def test_schema_content_pending_paths_block_confirmation(tmp_path):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    content = fixtures()["RootIdentity"]["positive"]
    content["acquisition_manifest_hash"] = "PENDING-HASH"
    install_schema_content(tmp_path, manifest, index, "RootIdentity", content)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, mode="confirmation"
    )
    assert not result.success
    assert result.primary_code == FailureCode.CONFIRMATION_PENDING_HASH
    assert any(
        "acquisition_manifest_hash" in failure.path for failure in result.failures
    )


def test_failure_code_registry_primary_order_is_explicit_and_stable():
    assert PRIMARY_ORDER == (
        FailureCode.D_TEST_FORBIDDEN,
        FailureCode.OUTPUT_ALREADY_EXISTS,
        FailureCode.MANIFEST_SCHEMA_INVALID,
        FailureCode.FILE_MISSING,
        FailureCode.HASH_MISMATCH,
        FailureCode.SCHEMA_INCOMPATIBLE,
        FailureCode.STALE_VERSION_REFERENCE,
        FailureCode.MISSING_DEPENDENCY_ENDPOINT,
        FailureCode.DEPENDENCY_CYCLE,
        FailureCode.CONFIRMATION_PENDING_HASH,
        FailureCode.PACKAGE_CONSISTENCY_INVALID,
    )


# --- stage1 D_test root/output follow-up regressions ---


def test_raw_mixed_separator_package_root_is_checked_by_public_validator(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    original = package_validator_module._contains_dtest_text
    observed: list[str] = []

    def spy(path_text):
        observed.append(str(path_text))
        return original(path_text)

    monkeypatch.setattr(package_validator_module, "_contains_dtest_text", spy)
    mixed_root = Path(str(tmp_path / "safe") + "\\D_test\\pkg")
    result = validate_and_commit_package(
        package_root=mixed_root, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.D_TEST_FORBIDDEN
    assert any(
        "safe" in item and "D_test" in item and "pkg" in item for item in observed
    )


def test_resolved_package_root_dtest_symlink_rejected_before_artifact_io(
    tmp_path, monkeypatch
):
    real_root = tmp_path / "D_test" / "pkg"
    real_root.mkdir(parents=True)
    write_artifact(real_root)
    manifest, index = package_index(real_root)
    link_root = tmp_path / "safe_root_link"
    try:
        os.symlink(real_root, link_root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable on this Windows surface: {exc}")

    def boom(*args, **kwargs):
        raise AssertionError(
            "resolved package-root D_test must be rejected before artifact I/O"
        )

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=link_root, manifest=manifest, index=index
    )
    assert not result.success
    assert result.primary_code == FailureCode.D_TEST_FORBIDDEN


def test_resolved_output_parent_dtest_symlink_rejected_before_artifact_io(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    real_output_parent = tmp_path / "D_test" / "out"
    real_output_parent.mkdir(parents=True)
    link_output_parent = tmp_path / "safe_output_link"
    try:
        os.symlink(real_output_parent, link_output_parent, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable on this Windows surface: {exc}")

    def boom(*args, **kwargs):
        raise AssertionError(
            "resolved output D_test must be rejected before artifact I/O"
        )

    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path,
        manifest=manifest,
        index=index,
        output_dir=link_output_parent / "receipt",
    )
    assert not result.success
    assert result.primary_code == FailureCode.D_TEST_FORBIDDEN
    assert not (real_output_parent / "receipt").exists()


def test_missing_index_required_diagnostics_are_deterministic_tuple_order(tmp_path):
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest_fixture(), index={}
    )
    paths = [
        failure.path
        for failure in result.failures
        if failure.message == "missing index field"
    ]
    assert paths == ["index.schema_version", "index.release_id", "index.artifacts"]


def test_lone_surrogate_unknown_index_key_reports_typed_failure_without_artifact_io(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["\ud800"] = 1
    output = tmp_path / "surrogate-out" / "receipt"

    def boom(*args, **kwargs):
        raise AssertionError("lone-surrogate unknown key must fail before artifact I/O")

    monkeypatch.setattr(Path, "is_file", boom)
    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=output
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID
    assert any(failure.path == "index.\\ud800" for failure in result.failures)
    assert not output.exists()


def test_cyclic_unknown_index_field_reports_typed_failure_without_artifact_io(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    index["loop"] = index
    output = tmp_path / "cyclic-out" / "receipt"

    def boom(*args, **kwargs):
        raise AssertionError("cyclic non-canonical index must fail before artifact I/O")

    monkeypatch.setattr(Path, "is_file", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=output
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID
    assert any(failure.path == "canonical_json" for failure in result.failures)
    assert not output.exists()


def test_package_root_resolve_runtimeerror_reports_typed_failure_without_artifact_io(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    output = tmp_path / "root-resolve-out" / "receipt"
    original_resolve = Path.resolve

    def resolve_spy(self, *args, **kwargs):
        if self == tmp_path:
            raise RuntimeError("simulated package-root symlink loop")
        return original_resolve(self, *args, **kwargs)

    def boom(*args, **kwargs):
        raise AssertionError(
            "package-root resolve failure must stop before artifact I/O"
        )

    monkeypatch.setattr(Path, "resolve", resolve_spy)
    monkeypatch.setattr(Path, "is_file", boom)
    monkeypatch.setattr(Path, "open", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=output
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID
    assert any(
        "cannot resolve package root" in failure.message for failure in result.failures
    )
    assert not output.exists()


def test_descriptor_candidate_resolve_runtimeerror_reports_typed_failure_without_artifact_io(
    tmp_path, monkeypatch
):
    write_artifact(tmp_path)
    manifest, index = package_index(tmp_path)
    output = tmp_path / "candidate-resolve-out" / "receipt"
    original_resolve = Path.resolve
    artifact_path = tmp_path / index["artifacts"][0]["path"]

    def resolve_spy(self, *args, **kwargs):
        if self == artifact_path:
            raise RuntimeError("simulated descriptor symlink loop")
        return original_resolve(self, *args, **kwargs)

    def boom(*args, **kwargs):
        raise AssertionError("descriptor resolve failure must stop before artifact I/O")

    monkeypatch.setattr(Path, "resolve", resolve_spy)
    monkeypatch.setattr(Path, "is_file", boom)
    monkeypatch.setattr(Path, "open", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    monkeypatch.setattr(package_validator_module, "_hash_file", boom)
    result = validate_and_commit_package(
        package_root=tmp_path, manifest=manifest, index=index, output_dir=output
    )
    assert not result.success
    assert result.primary_code == FailureCode.MANIFEST_SCHEMA_INVALID
    assert any("cannot resolve path" in failure.message for failure in result.failures)
    assert not output.exists()
