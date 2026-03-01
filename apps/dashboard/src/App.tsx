import { useCallback, useEffect, useState } from "react";
import { ConnectionBar } from "./components/ConnectionBar";
import { MeetingStatus } from "./components/MeetingStatus";
import { TranscriptFeed } from "./components/TranscriptFeed";
import { PipelineMonitor } from "./components/PipelineMonitor";
import { PipelineStats } from "./components/PipelineStats";
import { EventLog } from "./components/EventLog";
import { RailwayStatus } from "./components/RailwayStatus";
import { useWebSocket } from "./hooks/useWebSocket";
import { useWorkspaceInit } from "./hooks/useWorkspaceInit";

function getStoredRailwayConfig(): { railwayToken: string; railwayProjectId: string } {
  try {
    const raw = localStorage.getItem("yeschef_railway_config");
    if (raw) {
      const cfg = JSON.parse(raw) as { railwayToken?: string; railwayProjectId?: string };
      return {
        railwayToken: cfg.railwayToken ?? "",
        railwayProjectId: cfg.railwayProjectId ?? "e42012fb-9d96-4408-99cf-0f0717f6b06e",
      };
    }
  } catch {
    // ignore
  }
  return { railwayToken: "", railwayProjectId: "e42012fb-9d96-4408-99cf-0f0717f6b06e" };
}

export default function App() {
  const { status, messages, connect, disconnect, clearMessages } = useWebSocket();
  const { info, initStatus, error: initError } = useWorkspaceInit();

  const [railwayCfg, setRailwayCfg] = useState(getStoredRailwayConfig);

  // Auto-connect once workspace info is fetched. The vite proxy forwards /ws
  // to ws://localhost:8000, so we use a relative-style URL via window.location.
  useEffect(() => {
    if (initStatus === "ready" && info && status === "disconnected") {
      const apiUrl = `${window.location.protocol}//${window.location.host}`;
      connect({
        apiUrl,
        workspaceId: info.workspaceId,
        overlayToken: info.overlayToken,
      });
    }
  }, [initStatus, info, status, connect]);

  const handleRailwayConfig = useCallback((token: string, projectId: string) => {
    setRailwayCfg({ railwayToken: token, railwayProjectId: projectId });
  }, []);

  // The REST calls in PipelineMonitor go through the vite /api proxy too.
  const restConfig = {
    apiUrl: `${window.location.protocol}//${window.location.host}`,
    overlayToken: info?.overlayToken ?? "",
  };

  return (
    <div className="app">
      <ConnectionBar
        status={status}
        workspaceId={info?.workspaceId ?? ""}
        overlayToken={info?.overlayToken ?? ""}
        initStatus={initStatus}
        initError={initError}
        onDisconnect={disconnect}
        onReconnect={() => {
          if (info) {
            const apiUrl = `${window.location.protocol}//${window.location.host}`;
            connect({ apiUrl, workspaceId: info.workspaceId, overlayToken: info.overlayToken });
          }
        }}
        onRailwayConfig={handleRailwayConfig}
        railwayToken={railwayCfg.railwayToken}
        railwayProjectId={railwayCfg.railwayProjectId}
      />

      <main className="main-content">
        <MeetingStatus messages={messages} />

        <div className="two-col">
          <TranscriptFeed messages={messages} />
          <PipelineStats messages={messages} />
        </div>

        <PipelineMonitor
          messages={messages}
          apiUrl={restConfig.apiUrl}
          overlayToken={restConfig.overlayToken}
        />

        <RailwayStatus
          railwayToken={railwayCfg.railwayToken}
          projectId={railwayCfg.railwayProjectId}
        />

        <EventLog messages={messages} onClear={clearMessages} />
      </main>
    </div>
  );
}
