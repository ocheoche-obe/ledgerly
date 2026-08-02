"""Packaging rules for the backend Lambda asset — one source of truth for all functions.

Every Lambda in this app ships the same thing: the whole `backend/` tree minus the parts
that are not runtime code. That list used to be copy-pasted into three constructs, which is
how it drifted out of date.

**What goes wrong when this list is incomplete.** CDK's `Code.from_asset` matches only the
`exclude` globs — it does *not* read `.gitignore`. So a developer directory that git happily
ignores (`.venv/`, `.pytest_cache/`) is still staged into the asset. CI never noticed because
a fresh runner has neither, but on a workstation that had run `pytest` the staged asset grew
to ~154 MB against a real payload of ~320 KB. Two consequences, the second worse than the
first:

1. A local `cdk deploy` would try to ship a ~154 MB function package.
2. The local asset hash could never match CI's, so `cdk diff` always reported spurious
   Lambda `S3Key` changes — which quietly defeats the "review `cdk diff` before every
   deploy" habit that ADR-004 relies on, because there is always noise to look past.

Keep this list ahead of the tools: adding a Python tool that writes a dot-directory into
`backend/` means adding it here too.
"""
from pathlib import Path

from aws_cdk import aws_lambda as _lambda

# Repo root is two levels up from infra/ledgerly/ ; the Lambda source root is backend/.
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

BACKEND_ASSET_EXCLUDE = [
    # Not runtime code.
    "tests",
    "eval",
    # Build/tool droppings. `.venv` and the caches are gitignored but NOT excluded by git
    # status here — CDK globs the directory as-is (see module docstring).
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "**/__pycache__",
    "**/*.pyc",
    # Manifests and docs: the Lambda runtime provides boto3 and core/ has no third-party
    # runtime deps, so nothing here is installed at runtime. Excluding requirements-dev.txt
    # also makes its own "NOT shipped to Lambda" header comment true again.
    "pyproject.toml",
    "requirements-dev.txt",
    "*.md",
]


def backend_code() -> _lambda.AssetCode:
    """The backend source tree, packaged for Lambda. Use this instead of `from_asset`."""
    return _lambda.Code.from_asset(str(BACKEND_DIR), exclude=BACKEND_ASSET_EXCLUDE)
