"""CI guard (ADR-014, ADR-016): each stage talks to exactly one Plaid environment.

dev may reach only Plaid Sandbox (fake banks) and prod only Plaid Production (real banks). This
reads the synthesized templates in ``cdk.out`` (run ``cdk synth --all`` first) and fails if:

- any Lambda's ``PLAID_ENV`` in a stage is not that stage's environment, or none is set at all
  (so the check cannot pass by matching nothing);
- a stage's Plaid secrets live outside its own ``ledgerly/<stage>/plaid/`` namespace, or a
  stage's template names the other stage's Plaid secret or Plaid host;
- prod has the Sandbox test user, or dev lacks it;
- the OAuth redirect is not exactly ``<SiteUrl>/oauth/plaid`` where it is set.

    python check_plaid_environments.py [cdk.out]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED = {"Ledgerly-dev": ("dev", "sandbox"), "Ledgerly-prod": ("prod", "production")}
HOSTS = {"sandbox": "sandbox.plaid.com", "production": "production.plaid.com"}


def _lambda_envs(resources: dict) -> dict[str, dict]:
    return {
        logical_id: body.get("Properties", {}).get("Environment", {}).get("Variables", {})
        for logical_id, body in resources.items()
        if body.get("Type") == "AWS::Lambda::Function"
    }


def problems(template: dict, stage: str, plaid_env: str) -> list[str]:
    found: list[str] = []
    resources = template["Resources"]
    text = json.dumps(template)
    other_stage = "prod" if stage == "dev" else "dev"
    other_env = "production" if plaid_env == "sandbox" else "sandbox"

    envs = _lambda_envs(resources)
    plaid_fns = {lid: env for lid, env in envs.items() if "PLAID_ENV" in env}
    if not plaid_fns:
        found.append("no Lambda sets PLAID_ENV, so this check proves nothing")
    for lid, env in sorted(plaid_fns.items()):
        if env["PLAID_ENV"] != plaid_env:
            found.append(f"{lid}: PLAID_ENV={env['PLAID_ENV']!r}, expected {plaid_env!r}")
        for key in ("PLAID_KEYS_SECRET_ID", "PLAID_TOKENS_SECRET_ID"):
            if _secret_name(env.get(key), resources) is None or not _secret_name(
                    env.get(key), resources).startswith(f"ledgerly/{stage}/plaid/"):
                found.append(f"{lid}: {key} is outside ledgerly/{stage}/plaid/")
        redirect = env.get("PLAID_REDIRECT_URI")
        if redirect is not None and not _is_site_redirect(redirect):
            found.append(f"{lid}: PLAID_REDIRECT_URI is not <SiteUrl>/oauth/plaid")

    if f"ledgerly/{other_stage}/plaid/" in text:
        found.append(f"names a ledgerly/{other_stage}/plaid/ secret")
    if HOSTS[other_env] in text:
        found.append(f"names the {other_env} Plaid host")

    has_sandbox_user = any(
        "PlaidSandboxUser" in lid and body.get("Type") == "AWS::Cognito::UserPoolUser"
        for lid, body in resources.items()
    )
    if plaid_env == "production" and has_sandbox_user:
        found.append("has the Plaid Sandbox test user")
    if plaid_env == "sandbox" and not has_sandbox_user:
        found.append("is missing the Plaid Sandbox test user")
    return found


def _secret_name(value, resources: dict) -> str | None:
    """A secret name as written, or the ``Name`` of the stack secret the value refers to
    (CDK writes a created secret's name as an expression over its ``Ref``)."""
    if isinstance(value, str):
        return value
    refs = {lid for lid in resources if f'{{"Ref": "{lid}"}}' in json.dumps(value)}
    names = {resources[lid].get("Properties", {}).get("Name") for lid in refs
             if resources[lid].get("Type") == "AWS::SecretsManager::Secret"}
    return names.pop() if len(refs) == 1 and len(names) == 1 else None


def _is_site_redirect(value) -> bool:
    """``{"Fn::Join": ["", ["https://", {"Fn::GetAtt": [<Distribution>, "DomainName"]},
    "/oauth/plaid"]]}`` - the distribution's own domain plus the fixed path, nothing else."""
    try:
        sep, parts = value["Fn::Join"]
        return (sep == "" and len(parts) == 3 and parts[0] == "https://"
                and parts[1]["Fn::GetAtt"][1] == "DomainName"
                and "Distribution" in parts[1]["Fn::GetAtt"][0]
                and parts[2] == "/oauth/plaid")
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def main(out_dir: str = "cdk.out") -> int:
    out = Path(out_dir)
    failed = False
    for stack, (stage, plaid_env) in EXPECTED.items():
        template = json.loads((out / f"{stack}.template.json").read_text())
        found = problems(template, stage, plaid_env)
        if found:
            failed = True
            print(f"FAIL: {stack} (expected Plaid {plaid_env}):")
            for problem in found:
                print(f"  - {problem}")
        else:
            print(f"OK: {stack} talks to Plaid {plaid_env} only.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
