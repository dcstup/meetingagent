"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8080/ws";
const API_BASE_URL = toHttpBase(WS_URL);

interface ToolkitConnection {
  slug: string;
  name: string;
  isActive: boolean;
  connectedAccountId?: string;
  status?: string;
}

interface ConnectionsResponse {
  ok: boolean;
  userId: string;
  toolkits: ToolkitConnection[];
  message?: string;
}

interface AuthorizeResponse {
  ok: boolean;
  userId: string;
  toolkit: string;
  redirectUrl?: string;
  message?: string;
}

export default function SettingsPage() {
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toolkits, setToolkits] = useState<ToolkitConnection[]>([]);
  const [activeToolkit, setActiveToolkit] = useState<string | null>(null);

  const callbackStatus = useMemo(() => {
    if (typeof window === "undefined") {
      return null;
    }

    const params = new URLSearchParams(window.location.search);
    const status = params.get("status");
    const connectedAccountId = params.get("connected_account_id");
    const callbackUserId = params.get("user_id");

    if (callbackUserId && !userId) {
      setUserId(callbackUserId);
    }

    if (!status) {
      return null;
    }

    if (status === "success") {
      return `Authentication succeeded${connectedAccountId ? ` (${connectedAccountId})` : ""}`;
    }

    return "Authentication failed or was cancelled.";
  }, [userId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const callbackUserId = params.get("user_id");
    if (callbackUserId) {
      setUserId(callbackUserId);
      return;
    }

    const stored = window.localStorage.getItem("meeting-agent-composio-user-id");
    if (stored) {
      setUserId(stored);
    }
  }, []);

  useEffect(() => {
    if (!userId) {
      return;
    }

    if (typeof window !== "undefined") {
      window.localStorage.setItem("meeting-agent-composio-user-id", userId);
    }

    refreshConnections().catch(() => {
      // handled via error state
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  async function refreshConnections() {
    if (!userId) {
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE_URL}/composio/connections?userId=${encodeURIComponent(userId)}`
      );
      const payload = (await response.json()) as ConnectionsResponse;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || `Request failed (${response.status})`);
      }
      setToolkits(payload.toolkits || []);
    } catch (fetchError) {
      setError(stringifyError(fetchError));
      setToolkits([]);
    } finally {
      setLoading(false);
    }
  }

  async function connectToolkit(toolkit: string) {
    if (!userId) {
      setError("Set a user ID first");
      return;
    }

    setActiveToolkit(toolkit);
    setError(null);

    try {
      const callbackUrl = `${window.location.origin}/settings?user_id=${encodeURIComponent(userId)}&source=composio_settings`;
      const response = await fetch(`${API_BASE_URL}/composio/authorize`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ userId, toolkit, callbackUrl })
      });

      const payload = (await response.json()) as AuthorizeResponse;
      if (!response.ok || !payload.ok || !payload.redirectUrl) {
        throw new Error(payload.message || `Authorize failed (${response.status})`);
      }

      window.location.href = payload.redirectUrl;
    } catch (authorizeError) {
      setError(stringifyError(authorizeError));
      setActiveToolkit(null);
    }
  }

  const connectedCount = toolkits.filter((t) => t.isActive).length;

  return (
    <main className="shell">
      <section className="panel header-panel">
        <div className="controls-row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1>Composio Settings</h1>
            <p>Manage toolkit authentication outside meeting chat flow (menu authentication).</p>
          </div>
          <Link href="/" className="settings-link">
            Back to meeting
          </Link>
        </div>

        <div className="controls-row">
          <label>
            Composio user ID
            <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="user_123" />
          </label>

          <button className="secondary" onClick={() => refreshConnections()} disabled={loading || !userId}>
            {loading ? "Refreshing..." : "Refresh connections"}
          </button>

          <div className="pill online">Connected {connectedCount}/{toolkits.length || 0}</div>
        </div>

        {callbackStatus && <p className="result">{callbackStatus}</p>}
        {error && <p className="error">{error}</p>}
      </section>

      <section className="panel">
        <h2>Toolkit Connections</h2>
        {!userId ? (
          <p className="muted">Enter user ID to load toolkit statuses.</p>
        ) : toolkits.length === 0 ? (
          <p className="muted">No toolkits returned yet.</p>
        ) : (
          <div className="diagnostic-list">
            {toolkits.map((toolkit) => (
              <div key={toolkit.slug} className="diagnostic-item">
                <div className="diagnostic-head">
                  <span>
                    {toolkit.name} <span className="muted">({toolkit.slug})</span>
                  </span>
                  <span className={`diag-chip ${toolkit.isActive ? "pass" : "warn"}`}>
                    {toolkit.isActive ? "connected" : "not connected"}
                  </span>
                </div>

                <p className="muted small-text">
                  status: {toolkit.status || (toolkit.isActive ? "ACTIVE" : "NOT_CONNECTED")}
                </p>
                <p className="muted small-text">
                  connected account: {toolkit.connectedAccountId || "-"}
                </p>

                {!toolkit.isActive && (
                  <div className="controls-row">
                    <button
                      onClick={() => connectToolkit(toolkit.slug)}
                      disabled={activeToolkit === toolkit.slug}
                    >
                      {activeToolkit === toolkit.slug ? "Opening auth..." : `Connect ${toolkit.slug}`}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

function toHttpBase(wsUrl: string): string {
  if (wsUrl.startsWith("wss://")) {
    return wsUrl.replace("wss://", "https://").replace(/\/ws$/, "");
  }

  if (wsUrl.startsWith("ws://")) {
    return wsUrl.replace("ws://", "http://").replace(/\/ws$/, "");
  }

  return "http://localhost:8080";
}
