# M6 demo script (15 minutes, cameras on)

Before recording: VM is RUNNING, `/healthz` returns 200, Cloud Shell open in the Terraform folder, browser tabs ready (app, Logs Explorer, Metrics, Dashboard, Alert policy, Gmail, GitHub Actions, repo). Never show secrets, state files or the Secret Manager values.

| Min | Step | Rubric | What to show |
|---|---|---|---|
| 0:00 | Intro, architecture slide | all | Caddy, API, worker, Cloud SQL, GCS, Cloud Logging, Monitoring, GitHub Actions, WIF |
| 1:30 | Live HTTPS URL | 4 | Open https://34.132.226.2.nip.io, show `/healthz` version SHA, `/readyz`, `/console` |
| 3:00 | Controlled 5xx | 7 | `curl -X POST https://34.132.226.2.nip.io/ops/fault` six or more times. Show the JSON log line in Logs Explorer (`status` 500, `trace_id`) |
| 5:00 | Log-based metric | 7 | Metrics page for `occdesk-http-5xx-errors`, show the filter and the count rising |
| 6:30 | Dashboard | 7 | "Occurrence Desk" panels: 5xx count, CPU, memory, network, SQL. Refresh on |
| 8:00 | Alert | 7 | Policy "HTTP 5xx Error Rate", threshold, channel. Open the received email |
| 9:30 | Terraform | 9 | `terraform plan` live: "No changes". Name the resources Terraform does not manage |
| 11:00 | Push to main | 9 | Small commit, Actions run: test, deploy, health check, `/healthz` shows new SHA |
| 13:00 | Failed deploy and rollback | 9 | Run workflow with `break_health` true. Show Health false, Rolled back true, then site 200 and the previous SHA |
| 14:30 | Wrap up | 6 | Each person states what they built. Reminder: site stays up for grading |

Notes
- Each presenter's face must be on camera during their part. Audio-only narration is not accepted.
- Do the push in step 11:00 with a visible change, so the SHA before and after differs. Then the rollback step proves the previous version serves.
- Upload the full video to OneDrive. Share view or edit access with sdesini@cougarnet.uh.edu, krajan@cougarnet.uh.edu and skolanu@cougarnet.uh.edu. Submit the OneDrive link in Canvas.
- Submit the repo link, screenshots (dashboard, alert policy, received alert), the `terraform plan` output, the metric definition, and the run links for the green and the rolled-back pipeline.
