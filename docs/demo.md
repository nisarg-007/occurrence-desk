# Demo script

Twelve minutes, timed to the second, with a named fallback for every step.
**Rehearse three times with everyone present.** Nisarg calls it; each lane narrates sixty seconds.

Status: skeleton. Fill the timings in during week 10 rehearsals, and put the real fallbacks in
once the environment exists.

## Before the room

| # | Check | Who | Fallback if it fails |
|---|---|---|---|
| 1 | `make e2e` green against dev | Nisarg | run the local stack instead; say so out loud |
| 2 | Worklist empty, backlog zero, DLQ zero | Sowmya | `make dlq-drain`, then reset |
| 3 | Dashboard open on the second screen | Sowmya | screenshots from the week-9 run |
| 4 | Cost page loaded and current | Wasim | last Friday's figure from `docs/measurements.md` |
| 5 | Wifi off test passed (no paid API anywhere in the pipeline) | Smit | — |

## Run order

| Time | Step | Who | Fallback |
|---|---|---|---|
| 0:00 | One sentence on the problem: intake is the bottleneck, not judgement | Nisarg | — |
| 0:30 | The corpus: 30 ASRS report sets × 50 records, NASA's own codes as ground truth. Say the caveat out loud. | Smit | — |
| 1:30 | Worklist is empty. Fire the replay: December 2022, Winter Storm Elliott, 1,260× speed | Sowmya | pre-recorded run |
| 2:30 | Backlog climbs; worker count follows it up; **submit latency stays flat** | Sowmya | week-9 graphs |
| 4:00 | Parsed reports stream into the worklist without a page reload | Nisarg | refresh manually |
| 5:00 | Raw PDF beside the parsed record, fields lining up; then the accuracy table | Smit | screenshots |
| 6:30 | Open the top report; the linked flight beside it — two federal agencies, joined by one query | Parva | pre-linked example |
| 7:30 | Open `/why`: read the four numbers out loud | Nisarg | — |
| 8:30 | Backlog drains; task count comes back down; run the zero-loss query live | Sowmya | saved query output |
| 9:30 | Deploy: a commit on `main`, pipeline, new task definition, smoke test green | Wasim | recording |
| 10:30 | PITR restore timing; the cost graph and the budget alarms | Parva, Wasim | screenshots |
| 11:30 | One sentence each on what we would do next | all | — |

## The one thing that must not happen

Nobody suggests parsing inline to make a step easier. The 202 is the thesis.
