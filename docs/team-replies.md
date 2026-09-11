# Team Lane Confirmations

Per Appendix D of the work-description pack — each team member confirms their lane.

## Sowmya — Queue, Autoscaling, Observability & Load

I confirm: I have read Part 0 and my own Part.

I'm bringing: a data science / Python background.

I'm learning: message queues (SQS/ElasticMQ) and async processing, Docker and
containerization, and the Git/GitHub branch-and-PR workflow — all genuinely new to
me going into this milestone.

My M1 date: 2026-09-11 — local queue (ElasticMQ) stood up, verified reachable,
load-tested against the live API with real numbers (0% failures, submit median
17ms / p95 30ms), all committed and pushed.

One risk: my lane's full local flow (upload → real queue → worker → real database
→ worklist) can't be proven end-to-end until Smit's worker (`services/worker/`)
and Parva's database (`db/`) exist — both are currently empty. My pieces are ready
for them to build against.
