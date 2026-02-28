import type { FastifyBaseLogger } from "fastify";
import { ComposioAdapter } from "./composio-adapter.js";
import { MeetingStore } from "./meeting-store.js";
import { OpenAIAdapter } from "./openai-adapter.js";
import { StorageService } from "./storage.js";
import type { ActionItem, ComposioExecutionRequest, MeetingState } from "../types.js";

interface Broadcaster {
  publishMeeting(meetingId: string): void;
  publishActionStatus(
    meetingId: string,
    payload: { actionId: string; status: ActionItem["status"]; result?: string; error?: string }
  ): void;
  publishDebug(
    meetingId: string,
    payload: {
      provider: "openai" | "composio";
      stage: "input" | "output";
      operation: string;
      input: unknown;
      ts: string;
    }
  ): void;
}

export class Orchestrator {
  private extractionTimers = new Map<string, NodeJS.Timeout>();

  constructor(
    private store: MeetingStore,
    private openai: OpenAIAdapter,
    private composio: ComposioAdapter,
    private storage: StorageService,
    private broadcaster: Broadcaster,
    private logger: FastifyBaseLogger
  ) {}

  queueExtraction(meetingId: string): void {
    const pending = this.extractionTimers.get(meetingId);
    if (pending) {
      clearTimeout(pending);
    }

    const timer = setTimeout(async () => {
      this.extractionTimers.delete(meetingId);
      await this.runExtraction(meetingId);
    }, 900);

    this.extractionTimers.set(meetingId, timer);
  }

  async runExtraction(meetingId: string): Promise<void> {
    const recent = this.store.getRecentTranscriptWindow(meetingId, 24);
    const existing = this.store.getState(meetingId).actions;
    const compactTranscript = recent.map((line) => `${line.speaker}: ${line.text}`);

    this.broadcaster.publishDebug(meetingId, {
      provider: "openai",
      stage: "input",
      operation: "extract_action_items",
      input: {
        transcript: compactTranscript,
        existingActionCount: existing.length
      },
      ts: new Date().toISOString()
    });

    const extraction = await this.openai.extractActionItems(recent, existing);
    this.broadcaster.publishDebug(meetingId, {
      provider: "openai",
      stage: "output",
      operation: "extract_action_items",
      input: {
        actionCount: extraction.actions.length,
        actions: extraction.actions,
        modelOutput: extraction.modelOutput
      },
      ts: new Date().toISOString()
    });

    if (!extraction.actions.length) {
      return;
    }

    this.store.replaceSuggestedActions(meetingId, extraction.actions);
    this.broadcaster.publishMeeting(meetingId);
    await this.storage.saveMeetingSnapshot(this.store.getState(meetingId));
  }

  async approve(meetingId: string, actionId: string): Promise<void> {
    const action = this.store.setActionStatus(meetingId, actionId, "approved");
    if (!action) {
      return;
    }

    this.broadcaster.publishMeeting(meetingId);
    await this.storage.saveMeetingSnapshot(this.store.getState(meetingId));

    this.execute(meetingId, actionId).catch((error: unknown) => {
      this.logger.error({ error, meetingId, actionId }, "Execution failure");
    });
  }

  async deny(meetingId: string, actionId: string): Promise<void> {
    const action = this.store.setActionStatus(meetingId, actionId, "denied");
    if (!action) {
      return;
    }

    this.broadcaster.publishMeeting(meetingId);
    await this.storage.saveMeetingSnapshot(this.store.getState(meetingId));
  }

  async edit(
    meetingId: string,
    actionId: string,
    values: Pick<ActionItem, "title" | "owner" | "dueDate">
  ): Promise<void> {
    const action = this.store.editAction(meetingId, actionId, values);
    if (!action) {
      return;
    }

    this.broadcaster.publishMeeting(meetingId);
    await this.storage.saveMeetingSnapshot(this.store.getState(meetingId));
  }

  private async execute(meetingId: string, actionId: string): Promise<void> {
    const state = this.store.getState(meetingId);
    const action = state.actions.find((item) => item.id === actionId);
    if (!action || action.status !== "approved") {
      return;
    }

    this.store.setActionStatus(meetingId, actionId, "executing");
    this.broadcaster.publishActionStatus(meetingId, { actionId, status: "executing" });

    const executionRequest = buildComposioExecutionRequest(state, action);

    this.broadcaster.publishDebug(meetingId, {
      provider: "composio",
      stage: "input",
      operation: "execute_objective",
      input: executionRequest,
      ts: new Date().toISOString()
    });

    const result = await this.composio.execute(executionRequest);
    this.broadcaster.publishDebug(meetingId, {
      provider: "composio",
      stage: "output",
      operation: "execute_objective",
      input: result,
      ts: new Date().toISOString()
    });

    if (result.ok) {
      this.store.setActionStatus(meetingId, actionId, "completed", {
        executionResult: result.message,
        error: undefined
      });
      this.broadcaster.publishActionStatus(meetingId, {
        actionId,
        status: "completed",
        result: result.message
      });
    } else {
      this.store.setActionStatus(meetingId, actionId, "failed", { error: result.message });
      this.broadcaster.publishActionStatus(meetingId, {
        actionId,
        status: "failed",
        error: result.message
      });
    }

    this.broadcaster.publishMeeting(meetingId);
    await this.storage.saveMeetingSnapshot(this.store.getState(meetingId));
  }
}

function buildComposioExecutionRequest(
  state: MeetingState,
  action: ActionItem
): ComposioExecutionRequest {
  const objectiveSegments = [
    action.title.trim(),
    action.description.trim(),
    action.owner ? `Owner: ${action.owner}` : "",
    action.dueDate ? `Due: ${action.dueDate}` : ""
  ].filter(Boolean);
  const transcriptLines = state.transcript
    .filter((line) => line.text.trim().length > 0)
    .map((line) => ({
      speaker: line.speaker,
      text: line.text,
      isFinal: line.isFinal,
      ts: line.ts
    }));

  return {
    objective: objectiveSegments.join(" | "),
    meeting: {
      id: state.id
    },
    action: {
      id: action.id,
      title: action.title,
      description: action.description,
      owner: action.owner,
      dueDate: action.dueDate
    },
    transcriptContext: {
      source: "meeting_store_full_transcript",
      lineCount: transcriptLines.length,
      lines: transcriptLines
    },
    supabaseContext: {
      enabled: true,
      preferredLookupOrder: ["transcript_context", "supabase_lookup"],
      knownTables: ["meetings", "transcripts", "action_items"],
      notes:
        "If a required execution field is still missing after transcript inference, run Supabase lookup tools to resolve it before asking the user."
    }
  };
}
