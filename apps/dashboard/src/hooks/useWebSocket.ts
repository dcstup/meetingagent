import { useCallback, useEffect, useRef, useState } from "react";

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export interface WsConfig {
  apiUrl: string;
  workspaceId: string;
  overlayToken: string;
}

export interface WsMessage {
  id: string;
  receivedAt: string;
  type: string;
  payload: Record<string, unknown>;
  raw: string;
}

interface UseWebSocketReturn {
  status: ConnectionStatus;
  messages: WsMessage[];
  connect: (config: WsConfig) => void;
  disconnect: () => void;
  clearMessages: () => void;
}

const RECONNECT_DELAY_MS = 3000;
const MAX_MESSAGES = 500;

export function useWebSocket(): UseWebSocketReturn {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [messages, setMessages] = useState<WsMessage[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const configRef = useRef<WsConfig | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shouldReconnectRef = useRef(false);
  const messageCountRef = useRef(0);

  const clearReconnectTimer = () => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  };

  const openConnection = useCallback((config: WsConfig) => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const wsBase = config.apiUrl
      .replace(/^https:\/\//, "wss://")
      .replace(/^http:\/\//, "ws://")
      .replace(/\/$/, "");

    const url = `${wsBase}/ws?workspace=${encodeURIComponent(config.workspaceId)}`;

    setStatus("connecting");

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.addEventListener("open", () => {
      // Stay in "connecting" until auth is confirmed via auth_ok
      ws.send(JSON.stringify({ type: "auth", token: config.overlayToken }));
    });

    ws.addEventListener("message", (event) => {
      const raw = String(event.data);
      let parsed: { type?: string } & Record<string, unknown> = {};
      try {
        parsed = JSON.parse(raw) as typeof parsed;
      } catch {
        parsed = { type: "raw", data: raw };
      }

      const { type, ...rest } = parsed;

      if (type === "auth_ok") {
        setStatus("connected");
      }
      messageCountRef.current += 1;

      const msg: WsMessage = {
        id: `${messageCountRef.current}-${Date.now()}`,
        receivedAt: new Date().toISOString(),
        type: typeof type === "string" ? type : "unknown",
        payload: rest as Record<string, unknown>,
        raw,
      };

      setMessages((prev) => {
        const next = [msg, ...prev];
        return next.length > MAX_MESSAGES ? next.slice(0, MAX_MESSAGES) : next;
      });
    });

    ws.addEventListener("close", () => {
      setStatus("disconnected");
      wsRef.current = null;

      if (shouldReconnectRef.current && configRef.current) {
        reconnectTimerRef.current = setTimeout(() => {
          if (shouldReconnectRef.current && configRef.current) {
            openConnection(configRef.current);
          }
        }, RECONNECT_DELAY_MS);
      }
    });

    ws.addEventListener("error", () => {
      setStatus("error");
    });
  }, []);

  const connect = useCallback(
    (config: WsConfig) => {
      clearReconnectTimer();
      configRef.current = config;
      shouldReconnectRef.current = true;
      openConnection(config);
    },
    [openConnection]
  );

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    clearReconnectTimer();
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  useEffect(() => {
    return () => {
      shouldReconnectRef.current = false;
      clearReconnectTimer();
      wsRef.current?.close();
    };
  }, []);

  return { status, messages, connect, disconnect, clearMessages };
}
