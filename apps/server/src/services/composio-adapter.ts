import { promisify } from "node:util";
import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mkdir } from "node:fs/promises";
import { env } from "../lib/env.js";
import { buildComposioOpenAIUserPrompt } from "../lib/openai-prompts.js";
import type { ComposioExecutionRequest } from "../types.js";

const execFileAsync = promisify(execFile);

interface ExecutionResult {
  ok: boolean;
  message: string;
}

export class ComposioAdapter {
  async diagnose(): Promise<ExecutionResult> {
    const mode = env.COMPOSIO_EXEC_MODE;

    if (mode === "python_agents") {
      return this.probePythonAgents();
    }

    if (mode === "http") {
      if (!env.COMPOSIO_API_KEY || !env.COMPOSIO_BASE_URL) {
        return {
          ok: false,
          message: "COMPOSIO_API_KEY and COMPOSIO_BASE_URL are required for http mode"
        };
      }

      try {
        const response = await fetch(env.COMPOSIO_BASE_URL, {
          method: "GET",
          headers: { Authorization: `Bearer ${env.COMPOSIO_API_KEY}` }
        });
        if (response.ok) {
          return { ok: true, message: `Composio HTTP reachable (${response.status})` };
        }
        return {
          ok: false,
          message: `Composio HTTP check failed (${response.status})`
        };
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown HTTP connectivity error";
        return { ok: false, message: `Composio HTTP check failed: ${message}` };
      }
    }

    return {
      ok: true,
      message: "Composio mode is mock; external execution disabled"
    };
  }

  async execute(request: ComposioExecutionRequest): Promise<ExecutionResult> {
    const mode = env.COMPOSIO_EXEC_MODE;

    if (mode === "python_agents") {
      return this.executeViaPythonAgents(request);
    }

    if (mode === "http" && env.COMPOSIO_API_KEY && env.COMPOSIO_BASE_URL) {
      return this.executeViaHttp(request);
    }

    if (env.COMPOSIO_API_KEY && env.COMPOSIO_BASE_URL) {
      return this.executeViaHttp(request);
    }

    await wait(900);
    return {
      ok: true,
      message: `Mock execution complete for objective: ${request.objective}`
    };
  }

  private async executeViaHttp(request: ComposioExecutionRequest): Promise<ExecutionResult> {
    if (!env.COMPOSIO_API_KEY || !env.COMPOSIO_BASE_URL) {
      return {
        ok: false,
        message: "COMPOSIO_API_KEY and COMPOSIO_BASE_URL are required for http mode"
      };
    }

    const response = await fetch(`${env.COMPOSIO_BASE_URL}/actions/execute`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.COMPOSIO_API_KEY}`
      },
      body: JSON.stringify(request)
    });

    if (!response.ok) {
      const body = await response.text();
      return {
        ok: false,
        message: `Composio execution failed (${response.status}): ${body.slice(0, 240)}`
      };
    }

    const data = (await response.json()) as { message?: string; id?: string };
    return {
      ok: true,
      message: data.message ?? `Execution accepted${data.id ? ` (run ${data.id})` : ""}`
    };
  }

  private async executeViaPythonAgents(request: ComposioExecutionRequest): Promise<ExecutionResult> {
    const prompt = buildComposioOpenAIUserPrompt(request);
    try {
      const parsed = await runPythonRunner({ prompt, request });
      return parsed.ok
        ? { ok: true, message: parsed.message || "Composio Python runner completed" }
        : { ok: false, message: parsed.message || "Composio Python runner failed" };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown execution error";
      return {
        ok: false,
        message: `Python Composio execution failed: ${message}`
      };
    }
  }

  private async probePythonAgents(): Promise<ExecutionResult> {
    try {
      const parsed = await runPythonRunner({ probe: true });
      return parsed.ok
        ? { ok: true, message: parsed.message || "Composio Python runner ready" }
        : { ok: false, message: parsed.message || "Composio Python runner not ready" };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown diagnostic error";
      return { ok: false, message: `Composio python check failed: ${message}` };
    }
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runPythonRunner(payload: Record<string, unknown>): Promise<ExecutionResult> {
  const currentFilePath = fileURLToPath(import.meta.url);
  const currentDir = path.dirname(currentFilePath);
  const scriptPath = path.resolve(currentDir, "../../scripts/composio_execute.py");
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

  const parsed = parseRunnerOutput(stdout);
  if (parsed) {
    return parsed;
  }

  return {
    ok: false,
    message: stderr?.trim() || "Could not parse Python Composio runner output"
  };
}

function parseRunnerOutput(stdout: string): ExecutionResult | null {
  const lines = stdout
    .trim()
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return null;
  }

  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      const parsed = JSON.parse(lines[i]) as ExecutionResult;
      if (typeof parsed.ok === "boolean" && typeof parsed.message === "string") {
        return parsed;
      }
    } catch {
      continue;
    }
  }

  return null;
}
