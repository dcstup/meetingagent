import fastify from "fastify";
import cors from "@fastify/cors";
import websocket from "@fastify/websocket";
import { randomUUID } from "node:crypto";
import WebSocket, { type WebSocket as WSClient } from "ws";
import OpenAI from "openai";
import { env } from "./lib/env.js";
import { DeepgramAdapter } from "./services/deepgram-adapter.js";
import { MeetingStore } from "./services/meeting-store.js";
import { OpenAIAdapter } from "./services/openai-adapter.js";
import { ComposioAdapter } from "./services/composio-adapter.js";
import { ComposioConnectionsService } from "./services/composio-connections.js";
import { Orchestrator } from "./services/orchestrator.js";
import { StorageService } from "./services/storage.js";
import type { ClientEvent, ServerEvent } from "./types.js";

const app = fastify({ logger: true });

await app.register(cors, { origin: true });
await app.register(websocket);

const store = new MeetingStore();
const openai = new OpenAIAdapter();
const composio = new ComposioAdapter();
const composioConnections = new ComposioConnectionsService();
const storage = new StorageService();

const sockets = new Set<WSClient>();
const socketMeetings = new WeakMap<WSClient, string>();

const broadcaster = {
  publishMeeting(meetingId: string) {
    const payload = store.getState(meetingId);
    broadcastToMeeting(meetingId, { type: "meeting:state", payload });
  },
  publishActionStatus(
    meetingId: string,
    payload: {
      actionId: string;
      status: "suggested" | "approved" | "denied" | "executing" | "completed" | "failed";
      result?: string;
      error?: string;
    }
  ) {
    broadcastToMeeting(meetingId, { type: "action:status", payload });
  },
  publishDebug(
    meetingId: string,
    payload: {
      provider: "openai" | "composio";
      stage: "input" | "output";
      operation: string;
      input: unknown;
      ts: string;
    }
  ) {
    broadcastToMeeting(meetingId, { type: "debug:event", payload });
  }
};

const orchestrator = new Orchestrator(
  store,
  openai,
  composio,
  storage,
  broadcaster,
  app.log
);

const deepgram = new DeepgramAdapter(async ({ meetingId, id, speaker, text, isFinal }) => {
  const line = store.upsertTranscriptLine(meetingId, { id, speaker, text, isFinal });
  if (!line.text) {
    return;
  }

  broadcaster.publishMeeting(meetingId);
  broadcastToMeeting(meetingId, { type: "transcript:update", payload: line });

  if (isFinal) {
    orchestrator.queueExtraction(meetingId);
  }

  await storage.saveMeetingSnapshot(store.getState(meetingId));
});

app.get("/health", async () => {
  const mode = await storage.ping();
  return {
    ok: true,
    storage: mode,
    openai: Boolean(env.OPENAI_API_KEY),
    deepgram: Boolean(env.DEEPGRAM_API_KEY),
    composio: isComposioConfigured(),
    composioMode: env.COMPOSIO_EXEC_MODE
  };
});

app.get("/diagnostics", async () => {
  const checks: DiagnosticCheck[] = [];

  checks.push(await checkStorageConnectivity());
  checks.push(await checkOpenAIConnectivity());
  checks.push(await checkDeepgramConnectivity());
  checks.push(await checkComposioConnectivity());

  return {
    ok: checks.every((check) => check.status !== "fail"),
    generatedAt: new Date().toISOString(),
    summary: summarizeChecks(checks),
    environment: {
      port: env.PORT,
      openaiModel: env.OPENAI_MODEL,
      composioMode: env.COMPOSIO_EXEC_MODE,
      hasOpenAIKey: Boolean(env.OPENAI_API_KEY),
      hasDeepgramKey: Boolean(env.DEEPGRAM_API_KEY),
      hasComposioKey: Boolean(env.COMPOSIO_API_KEY),
      hasComposioBaseUrl: Boolean(env.COMPOSIO_BASE_URL),
      hasComposioExternalUserId: Boolean(env.COMPOSIO_EXTERNAL_USER_ID),
      hasSupabaseUrl: Boolean(env.SUPABASE_URL),
      hasSupabaseServiceRoleKey: Boolean(env.SUPABASE_SERVICE_ROLE_KEY)
    },
    checks
  };
});

app.get(
  "/composio/connections",
  async (
    request: import("fastify").FastifyRequest<{ Querystring: { userId?: string } }>,
    reply
  ) => {
    const userId = request.query.userId?.trim() || env.COMPOSIO_EXTERNAL_USER_ID?.trim() || "";
    if (!userId) {
      return reply.code(400).send({
        ok: false,
        message: "Missing userId query parameter (or set COMPOSIO_EXTERNAL_USER_ID)"
      });
    }

    const result = await composioConnections.listConnections(userId);
    if (!result.ok) {
      return reply.code(502).send(result);
    }

    return result;
  }
);

app.post(
  "/composio/authorize",
  async (
    request: import("fastify").FastifyRequest<{
      Body: { userId?: string; toolkit?: string; callbackUrl?: string };
    }>,
    reply
  ) => {
    const userId = request.body.userId?.trim() || env.COMPOSIO_EXTERNAL_USER_ID?.trim() || "";
    const toolkit = request.body.toolkit?.trim() || "";

    if (!userId) {
      return reply.code(400).send({
        ok: false,
        message: "Missing userId (or set COMPOSIO_EXTERNAL_USER_ID)"
      });
    }

    if (!toolkit) {
      return reply.code(400).send({
        ok: false,
        message: "Missing toolkit"
      });
    }

    const result = await composioConnections.authorizeToolkit(
      userId,
      toolkit,
      request.body.callbackUrl
    );
    if (!result.ok) {
      return reply.code(502).send(result);
    }

    return result;
  }
);

app.get("/ws", { websocket: true }, (connection: unknown) => {
  const socket = (
    typeof connection === "object" &&
    connection !== null &&
    "socket" in connection
      ? (connection as { socket: WSClient }).socket
      : connection
  ) as WSClient;
  sockets.add(socket);

  socket.on("message", async (raw: WebSocket.RawData) => {
    try {
      const incoming = JSON.parse(String(raw)) as ClientEvent;
      await handleClientEvent(socket, incoming);
    } catch (error) {
      send(socket, {
        type: "error",
        payload: {
          message:
            error instanceof Error ? error.message : "Failed to process websocket payload"
        }
      });
    }
  });

  socket.on("close", () => {
    sockets.delete(socket);
  });
});

async function handleClientEvent(
  socket: WSClient,
  event: ClientEvent
): Promise<void> {
  switch (event.type) {
    case "meeting:start": {
      const meetingId = event.payload.meetingId || randomUUID();
      socketMeetings.set(socket, meetingId);
      store.getOrCreate(meetingId);
      deepgram.ensureSession(meetingId);
      send(socket, { type: "meeting:state", payload: store.getState(meetingId) });
      return;
    }

    case "audio:chunk": {
      const { meetingId, chunkBase64 } = event.payload;
      const buffer = Buffer.from(chunkBase64, "base64");
      deepgram.sendAudioChunk(meetingId, buffer);
      return;
    }

    case "transcript:inject": {
      const { meetingId, text, speaker } = event.payload;
      const line = store.upsertTranscriptLine(meetingId, {
        speaker: speaker || "Speaker 1",
        text,
        isFinal: true
      });
      if (!line.text) {
        return;
      }
      broadcaster.publishMeeting(meetingId);
      broadcastToMeeting(meetingId, { type: "transcript:update", payload: line });
      orchestrator.queueExtraction(meetingId);
      await storage.saveMeetingSnapshot(store.getState(meetingId));
      return;
    }

    case "action:approve": {
      await orchestrator.approve(event.payload.meetingId, event.payload.actionId);
      return;
    }

    case "action:deny": {
      await orchestrator.deny(event.payload.meetingId, event.payload.actionId);
      return;
    }

    case "action:edit": {
      const { meetingId, actionId, title, owner, dueDate } = event.payload;
      await orchestrator.edit(meetingId, actionId, { title, owner, dueDate });
      return;
    }

    default:
      return;
  }
}

function broadcastToMeeting(meetingId: string, event: ServerEvent): void {
  for (const socket of sockets) {
    if (socket.readyState !== WebSocket.OPEN) {
      continue;
    }

    if (socketMeetings.get(socket) !== meetingId) {
      continue;
    }

    send(socket, event);
  }
}

function send(socket: WSClient, event: ServerEvent): void {
  if (socket.readyState !== WebSocket.OPEN) {
    return;
  }

  socket.send(JSON.stringify(event));
}

type DiagnosticStatus = "pass" | "fail" | "warn";

interface DiagnosticCheck {
  id: string;
  name: string;
  status: DiagnosticStatus;
  message: string;
  details?: Record<string, unknown>;
  nextSteps?: string[];
  durationMs?: number;
}

async function checkStorageConnectivity(): Promise<DiagnosticCheck> {
  const startedAt = Date.now();
  const status = await storage.diagnose();
  const { mode, hasSupabaseUrl, hasSupabaseServiceRoleKey, reason } = status;

  if (!hasSupabaseUrl || !hasSupabaseServiceRoleKey) {
    return {
      id: "storage",
      name: "Storage (Supabase or Memory)",
      status: "warn",
      message: "Using in-memory fallback storage",
      details: {
        mode,
        hasSupabaseUrl,
        hasSupabaseServiceRoleKey,
        reason: reason ?? null
      },
      nextSteps: [
        "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env",
        "Apply /supabase/schema.sql to your Supabase project",
        "Restart the server and re-run checks"
      ],
      durationMs: Date.now() - startedAt
    };
  }

  if (mode !== "supabase") {
    return {
      id: "storage",
      name: "Storage (Supabase or Memory)",
      status: "warn",
      message: "Supabase variables are set, but connection fell back to memory",
      details: {
        mode,
        hasSupabaseUrl,
        hasSupabaseServiceRoleKey,
        reason: reason ?? null
      },
      nextSteps: [
        "Verify SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY values",
        "Confirm outbound network access from the server",
        "Check Supabase project status and table permissions"
      ],
      durationMs: Date.now() - startedAt
    };
  }

  return {
    id: "storage",
    name: "Storage (Supabase or Memory)",
    status: "pass",
    message: "Supabase reachable",
    details: {
      mode,
      hasSupabaseUrl,
      hasSupabaseServiceRoleKey,
      reason: reason ?? null
    },
    durationMs: Date.now() - startedAt
  };
}

async function checkOpenAIConnectivity(): Promise<DiagnosticCheck> {
  const startedAt = Date.now();
  if (!env.OPENAI_API_KEY) {
    return {
      id: "openai",
      name: "OpenAI API",
      status: "fail",
      message: "OPENAI_API_KEY missing",
      nextSteps: ["Set OPENAI_API_KEY in .env and restart the server"],
      details: { model: env.OPENAI_MODEL, hasOpenAIKey: false },
      durationMs: Date.now() - startedAt
    };
  }

  const client = new OpenAI({ apiKey: env.OPENAI_API_KEY });

  try {
    await withTimeout(client.models.retrieve(env.OPENAI_MODEL), 9000);
    return {
      id: "openai",
      name: "OpenAI API",
      status: "pass",
      message: `Connected (model '${env.OPENAI_MODEL}' reachable)`,
      details: { model: env.OPENAI_MODEL, hasOpenAIKey: true },
      durationMs: Date.now() - startedAt
    };
  } catch {
    try {
      await withTimeout(client.models.list(), 9000);
      return {
        id: "openai",
        name: "OpenAI API",
        status: "warn",
        message: `API key works, but model '${env.OPENAI_MODEL}' is unavailable for this key`,
        details: { model: env.OPENAI_MODEL, hasOpenAIKey: true },
        nextSteps: [
          "Set OPENAI_MODEL to a model available to this API key",
          "Re-run checks and confirm model reachability"
        ],
        durationMs: Date.now() - startedAt
      };
    } catch (error) {
      return {
        id: "openai",
        name: "OpenAI API",
        status: "fail",
        message: `Connection failed: ${stringifyError(error)}`,
        details: { model: env.OPENAI_MODEL, hasOpenAIKey: true },
        nextSteps: [
          "Verify OPENAI_API_KEY is valid and has billing/access enabled",
          "Check network egress/firewall settings from the backend"
        ],
        durationMs: Date.now() - startedAt
      };
    }
  }
}

async function checkDeepgramConnectivity(): Promise<DiagnosticCheck> {
  const startedAt = Date.now();
  if (!env.DEEPGRAM_API_KEY) {
    return {
      id: "deepgram",
      name: "Deepgram API",
      status: "fail",
      message: "DEEPGRAM_API_KEY missing",
      nextSteps: ["Set DEEPGRAM_API_KEY in .env and restart the server"],
      details: { hasDeepgramKey: false },
      durationMs: Date.now() - startedAt
    };
  }

  try {
    const response = await withTimeout(
      fetch("https://api.deepgram.com/v1/projects", {
        method: "GET",
        headers: {
          Authorization: `Token ${env.DEEPGRAM_API_KEY}`
        }
      }),
      9000
    );

    if (!response.ok) {
      const body = await response.text();
      return {
        id: "deepgram",
        name: "Deepgram API",
        status: "fail",
        message: `Connection failed (${response.status}): ${body.slice(0, 140)}`,
        details: { hasDeepgramKey: true, statusCode: response.status },
        nextSteps: [
          "Verify DEEPGRAM_API_KEY is active and belongs to the expected project",
          "Check backend network access to api.deepgram.com"
        ],
        durationMs: Date.now() - startedAt
      };
    }

    const payload = (await response.json()) as { projects?: unknown[] };
    const count = Array.isArray(payload.projects) ? payload.projects.length : 0;

    return {
      id: "deepgram",
      name: "Deepgram API",
      status: "pass",
      message: `Connected (${count} projects visible)`,
      details: { hasDeepgramKey: true, projectCount: count },
      durationMs: Date.now() - startedAt
    };
  } catch (error) {
    return {
      id: "deepgram",
      name: "Deepgram API",
      status: "fail",
      message: `Connection failed: ${stringifyError(error)}`,
      details: { hasDeepgramKey: true },
      nextSteps: [
        "Check backend network access to api.deepgram.com",
        "Verify DEEPGRAM_API_KEY value and account status"
      ],
      durationMs: Date.now() - startedAt
    };
  }
}

async function checkComposioConnectivity(): Promise<DiagnosticCheck> {
  const startedAt = Date.now();
  const details = {
    mode: env.COMPOSIO_EXEC_MODE,
    hasComposioKey: Boolean(env.COMPOSIO_API_KEY),
    hasComposioBaseUrl: Boolean(env.COMPOSIO_BASE_URL),
    hasComposioExternalUserId: Boolean(env.COMPOSIO_EXTERNAL_USER_ID),
    pythonBin: env.COMPOSIO_PYTHON_BIN
  };

  if (env.COMPOSIO_EXEC_MODE === "mock") {
    return {
      id: "composio",
      name: "Composio",
      status: "warn",
      message: "COMPOSIO_EXEC_MODE=mock (external execution disabled)",
      details,
      nextSteps: [
        "Set COMPOSIO_EXEC_MODE=python_agents",
        "Set COMPOSIO_EXTERNAL_USER_ID (your Composio external user id)",
        "Install Python deps: python3 -m pip install -r apps/server/scripts/requirements.txt",
        "Re-run checks and confirm Composio status is pass"
      ],
      durationMs: Date.now() - startedAt
    };
  }

  if (env.COMPOSIO_EXEC_MODE === "python_agents" && !env.COMPOSIO_EXTERNAL_USER_ID) {
    return {
      id: "composio",
      name: "Composio",
      status: "fail",
      message: "COMPOSIO_EXTERNAL_USER_ID missing for python_agents mode",
      details,
      nextSteps: [
        "Set COMPOSIO_EXTERNAL_USER_ID in .env",
        "Restart the server and re-run checks"
      ],
      durationMs: Date.now() - startedAt
    };
  }

  if (env.COMPOSIO_EXEC_MODE === "python_agents" && !env.COMPOSIO_API_KEY) {
    return {
      id: "composio",
      name: "Composio",
      status: "fail",
      message: "COMPOSIO_API_KEY missing for python_agents mode",
      details,
      nextSteps: [
        "Set COMPOSIO_API_KEY in .env",
        "Restart the server and re-run checks"
      ],
      durationMs: Date.now() - startedAt
    };
  }

  if (env.COMPOSIO_EXEC_MODE === "http" && (!env.COMPOSIO_API_KEY || !env.COMPOSIO_BASE_URL)) {
    return {
      id: "composio",
      name: "Composio",
      status: "fail",
      message: "COMPOSIO_API_KEY and COMPOSIO_BASE_URL are required for http mode",
      details,
      nextSteps: [
        "Set COMPOSIO_API_KEY and COMPOSIO_BASE_URL in .env",
        "Restart the server and re-run checks"
      ],
      durationMs: Date.now() - startedAt
    };
  }

  const result = await withTimeout(composio.diagnose(), 20000).catch((error: unknown) => ({
    ok: false,
    message: stringifyError(error)
  }));

  return {
    id: "composio",
    name: "Composio",
    status: result.ok ? "pass" : "fail",
    message: result.message,
    details,
    nextSteps: result.ok
      ? undefined
      : [
          "Verify Composio account/app connections for this external user",
          "If using python_agents mode, verify Python deps are installed",
          "Check OPENAI_API_KEY is present for OpenAI agents provider"
        ],
    durationMs: Date.now() - startedAt
  };
}

function isComposioConfigured(): boolean {
  if (env.COMPOSIO_EXEC_MODE === "python_agents") {
    return Boolean(env.COMPOSIO_API_KEY && env.COMPOSIO_EXTERNAL_USER_ID);
  }

  if (env.COMPOSIO_EXEC_MODE === "http") {
    return Boolean(env.COMPOSIO_API_KEY && env.COMPOSIO_BASE_URL);
  }

  return true;
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms);
    promise
      .then((value) => resolve(value))
      .catch((error: unknown) => reject(error))
      .finally(() => clearTimeout(timeout));
  });
}

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

function summarizeChecks(checks: DiagnosticCheck[]): {
  pass: number;
  warn: number;
  fail: number;
} {
  const summary = { pass: 0, warn: 0, fail: 0 };
  for (const check of checks) {
    summary[check.status] += 1;
  }
  return summary;
}

try {
  await app.listen({ port: env.PORT, host: "0.0.0.0" });
  app.log.info({ port: env.PORT }, "Meeting Agent server started");
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
