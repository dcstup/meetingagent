import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { env } from "../lib/env.js";
import type { ActionItem, MeetingState, TranscriptLine } from "../types.js";

interface PersistedState {
  meetings: MeetingState[];
}

export class StorageService {
  private supabase?: SupabaseClient;
  private memory: PersistedState = { meetings: [] };

  constructor() {
    if (env.SUPABASE_URL && env.SUPABASE_SERVICE_ROLE_KEY) {
      this.supabase = createClient(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY);
    }
  }

  async saveMeetingSnapshot(meeting: MeetingState): Promise<void> {
    if (!this.supabase) {
      const idx = this.memory.meetings.findIndex((item) => item.id === meeting.id);
      if (idx === -1) {
        this.memory.meetings.push(structuredClone(meeting));
      } else {
        this.memory.meetings[idx] = structuredClone(meeting);
      }
      return;
    }

    await this.supabase.from("meetings").upsert({
      id: meeting.id,
      created_at: meeting.createdAt,
      last_extracted_at: meeting.lastExtractedAt ?? null
    });

    await this.supabase
      .from("transcripts")
      .upsert(meeting.transcript.map(mapTranscript), { onConflict: "id" });

    await this.supabase
      .from("action_items")
      .upsert(meeting.actions.map(mapAction), { onConflict: "id" });
  }

  async ping(): Promise<"supabase" | "memory"> {
    const status = await this.diagnose();
    return status.mode;
  }

  async diagnose(): Promise<{
    mode: "supabase" | "memory";
    reason?: string;
    hasSupabaseUrl: boolean;
    hasSupabaseServiceRoleKey: boolean;
  }> {
    const hasSupabaseUrl = Boolean(env.SUPABASE_URL);
    const hasSupabaseServiceRoleKey = Boolean(env.SUPABASE_SERVICE_ROLE_KEY);

    if (!this.supabase) {
      return {
        mode: "memory",
        reason: "Supabase client not configured from env",
        hasSupabaseUrl,
        hasSupabaseServiceRoleKey
      };
    }

    const { error } = await this.supabase.from("meetings").select("id").limit(1);
    if (error) {
      return {
        mode: "memory",
        reason: error.message,
        hasSupabaseUrl,
        hasSupabaseServiceRoleKey
      };
    }
    return {
      mode: "supabase",
      hasSupabaseUrl,
      hasSupabaseServiceRoleKey
    };
  }
}

function mapTranscript(line: TranscriptLine) {
  return {
    id: line.id,
    speaker: line.speaker,
    text: line.text,
    is_final: line.isFinal,
    ts: line.ts
  };
}

function mapAction(action: ActionItem) {
  return {
    id: action.id,
    title: action.title,
    description: action.description,
    owner: action.owner,
    due_date: action.dueDate ?? null,
    confidence: action.confidence,
    status: action.status,
    source_transcript_ids: action.sourceTranscriptIds,
    execution_plan: action.executionPlan ?? null,
    execution_result: action.executionResult ?? null,
    error: action.error ?? null,
    updated_at: action.updatedAt
  };
}
