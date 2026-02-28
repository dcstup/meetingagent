import WebSocket from "ws";
import { env } from "../lib/env.js";

type TranscriptCallback = (payload: {
  meetingId: string;
  id?: string;
  speaker: string;
  text: string;
  isFinal: boolean;
}) => void;

interface Session {
  socket?: WebSocket;
  mockChunkCount: number;
  pendingChunks: Buffer[];
  keepAliveTimer?: NodeJS.Timeout;
  reconnectTimer?: NodeJS.Timeout;
  fallbackToMock: boolean;
  reconnectAttempts: number;
}

export class DeepgramAdapter {
  private sessions = new Map<string, Session>();

  constructor(private onTranscript: TranscriptCallback) {}

  ensureSession(meetingId: string): void {
    const existing = this.sessions.get(meetingId);
    if (existing) {
      if (!existing.fallbackToMock && !existing.socket && !existing.reconnectTimer) {
        this.openSocket(meetingId, existing);
      }
      return;
    }

    if (!env.DEEPGRAM_API_KEY) {
      this.sessions.set(meetingId, {
        mockChunkCount: 0,
        pendingChunks: [],
        fallbackToMock: true,
        reconnectAttempts: 0
      });
      return;
    }

    const session: Session = {
      mockChunkCount: 0,
      pendingChunks: [],
      fallbackToMock: false,
      reconnectAttempts: 0
    };
    this.sessions.set(meetingId, session);
    this.openSocket(meetingId, session);
  }

  private openSocket(meetingId: string, session: Session): void {
    if (!env.DEEPGRAM_API_KEY || session.fallbackToMock || session.socket) {
      return;
    }

    const url =
      "wss://api.deepgram.com/v1/listen?model=nova-2&diarize=true&smart_format=true&interim_results=true&endpointing=300";

    const socket = new WebSocket(url, {
      headers: {
        Authorization: `Token ${env.DEEPGRAM_API_KEY}`
      }
    });

    session.socket = socket;

    socket.on("open", () => {
      session.reconnectAttempts = 0;
      const queued = [...session.pendingChunks];
      session.pendingChunks = [];

      for (const chunk of queued) {
        socket.send(chunk);
      }

      session.keepAliveTimer = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "KeepAlive" }));
        }
      }, 4000);
    });

    socket.on("message", (raw) => {
      try {
        const parsed = JSON.parse(String(raw));
        const alt = parsed?.channel?.alternatives?.[0];
        const text = alt?.transcript as string | undefined;
        if (!text || !text.trim()) {
          return;
        }

        const speakerValue = alt?.words?.[0]?.speaker;
        const speaker =
          typeof speakerValue === "number" ? `Speaker ${speakerValue + 1}` : "Speaker";
        const channelIndex = Array.isArray(parsed?.channel_index)
          ? parsed.channel_index.join("-")
          : "0";
        const startMs =
          typeof parsed?.start === "number" ? Math.round(parsed.start * 1000) : undefined;
        const transcriptId =
          typeof startMs === "number" ? `dg-${channelIndex}-${startMs}` : undefined;

        this.onTranscript({
          meetingId,
          id: transcriptId,
          speaker,
          text,
          isFinal: Boolean(parsed?.is_final)
        });
      } catch {
        // Ignore malformed packets from provider.
      }
    });

    socket.on("error", () => {
      this.cleanupSocket(session);
      this.scheduleReconnect(meetingId, session);
    });

    socket.on("close", () => {
      this.cleanupSocket(session);
      this.scheduleReconnect(meetingId, session);
    });
  }

  private scheduleReconnect(meetingId: string, session: Session): void {
    if (session.fallbackToMock || session.reconnectTimer) {
      return;
    }

    session.reconnectAttempts += 1;
    const delay = Math.min(12000, 1000 * 2 ** Math.min(session.reconnectAttempts, 4));

    session.reconnectTimer = setTimeout(() => {
      session.reconnectTimer = undefined;
      // Session may have been stopped while waiting.
      if (!this.sessions.has(meetingId)) {
        return;
      }
      this.openSocket(meetingId, session);
    }, delay);
  }

  private cleanupSocket(session: Session): void {
    if (session.keepAliveTimer) {
      clearInterval(session.keepAliveTimer);
      session.keepAliveTimer = undefined;
    }

    session.socket = undefined;
  }

  sendAudioChunk(meetingId: string, buffer: Buffer): void {
    const session = this.sessions.get(meetingId);
    if (!session) {
      this.ensureSession(meetingId);
      return this.sendAudioChunk(meetingId, buffer);
    }

    if (session.fallbackToMock) {
      session.mockChunkCount += 1;
      if (session.mockChunkCount % 5 === 0) {
        this.onTranscript({
          meetingId,
          speaker: "Speaker 1",
          text: "Discussed follow-ups and assigned next steps for launch prep.",
          isFinal: true
        });
      }
      return;
    }

    if (session.socket?.readyState === WebSocket.OPEN) {
      session.socket.send(buffer);
      return;
    }

    session.pendingChunks.push(buffer);
    if (session.pendingChunks.length > 120) {
      session.pendingChunks.shift();
    }

    if (!session.socket && !session.reconnectTimer) {
      this.openSocket(meetingId, session);
    }
  }

  stopSession(meetingId: string): void {
    const session = this.sessions.get(meetingId);
    if (!session) {
      return;
    }

    if (session.reconnectTimer) {
      clearTimeout(session.reconnectTimer);
      session.reconnectTimer = undefined;
    }

    if (session.keepAliveTimer) {
      clearInterval(session.keepAliveTimer);
      session.keepAliveTimer = undefined;
    }

    if (session.socket && session.socket.readyState === WebSocket.OPEN) {
      session.socket.send(JSON.stringify({ type: "Finalize" }));
      session.socket.close();
    }

    this.sessions.delete(meetingId);
  }
}
