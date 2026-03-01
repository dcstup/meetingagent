import { useMemo } from "react";
import type { WsMessage } from "../hooks/useWebSocket";

interface MeetingState {
  sessionId: string;
  status: string;
  meetUrl?: string;
  startedAt?: string;
  botId?: string;
}

interface Props {
  messages: WsMessage[];
}

function formatDuration(isoStart: string): string {
  const diffMs = Date.now() - new Date(isoStart).getTime();
  const totalSec = Math.floor(diffMs / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

const STATUS_CLASS: Record<string, string> = {
  active: "badge--green",
  connecting: "badge--yellow",
  idle: "badge--grey",
  ended: "badge--grey",
  error: "badge--red",
};

export function MeetingStatus({ messages }: Props) {
  const meetingState = useMemo<MeetingState | null>(() => {
    // Find the latest meeting_status message
    const latest = messages.find((m) => m.type === "meeting_status");
    if (!latest) return null;
    const p = latest.payload;
    return {
      sessionId: String(p.session_id ?? p.sessionId ?? ""),
      status: String(p.status ?? "unknown"),
      meetUrl: typeof p.meet_url === "string" ? p.meet_url : undefined,
      startedAt: typeof p.started_at === "string" ? p.started_at : undefined,
      botId: typeof p.bot_id === "string" ? p.bot_id : undefined,
    };
  }, [messages]);

  if (!meetingState) {
    return (
      <section className="panel">
        <h2 className="panel__title">Active Meeting</h2>
        <p className="muted">No meeting status received yet. Waiting for WebSocket messages...</p>
      </section>
    );
  }

  const badgeClass = STATUS_CLASS[meetingState.status] ?? "badge--grey";

  return (
    <section className="panel">
      <h2 className="panel__title">Active Meeting</h2>
      <div className="meeting-grid">
        <div className="meeting-field">
          <span className="meeting-field__label">Session ID</span>
          <span className="meeting-field__value code">{meetingState.sessionId || "—"}</span>
        </div>
        <div className="meeting-field">
          <span className="meeting-field__label">Status</span>
          <span className={`badge ${badgeClass}`}>{meetingState.status}</span>
        </div>
        {meetingState.startedAt && (
          <div className="meeting-field">
            <span className="meeting-field__label">Duration</span>
            <span className="meeting-field__value">{formatDuration(meetingState.startedAt)}</span>
          </div>
        )}
        {meetingState.meetUrl && (
          <div className="meeting-field meeting-field--wide">
            <span className="meeting-field__label">Meet URL</span>
            <span className="meeting-field__value code">{meetingState.meetUrl}</span>
          </div>
        )}
        {meetingState.botId && (
          <div className="meeting-field">
            <span className="meeting-field__label">Bot ID</span>
            <span className="meeting-field__value code">{meetingState.botId}</span>
          </div>
        )}
      </div>
    </section>
  );
}
