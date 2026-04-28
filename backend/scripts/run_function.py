"""Run a target Python function directly from CLI (no pytest required).

Examples:
    python backend/scripts/run_function.py app.shared.api.health.health
    python backend/scripts/run_function.py app.shared.api.health.health --expect '{"status":"ok","service":"knowledgedeck_backend"}'
    python backend/scripts/run_function.py math.pow --args '[2, 5]' --expect 32
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def parse_json_field(raw: str, fallback: Any) -> Any:
    if raw == "":
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON: {err}") from err


def import_callable(path: str):
    if "." not in path:
        raise ValueError("Use full import path, e.g. app.shared.api.health.health")

    module_name, attr_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    target = getattr(module, attr_name, None)
    if target is None or not callable(target):
        raise ValueError(f"Target '{path}' is not callable")
    return target


def normalize_for_print(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return repr(value)


def run_target(fn, args: list[Any], kwargs: dict[str, Any]) -> Any:
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Python function and optionally assert result")
    parser.add_argument("target", help="Callable import path, e.g. app.shared.api.health.health")
    parser.add_argument("--args", default="[]", help="JSON list for positional args")
    parser.add_argument("--kwargs", default="{}", help="JSON object for keyword args")
    parser.add_argument("--expect", default="", help="Expected JSON result (optional)")
    args = parser.parse_args()

    try:
        fn = import_callable(args.target)
        fn_args = parse_json_field(args.args, [])
        fn_kwargs = parse_json_field(args.kwargs, {})
        if not isinstance(fn_args, list):
            raise ValueError("--args must be a JSON list")
        if not isinstance(fn_kwargs, dict):
            raise ValueError("--kwargs must be a JSON object")

        result = run_target(fn, fn_args, fn_kwargs)
        print(normalize_for_print(result))

        if args.expect != "":
            expected = parse_json_field(args.expect, None)
            if result != expected:
                print("\n[FAIL] Result does not match expected value.")
                print(f"expected: {normalize_for_print(expected)}")
                return 1
            print("\n[ OK ] Result matches expected value.")

        return 0
    except Exception as err:  # CLI utility; surface friendly message.
        print(f"[ERROR] {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
