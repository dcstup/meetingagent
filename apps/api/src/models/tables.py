import uuid
import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Index, Integer, String, Text, Float, ForeignKey, DateTime, func, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from .base import Base


class MeetingStatus(str, enum.Enum):
    pending = "pending"
    bot_joining = "bot_joining"
    connecting = "connecting"  # adapter-agnostic alias for bot_joining
    active = "active"
    ended = "ended"
    failed = "failed"


class ProposalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    dismissed = "dismissed"
    dropped = "dropped"


class ExecutionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    composio_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    has_google_calendar: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    overlay_token: Mapped[str] = mapped_column(String(255))
    webhook_secret: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    google_event_id: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    meet_url: Mapped[str] = mapped_column(String(500))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingSession(Base):
    __tablename__ = "meeting_sessions"
    __table_args__ = (
        Index("ix_meeting_sessions_workspace_status", "workspace_id", "status"),
        Index("ix_meeting_sessions_recall_bot_id", "recall_bot_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    calendar_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calendar_events.id"), nullable=True)
    recall_bot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adapter_type: Mapped[str | None] = mapped_column(String(32), default="recall", nullable=True)
    adapter_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meet_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[MeetingStatus] = mapped_column(SAEnum(MeetingStatus), default=MeetingStatus.pending)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Utterance(Base):
    __tablename__ = "utterances"
    __table_args__ = (
        Index("ix_utterances_session_created", "session_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting_sessions.id"))
    speaker: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        Index("ix_proposals_session_status", "session_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting_sessions.id"))
    action_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    dedupe_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(SAEnum(ProposalStatus), default=ProposalStatus.pending)
    source_text: Mapped[str] = mapped_column(Text)
    gate_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    gate_avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    gate_readiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gate_evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    gate_missing_info: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    gate_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Execution(Base):
    __tablename__ = "executions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposals.id"))
    status: Mapped[ExecutionStatus] = mapped_column(SAEnum(ExecutionStatus), default=ExecutionStatus.pending)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
