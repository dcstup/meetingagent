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

export interface ActionItem {
  id: string;
  title: string;
  description: string;
  owner: string;
  dueDate?: string;
  confidence: number;
  status: ActionStatus;
  sourceTranscriptIds: string[];
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

export interface DebugEventPayload {
  provider: "openai" | "composio";
  stage: "input" | "output";
  operation: string;
  input: unknown;
  ts: string;
}

export type ServerEvent =
  | { type: "meeting:state"; payload: MeetingState }
  | { type: "transcript:update"; payload: TranscriptLine }
  | { type: "actions:update"; payload: ActionItem[] }
  | { type: "debug:event"; payload: DebugEventPayload }
  | {
      type: "action:status";
      payload: { actionId: string; status: ActionStatus; result?: string; error?: string };
    }
  | { type: "error"; payload: { message: string } };
