import { createHash } from "node:crypto";
import OpenAI from "openai";
import { env } from "../lib/env.js";
import { OPENAI_PROMPTS, buildOpenAIExtractionUserInput } from "../lib/openai-prompts.js";
import type { ActionItem, TranscriptLine } from "../types.js";

interface SuggestedAction {
  title: string;
  description: string;
  owner: string;
  dueDate?: string;
  confidence: number;
}

interface ExtractResult {
  actions: ActionItem[];
  modelOutput: unknown;
}

export class OpenAIAdapter {
  private client?: OpenAI;

  constructor() {
    if (env.OPENAI_API_KEY) {
      this.client = new OpenAI({ apiKey: env.OPENAI_API_KEY });
    }
  }

  async extractActionItems(
    transcriptWindow: TranscriptLine[],
    existing: ActionItem[]
  ): Promise<ExtractResult> {
    const finalLines = transcriptWindow.filter((line) => line.isFinal);
    const fallbackLine =
      finalLines.length === 0 ? transcriptWindow[transcriptWindow.length - 1] : undefined;
    const linesForExtraction =
      finalLines.length > 0
        ? finalLines
        : fallbackLine && fallbackLine.text.trim().length > 12
          ? [fallbackLine]
          : [];
    if (!linesForExtraction.length) {
      return { actions: [], modelOutput: { reason: "No extractable transcript lines" } };
    }

    if (!this.client) {
      return {
        actions: [],
        modelOutput: { reason: "OPENAI_API_KEY not configured for extraction" }
      };
    }

    const existingKeys = new Set(existing.map((item) => toActionKey(item.title, item.owner, item.dueDate)));
    const extraction = await this.extractWithResponses(linesForExtraction, existing);
    const suggestionPool = extraction.actions;

    const seenKeys = new Set<string>();
    const deduped = suggestionPool.filter((candidate) => {
      const key = toActionKey(candidate.title, candidate.owner, candidate.dueDate);
      if (!key || existingKeys.has(key) || seenKeys.has(key)) {
        return false;
      }
      seenKeys.add(key);
      return true;
    });

    const actions: ActionItem[] = deduped.map((candidate) => ({
      id: `act_${stableHash(toActionKey(candidate.title, candidate.owner, candidate.dueDate))}`,
      title: candidate.title,
      description: candidate.description,
      owner: candidate.owner || "Unassigned",
      dueDate: candidate.dueDate,
      confidence: candidate.confidence,
      status: "suggested" as const,
      sourceTranscriptIds: linesForExtraction.map((line) => line.id),
      updatedAt: new Date().toISOString()
    }));

    return { actions, modelOutput: extraction.modelOutput };
  }

  private async extractWithResponses(
    lines: TranscriptLine[],
    existing: ActionItem[]
  ): Promise<{ actions: SuggestedAction[]; modelOutput: unknown }> {
    const client = this.client;
    if (!client) {
      return {
        actions: [],
        modelOutput: { reason: "OPENAI_API_KEY not configured for extraction" }
      };
    }

    const compactTranscript = toCompactTranscript(lines);
    const existingContext = existing.slice(0, 12).map((item) => ({
      title: item.title,
      owner: item.owner,
      dueDate: item.dueDate,
      status: item.status
    }));

    const userInput = buildOpenAIExtractionUserInput(compactTranscript, existingContext);

    const schema = {
      type: "object",
      additionalProperties: false,
      required: ["actions"],
      properties: {
        actions: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["title", "description", "owner", "confidence"],
            properties: {
              title: { type: "string" },
              description: { type: "string" },
              owner: { type: "string" },
              dueDate: { type: ["string", "null"] },
              confidence: { type: "number", minimum: 0, maximum: 1 }
            }
          }
        }
      }
    };

    try {
      const response = await client.responses.create({
        model: env.OPENAI_MODEL,
        input: [
          {
            role: "system",
            content: OPENAI_PROMPTS.extractSystem
          },
          { role: "user", content: userInput }
        ],
        text: {
          format: {
            type: "json_schema",
            name: "action_items",
            schema,
            strict: false
          }
        }
      } as never);

      const raw = response.output_text;
      if (!raw) {
        return {
          actions: [],
          modelOutput: { raw: null, reason: "Empty model output" }
        };
      }

      const parsed = JSON.parse(raw) as { actions: SuggestedAction[] };
      return {
        actions: parsed.actions ?? [],
        modelOutput: {
          raw,
          parsed
        }
      };
    } catch (error) {
      return {
        actions: [],
        modelOutput: {
          error: error instanceof Error ? error.message : "Unknown extraction error"
        }
      };
    }
  }
}

function toCompactTranscript(lines: TranscriptLine[]): string {
  return lines
    .map((line) => `${line.speaker}: ${line.text.trim()}`)
    .filter((line) => line.length > 0)
    .join("\n");
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function toActionKey(title: string, owner?: string, dueDate?: string): string {
  const normalizedTitle = normalize(title).replace(/[^a-z0-9\s]/g, "");
  if (!normalizedTitle) {
    return "";
  }
  const normalizedOwner = normalize(owner || "unassigned").replace(/[^a-z0-9\s]/g, "");
  const normalizedDueDate = normalize(dueDate || "");
  return `${normalizedTitle}|${normalizedOwner}|${normalizedDueDate}`;
}

function stableHash(value: string): string {
  return createHash("sha1").update(value).digest("hex").slice(0, 16);
}
