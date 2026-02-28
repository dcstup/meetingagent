import { promisify } from "node:util";
import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mkdir } from "node:fs/promises";
import { env } from "../lib/env.js";

const execFileAsync = promisify(execFile);

export interface ComposioToolkitConnection {
  slug: string;
  name: string;
  isActive: boolean;
  connectedAccountId?: string;
  status?: string;
}

export interface ComposioConnectionsResult {
  ok: boolean;
  userId: string;
  toolkits: ComposioToolkitConnection[];
  message?: string;
}

export interface ComposioAuthorizeResult {
  ok: boolean;
  userId: string;
  toolkit: string;
  redirectUrl?: string;
  message?: string;
}

export class ComposioConnectionsService {
  async listConnections(userId: string): Promise<ComposioConnectionsResult> {
    const result = await runConnectionsScript({ mode: "status", user_id: userId });
    return {
      ok: Boolean(result.ok),
      userId,
      toolkits: Array.isArray(result.toolkits) ? (result.toolkits as ComposioToolkitConnection[]) : [],
      message: typeof result.message === "string" ? result.message : undefined
    };
  }

  async authorizeToolkit(
    userId: string,
    toolkit: string,
    callbackUrl?: string
  ): Promise<ComposioAuthorizeResult> {
    const result = await runConnectionsScript({
      mode: "authorize",
      user_id: userId,
      toolkit,
      callback_url: callbackUrl
    });

    return {
      ok: Boolean(result.ok),
      userId,
      toolkit,
      redirectUrl: typeof result.redirect_url === "string" ? result.redirect_url : undefined,
      message: typeof result.message === "string" ? result.message : undefined
    };
  }
}

async function runConnectionsScript(
  payload: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const currentFilePath = fileURLToPath(import.meta.url);
  const currentDir = path.dirname(currentFilePath);
  const scriptPath = path.resolve(currentDir, "../../scripts/composio_connections.py");
  const payloadText = JSON.stringify(payload);
  const composioCacheDir = path.resolve(process.cwd(), ".composio-cache");
  await mkdir(composioCacheDir, { recursive: true });

  const { stdout, stderr } = await execFileAsync(env.COMPOSIO_PYTHON_BIN, [scriptPath, payloadText], {
    env: {
      ...process.env,
      COMPOSIO_CACHE_DIR: process.env.COMPOSIO_CACHE_DIR ?? composioCacheDir
    },
    timeout: 120000,
    maxBuffer: 1024 * 1024
  });

  const parsed = parseJsonFromStdout(stdout);
  if (parsed) {
    return parsed;
  }

  return {
    ok: false,
    message: stderr?.trim() || "Could not parse Composio connections script output"
  };
}

function parseJsonFromStdout(stdout: string): Record<string, unknown> | null {
  const lines = stdout
    .trim()
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      const parsed = JSON.parse(lines[i]) as Record<string, unknown>;
      return parsed;
    } catch {
      continue;
    }
  }

  return null;
}
