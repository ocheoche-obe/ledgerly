#!/usr/bin/env bash
# Ledgerly AWS account guard (fires as a SessionStart hook, scoped to THIS repo).
#
# This repo shares one AWS SSO login with another project (CareerVault) that lives in a
# DIFFERENT account under the same Organization. This guard asserts the shell is pointed at
# THIS project's account so work here can never silently hit the other one.
#
# Non-blocking by design: it ALWAYS exits 0. It informs; it does not gate. The hard gate is
# the deploy-time account pin in infra/app.py (ADR-010) and the /start-slice assertion.

set -uo pipefail

PROFILE="ledgerly-dev"
EXPECTED="816020558700"
REGION="us-east-1"

account="$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text 2>/dev/null)"

if [ -z "$account" ] || [ "$account" = "None" ]; then
  echo "⚠ AWS ($PROFILE): not authenticated — run: aws sso login --profile $PROFILE"
elif [ "$account" = "$EXPECTED" ]; then
  echo "✓ OK — AWS profile $PROFILE → account $EXPECTED ($REGION)"
else
  echo "✗ MISMATCH — profile $PROFILE resolves to $account, expected $EXPECTED; do NOT run aws/sam here"
fi

exit 0
