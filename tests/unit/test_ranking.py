"""The score has to be deterministic and explainable. These tests are what makes that a claim
rather than an intention."""

from __future__ import annotations

import datetime as dt

import pytest

from services.api import ranking

TODAY = dt.date(2026, 9, 8)


def test_score_is_deterministic():
    inp = ranking.ScoreInput((0.9,), 0.8, TODAY - dt.timedelta(days=30), False)
    assert ranking.priority(inp, TODAY) == ranking.priority(inp, TODAY)


def test_all_terms_maxed_is_100():
    inp = ranking.ScoreInput((1.0,), 1.0, TODAY, True)
    assert ranking.priority(inp, TODAY) == 100


def test_empty_report_is_not_zero():
    """An unclassified, unlinked, undated report is unknown-risk, not zero-risk. Scoring it 0
    would bury exactly the reports nobody has looked at yet."""
    assert ranking.priority(ranking.ScoreInput(), TODAY) > 0


def test_worst_hazard_wins():
    mild = ranking.priority(ranking.ScoreInput((0.2,), report_date=TODAY), TODAY)
    mixed = ranking.priority(ranking.ScoreInput((0.2, 0.95), report_date=TODAY), TODAY)
    assert mixed > mild


def test_recency_decays_and_never_inverts():
    scores = [
        ranking.priority(
            ranking.ScoreInput((0.5,), report_date=TODAY - dt.timedelta(days=d)), TODAY
        )
        for d in (0, 30, 365, 3650)
    ]
    assert scores == sorted(scores, reverse=True)


def test_one_year_old_report_keeps_about_a_third_of_its_recency():
    assert ranking.recency(TODAY - dt.timedelta(days=365), TODAY) == pytest.approx(0.3679, abs=1e-3)


def test_future_dated_report_is_not_more_urgent_than_today():
    future = ranking.recency(TODAY + dt.timedelta(days=10), TODAY)
    assert future == pytest.approx(ranking.recency(TODAY, TODAY))


def test_manager_flag_is_worth_ten_points():
    base = ranking.ScoreInput((0.5,), 0.5, TODAY, False)
    flagged = ranking.ScoreInput((0.5,), 0.5, TODAY, True)
    assert ranking.priority(flagged, TODAY) - ranking.priority(base, TODAY) == 10


def test_weights_sum_to_one():
    total = ranking.W_SEVERITY + ranking.W_LINK + ranking.W_RECENCY + ranking.W_MANAGER
    assert total == pytest.approx(1.0)


def test_explanation_products_reconstruct_the_score():
    inp = ranking.ScoreInput((0.7,), 0.4, TODAY - dt.timedelta(days=100), True)
    payload = ranking.explain(inp, TODAY)
    rebuilt = round(100 * sum(t["product"] for t in payload["terms"]))
    assert rebuilt == payload["priority"] == ranking.priority(inp, TODAY)


def test_every_term_carries_an_explanation():
    payload = ranking.explain(ranking.ScoreInput(), TODAY)
    assert len(payload["terms"]) == 4
    assert all(t["explanation"].strip() for t in payload["terms"])
