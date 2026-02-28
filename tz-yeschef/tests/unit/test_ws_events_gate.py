"""Tests for Task 10: WebSocket events with gate data."""
from src.schemas.ws_events import ProposalCreatedEvent, ProposalDroppedEvent


def test_proposal_created_accepts_gate_fields():
    event = ProposalCreatedEvent(data={
        "id": "p1",
        "title": "Draft email",
        "gate_scores": {"clarity": 4, "actionability": 5},
        "gate_evidence_quote": "Let's send that email",
        "gate_missing_info": ["recipient unclear"],
        "gate_avg_score": 4.5,
    })
    assert event.type == "proposal_created"
    assert event.data["gate_scores"]["clarity"] == 4
    assert event.data["gate_avg_score"] == 4.5


def test_proposal_dropped_event():
    event = ProposalDroppedEvent(data={
        "id": "p1",
        "title": "Draft email",
        "gate_scores": {"clarity": 2},
        "gate_avg_score": 2.0,
        "gate_readiness": 1,
        "gate_evidence_quote": "still debating",
        "gate_missing_info": ["no consensus"],
        "gate_passed": False,
    })
    assert event.type == "proposal_dropped"
    assert event.data["gate_passed"] is False
