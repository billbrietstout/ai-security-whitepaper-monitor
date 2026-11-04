# Run files

`scripts/file_issues.py` writes one checkpoint per weekly pass: `runs/YYYY-MM-DD.json`. The date is UTC. `runs/latest.txt` stores the date of the file the last command wrote.

The file is rewritten after each reserved WP- id, each opened issue, and each project add.

- `done` lists WP- ids that are finished for this pass.
- `pending` lists WP- ids that still need an issue or a project item.
- `created_issues` maps a WP- id to the issue number this pass opened.
- `issues` maps a WP- id to an issue number. That includes a paper that was already filed.

Item status:

- `pending` means the id is reserved and the issue is not open yet.
- `issue_open` means the issue exists and the project item is not recorded yet.
- `done` means the issue exists and the project item is recorded.
- `already_filed` means an issue for that URL already existed. The command did not open another one.

A later run reads this file and continues `pending` and `issue_open` items. Pass `--date` when you need a specific file, including a file that was still pending after UTC midnight. The command does not open a second issue for a WP- id that already has a `<!-- wp-id: WP-0000 -->` marker.

`runs/gh-write-log.json` is the hourly write log for `scripts/gh_rate.py`. It holds timestamps only. When the log already has 400 writes in the last hour, the next filing command stops before it creates another issue. Delete it only when no filing command is running and you intend to reset that local count. The GitHub token is not in this file.
