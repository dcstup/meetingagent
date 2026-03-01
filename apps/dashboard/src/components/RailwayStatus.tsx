import { useCallback, useEffect, useRef, useState } from "react";

const RAILWAY_GRAPHQL = "/railway-api";
const REFRESH_INTERVAL_MS = 15_000;

const DEPLOYMENTS_QUERY = `
  query deployments($projectId: String!, $environmentId: String!) {
    deployments(
      first: 10
      input: { projectId: $projectId, environmentId: $environmentId }
    ) {
      edges {
        node {
          id
          status
          staticUrl
          createdAt
          updatedAt
          service {
            name
            id
          }
          meta
        }
      }
    }
  }
`;

const ENVIRONMENTS_QUERY = `
  query environments($projectId: String!) {
    environments(projectId: $projectId) {
      edges {
        node {
          id
          name
        }
      }
    }
  }
`;

interface DeploymentMeta {
  commitHash?: string;
  commitMessage?: string;
  branch?: string;
}

interface Deployment {
  id: string;
  status: string;
  staticUrl?: string;
  createdAt: string;
  updatedAt: string;
  service: { name: string; id: string };
  meta?: unknown;
}

function parseMeta(raw: unknown): DeploymentMeta {
  if (!raw) return {};
  if (typeof raw === "object") return raw as DeploymentMeta;
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as DeploymentMeta;
    } catch {
      return {};
    }
  }
  return {};
}

interface Environment {
  id: string;
  name: string;
}

interface Props {
  railwayToken: string;
  projectId: string;
}

type FetchState = "idle" | "loading" | "ok" | "error";

function statusColor(status: string): string {
  switch (status.toUpperCase()) {
    case "SUCCESS":
      return "green";
    case "BUILDING":
      return "yellow";
    case "DEPLOYING":
    case "INITIALIZING":
      return "blue";
    case "FAILED":
    case "CRASHED":
    case "REMOVED":
      return "red";
    default:
      return "grey";
  }
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function duration(createdAt: string, updatedAt: string): string {
  const ms = new Date(updatedAt).getTime() - new Date(createdAt).getTime();
  if (ms <= 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function truncate(str: string | undefined, max: number): string {
  if (!str) return "—";
  return str.length > max ? str.slice(0, max) + "…" : str;
}

export function RailwayStatus({ railwayToken, projectId }: Props) {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [fetchState, setFetchState] = useState<FetchState>("idle");
  const [error, setError] = useState<string>("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDeployments = useCallback(async () => {
    if (!railwayToken || !projectId) return;

    setFetchState("loading");
    setError("");

    try {
      // First resolve environment ID for "production"
      const envRes = await fetch(RAILWAY_GRAPHQL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${railwayToken}`,
        },
        body: JSON.stringify({
          query: ENVIRONMENTS_QUERY,
          variables: { projectId },
        }),
      });

      if (!envRes.ok) {
        throw new Error(`HTTP ${envRes.status}: ${envRes.statusText}`);
      }

      const envData = await envRes.json();

      if (envData.errors?.length) {
        throw new Error(envData.errors[0].message);
      }

      const envEdges: { node: Environment }[] =
        envData.data?.environments?.edges ?? [];

      const prodEnv =
        envEdges.find(
          (e) => e.node.name.toLowerCase() === "production"
        )?.node ?? envEdges[0]?.node;

      if (!prodEnv) {
        throw new Error("No environments found for this project");
      }

      const depRes = await fetch(RAILWAY_GRAPHQL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${railwayToken}`,
        },
        body: JSON.stringify({
          query: DEPLOYMENTS_QUERY,
          variables: { projectId, environmentId: prodEnv.id },
        }),
      });

      if (!depRes.ok) {
        throw new Error(`HTTP ${depRes.status}: ${depRes.statusText}`);
      }

      const depData = await depRes.json();

      if (depData.errors?.length) {
        throw new Error(depData.errors[0].message);
      }

      const edges: { node: Deployment }[] =
        depData.data?.deployments?.edges ?? [];

      setDeployments(edges.map((e) => e.node));
      setFetchState("ok");
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setFetchState("error");
    }
  }, [railwayToken, projectId]);

  useEffect(() => {
    if (!railwayToken || !projectId) {
      setFetchState("idle");
      return;
    }

    fetchDeployments();

    timerRef.current = setInterval(fetchDeployments, REFRESH_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchDeployments, railwayToken, projectId]);

  const isEmpty = !railwayToken || !projectId;

  return (
    <div className="panel railway-status">
      <div className="railway-status__header">
        <h2 className="panel__title">
          Railway Deployments
          <span className="railway-status__env-badge">production</span>
        </h2>
        <div className="railway-status__meta">
          {lastRefresh && (
            <span className="railway-status__last-refresh">
              refreshed {timeAgo(lastRefresh.toISOString())}
            </span>
          )}
          {fetchState === "loading" && (
            <span className="railway-status__spinner" aria-label="Loading" />
          )}
          {!isEmpty && (
            <button
              className="btn btn--ghost btn--sm"
              onClick={fetchDeployments}
              disabled={fetchState === "loading"}
            >
              Refresh
            </button>
          )}
        </div>
      </div>

      {isEmpty && (
        <p className="muted railway-status__prompt">
          Enter a Railway API token and Project ID in the connection bar above
          to view deployment status.
        </p>
      )}

      {fetchState === "error" && (
        <div className="railway-status__error">
          <span className="railway-status__error-icon">!</span>
          {error}
        </div>
      )}

      {fetchState !== "idle" && !isEmpty && deployments.length === 0 && fetchState === "ok" && (
        <p className="muted">No deployments found.</p>
      )}

      {deployments.length > 0 && (
        <div className="railway-deploy-table">
          <div className="railway-deploy-table__head">
            <span>Service</span>
            <span>Status</span>
            <span>Branch / Commit</span>
            <span>Message</span>
            <span>Duration</span>
            <span>When</span>
          </div>
          {deployments.map((dep) => {
            const color = statusColor(dep.status);
            const meta = parseMeta(dep.meta);
            return (
              <div key={dep.id} className="railway-deploy-row">
                <span className="railway-deploy-row__service">
                  {dep.service?.name ?? "—"}
                </span>
                <span>
                  <span className={`badge badge--${color} railway-deploy-row__status`}>
                    {dep.status}
                  </span>
                </span>
                <span className="railway-deploy-row__commit code">
                  {meta.branch ? (
                    <span className="railway-deploy-row__branch">
                      {meta.branch}
                    </span>
                  ) : null}
                  {meta.commitHash ? (
                    <span className="railway-deploy-row__sha">
                      {meta.commitHash.slice(0, 7)}
                    </span>
                  ) : (
                    <span className="text--muted">—</span>
                  )}
                </span>
                <span className="railway-deploy-row__message">
                  {truncate(meta.commitMessage, 48)}
                </span>
                <span className="railway-deploy-row__duration code">
                  {duration(dep.createdAt, dep.updatedAt)}
                </span>
                <span className="railway-deploy-row__when">
                  {timeAgo(dep.createdAt)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
