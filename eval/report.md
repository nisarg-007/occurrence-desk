# Hazard categorisation - held-out accuracy

Trained on 1200 records (24 report sets), evaluated on 300 held-out records (6 report sets held out entirely).

Held-out report sets: ctlr, ems, icing, nmac, plt_ctlr, upsets

**micro-F1: 0.783**  **macro-F1: 0.574**

Micro-F1 counts every prediction equally; macro-F1 weights every label equally regardless of how rare it is - which is why macro is lower: rare categories are genuinely harder and this is not hidden.


## Per-label breakdown

| Label | Precision | Recall | F1 | Support (test) |
|---|---|---|---|---|
| ATC Issue | 0.85 | 0.68 | 0.76 | 128 |
| Aircraft Equipment Problem | 0.94 | 0.78 | 0.85 | 94 |
| Airspace Violation | 0.60 | 0.50 | 0.55 | 12 |
| Conflict | 0.90 | 0.98 | 0.94 | 114 |
| Deviation - Altitude | 0.54 | 0.64 | 0.59 | 53 |
| Deviation - Speed | 0.33 | 0.09 | 0.14 | 11 |
| Deviation - Track / Heading | 0.86 | 0.18 | 0.29 | 34 |
| Deviation / Discrepancy - Procedural | 0.75 | 0.98 | 0.85 | 219 |
| Flight Deck / Cabin / Aircraft Event | 0.25 | 0.14 | 0.18 | 7 |
| Ground Event / Encounter | 0.89 | 0.22 | 0.36 | 36 |
| Ground Incursion | 0.57 | 0.87 | 0.68 | 15 |
| Inflight Event / Encounter | 0.82 | 0.83 | 0.83 | 136 |
| Other | 1.00 | 0.29 | 0.44 | 7 |

## Error analysis (10 held-out mismatches)

216 of 300 held-out records did not get an EXACT label-set match (one label added, dropped, or both counts as a miss here, even if the rest of that record's labels were right - the per-record 'samples avg' F1 printed by classification_report is the fairer number for how close a typical prediction actually was).

- **ACN 2105330** (set `ctlr`) - true: ['ATC Issue', 'Deviation - Track / Heading', 'Deviation / Discrepancy - Procedural', 'Ground Event / Encounter'] | predicted: ['Deviation / Discrepancy - Procedural']
  > We had weather today with a high volume workload due to additional weather in the Houston metro. This caused more aircraft to be routed into the area and cause our numbers to be near or above most of the morning and earl...

- **ACN 2105322** (set `ctlr`) - true: ['ATC Issue', 'Aircraft Equipment Problem', 'Deviation / Discrepancy - Procedural'] | predicted: ['Deviation / Discrepancy - Procedural']
  > I chose this aircraft as an example but I really want to report is the unsafe conditions the FAA is making us work. We have been short staffed for too many years and it's creating so many unsafe situations. This example ...

- **ACN 2103770** (set `ctlr`) - true: ['ATC Issue', 'Conflict'] | predicted: ['ATC Issue', 'Conflict', 'Deviation / Discrepancy - Procedural']
  > In the process of changing flows from south to north flow. The arrival end was vectoring to 04L and 03R the Tower departed two aircraft off of 21L opposite direction. Tower put the two aircraft on my frequency climbing v...

- **ACN 2103769** (set `ctlr`) - true: ['ATC Issue', 'Deviation / Discrepancy - Procedural', 'Ground Event / Encounter'] | predicted: ['Deviation / Discrepancy - Procedural']
  > Aircraft X was requesting UHF frequency for SBN. We shipped aircraft to SBN [Approach] on 257.8 and aircraft came back and told us the people on 257.8 told them its the wrong frequency. I contacted SBN approach to verify...

- **ACN 2103374** (set `ctlr`) - true: ['ATC Issue', 'Deviation / Discrepancy - Procedural', 'Other'] | predicted: ['ATC Issue', 'Deviation / Discrepancy - Procedural']
  > On Day 0 at approximately XA00Z White Sands Missile Range (WSMR) began their GPS Jamming procedures that they conduct annually around this time of year. Typically GPS jamming exercises have less of an impact in the previ...

- **ACN 2100867** (set `ctlr`) - true: ['ATC Issue', 'Conflict', 'Ground Event / Encounter'] | predicted: ['ATC Issue', 'Conflict', 'Deviation / Discrepancy - Procedural']
  > 5 minutes after taking position from previous controller, splitting off LC2 (Local Control) to accommodate increasing volume of traffic. After briefing given to parallel controller and while monitoring departures from th...

- **ACN 2100496** (set `ctlr`) - true: ['ATC Issue', 'Aircraft Equipment Problem', 'Deviation - Altitude', 'Deviation / Discrepancy - Procedural'] | predicted: ['ATC Issue', 'Aircraft Equipment Problem', 'Deviation / Discrepancy - Procedural']
  > GPS jamming was causing a ton of issues in the sector. I was getting overwhelmed with reports about aircraft losing equipment. Some aircraft needed headings as they could no longer navigate point-to-point. Per the LOA (L...

- **ACN 2100050** (set `ctlr`) - true: ['ATC Issue', 'Deviation / Discrepancy - Procedural', 'Ground Event / Encounter'] | predicted: ['Deviation / Discrepancy - Procedural']
  > Yet another serious safety issue, by the same OM I reported a couple weeks ago, due to not doing a "Stop Buzzer" call as per our facility standard operating procedures, SOP. Yesterday we had GPS jamming in effect with mu...

- **ACN 2098635** (set `ctlr`) - true: ['Ground Event / Encounter'] | predicted: ['Deviation / Discrepancy - Procedural']
  > Aicraft X seen on Taxiway 1 after landing Runway XXR with a collapsed front gear and prop striking the asphalt, Pilot was notified to shut down engine. 30 minutes after, we were notified by airport authority that aircraf...

- **ACN 2098625** (set `ctlr`) - true: ['ATC Issue', 'Airspace Violation', 'Deviation / Discrepancy - Procedural', 'Inflight Event / Encounter'] | predicted: ['Deviation / Discrepancy - Procedural', 'Inflight Event / Encounter']
  > Aircraft had been given a clearance ZZZ-ZZZ1 at 040. This is a normal VFR route below 040 feet. I was working many 172's in this area that were VFR. I lost sight of this one being IFR. Just as they entered the 060 at 040...
