#!/bin/bash
# Schedule the scraper (step 9). Only with the client's approval, on demand.
# macOS → launchd (runs missed jobs after wake) · Linux → user crontab.
#
#   ./scripts/schedule.sh weekly MON 07:00   --approved-by "Client name, 2026-11-26"
#   ./scripts/schedule.sh every15 07:00      --approved-by "..."   (1st and 15th of each month)
#   ./scripts/schedule.sh monthly 1 07:00    --approved-by "..."   (day 1-28)
#   ./scripts/schedule.sh status             show the installed schedule + last run
#   ./scripts/schedule.sh run-now            trigger the scheduled job once, now
#   ./scripts/schedule.sh remove             stop scheduling
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$(basename "$PROJECT_DIR" | tr '[:upper:] ' '[:lower:]-')"
LABEL="local.${NAME}.scraper"
LOG_DIR="$PROJECT_DIR/data/logs"
APPROVALS="$PROJECT_DIR/schedule_approvals.log"
# What the schedule runs: incremental scrape → selected export formats → verification.
SCHEDULE_CMD="${SCHEDULE_CMD:-cd '$PROJECT_DIR' && ./scripts/run.sh && ./scripts/export.sh && { [ ! -x ./scripts/verify.sh ] || ./scripts/verify.sh; }}"
OS="$(uname -s)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
CRON_TAG="# scraper:$LABEL"

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
die() { echo "$*" >&2; exit 1; }

parse_time() { # HH:MM -> sets HH MM
  [[ "$1" =~ ^([0-9]{1,2}):([0-9]{2})$ ]] || die "Bad time '$1' (use HH:MM)"
  HH=$((10#${BASH_REMATCH[1]})); MM=$((10#${BASH_REMATCH[2]}))
  (( HH < 24 && MM < 60 )) || die "Bad time '$1'"
}

require_approval() {
  [[ -n "${APPROVED_BY:-}" ]] || die "Refusing to schedule without --approved-by \"<who>, <date>\".
Scheduling happens only after the client approved the full result (SKILL step 9)."
  [[ -x "$PROJECT_DIR/scripts/run.sh" ]] || die "Missing scripts/run.sh"
  mkdir -p "$LOG_DIR"
}

log_approval() {
  printf '%s\t%s\t%s\tapproved by: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(whoami)" "$1" "$APPROVED_BY" >> "$APPROVALS"
  echo "Approval logged in $APPROVALS"
}

# --------------------------------------------------------------------------- macOS
launchd_install() { # $1 = <dict> entries for StartCalendarInterval, $2 = description
  case "$PROJECT_DIR" in
    "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
      echo "WARNING: launchd can't read $PROJECT_DIR without Full Disk Access for /bin/bash."
      echo "         Move the project to e.g. ~/Projects/ or grant access, or the job will fail." ;;
  esac
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-c</string><string>$SCHEDULE_CMD</string></array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>StartCalendarInterval</key>
  <array>
$1  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/schedule.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/schedule.err.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "Scheduled (launchd): $2"; echo "Plist: $PLIST"
}

ld_entry() { # [extra keys] -> one <dict> with HH/MM
  printf '    <dict>%s<key>Hour</key><integer>%d</integer><key>Minute</key><integer>%d</integer></dict>\n' "${1:-}" "$HH" "$MM"
}

# --------------------------------------------------------------------------- Linux
cron_install() { # $1 = cron expression, $2 = description
  local line="$1 /bin/bash -c \"$SCHEDULE_CMD\" >> '$LOG_DIR/schedule.out.log' 2>&1 $CRON_TAG"
  { crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true; echo "$line"; } | crontab -
  echo "Scheduled (cron): $2"; echo "Crontab line: $line"
}

install() { # $1 launchd dicts, $2 cron expr, $3 description
  require_approval
  if [[ "$OS" == "Darwin" ]]; then launchd_install "$1" "$3"; else cron_install "$2" "$3"; fi
  log_approval "$3"
}

# --------------------------------------------------------------------------- CLI
cmd="${1:-}"; shift || true
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --approved-by) APPROVED_BY="${2:-}"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

case "$cmd" in
  weekly)
    [[ $# -eq 2 ]] || usage
    day=$(echo "$1" | tr '[:lower:]' '[:upper:]')
    case "$day" in SUN) n=0;; MON) n=1;; TUE) n=2;; WED) n=3;; THU) n=4;; FRI) n=5;; SAT) n=6;; *) die "Day must be MON..SUN";; esac
    parse_time "$2"
    install "$(ld_entry "<key>Weekday</key><integer>$n</integer>")"$'\n' "$MM $HH * * $n" "every $day at $2" ;;
  every15)
    [[ $# -eq 1 ]] || usage
    parse_time "$1"
    install "$(ld_entry "<key>Day</key><integer>1</integer>")"$'\n'"$(ld_entry "<key>Day</key><integer>15</integer>")"$'\n' \
      "$MM $HH 1,15 * *" "every 15 days (1st and 15th) at $1" ;;
  monthly)
    [[ $# -eq 2 && "$1" =~ ^[0-9]+$ && "$1" -ge 1 && "$1" -le 28 ]] || die "Usage: monthly <day 1-28> HH:MM"
    parse_time "$2"
    install "$(ld_entry "<key>Day</key><integer>$1</integer>")"$'\n' "$MM $HH $1 * *" "day $1 of every month at $2" ;;
  status)
    if [[ "$OS" == "Darwin" ]]; then
      if [[ -f "$PLIST" ]]; then
        echo "Installed: $PLIST"
        /usr/libexec/PlistBuddy -c "Print :StartCalendarInterval" "$PLIST"
        launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state|last exit code|runs" || echo "(not loaded)"
      else echo "No schedule installed."; fi
    else
      crontab -l 2>/dev/null | grep -F "$CRON_TAG" || echo "No schedule installed."
    fi
    [[ -f "$APPROVALS" ]] && { echo; echo "Approvals:"; tail -n 3 "$APPROVALS"; }
    [[ -f "$PROJECT_DIR/data/last_run.json" ]] && { echo; echo "Last run:"; cat "$PROJECT_DIR/data/last_run.json"; } ;;
  run-now)
    if [[ "$OS" == "Darwin" && -f "$PLIST" ]]; then
      launchctl kickstart "$DOMAIN/$LABEL" && echo "Started. Follow: tail -f $LOG_DIR/schedule.out.log"
    else
      /bin/bash -c "$SCHEDULE_CMD"
    fi ;;
  remove)
    if [[ "$OS" == "Darwin" ]]; then
      launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true; rm -f "$PLIST"
    else
      { crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true; } | crontab -
    fi
    echo "Schedule removed." ;;
  *) usage ;;
esac
