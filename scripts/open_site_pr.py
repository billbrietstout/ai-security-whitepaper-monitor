#!/usr/bin/env python3
"""Open a pull request on the site repo with the included-paper inventory.

The token must be able to push a branch and open a pull request on
billbrietstout/ai-shared-responsibility. The script reads SITE_REPO_TOKEN,
GITHUB_TOKEN, or GH_TOKEN. It does not print those values.

    python3 scripts/site_inventory.py --out /tmp/site-inventory
    python3 scripts/open_site_pr.py --from /tmp/site-inventory

It does not force-push. It does not merge the pull request.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_REPO = "billbrietstout/ai-shared-responsibility"
DEFAULT_BASE = "main"

sys.path.insert(0, str(ROOT / "scripts"))
import site_inventory  # noqa: E402


def token() -> str:
    value = (
        os.environ.get("SITE_REPO_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or ""
    ).strip()
    if not value:
        raise SystemExit(
            "Set SITE_REPO_TOKEN, GITHUB_TOKEN, or GH_TOKEN with permission "
            "to open a pull request on the site repository."
        )
    return value


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source_dir", default="")
    parser.add_argument("--repo", default=os.environ.get("SITE_REPO", DEFAULT_SITE_REPO))
    parser.add_argument("--base", default=os.environ.get("SITE_PR_BASE", DEFAULT_BASE))
    args = parser.parse_args()

    if args.source_dir:
        built = Path(args.source_dir)
    else:
        built = Path(tempfile.mkdtemp(prefix="site-inventory-"))
        subprocess.check_call(
            [sys.executable, str(ROOT / "scripts" / "site_inventory.py"), "--out", str(built)],
            cwd=ROOT,
        )

    full_path = built / "whitepapers.json"
    slim_path = built / "whitepapers.slim.json"
    if not full_path.exists() or not slim_path.exists():
        raise SystemExit("Missing whitepapers.json or whitepapers.slim.json in --from")

    full = json.loads(full_path.read_text(encoding="utf-8"))
    auth = token()
    env = os.environ.copy()
    env["GH_TOKEN"] = auth
    env["GITHUB_TOKEN"] = auth
    today = datetime.now(timezone.utc).date().isoformat()
    branch = f"inventory/{today}"

    work = Path(tempfile.mkdtemp(prefix="site-repo-"))
    clone = run(
        ["gh", "repo", "clone", args.repo, str(work), "--", "--branch", args.base, "--depth", "1"],
        cwd=ROOT,
        env=env,
    )
    if clone.returncode != 0:
        raise SystemExit("Could not clone the site repository. Check SITE_REPO_TOKEN and SITE_PR_BASE.")

    dest_full = work / "data" / "whitepapers.json"
    dest_slim = work / "data" / "whitepapers.slim.json"
    dest_full.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(full_path, dest_full)
    shutil.copyfile(slim_path, dest_slim)
    site_inventory.patch_index(
        work / "data" / "index.json",
        full["count"],
        full["count"],
        full["updated"],
    )

    status = run(["git", "status", "--porcelain", "--", "data/whitepapers.json", "data/whitepapers.slim.json", "data/index.json"], cwd=work)
    if not status.stdout.strip():
        print("Site inventory is already current. No pull request.")
        return

    run(["git", "checkout", "-b", branch], cwd=work)
    run(["git", "add", "--", "data/whitepapers.json", "data/whitepapers.slim.json", "data/index.json"], cwd=work)
    message = f"Update the whitepaper inventory from the monitor ({today})"
    commit = run(["git", "commit", "-m", message], cwd=work)
    if commit.returncode != 0:
        raise SystemExit("git commit failed on the site clone.")
    push = run(["git", "push", "-u", "origin", branch], cwd=work, env=env)
    if push.returncode != 0:
        raise SystemExit("git push to the site repository failed.")
    body = (
        "Copies included papers from `billbrietstout/ai-security-whitepaper-monitor` "
        "into `/data/whitepapers.json` and `/data/whitepapers.slim.json`.\n"
        "\n"
        f"Count: {full['count']} included papers, {full.get('extracted_count', 0)} with extraction.\n"
        "This is an inventory, not a principle-catalog change.\n"
    )
    pr = run(
        [
            "gh", "pr", "create",
            "--repo", args.repo,
            "--base", args.base,
            "--head", branch,
            "--title", message,
            "--body", body,
        ],
        cwd=work,
        env=env,
    )
    if pr.returncode != 0:
        raise SystemExit("Could not open the site pull request.")
    print(pr.stdout.strip() or f"Opened a pull request into {args.base}.")


if __name__ == "__main__":
    main()
