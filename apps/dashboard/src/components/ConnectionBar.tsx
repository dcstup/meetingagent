import { useCallback, useEffect, useState } from "react";
import type { ConnectionStatus } from "../hooks/useWebSocket";
import type { InitStatus } from "../hooks/useWorkspaceInit";

const LS_RAILWAY_KEY = "yeschef_railway_config";

interface RailwayConfig {
  railwayToken: string;
  railwayProjectId: string;
}

function loadRailwayConfig(token: string, projectId: string): RailwayConfig {
  try {
    const raw = localStorage.getItem(LS_RAILWAY_KEY);
    if (raw) return JSON.parse(raw) as RailwayConfig;
  } catch {
    // ignore
  }
  return { railwayToken: token, railwayProjectId: projectId };
}

function saveRailwayConfig(config: RailwayConfig) {
  try {
    localStorage.setItem(LS_RAILWAY_KEY, JSON.stringify(config));
  } catch {
    // ignore
  }
}

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting...",
  connected: "Connected",
  error: "Error",
};

interface Props {
  status: ConnectionStatus;
  workspaceId: string;
  overlayToken: string;
  initStatus: InitStatus;
  initError: string | null;
  onDisconnect: () => void;
  onReconnect: () => void;
  onRailwayConfig: (token: string, projectId: string) => void;
  railwayToken: string;
  railwayProjectId: string;
}

export function ConnectionBar({
  status,
  workspaceId,
  overlayToken,
  initStatus,
  initError,
  onDisconnect,
  onReconnect,
  onRailwayConfig,
  railwayToken,
  railwayProjectId,
}: Props) {
  const [railwayCfg, setRailwayCfg] = useState<RailwayConfig>(() =>
    loadRailwayConfig(railwayToken, railwayProjectId)
  );

  useEffect(() => {
    saveRailwayConfig(railwayCfg);
    onRailwayConfig(railwayCfg.railwayToken, railwayCfg.railwayProjectId);
  }, [railwayCfg, onRailwayConfig]);

  const handleAction = useCallback(() => {
    if (status === "connected") {
      onDisconnect();
    } else {
      onReconnect();
    }
  }, [status, onDisconnect, onReconnect]);

  const initLabel =
    initStatus === "loading"
      ? "Fetching workspace..."
      : initStatus === "error"
      ? `Init error: ${initError}`
      : null;

  return (
    <header className="connection-bar">
      <div className="connection-bar__brand">
        <span className="brand-logo">YesChef</span>
        <span className="brand-sub">Debug Dashboard</span>
      </div>

      <div className="connection-bar__fields">
        {/* Auto-populated workspace info — read-only */}
        <label className="field-group">
          <span className="field-label">Workspace ID</span>
          <input
            className="field-input field-input--readonly"
            value={workspaceId || (initLabel ?? "")}
            readOnly
            placeholder="auto-fetched..."
            title={workspaceId}
          />
        </label>

        <label className="field-group">
          <span className="field-label">Overlay Token</span>
          <input
            className="field-input field-input--readonly field-input--token"
            type="password"
            value={overlayToken}
            readOnly
            placeholder="auto-fetched..."
          />
        </label>

        <div className="connection-bar__divider" />

        <label className="field-group">
          <span className="field-label">Railway Token</span>
          <input
            className="field-input field-input--token"
            type="password"
            value={railwayCfg.railwayToken}
            onChange={(e) =>
              setRailwayCfg((c) => ({ ...c, railwayToken: e.target.value }))
            }
            placeholder="railway api token"
          />
        </label>

        <label className="field-group">
          <span className="field-label">Railway Project ID</span>
          <input
            className="field-input"
            value={railwayCfg.railwayProjectId}
            onChange={(e) =>
              setRailwayCfg((c) => ({ ...c, railwayProjectId: e.target.value }))
            }
            placeholder="project-uuid"
          />
        </label>
      </div>

      <div className="connection-bar__actions">
        <button
          className={status === "connected" ? "btn btn--danger" : "btn btn--primary"}
          onClick={handleAction}
          disabled={status === "connecting" || initStatus === "loading"}
        >
          {status === "connecting"
            ? "Connecting..."
            : status === "connected"
            ? "Disconnect"
            : "Reconnect"}
        </button>

        <div className={`status-pill status-pill--${status}`}>
          <span className="status-pill__dot" />
          {STATUS_LABELS[status]}
        </div>
      </div>
    </header>
  );
}
