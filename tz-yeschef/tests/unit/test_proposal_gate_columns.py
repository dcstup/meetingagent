"""Tests for Task 3: gate score columns on Proposal model and dropped status."""
from src.models.tables import Proposal, ProposalStatus


def test_proposal_has_gate_score_columns():
    cols = {c.name for c in Proposal.__table__.columns}
    assert "gate_scores" in cols
    assert "gate_avg_score" in cols
    assert "gate_readiness" in cols
    assert "gate_evidence_quote" in cols
    assert "gate_missing_info" in cols
    assert "gate_passed" in cols


def test_proposal_status_has_dropped():
    assert ProposalStatus.dropped == "dropped"


def test_gate_columns_nullable():
    col_map = {c.name: c for c in Proposal.__table__.columns}
    assert col_map["gate_scores"].nullable is True
    assert col_map["gate_avg_score"].nullable is True
    assert col_map["gate_readiness"].nullable is True
    assert col_map["gate_evidence_quote"].nullable is True
    assert col_map["gate_missing_info"].nullable is True
    assert col_map["gate_passed"].nullable is True
