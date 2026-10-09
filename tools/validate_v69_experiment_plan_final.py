from __future__ import annotations

import json as std_json

import numpy as np

import validate_v69_experiment_plan as validator


_original_dumps = std_json.dumps


def _safe_dumps(obj: object, *args: object, **kwargs: object) -> str:
    kwargs.setdefault(
        "default",
        lambda value: bool(value) if isinstance(value, np.bool_) else float(value),
    )
    return _original_dumps(obj, *args, **kwargs)


validator.json.dumps = _safe_dumps


if __name__ == "__main__":
    validator.main()
