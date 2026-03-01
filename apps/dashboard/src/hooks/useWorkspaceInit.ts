import { useEffect, useState } from "react";

export interface WorkspaceInfo {
  workspaceId: string;
  overlayToken: string;
  hasGoogle: boolean;
  hasGoogleCalendar: boolean;
}

export type InitStatus = "idle" | "loading" | "ready" | "error";

export function useWorkspaceInit() {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [initStatus, setInitStatus] = useState<InitStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setInitStatus("loading");
      try {
        const res = await fetch("/api/workspace/init", { method: "POST" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as {
          workspace_id: string;
          overlay_token: string;
          has_google: boolean;
          has_google_calendar: boolean;
        };
        if (cancelled) return;
        setInfo({
          workspaceId: data.workspace_id,
          overlayToken: data.overlay_token,
          hasGoogle: data.has_google,
          hasGoogleCalendar: data.has_google_calendar,
        });
        setInitStatus("ready");
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setInitStatus("error");
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, []);

  return { info, initStatus, error };
}
