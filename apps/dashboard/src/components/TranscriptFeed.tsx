import { useEffect, useMemo, useRef } from "react";
import type { WsMessage } from "../hooks/useWebSocket";

interface Utterance {
  id: string;
  speaker: string;
  text: string;
  timestampMs: number;
  receivedAt: string;
}

interface Props {
  messages: WsMessage[];
}

function formatTime(isoOrMs: string | number): string {
  const d = typeof isoOrMs === "number" ? new Date(isoOrMs) : new Date(isoOrMs);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Assign a stable color per speaker name
const SPEAKER_COLORS = [
  "#C6A559", // gold
  "#7ecfcf", // teal
  "#b07fe8", // purple
  "#7ecf97", // green
  "#e87f7f", // red
  "#7fa8e8", // blue
];
const speakerColorCache = new Map<string, string>();
let colorIdx = 0;

function getSpeakerColor(speaker: string): string {
  if (!speakerColorCache.has(speaker)) {
    speakerColorCache.set(speaker, SPEAKER_COLORS[colorIdx % SPEAKER_COLORS.length]);
    colorIdx++;
  }
  return speakerColorCache.get(speaker)!;
}

export function TranscriptFeed({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  const utterances = useMemo<Utterance[]>(() => {
    return messages
      .filter((m) => m.type === "utterance")
      .map((m) => {
        const p = m.payload;
        return {
          id: m.id,
          speaker: String(p.speaker ?? p.participant_name ?? "Unknown"),
          text: String(p.text ?? p.transcript ?? ""),
          timestampMs:
            typeof p.timestamp_ms === "number"
              ? p.timestamp_ms
              : new Date(m.receivedAt).getTime(),
          receivedAt: m.receivedAt,
        };
      })
      .reverse(); // messages are newest-first; reverse for chronological order
  }, [messages]);

  // Auto-scroll to bottom on new utterances
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [utterances.length]);

  return (
    <section className="panel panel--grow">
      <h2 className="panel__title">
        Live Transcript
        <span className="panel__count">{utterances.length}</span>
      </h2>

      <div className="transcript-feed">
        {utterances.length === 0 ? (
          <p className="muted transcript-feed__empty">
            No utterances yet. Transcript lines will appear here as the bot receives audio.
          </p>
        ) : (
          utterances.map((u) => (
            <div key={u.id} className="utterance">
              <div className="utterance__meta">
                <span
                  className="utterance__speaker"
                  style={{ color: getSpeakerColor(u.speaker) }}
                >
                  {u.speaker}
                </span>
                <span className="utterance__time">{formatTime(u.timestampMs)}</span>
              </div>
              <p className="utterance__text">{u.text}</p>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}
