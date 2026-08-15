#!/usr/bin/env bash
# notify.sh <message> — the transport runner/notify.py and runner/digest.py shell out to.
# Wave-0 review gate item 2: Slack webhook + Resend email, fully env-driven, no secrets committed.
#   SLACK_WEBHOOK_URL   Slack incoming-webhook URL (optional)
#   RESEND_API_KEY      Resend API key (optional)
#   NOTIFY_EMAIL_TO     default kalepasch@gmail.com
#   NOTIFY_EMAIL_FROM   default "Madeus <notify@madeus.cc>"
# With neither configured this falls back to stdout (previous behavior), never fails.
set -u
MSG="${1:-}"
[ -z "$MSG" ] && exit 0
sent=0

if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  payload=$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1][:3000]}))' "$MSG" 2>/dev/null)
  if [ -n "$payload" ]; then
    curl -fsS -m 15 -X POST -H 'Content-Type: application/json' \
      -d "$payload" "$SLACK_WEBHOOK_URL" >/dev/null 2>&1 && sent=1
  fi
fi

if [ -n "${RESEND_API_KEY:-}" ]; then
  TO="${NOTIFY_EMAIL_TO:-kalepasch@gmail.com}"
  FROM="${NOTIFY_EMAIL_FROM:-Madeus <notify@madeus.cc>}"
  payload=$(python3 -c '
import json, sys
msg, to, frm = sys.argv[1], sys.argv[2], sys.argv[3]
subject = (msg.strip().splitlines() or ["notification"])[0][:120]
print(json.dumps({"from": frm, "to": [to], "subject": subject, "text": msg[:20000]}))
' "$MSG" "$TO" "$FROM" 2>/dev/null)
  if [ -n "$payload" ]; then
    curl -fsS -m 20 -X POST "https://api.resend.com/emails" \
      -H "Authorization: Bearer $RESEND_API_KEY" -H 'Content-Type: application/json' \
      -d "$payload" >/dev/null 2>&1 && sent=1
  fi
fi

if [ "$sent" = "0" ]; then
  echo "[notify] $MSG"
fi
exit 0
