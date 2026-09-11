"""
Stage 9: given only the narrative (the pilot's written paragraph), predict
which safety-hazard categories NASA's own analysts assigned.

This is graded against real expert labels, not labels we made up - which is
exactly why the work-pack calls this the one number in the project worth
putting on a slide, AND why it explicitly expects an honest, unflattering
score rather than a suspiciously perfect one.

Label design (a decision, not something the source PDFs spell out exactly):
NASA codes each anomaly as a field like "Events.Anomaly.Conflict : NMAC" -
an AXIS ("Conflict") and a specific VALUE ("NMAC") for that axis. We predict
at the AXIS level: "does this record involve a Conflict-type anomaly at
all", not the finer-grained value. That matches how ranking/hazard_categories
is used elsewhere in the project (broad categories, not every sub-value),
and it's what makes "count distinct Anomaly.* top-level values, keep >= 30
examples" (work-pack section 3.6) unambiguous to compute.

Axes with fewer than 30 examples across the corpus are folded into a single
"Other" label rather than dropped, so every record still has at least one
label and rare categories aren't silently thrown away.

Split: by REPORT SET (topic), not by individual record. The 50 records in
one set (e.g. all 50 "Near Midair Collision" reports) share a topic and
often similar vocabulary; splitting at the record level would train and test
on near-siblings and quietly inflate the score. Splitting by set is the
honest split - see the work-pack, section 3.6.

Run from the repo root:
    python services/worker/classifier.py
"""

import glob
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, "services/worker")
import joblib
from parser import parse_pdf  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, f1_score, precision_recall_fscore_support
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.svm import LinearSVC

MODEL_PATH = "services/worker/model/hazard_model.joblib"


def make_classifier():
    # CalibratedClassifierCV wraps LinearSVC so predict_proba returns real
    # probabilities in [0,1] - a bare LinearSVC only gives a decision-function
    # margin, which isn't the "confidence" number the extraction-record
    # contract asks for. Still LinearSVC underneath, per the work-pack.
    return OneVsRestClassifier(CalibratedClassifierCV(LinearSVC(), cv=3))


ANOMALY_RE = re.compile(r"^Events\.Anomaly\.(.+)$")
MIN_LABEL_COUNT = 30
OTHER = "Other"


def load_all_records():
    """Returns list of (set_name, record_dict) for every record in every
    downloaded report set."""
    out = []
    for path in sorted(glob.glob("services/worker/sample_pdfs/*.pdf")):
        set_name = os.path.splitext(os.path.basename(path))[0]
        for rec in parse_pdf(path, document_id=1):
            out.append((set_name, rec))
    return out


def anomaly_axes(record: dict) -> set[str]:
    axes = set()
    for f in record["fields"]:
        m = ANOMALY_RE.match(f["path"])
        if m:
            axes.add(m.group(1))
    return axes


def build_label_set(all_records):
    counts = Counter()
    for _, rec in all_records:
        for axis in anomaly_axes(rec):
            counts[axis] += 1
    kept = sorted(axis for axis, c in counts.items() if c >= MIN_LABEL_COUNT)
    dropped = sorted(axis for axis, c in counts.items() if c < MIN_LABEL_COUNT)
    return kept, dropped, counts


def record_labels(record: dict, kept: list[str]) -> set[str]:
    axes = anomaly_axes(record)
    labels = {a for a in axes if a in kept}
    if any(a not in kept for a in axes):
        labels.add(OTHER)
    return labels


def main():
    print("Loading and parsing all 30 report sets...")
    all_records = load_all_records()
    print(f"Total records: {len(all_records)}")

    kept, dropped, counts = build_label_set(all_records)
    print(
        f"\nKept {len(kept)} labels (>= {MIN_LABEL_COUNT} examples), "
        f"{len(dropped)} rare axes folded into '{OTHER}': {dropped}"
    )

    os.makedirs("eval", exist_ok=True)
    with open("eval/labels.json", "w") as f:
        json.dump({"kept": kept, "dropped_into_other": dropped, "counts": counts}, f, indent=2)
    print("Saved eval/labels.json")

    all_labels = kept + [OTHER]
    mlb = MultiLabelBinarizer(classes=all_labels)

    set_names = sorted({s for s, _ in all_records})
    from sklearn.model_selection import train_test_split

    train_sets, test_sets = train_test_split(set_names, test_size=0.2, random_state=42)
    train_sets, test_sets = set(train_sets), set(test_sets)
    print(f"\nSplit by report set: {len(train_sets)} train sets, {len(test_sets)} test sets")
    print(f"Test sets: {sorted(test_sets)}")

    train = [(s, r) for s, r in all_records if s in train_sets]
    test = [(s, r) for s, r in all_records if s in test_sets]
    print(f"Train records: {len(train)}  Test records: {len(test)}")

    X_train_text = [r["narrative"] for _, r in train]
    X_test_text = [r["narrative"] for _, r in test]
    y_train = mlb.fit_transform([record_labels(r, kept) for _, r in train])
    y_test = mlb.transform([record_labels(r, kept) for _, r in test])

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    X_train = vectorizer.fit_transform(X_train_text)
    X_test = vectorizer.transform(X_test_text)

    clf = make_classifier()
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)

    micro = f1_score(y_test, y_pred, average="micro", zero_division=0)
    macro = f1_score(y_test, y_pred, average="macro", zero_division=0)
    print(
        f"\ncategorisation micro-F1 {micro:.3f}  macro-F1 {macro:.3f}  "
        f"(n={len(test)} held-out records)"
    )

    precision, recall, f1, support = precision_recall_fscore_support(
        y_test, y_pred, average=None, zero_division=0
    )

    report_lines = []
    report_lines.append("# Hazard categorisation - held-out accuracy\n")
    report_lines.append(
        f"Trained on {len(train)} records ({len(train_sets)} report sets), "
        f"evaluated on {len(test)} held-out records "
        f"({len(test_sets)} report sets held out entirely).\n"
    )
    report_lines.append(f"Held-out report sets: {', '.join(sorted(test_sets))}\n")
    report_lines.append(f"**micro-F1: {micro:.3f}**  **macro-F1: {macro:.3f}**\n")
    report_lines.append(
        "Micro-F1 counts every prediction equally; macro-F1 weights every label equally "
        "regardless of how rare it is - which is why macro is lower: rare categories are "
        "genuinely harder and this is not hidden.\n"
    )
    report_lines.append("\n## Per-label breakdown\n")
    report_lines.append("| Label | Precision | Recall | F1 | Support (test) |")
    report_lines.append("|---|---|---|---|---|")
    for label, p, r, f, s in zip(all_labels, precision, recall, f1, support, strict=False):
        report_lines.append(f"| {label} | {p:.2f} | {r:.2f} | {f:.2f} | {s} |")

    # error analysis: pull genuine misses from the held-out set
    report_lines.append("\n## Error analysis (10 held-out mismatches)\n")
    mismatches = []
    for i, (set_name, rec) in enumerate(test):
        true = mlb.inverse_transform(y_test[i : i + 1])[0]
        pred = mlb.inverse_transform(y_pred[i : i + 1])[0]
        if set(true) != set(pred):
            mismatches.append((set_name, rec, true, pred))

    report_lines.append(
        f"{len(mismatches)} of {len(test)} held-out records did not get an EXACT "
        f"label-set match (one label added, dropped, or both counts as a miss here, "
        f"even if the rest of that record's labels were right - the per-record "
        f"'samples avg' F1 printed by classification_report is the fairer number "
        f"for how close a typical prediction actually was).\n"
    )
    for set_name, rec, true, pred in mismatches[:10]:
        snippet = rec["narrative"][:220].replace("\n", " ")
        report_lines.append(
            f"- **ACN {rec['acn']}** (set `{set_name}`) - true: {sorted(true)} | "
            f"predicted: {sorted(pred)}\n  > {snippet}...\n"
        )

    with open("eval/report.md", "w") as f:
        f.write("\n".join(report_lines))
    print("\nSaved eval/report.md")
    print(classification_report(y_test, y_pred, target_names=all_labels, zero_division=0))

    # The held-out split above is for honest reporting only - it deliberately
    # withholds 6 report sets so the printed score means something. The model
    # the worker actually uses in production is a SEPARATE model retrained on
    # every record we have, because throwing away 20% of the training data
    # forever would make the shipped model worse for no reason once we've
    # already measured its accuracy.
    print("\nRetraining final production model on all 1,500 records...")
    all_text = [r["narrative"] for _, r in all_records]
    y_all = mlb.transform([record_labels(r, kept) for _, r in all_records])
    final_vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    X_all = final_vectorizer.fit_transform(all_text)
    final_clf = make_classifier()
    final_clf.fit(X_all, y_all)

    os.makedirs("services/worker/model", exist_ok=True)
    joblib.dump(
        {
            "vectorizer": final_vectorizer,
            "classifier": final_clf,
            "labels": all_labels,
            "held_out_micro_f1": micro,
            "held_out_macro_f1": macro,
        },
        MODEL_PATH,
    )
    print(f"Saved {MODEL_PATH}")


if __name__ == "__main__":
    main()
