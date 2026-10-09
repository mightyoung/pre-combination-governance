"""Strict, credential-free Archive A/B target configuration."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TARGET_FIELDS = frozenset(
    {
        "name",
        "root",
        "failure_domain",
        "off_host",
        "off_volume",
        "immutable",
        "append_only",
        "live_evidence",
    }
)
_CREDENTIAL_KEY = re.compile(
    r"credential|password|passwd|secret|token|private[_-]?key|"
    r"access[_-]?key|api[_-]?key|authorization|bearer",
    re.IGNORECASE,
)
_CREDENTIAL_VALUE = re.compile(
    r"(?:credential|password|passwd|secret|token|private[_-]?key|"
    r"access[_-]?key|api[_-]?key|authorization)\s*[:=]|"
    r"\bbearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE,
)


def _credential_errors(
    value: Any,
    path: str = "$",
    *,
    scan_values: bool = False,
) -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _CREDENTIAL_KEY.search(key_text):
                errors.append(
                    f"{path}.{key_text}: embedded credential field is forbidden"
                )
            errors.extend(
                _credential_errors(
                    child,
                    f"{path}.{key_text}",
                    scan_values=scan_values or key_text == "live_evidence",
                )
            )
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            errors.extend(
                _credential_errors(
                    child,
                    f"{path}[{index}]",
                    scan_values=scan_values,
                )
            )
    elif isinstance(value, str) and (
        _CREDENTIAL_VALUE.search(value)
        or (scan_values and _CREDENTIAL_KEY.search(value))
    ):
        errors.append(f"{path}: embedded credential value is forbidden")
    return errors


@dataclass(frozen=True)
class ArchiveTarget:
    name: str
    root: str
    failure_domain: str
    off_host: bool = False
    off_volume: bool = False
    immutable: bool = False
    append_only: bool = False
    live_evidence: Mapping[str, Any] | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.name, str) or not self.name:
            errors.append("name is required")
        if not isinstance(self.root, str) or not self.root:
            errors.append("root is required")
        elif not Path(self.root).is_absolute():
            errors.append("root must be absolute")
        else:
            if ".." in Path(self.root).parts:
                errors.append("root must not contain parent-directory aliases")
            errors.extend(
                f"root contains symbolic-link component: {component}"
                for component in _symlink_components(Path(self.root))
            )
        if not isinstance(self.failure_domain, str) or not self.failure_domain:
            errors.append("failure_domain is required")
        for field in ("off_host", "off_volume", "immutable", "append_only"):
            if not isinstance(getattr(self, field), bool):
                errors.append(f"{field} must be boolean")
        if not (self.immutable or self.append_only):
            errors.append("target must be immutable or append-only")
        if self.live_evidence is not None:
            if not isinstance(self.live_evidence, Mapping):
                errors.append("live_evidence must be an object")
            else:
                errors.extend(
                    _credential_errors(
                        self.live_evidence,
                        scan_values=True,
                    )
                )
        return errors


def _canonical_root(value: str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _symlink_components(path: Path) -> list[str]:
    found: list[str] = []
    current = Path(path.anchor) if path.anchor else Path()
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        current /= part
        if current.is_symlink():
            found.append(str(current))
    return found


def _from_mapping(value: Mapping[str, Any]) -> ArchiveTarget:
    credential_errors = _credential_errors(value)
    if credential_errors:
        raise ValueError("; ".join(credential_errors))
    unknown = set(value) - _TARGET_FIELDS
    if unknown:
        names = ", ".join(sorted(map(str, unknown)))
        raise ValueError(f"unknown archive target fields: {names}")
    return ArchiveTarget(**dict(value))


def validate_archive_targets(targets: Iterable[ArchiveTarget]) -> list[str]:
    selected = list(targets)
    if len(selected) != 2:
        return ["Archive A/B requires exactly two targets"]
    if not all(isinstance(target, ArchiveTarget) for target in selected):
        return ["each archive target must be an ArchiveTarget"]
    errors: list[str] = []
    if {target.name for target in selected} != {"A", "B"}:
        errors.append("target names must be exactly A and B")
    for target in selected:
        errors.extend(f"{target.name}: {error}" for error in target.validate())
    roots: dict[str, Path] = {}
    for target in selected:
        if isinstance(target.root, str) and Path(target.root).is_absolute():
            roots[target.name] = _canonical_root(target.root)
            for component in _symlink_components(Path(target.root)):
                errors.append(
                    f"{target.name}: symlink path component is forbidden: {component}"
                )
    if set(roots) == {"A", "B"}:
        a, b = roots["A"], roots["B"]
        if a == b:
            errors.append("A and B archive roots must be distinct")
        elif a in b.parents or b in a.parents:
            errors.append("A and B archive roots must not be nested")
    domains = {
        target.failure_domain.strip().casefold()
        for target in selected
        if isinstance(target.failure_domain, str)
    }
    if len(domains) != 2:
        errors.append("A and B must use independent failure domains")
    target_b = next((target for target in selected if target.name == "B"), None)
    if target_b is not None and not (target_b.off_host or target_b.off_volume):
        errors.append("B must be off-host or off-volume")
    return errors


def load_archive_targets(config: str | Path | Mapping[str, Any]) -> list[ArchiveTarget]:
    data = (
        json.loads(Path(config).read_text(encoding="utf-8"))
        if isinstance(config, str | Path)
        else config
    )
    if not isinstance(data, Mapping):
        raise ValueError("archive config must be an object")
    if set(data) != {"targets"}:
        raise ValueError("archive config must contain only targets")
    raw_targets = data["targets"]
    if not isinstance(raw_targets, list) or len(raw_targets) != 2:
        raise ValueError("archive config must contain exactly two targets")
    if not all(isinstance(item, Mapping) for item in raw_targets):
        raise ValueError("each archive target must be an object")
    targets = [_from_mapping(item) for item in raw_targets]
    errors = validate_archive_targets(targets)
    if errors:
        raise ValueError("invalid archive targets: " + "; ".join(errors))
    return targets


__all__ = ["ArchiveTarget", "load_archive_targets", "validate_archive_targets"]
