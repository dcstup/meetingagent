import { useState, useMemo, useCallback } from "react";
import type { WsMessage } from "../hooks/useWebSocket";

interface Props {
  messages: WsMessage[];
  onClear: () => void;
}

const ALL_TYPES = "__all__";

export function EventLog({ messages, onClear }: Props) {
  const [filter, setFilter] = useState<string>(ALL_TYPES);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const messageTypes = useMemo<string[]>(() => {
    const types = new Set<string>();
    for (const m of messages) types.add(m.type);
    return Array.from(types).sort();
  }, [messages]);

  const filtered = useMemo(() => {
    if (filter === ALL_TYPES) return messages;
    return messages.filter((m) => m.type === filter);
  }, [messages, filter]);

  const toggleExpand = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const TYPE_COLORS: Record<string, string> = {
    auth_ok: "#7ecf97",
    meeting_status: "#7fa8e8",
    utterance: "#C6A559",
    proposal_created: "#7ecfcf",
    proposal_dropped: "#e87f7f",
    proposal_filtered: "#b07fe8",
    proposal_updated: "#7fa8e8",
    execution_started: "#C6A559",
    execution_completed: "#7ecf97",
  };

  function getTypeColor(type: string): string {
    return TYPE_COLORS[type] ?? "#8899aa";
  }

  return (
    <section className="panel">
      <div className="event-log__header">
        <h2 className="panel__title">
          Event Log
          <span className="panel__count">{filtered.length}</span>
        </h2>

        <div className="event-log__controls">
          <select
            className="field-input field-input--sm"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value={ALL_TYPES}>All types</option>
            {messageTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          <button className="btn btn--ghost btn--sm" onClick={onClear} disabled={messages.length === 0}>
            Clear
          </button>
        </div>
      </div>

      <div className="event-log__list">
        {filtered.length === 0 ? (
          <p className="muted">
            {messages.length === 0
              ? "No events received yet. Connect and wait for pipeline activity."
              : "No events match the current filter."}
          </p>
        ) : (
          filtered.map((m) => {
            const isOpen = expanded.has(m.id);
            const color = getTypeColor(m.type);

            return (
              <div key={m.id} className="event-entry">
                <button
                  className="event-entry__summary"
                  onClick={() => toggleExpand(m.id)}
                  aria-expanded={isOpen}
                >
                  <span className="event-entry__time">
                    {new Date(m.receivedAt).toLocaleTimeString(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                  <span
                    className="event-entry__type"
                    style={{ color }}
                  >
                    {m.type}
                  </span>
                  <span className="event-entry__chevron">{isOpen ? "▲" : "▼"}</span>
                </button>

                {isOpen && (
                  <pre className="event-entry__payload">
                    {JSON.stringify({ type: m.type, ...m.payload }, null, 2)}
                  </pre>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
