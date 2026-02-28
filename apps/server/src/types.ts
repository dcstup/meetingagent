export type ActionStatus =
  | "suggested"
  | "approved"
  | "denied"
  | "executing"
  | "completed"
  | "failed";

export interface TranscriptLine {
  id: string;
  speaker: string;
  text: string;
  isFinal: boolean;
  ts: string;
}

export interface ExecutionPlan {
  integration: "gmail" | "calendar" | "slack" | "linear" | "docs" | "generic";
  operation: string;
  payload: Record<string, unknown>;
}

export interface ComposioExecutionRequest {
  objective: string;
  meeting: {
    id: string;
  };
  action: {
    id: string;
    title: string;
    description: string;
    owner: string;
    dueDate?: string;
  };
  transcriptContext: {
    source: "meeting_store_full_transcript";
    lineCount: number;
    lines: Array<Pick<TranscriptLine, "speaker" | "text" | "isFinal" | "ts">>;
  };
  supabaseContext: {
    enabled: boolean;
    preferredLookupOrder: ["transcript_context", "supabase_lookup"];
    knownTables: string[];
    notes: string;
  };
}

export interface ActionItem {
  id: string;
  title: string;
  description: string;
  owner: string;
  dueDate?: string;
  confidence: number;
  status: ActionStatus;
  sourceTranscriptIds: string[];
  executionPlan?: ExecutionPlan;
  executionResult?: string;
  error?: string;
  updatedAt: string;
}

export interface MeetingState {
  id: string;
  createdAt: string;
  transcript: TranscriptLine[];
  actions: ActionItem[];
  lastExtractedAt?: string;
}

export interface DebugEvent {
  provider: "openai" | "composio";
  stage: "input" | "output";
  operation: string;
  input: unknown;
  ts: string;
}

export type ClientEvent =
  | { type: "meeting:start"; payload: { meetingId: string } }
  | {
      type: "audio:chunk";
      payload: { meetingId: string; chunkBase64: string; mimeType: string };
    }
  | {
      type: "transcript:inject";
      payload: { meetingId: string; text: string; speaker?: string };
    }
  | { type: "action:approve"; payload: { meetingId: string; actionId: string } }
  | { type: "action:deny"; payload: { meetingId: string; actionId: string } }
  | {
      type: "action:edit";
      payload: {
        meetingId: string;
        actionId: string;
        title: string;
        owner: string;
        dueDate?: string;
      };
    };

export type ServerEvent =
  | { type: "meeting:state"; payload: MeetingState }
  | { type: "transcript:update"; payload: TranscriptLine }
  | { type: "actions:update"; payload: ActionItem[] }
  | { type: "debug:event"; payload: DebugEvent }
  | {
      type: "action:status";
      payload: { actionId: string; status: ActionStatus; result?: string; error?: string };
    }
  | { type: "error"; payload: { message: string } };
