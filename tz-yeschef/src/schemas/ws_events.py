from pydantic import BaseModel
from typing import Any, Literal


class WSEvent(BaseModel):
    type: str
    data: dict[str, Any] = {}


class MeetingStatusEvent(WSEvent):
    type: Literal["meeting_status"] = "meeting_status"


class UtteranceEvent(WSEvent):
    type: Literal["utterance"] = "utterance"


class ProposalCreatedEvent(WSEvent):
    type: Literal["proposal_created"] = "proposal_created"


class ProposalUpdatedEvent(WSEvent):
    type: Literal["proposal_updated"] = "proposal_updated"


class ExecutionStartedEvent(WSEvent):
    type: Literal["execution_started"] = "execution_started"


class ProposalDroppedEvent(WSEvent):
    type: Literal["proposal_dropped"] = "proposal_dropped"


class ExecutionCompletedEvent(WSEvent):
    type: Literal["execution_completed"] = "execution_completed"
