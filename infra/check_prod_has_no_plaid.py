"""CI guard (ADR-014): the prod stack must synthesize with no Plaid resources at all.

Plaid is Sandbox-only and dev-only until a follow-up ADR says otherwise. This reads the
synthesized templates in ``cdk.out`` (run ``cdk synth --all`` first) and fails if anything
Plaid-related appears in prod - a Lambda, a route, a secret, an IAM statement, an environment
variable. It also fails if dev has *none*, so the check cannot pass by matching nothing.

    python check_prod_has_no_plaid.py [cdk.out]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def plaid_hits(template_path: Path) -> list[str]:
    """Logical IDs of resources whose ID or definition mentions Plaid, case-insensitively."""
    resources = json.loads(template_path.read_text())["Resources"]
    return sorted(
        logical_id for logical_id, body in resources.items()
        if "plaid" in logical_id.lower() or "plaid" in json.dumps(body).lower()
    )


def main(out_dir: str = "cdk.out") -> int:
    out = Path(out_dir)
    prod = plaid_hits(out / "Ledgerly-prod.template.json")
    dev = plaid_hits(out / "Ledgerly-dev.template.json")
    if prod:
        print(f"FAIL: Ledgerly-prod has {len(prod)} Plaid-related resource(s):")
        for logical_id in prod:
            print(f"  - {logical_id}")
        return 1
    if not dev:
        print("FAIL: Ledgerly-dev has no Plaid resources, so this check proves nothing.")
        return 1
    print(f"OK: Ledgerly-prod has no Plaid resources (Ledgerly-dev has {len(dev)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
