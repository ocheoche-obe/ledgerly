"""Tests for the two prod guards this repo leans on (ADR-016): the per-stage Plaid check and
the SPA's Content-Security-Policy. The check tests read the real synthesized templates, so run
``cdk synth --all`` first (CI does), then tamper with copies and assert each tamper is caught.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import sys
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INFRA))

import check_plaid_environments as guard

from ledgerly.config import STAGES
from ledgerly.constructs.web import content_security_policy

CDK_OUT = INFRA / "cdk.out"


def _template(stack: str) -> dict:
    path = CDK_OUT / f"{stack}.template.json"
    if not path.exists():
        pytest.skip("run `cdk synth --all` first")
    return json.loads(path.read_text())


@pytest.fixture
def dev() -> dict:
    return _template("Ledgerly-dev")


@pytest.fixture
def prod() -> dict:
    return _template("Ledgerly-prod")


def _plaid_fns(template: dict) -> list[dict]:
    return [env for env in guard._lambda_envs(template["Resources"]).values()
            if "PLAID_ENV" in env]


def test_the_synthesized_stages_pass(dev, prod):
    assert guard.problems(dev, "dev", "sandbox") == []
    assert guard.problems(prod, "prod", "production") == []


def test_prod_pointed_at_sandbox_is_caught(prod):
    bad = copy.deepcopy(prod)
    _plaid_fns(bad)[0]["PLAID_ENV"] = "sandbox"
    assert any("PLAID_ENV='sandbox'" in p for p in guard.problems(bad, "prod", "production"))


def test_a_template_with_no_plaid_env_cannot_pass_vacuously(prod):
    bad = copy.deepcopy(prod)
    for env in _plaid_fns(bad):
        del env["PLAID_ENV"]
    assert any("proves nothing" in p for p in guard.problems(bad, "prod", "production"))


def test_the_other_stages_secret_is_caught(prod):
    bad = copy.deepcopy(prod)
    _plaid_fns(bad)[0]["PLAID_KEYS_SECRET_ID"] = "ledgerly/dev/plaid/api-keys"
    found = guard.problems(bad, "prod", "production")
    assert any("PLAID_KEYS_SECRET_ID is outside ledgerly/prod/plaid/" in p for p in found)
    assert any("ledgerly/dev/plaid/" in p for p in found)


def test_the_other_stages_host_is_caught(dev):
    bad = copy.deepcopy(dev)
    _plaid_fns(bad)[0]["EXTRA"] = "https://production.plaid.com"
    assert any("production Plaid host" in p for p in guard.problems(bad, "dev", "sandbox"))


def test_the_sandbox_user_belongs_to_dev_only(dev, prod):
    user = {lid: body for lid, body in dev["Resources"].items() if "PlaidSandboxUser" in lid}
    assert user, "dev should synthesize the Sandbox user"
    bad_prod = copy.deepcopy(prod)
    bad_prod["Resources"].update(copy.deepcopy(user))
    assert "has the Plaid Sandbox test user" in guard.problems(bad_prod, "prod", "production")
    bad_dev = copy.deepcopy(dev)
    for lid in user:
        del bad_dev["Resources"][lid]
    assert "is missing the Plaid Sandbox test user" in guard.problems(bad_dev, "dev", "sandbox")


def test_a_redirect_to_anywhere_but_the_site_is_caught(prod):
    bad = copy.deepcopy(prod)
    redirects = [env for env in _plaid_fns(bad) if "PLAID_REDIRECT_URI" in env]
    assert redirects, "prod should send Plaid its OAuth redirect"
    redirects[0]["PLAID_REDIRECT_URI"] = "https://example.com/oauth/plaid"
    assert any("PLAID_REDIRECT_URI" in p for p in guard.problems(bad, "prod", "production"))


def _directives(policy: str) -> dict[str, list[str]]:
    return {d.split()[0]: d.split()[1:] for d in policy.split("; ")}


def test_each_stage_csp_names_only_its_own_plaid_host():
    dev = _directives(content_security_policy(STAGES["dev"]))
    prod = _directives(content_security_policy(STAGES["prod"]))
    assert "https://sandbox.plaid.com/" in dev["connect-src"]
    assert "https://production.plaid.com/" in prod["connect-src"]
    assert not any("production.plaid.com" in v for v in dev["connect-src"])
    assert not any("sandbox.plaid.com" in v for v in prod["connect-src"])
    assert prod["frame-src"] == ["https://cdn.plaid.com/"]
    assert prod["frame-ancestors"] == ["'none'"] and prod["object-src"] == ["'none'"]


def test_a_stage_without_plaid_gets_the_strict_csp():
    stage = dataclasses.replace(STAGES["prod"], plaid_env=None, plaid_oauth_redirect=False)
    policy = content_security_policy(stage)
    assert "plaid" not in policy
    assert "'unsafe-inline'" not in _directives(policy)["script-src"]
    assert _directives(policy)["frame-src"] == ["'none'"]
