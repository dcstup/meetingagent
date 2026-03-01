import { useState, useMemo, useCallback } from "react";
import type { WsMessage } from "../hooks/useWebSocket";

type Tab = "passed" | "dropped" | "filtered";

interface GateScores {
  specificity?: number;
  actionability?: number;
  speaker_commitment?: number;
  temporal_grounding?: number;
  novelty?: number;
  completeness?: number;
  feasibility?: number;
  [key: string]: number | undefined;
}

interface PassedProposal {
  id: string;
  title: string;
  body: string;
  confidence?: number;
  readiness?: number;
  gateAvgScore?: number;
  gateScores?: GateScores;
  evidenceQuote?: string;
  receivedAt: string;
  executionId?: string;
  executionStatus?: string;
}

interface DroppedProposal {
  id: string;
  title: string;
  body: string;
  gateAvgScore?: number;
  gateScores?: GateScores;
  evidenceQuote?: string;
  missingInfo?: string;
  filterReason?: string;
  receivedAt: string;
}

interface FilteredItem {
  id: string;
  title: string;
  body: string;
  confidence?: number;
  readiness?: number;
  filterReason?: string;
  receivedAt: string;
}

interface Props {
  messages: WsMessage[];
  apiUrl: string;
  overlayToken: string;
}

function getStr(obj: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const k of keys) {
    if (typeof obj[k] === "string") return obj[k] as string;
  }
  return undefined;
}

function getNum(obj: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const k of keys) {
    if (typeof obj[k] === "number") return obj[k] as number;
  }
  return undefined;
}

function ScoreGrid({ scores }: { scores: GateScores }) {
  const entries = Object.entries(scores).filter(([, v]) => typeof v === "number");
  if (entries.length === 0) return null;
  return (
    <div className="score-grid">
      {entries.map(([dim, val]) => (
        <div key={dim} className="score-cell">
          <span className="score-cell__dim">{dim.replace(/_/g, " ")}</span>
          <span className={`score-cell__val ${(val ?? 0) >= 4 ? "score--good" : "score--bad"}`}>
            {typeof val === "number" ? val.toFixed(1) : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

function PassedCard({
  proposal,
  apiUrl,
  overlayToken,
}: {
  proposal: PassedProposal;
  apiUrl: string;
  overlayToken: string;
}) {
  const [scoresOpen, setScoresOpen] = useState(false);
  const [approving, setApproving] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const callApi = useCallback(
    async (action: "approve" | "dismiss") => {
      const setter = action === "approve" ? setApproving : setDismissing;
      setter(true);
      try {
        const base = apiUrl.replace(/\/$/, "");
        const resp = await fetch(`${base}/api/proposals/${proposal.id}/${action}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${overlayToken}`,
          },
        });
        if (resp.ok) {
          setResult(action === "approve" ? "Approved" : "Dismissed");
        } else {
          setResult(`Error ${resp.status}`);
        }
      } catch (e) {
        setResult(e instanceof Error ? e.message : "Request failed");
      } finally {
        setter(false);
      }
    },
    [apiUrl, overlayToken, proposal.id]
  );

  return (
    <div className="proposal-card proposal-card--passed">
      <div className="proposal-card__header">
        <h4 className="proposal-card__title">{proposal.title}</h4>
        <div className="proposal-card__meta">
          {typeof proposal.gateAvgScore === "number" && (
            <span className="badge badge--green">avg {proposal.gateAvgScore.toFixed(2)}</span>
          )}
          <span className="proposal-card__time">
            {new Date(proposal.receivedAt).toLocaleTimeString()}
          </span>
        </div>
      </div>

      <p className="proposal-card__body">{proposal.body}</p>

      {proposal.evidenceQuote && (
        <blockquote className="proposal-card__quote">"{proposal.evidenceQuote}"</blockquote>
      )}

      {proposal.gateScores && (
        <div className="proposal-card__scores">
          <button
            className="btn-text"
            onClick={() => setScoresOpen((o) => !o)}
          >
            {scoresOpen ? "Hide scores" : "Show gate scores"}
          </button>
          {scoresOpen && <ScoreGrid scores={proposal.gateScores} />}
        </div>
      )}

      {result ? (
        <p className={`proposal-card__result ${result === "Approved" ? "text--green" : "text--muted"}`}>
          {result}
        </p>
      ) : (
        <div className="proposal-card__actions">
          <button
            className="btn btn--primary btn--sm"
            onClick={() => callApi("approve")}
            disabled={approving || dismissing}
          >
            {approving ? "..." : "Approve"}
          </button>
          <button
            className="btn btn--danger btn--sm"
            onClick={() => callApi("dismiss")}
            disabled={approving || dismissing}
          >
            {dismissing ? "..." : "Dismiss"}
          </button>
        </div>
      )}
    </div>
  );
}

function DroppedCard({ proposal }: { proposal: DroppedProposal }) {
  const [scoresOpen, setScoresOpen] = useState(false);

  return (
    <div className="proposal-card proposal-card--dropped">
      <div className="proposal-card__header">
        <h4 className="proposal-card__title">{proposal.title}</h4>
        <div className="proposal-card__meta">
          {typeof proposal.gateAvgScore === "number" && (
            <span className="badge badge--red">avg {proposal.gateAvgScore.toFixed(2)}</span>
          )}
          <span className="proposal-card__time">
            {new Date(proposal.receivedAt).toLocaleTimeString()}
          </span>
        </div>
      </div>

      <p className="proposal-card__body">{proposal.body}</p>

      {proposal.filterReason && (
        <p className="proposal-card__reason">
          <strong>Reason:</strong> {proposal.filterReason}
        </p>
      )}

      {proposal.missingInfo && (
        <p className="proposal-card__missing">
          <strong>Missing:</strong> {proposal.missingInfo}
        </p>
      )}

      {proposal.evidenceQuote && (
        <blockquote className="proposal-card__quote">"{proposal.evidenceQuote}"</blockquote>
      )}

      {proposal.gateScores && (
        <div className="proposal-card__scores">
          <button className="btn-text" onClick={() => setScoresOpen((o) => !o)}>
            {scoresOpen ? "Hide scores" : "Show gate scores"}
          </button>
          {scoresOpen && <ScoreGrid scores={proposal.gateScores} />}
        </div>
      )}
    </div>
  );
}

function FilteredCard({ item }: { item: FilteredItem }) {
  return (
    <div className="proposal-card proposal-card--filtered">
      <div className="proposal-card__header">
        <h4 className="proposal-card__title">{item.title}</h4>
        <span className="proposal-card__time">
          {new Date(item.receivedAt).toLocaleTimeString()}
        </span>
      </div>

      <p className="proposal-card__body">{item.body}</p>

      <div className="proposal-card__chips">
        {typeof item.confidence === "number" && (
          <span className="chip">confidence {(item.confidence * 100).toFixed(0)}%</span>
        )}
        {typeof item.readiness === "number" && (
          <span className="chip">readiness {item.readiness.toFixed(1)}</span>
        )}
      </div>

      {item.filterReason && (
        <p className="proposal-card__reason">
          <strong>Filtered:</strong> {item.filterReason}
        </p>
      )}
    </div>
  );
}

export function PipelineMonitor({ messages, apiUrl, overlayToken }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("passed");

  const passed = useMemo<PassedProposal[]>(() => {
    return messages
      .filter((m) => m.type === "proposal_created")
      .map((m) => {
        const p = (m.payload?.data ?? m.payload) as any;
        const gs = (p.gate_scores ?? p.gateScores) as Record<string, unknown> | undefined;
        return {
          id: String(p.id ?? p.proposal_id ?? m.id),
          title: String(p.title ?? "Untitled"),
          body: String(p.body ?? p.description ?? ""),
          confidence: getNum(p, "confidence"),
          readiness: getNum(p, "gate_readiness", "readiness"),
          gateAvgScore: getNum(p, "gate_avg_score", "gateAvgScore"),
          gateScores: gs as GateScores | undefined,
          evidenceQuote: getStr(p, "gate_evidence_quote", "evidence_quote", "evidenceQuote"),
          receivedAt: m.receivedAt,
        };
      });
  }, [messages]);

  const dropped = useMemo<DroppedProposal[]>(() => {
    return messages
      .filter((m) => m.type === "proposal_dropped")
      .map((m) => {
        const p = (m.payload?.data ?? m.payload) as any;
        const gs = (p.gate_scores ?? p.gateScores) as Record<string, unknown> | undefined;
        return {
          id: String(p.id ?? p.proposal_id ?? m.id),
          title: String(p.title ?? "Untitled"),
          body: String(p.body ?? p.description ?? ""),
          gateAvgScore: getNum(p, "gate_avg_score", "gateAvgScore"),
          gateScores: gs as GateScores | undefined,
          evidenceQuote: getStr(p, "gate_evidence_quote", "evidence_quote", "evidenceQuote"),
          missingInfo: getStr(p, "gate_missing_info", "missing_info", "missingInfo"),
          filterReason: getStr(p, "reason", "filter_reason", "filterReason"),
          receivedAt: m.receivedAt,
        };
      });
  }, [messages]);

  const filtered = useMemo<FilteredItem[]>(() => {
    return messages
      .filter((m) => m.type === "proposal_filtered")
      .map((m) => {
        const p = (m.payload?.data ?? m.payload) as any;
        return {
          id: String(p.id ?? m.id),
          title: String(p.title ?? "Untitled"),
          body: String(p.body ?? p.description ?? ""),
          confidence: getNum(p, "confidence"),
          readiness: getNum(p, "readiness", "gate_readiness"),
          filterReason: getStr(p, "reason", "filter_reason", "filterReason"),
          receivedAt: m.receivedAt,
        };
      });
  }, [messages]);

  const TAB_LABELS: Record<Tab, string> = {
    passed: `Passed Gate (${passed.length})`,
    dropped: `Dropped by Gate (${dropped.length})`,
    filtered: `Filtered Pre-Gate (${filtered.length})`,
  };

  return (
    <section className="panel">
      <h2 className="panel__title">Pipeline Monitor</h2>

      <div className="tab-bar">
        {(["passed", "dropped", "filtered"] as Tab[]).map((tab) => (
          <button
            key={tab}
            className={`tab-btn ${activeTab === tab ? "tab-btn--active" : ""} tab-btn--${tab}`}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      <div className="proposal-list">
        {activeTab === "passed" && (
          <>
            {passed.length === 0 ? (
              <p className="muted">No proposals have passed the gate yet.</p>
            ) : (
              passed.map((p) => (
                <PassedCard key={p.id} proposal={p} apiUrl={apiUrl} overlayToken={overlayToken} />
              ))
            )}
          </>
        )}

        {activeTab === "dropped" && (
          <>
            {dropped.length === 0 ? (
              <p className="muted">No proposals have been dropped by the gate yet.</p>
            ) : (
              dropped.map((p) => <DroppedCard key={p.id} proposal={p} />)
            )}
          </>
        )}

        {activeTab === "filtered" && (
          <>
            {filtered.length === 0 ? (
              <p className="muted">No proposals have been filtered pre-gate yet.</p>
            ) : (
              filtered.map((item) => <FilteredCard key={item.id} item={item} />)
            )}
          </>
        )}
      </div>
    </section>
  );
}
