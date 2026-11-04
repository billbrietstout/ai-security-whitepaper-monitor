#!/usr/bin/env python3
"""Open one batch of screened papers, then stop so the run can be resumed.

  python3 scripts/file_issues.py run --queue work/queue.json --batch-size 25
  python3 scripts/file_issues.py show

The first command writes runs/<date>.json after it reserves each WP- id,
after it opens each issue, and after it adds each GitHub Project item.
Run it again to continue pending ids. Pass --date YYYY-MM-DD to pick a
file. When --date is omitted, runs/latest.txt names the file.

--batch-size defaults to 25. Use a value from 25 to 50 on a long queue.
Set WEEKLY_BATCH_SIZE to change the default.

GITHUB_TOKEN or GH_TOKEN opens issues. GITHUB_PROJECTS_TOKEN adds items
to GitHub Project 2. If GITHUB_PROJECTS_TOKEN is unset, the project step
uses the issue token. The tokens are not printed.

--dry-run writes the run file and does not call GitHub.
--skip-project leaves new issues at issue_open so a later run can add them.

Content-creating calls (issue creates and project adds) go through
scripts/gh_rate.py. The default pace is 1 second apart. The default
hourly budget is 400 writes, under GitHub's 500 writes an hour. At the
budget the command saves the run file and exits 2. Run it again after
the time it prints. --write-delay and --write-budget override the
defaults. GITHUB_WRITE_DELAY and GITHUB_HOURLY_WRITE_BUDGET do the same.
The delay cannot be under 1 second. The budget cannot be over 450.

The command does not close, delete, or edit an issue.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import filing  # noqa: E402
import gh_rate  # noqa: E402
import inventory  # noqa: E402


def _print_item(item: dict) -> None:
    number = item.get("issue_number")
    suffix = f" issue #{number}" if number else ""
    extras = item.get("also_found") or []
    extra = ""
    if extras:
        joined = ", ".join(f"#{value}" for value in extras)
        extra = f" (also {joined})"
    print(f"{item['wp_id']}: {item['status']}{suffix}{extra}")


def _run(args: argparse.Namespace) -> None:
    repository = inventory.repository_slug()
    batch_size = filing.resolve_batch_size(args.batch_size)
    path = filing.resolve_run_path(date=args.date, run=args.run)
    path = filing.roll_completed_run(
        path,
        have_queue=args.queue is not None,
        pinned=bool(args.date or args.run),
    )
    if not path.exists() and args.queue is None:
        raise SystemExit("Pass --queue to start a run. A later run resumes the file written here.")
    queue = filing.load_queue(args.queue) if args.queue else []
    owner = args.project_owner or repository.split("/")[0]
    date = args.date or filing.utc_today()
    if path.exists():
        existing = filing.RunStore.load(path)
        date = str(existing.data.get("date") or date)
    store = filing.prepare_run(
        path,
        date=date,
        repository=repository,
        project_owner=owner,
        project_number=args.project_number,
        batch_size=batch_size,
    )
    if queue:
        filing.merge_queue(store, queue, inventory.load_inventory())
    if args.dry_run:
        print(filing.format_run(store))
        print(f"Wrote {path}. GitHub was not contacted.")
        return
    limiter = gh_rate.Limiter.from_env(
        write_delay=args.write_delay,
        hourly_budget=args.write_budget,
    )
    gh_rate.set_shared_limiter(limiter)
    gap = f"{limiter.write_delay:g} second" if limiter.write_delay == 1 else f"{limiter.write_delay:g} seconds"
    print(f"GitHub writes: {gap} apart, {limiter.hourly_budget} per hour, one request at a time.")
    client = filing.GithubRestClient(
        repository,
        issue_token=filing.issue_token(),
        project_token=filing.project_token(),
        limiter=limiter,
    )
    project_id = ""
    if not args.skip_project:
        project_id = filing.resolve_project_id(client, owner, args.project_number)
        store.data["project_id"] = project_id
        store.data["project_owner"] = owner
        store.data["project_number"] = args.project_number
        store.save()
    try:
        filed = filing.file_batch(
            store,
            client,
            project_id,
            batch_size,
            skip_project=args.skip_project,
            on_item=_print_item,
        )
    except gh_rate.WriteBudgetExceeded as exc:
        print(str(exc))
        print(filing.format_run(store))
        print(f"Checkpoint saved at {path}. Run the same command again after the budget resets.")
        raise SystemExit(2) from None
    except filing.GithubError as exc:
        print(filing.redact(str(exc), filing.secrets_from_env()))
        raise SystemExit(1) from None
    print(filing.format_run(store))
    if filed == 0:
        print(f"Nothing pending in {path}.")
    elif store.data["pending"]:
        print("Run the same command again to file the next batch.")
    if args.skip_project:
        print("Project adds were skipped. Items stay issue_open until a run adds them.")


def _show(args: argparse.Namespace) -> None:
    path = filing.resolve_run_path(date=args.date, run=args.run)
    if not path.exists():
        raise SystemExit(f"No run file at {path}.")
    print(filing.format_run(filing.RunStore.load(path)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="file one batch, or resume a run file")
    run.add_argument("--queue", type=Path, help="JSON file of screened papers")
    run.add_argument("--date", default="", help="UTC date of the run file, YYYY-MM-DD")
    run.add_argument("--run", type=Path, help="path to the run file")
    run.add_argument("--batch-size", type=int, default=None, help="papers to process (default 25, use 25 to 50)")
    run.add_argument("--project-number", type=int, default=2, help="GitHub Project number (default 2)")
    run.add_argument("--project-owner", default="", help="user or organization that owns the project")
    run.add_argument("--dry-run", action="store_true", help="write the run file and do not call GitHub")
    run.add_argument("--skip-project", action="store_true", help="open issues and leave project adds for a later run")
    run.add_argument(
        "--write-delay",
        type=float,
        default=None,
        help="seconds between content-creating calls (default 1, minimum 1)",
    )
    run.add_argument(
        "--write-budget",
        type=int,
        default=None,
        help="content-creating calls allowed per hour (default 400, maximum 450)",
    )
    run.set_defaults(func=_run)

    show = sub.add_parser("show", help="print done and pending WP- ids")
    show.add_argument("--date", default="")
    show.add_argument("--run", type=Path)
    show.set_defaults(func=_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
