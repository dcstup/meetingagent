import { randomUUID } from "node:crypto";
import type { ActionItem, ActionStatus, MeetingState, TranscriptLine } from "../types.js";

export class MeetingStore {
  private meetings = new Map<string, MeetingState>();

  getOrCreate(meetingId: string): MeetingState {
    const existing = this.meetings.get(meetingId);
    if (existing) {
      return existing;
    }

    const created: MeetingState = {
      id: meetingId,
      createdAt: new Date().toISOString(),
      transcript: [],
      actions: []
    };
    this.meetings.set(meetingId, created);
    return created;
  }

  upsertTranscriptLine(
    meetingId: string,
    line: Pick<TranscriptLine, "speaker" | "text" | "isFinal"> & { id?: string }
  ): TranscriptLine {
    const meeting = this.getOrCreate(meetingId);
    const next: TranscriptLine = {
      id: line.id ?? randomUUID(),
      speaker: line.speaker,
      text: line.text.trim(),
      isFinal: line.isFinal,
      ts: new Date().toISOString()
    };

    if (!next.text) {
      return next;
    }

    const existingById = line.id
      ? meeting.transcript.find((entry) => entry.id === line.id)
      : undefined;
    if (existingById) {
      existingById.speaker = next.speaker;
      existingById.text = next.text;
      existingById.isFinal = next.isFinal;
      existingById.ts = next.ts;
      return existingById;
    }

    // Fallback coalescing if provider packet IDs are unavailable.
    const trailing = meeting.transcript.slice(-4);
    const lastInProgress = [...trailing]
      .reverse()
      .find((entry) => entry.speaker === next.speaker && !entry.isFinal);
    if (lastInProgress) {
      const left = normalizeTranscriptText(lastInProgress.text);
      const right = normalizeTranscriptText(next.text);
      if (left === right || left.startsWith(right) || right.startsWith(left)) {
        lastInProgress.text = next.text;
        lastInProgress.isFinal = next.isFinal;
        lastInProgress.ts = next.ts;
        return lastInProgress;
      }
    }

    meeting.transcript.push(next);
    return next;
  }

  replaceSuggestedActions(meetingId: string, suggested: ActionItem[]): ActionItem[] {
    const meeting = this.getOrCreate(meetingId);
    const actionable = new Map<string, ActionItem>();

    for (const action of meeting.actions) {
      if (action.status !== "suggested") {
        actionable.set(action.id, action);
      }
    }

    for (const action of suggested) {
      actionable.set(action.id, action);
    }

    const merged = [...actionable.values()].sort((a, b) =>
      a.updatedAt > b.updatedAt ? -1 : 1
    );

    meeting.actions = merged;
    meeting.lastExtractedAt = new Date().toISOString();
    return merged;
  }

  setActionStatus(
    meetingId: string,
    actionId: string,
    status: ActionStatus,
    patch?: Partial<ActionItem>
  ): ActionItem | undefined {
    const meeting = this.getOrCreate(meetingId);
    const target = meeting.actions.find((action) => action.id === actionId);
    if (!target) {
      return undefined;
    }

    target.status = status;
    target.updatedAt = new Date().toISOString();
    if (patch) {
      Object.assign(target, patch, { updatedAt: target.updatedAt });
    }

    return target;
  }

  editAction(
    meetingId: string,
    actionId: string,
    values: Pick<ActionItem, "title" | "owner" | "dueDate">
  ): ActionItem | undefined {
    const meeting = this.getOrCreate(meetingId);
    const target = meeting.actions.find((action) => action.id === actionId);
    if (!target) {
      return undefined;
    }

    target.title = values.title;
    target.owner = values.owner;
    target.dueDate = values.dueDate;
    target.updatedAt = new Date().toISOString();
    return target;
  }

  getRecentTranscriptWindow(meetingId: string, lines = 8): TranscriptLine[] {
    const meeting = this.getOrCreate(meetingId);
    return meeting.transcript.slice(-lines);
  }

  getState(meetingId: string): MeetingState {
    return this.getOrCreate(meetingId);
  }
}

function normalizeTranscriptText(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}
