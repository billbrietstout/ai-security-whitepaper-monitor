#!/usr/bin/env python3
"""Commit the export and the run file on the current branch, then open a pull request.

  git checkout -b weekly/2026-11-04
  python3 scripts/open_inventory_pr.py

The command runs the local schema check first. It commits
data/whitepapers.json, data/whitepapers.csv, and runs/. It pushes the
current branch with `git push -u origin <branch>` and opens a pull request
into master. Use it after a weekly filing pass or after an extraction edit.

It refuses to run on master or main. It does not force-push. It does not
merge the pull request. The GitHub check validate-whitepapers must pass
before merge.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import gh_rate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRANCHES = {"master", "main", "HEAD"}
EXPORT_PATHS = ["data/whitepapers.json", "data/whitepapers.csv", "runs"]
STAGE = ["git", "add", "--", *EXPORT_PATHS]


def commit_command(message: str) -> list[str]:
    """Commit the export paths only. Other staged files stay out of the commit."""
    return ["git", "commit", "-m", message, "--", *EXPORT_PATHS]


def export_cached_diff_command() -> list[str]:
    return ["git", "diff", "--cached", "--quiet", "--", *EXPORT_PATHS]


def refuse_default_branch(branch: str) -> None:
    if branch in DEFAULT_BRANCHES or not branch.strip() or any(char.isspace() for char in branch):
        today = datetime.now(timezone.utc).date().isoformat()
        raise SystemExit(
            f"Refusing to commit or push from {branch}. "
            "Weekly data changes go through a pull request.\n"
            f"git checkout -b weekly/{today}\n"
            "python3 scripts/open_inventory_pr.py"
        )


def push_command(branch: str) -> list[str]:
    refuse_default_branch(branch)
    if branch.startswith("-"):
        raise SystemExit("Refusing that branch name.")
    return ["git", "push", "-u", "origin", branch]


def pr_command(title: str, body: str) -> list[str]:
    return ["gh", "pr", "create", "--base", "master", "--title", title, "--body", body]


def pr_body() -> str:
    return (
        "This pull request updates `data/whitepapers.json` and `data/whitepapers.csv` from the issues.\n"
        "\n"
        "When this pass filed issues, `runs/` records which WP- ids are done, which are still pending, "
        "and the issue number for each created issue.\n"
        "\n"
        "The `validate-whitepapers` check must pass before merge. "
        "It checks the schema, the WP- id rules, and a fresh read of the issues.\n"
    )


def main() -> None:
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()
    refuse_default_branch(branch)
    subprocess.check_call(
        [sys.executable, str(ROOT / "scripts" / "validate_whitepapers.py"), "--schema-only"],
        cwd=ROOT,
    )
    subprocess.check_call(STAGE, cwd=ROOT)
    staged = subprocess.run(export_cached_diff_command(), cwd=ROOT)
    if staged.returncode == 0:
        raise SystemExit("Nothing staged in the export or the run file. Nothing was pushed.")
    if staged.returncode != 1:
        raise SystemExit("git diff --cached failed.")
    today = datetime.now(timezone.utc).date().isoformat()
    message = f"Update the whitepaper export ({today})"
    subprocess.check_call(commit_command(message), cwd=ROOT)
    subprocess.check_call(push_command(branch), cwd=ROOT)
    try:
        gh_rate.run_github_cli(pr_command(message, pr_body()), write=True, cwd=ROOT)
    except gh_rate.WriteBudgetExceeded as exc:
        raise SystemExit(str(exc)) from None
    print(f"Pushed {branch} and opened a pull request into master.")


if __name__ == "__main__":
    main()
