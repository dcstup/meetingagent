import type { ActionItem, ComposioExecutionRequest } from "../types.js";

/**
 * Single source of truth for every OpenAI-facing prompt/snippet in the server.
 * Edit text here to change extraction/planning/execution behavior.
 */
export const OPENAI_PROMPTS = {
  extractSystem:
    "Extract concrete action items from full meeting context. Infer commitments from context and intent. Exclude brainstorming unless a clear deliverable commitment exists. Return only net-new actions not already in existing_actions.",

  composioExecutionSystem:
    "You are an execution agent with Composio meta tools. Decide and execute the right toolkit/tool for the objective. Use COMPOSIO_SEARCH_TOOLS to discover best tools when needed. Do not convert actionable objectives (email/chat/calendar/docs/issues) into generic todo items. Prefer direct execution of the requested outcome.",

  composioExecutionInferencePolicy:
    "Missing-data resolution policy: (1) First infer from the provided full meeting transcript context and approved action context. Reason from whole context, not fixed action phrases. (2) If still missing, look up data in Supabase using available Composio tools. Only after both fail should you ask for user clarification.",

  composioExecutionSupabasePolicy:
    "Supabase lookup policy: run read-oriented lookups to resolve required fields (for example recipient emails, identifiers, or prior decision details). Prefer exact matches and return the concrete record used for disambiguation in your final response.",

  composioExecutionAuthPolicy:
    "If authentication is missing for the selected toolkit, report exactly which toolkit must be connected and why, then stop without fabricating execution.",
} as const;

export function buildOpenAIExtractionUserInput(
  compactTranscript: string,
  existingActions: Array<
    Pick<ActionItem, "title" | "owner" | "dueDate" | "status">
  >,
): string {
  return JSON.stringify({
    transcript: compactTranscript,
    existing_actions: existingActions,
  });
}

export function buildComposioOpenAIUserPrompt(
  request: ComposioExecutionRequest,
): string {
  const actionPayload = JSON.stringify(request.action, null, 2);
  const transcriptPayload = JSON.stringify(request.transcriptContext, null, 2);
  const supabasePayload = JSON.stringify(request.supabaseContext, null, 2);

  return [
    OPENAI_PROMPTS.composioExecutionSystem,
    OPENAI_PROMPTS.composioExecutionInferencePolicy,
    OPENAI_PROMPTS.composioExecutionSupabasePolicy,
    OPENAI_PROMPTS.composioExecutionAuthPolicy,
    `Objective: ${request.objective}`,
    `Meeting ID: ${request.meeting.id}`,
    "Approved action context:",
    actionPayload,
    "Full meeting transcript context (first source for inference):",
    transcriptPayload,
    "Supabase lookup context (second source for missing fields):",
    supabasePayload,
  ].join("\n\n");
}
