"""Credential-free PMSS transport doctor; no platform actions or credentials."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from powerbid.pmss_connectivity_diagnostics import DEFAULT_PROXY, diagnose  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Credential-free PMSS VPN path diagnosis")
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--timeout", type=int, default=7)
    args = parser.parse_args()
    try:
        data = diagnose(args.target_url, proxy_url=args.proxy, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0 if data["state"] == "PRIVATE_ENDPOINT_REACHABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
