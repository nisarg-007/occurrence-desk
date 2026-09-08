# Runbooks

An alarm with no runbook is a notification, not an alarm. One page per alarm, each stating the
threshold **and the action**.

| Runbook | Owner | Status |
|---|---|---|
| `restore.md` — PITR restore: what broke, exact commands, time taken, cost | Parva | M3 |
| `backlog-growing.md` — oldest message age > 15 min | Sowmya | M2 |
| `dlq-nonempty.md` — read `error_text`, reproduce locally, `make dlq-drain` | Sowmya | M2 |
| `api-5xx.md` — > 1% over 5 min → roll back to the previous task definition | Sowmya | M2 |
| `scale-out-stuck.md` — RunningTaskCount at max for 10 min | Sowmya | M2 |
| `budget.md` — 50 / 80 / 100% of $100 → `make cloud-down` | Wasim | M2 |
