"""Minimal backend smoke check runner (no pytest required).

Usage:
    python backend/scripts/smoke_check.py
    python backend/scripts/smoke_check.py --base-url http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def get_json(url: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        body = resp.read().decode("utf-8")
    return status, json.loads(body)


def check_endpoint(base_url: str, path: str, expected_status: int, expected_key: str, timeout: float) -> bool:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        status, data = get_json(url, timeout)
    except urllib.error.URLError as err:
        print(f"[FAIL] {path}: request error -> {err}")
        return False
    except json.JSONDecodeError as err:
        print(f"[FAIL] {path}: invalid JSON -> {err}")
        return False

    if status != expected_status:
        print(f"[FAIL] {path}: status {status}, expected {expected_status}")
        return False
    if expected_key not in data:
        print(f"[FAIL] {path}: missing key '{expected_key}' in {data}")
        return False

    print(f"[ OK ] {path}: status={status}, {expected_key}={data[expected_key]!r}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simple backend smoke checks without pytest")
    parser.add_argument("--base-url", default="http://localhost:8080", help="Backend base URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout (seconds)")
    args = parser.parse_args()

    checks = [
        ("/health", 200, "status"),
        ("/ready", 200, "status"),
    ]

    results = [
        check_endpoint(args.base_url, path, status, key, args.timeout)
        for path, status, key in checks
    ]

    if all(results):
        print("\nSmoke checks passed.")
        return 0

    print("\nSmoke checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
