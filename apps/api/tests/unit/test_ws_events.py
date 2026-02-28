from src.schemas.ws_events import (
    WSEvent,
    MeetingStatusEvent,
    UtteranceEvent,
    ProposalCreatedEvent,
    ExecutionCompletedEvent,
)


def test_ws_event_serialization():
    event = WSEvent(type="test", data={"key": "value"})
    d = event.model_dump()
    assert d["type"] == "test"
    assert d["data"]["key"] == "value"


def test_meeting_status_event():
    event = MeetingStatusEvent(data={"session_id": "123", "status": "active"})
    assert event.type == "meeting_status"


def test_utterance_event():
    event = UtteranceEvent(data={"speaker": "Alice", "text": "Hello"})
    assert event.type == "utterance"


def test_proposal_created_event():
    event = ProposalCreatedEvent(data={"id": "p1", "title": "Draft email"})
    assert event.type == "proposal_created"


def test_execution_completed_event():
    event = ExecutionCompletedEvent(data={"id": "e1", "status": "success"})
    assert event.type == "execution_completed"
