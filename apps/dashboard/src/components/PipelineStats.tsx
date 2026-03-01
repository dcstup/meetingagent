import { useMemo } from "react";
import type { WsMessage } from "../hooks/useWebSocket";

interface Stats {
  utterancesReceived: number;
  extractionCycles: number;
  itemsExtracted: number;
  itemsFiltered: number;
  gatePassed: number;
  gateDropped: number;
  executionsStarted: number;
  executionsCompleted: number;
}

interface Props {
  messages: WsMessage[];
}

interface StatCardProps {
  label: string;
  value: number;
  accent?: "gold" | "green" | "red" | "blue" | "grey";
}

function StatCard({ label, value, accent = "grey" }: StatCardProps) {
  return (
    <div className={`stat-card stat-card--${accent}`}>
      <span className="stat-card__value">{value}</span>
      <span className="stat-card__label">{label}</span>
    </div>
  );
}

export function PipelineStats({ messages }: Props) {
  const stats = useMemo<Stats>(() => {
    const counts: Stats = {
      utterancesReceived: 0,
      extractionCycles: 0,
      itemsExtracted: 0,
      itemsFiltered: 0,
      gatePassed: 0,
      gateDropped: 0,
      executionsStarted: 0,
      executionsCompleted: 0,
    };

    for (const m of messages) {
      switch (m.type) {
        case "utterance":
          counts.utterancesReceived++;
          break;
        case "extraction_cycle":
          counts.extractionCycles++;
          // payload may include items_count
          if (typeof m.payload.items_count === "number") {
            counts.itemsExtracted += m.payload.items_count;
          }
          break;
        case "proposal_filtered":
          counts.itemsFiltered++;
          break;
        case "proposal_created":
          counts.gatePassed++;
          // count items extracted from these too if no dedicated cycle event
          break;
        case "proposal_dropped":
          counts.gateDropped++;
          break;
        case "execution_started":
          counts.executionsStarted++;
          break;
        case "execution_completed":
          counts.executionsCompleted++;
          break;
        default:
          break;
      }
    }

    // If no explicit extraction cycle events, estimate from proposals
    if (counts.extractionCycles === 0 && counts.itemsExtracted === 0) {
      counts.itemsExtracted = counts.gatePassed + counts.gateDropped + counts.itemsFiltered;
    }

    return counts;
  }, [messages]);

  return (
    <section className="panel">
      <h2 className="panel__title">Pipeline Stats</h2>
      <div className="stats-grid">
        <StatCard label="Utterances" value={stats.utterancesReceived} accent="blue" />
        <StatCard label="Extraction Cycles" value={stats.extractionCycles} accent="grey" />
        <StatCard label="Items Extracted" value={stats.itemsExtracted} accent="gold" />
        <StatCard label="Filtered Pre-Gate" value={stats.itemsFiltered} accent="grey" />
        <StatCard label="Gate Passed" value={stats.gatePassed} accent="green" />
        <StatCard label="Gate Dropped" value={stats.gateDropped} accent="red" />
        <StatCard label="Executions Started" value={stats.executionsStarted} accent="blue" />
        <StatCard label="Executions Done" value={stats.executionsCompleted} accent="green" />
      </div>
    </section>
  );
}
