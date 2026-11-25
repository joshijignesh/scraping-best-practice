# Scheduling (step 9 — approval-gated)

## The gate

Schedule **only** when both are true:
1. The client approved the verified full result (step 8), and
2. The user explicitly asks for scheduling now.

Then ask for: cadence (weekly / every 15 days / monthly), day, time, timezone, which machine or
service runs it, and who gets notified on failure. Record the approval
(`--approved-by "Name, date"` → `schedule_approvals.log`, committed to git).

## Cadences

| Cadence | launchd (macOS) | cron (Linux) | GitHub Actions |
|---|---|---|---|
| Weekly, Monday 07:00 | `Weekday=1 Hour=7 Minute=0` | `0 7 * * 1` | `cron: "30 1 * * 1"` (UTC!) |
| Every 15 days | `Day=1` and `Day=15`, 07:00 | `0 7 1,15 * *` | `cron: "30 1 1,15 * *"` |
| Monthly, 1st 07:00 | `Day=1 Hour=7 Minute=0` | `0 7 1 * *` | `cron: "30 1 1 * *"` |

"Every 15 days" is implemented as the **1st and 15th of each month** (calendar schedulers have no
true 15-day interval and an interval timer drifts after sleep/reboot). If the client needs a strict
15-day gap, schedule daily and add a guard in `run`: skip when `last_run.json.finished` is less
than 15 days old (`--min-days 15`).

`templates/schedule.sh` installs these on macOS (launchd) or Linux (crontab):

```bash
./scripts/schedule.sh weekly MON 07:00 --approved-by "Client, 2026-11-26"
./scripts/schedule.sh every15 07:00     --approved-by "Client, 2026-11-26"
./scripts/schedule.sh monthly 1 07:00   --approved-by "Client, 2026-11-26"
./scripts/schedule.sh status
./scripts/schedule.sh run-now
./scripts/schedule.sh remove
```

The scheduled command (`SCHEDULE_CMD` in the script) defaults to
`scripts/run.sh && scripts/export.sh && scripts/verify.sh`: incremental run, then the selected
export formats, then verification.

## What every scheduled job must have

- **Lock file**, so a manual run and the schedule never overlap.
- **Non-zero exit** on any failure or incomplete list, so the scheduler records it.
- **Logs** in `data/logs/` (stdout/stderr) plus the run's own `data/runs/<run_id>/run.log`.
- **Notification** of the result (macOS `osascript display notification`, email, Slack webhook;
  ask the user which one).
- **Absolute paths** and an explicit `PATH`. Schedulers don't load your shell profile.
- **Missed runs**: launchd runs a missed calendar job after wake. Plain cron doesn't (use
  `anacron` or systemd `Persistent=true`).

## Platform notes

- **macOS launchd:** jobs can't read `~/Desktop`, `~/Documents`, `~/Downloads` without Full Disk
  Access for `/bin/bash`. Move the project to e.g. `~/Projects/` before scheduling, or grant
  access. Plist in `~/Library/LaunchAgents/`, load with `launchctl bootstrap gui/$(id -u) <plist>`.
- **Linux systemd timer** (preferred over cron on servers):
  ```ini
  # ~/.config/systemd/user/scraper.timer
  [Timer]
  OnCalendar=Mon *-*-* 07:00:00        # weekly; *-*-01,15 07:00:00 every 15 days; *-*-01 07:00:00 monthly
  Persistent=true
  [Install]
  WantedBy=timers.target
  ```
  plus `scraper.service` with `ExecStart=/path/scripts/run.sh` and `WorkingDirectory=`.
- **GitHub Actions:** cron is UTC; Playwright needs `npx playwright install --with-deps chromium`
  (or `python -m playwright install --with-deps chromium`); upload exports as artifacts. Note
  that the site may block datacenter IPs and the runner has no persistent captures (cache them
  with `actions/cache` or the incremental mode degrades to full every time).
- **Windows Task Scheduler:** `schtasks /Create /SC WEEKLY /D MON /ST 07:00 /TN scraper /TR "C:\path\scripts\run.bat"`.

## After installing

Run `schedule.sh run-now` once, watch the log, and confirm with `status` that the job exited 0.
Tell the user the plist/crontab location and how to remove it.
