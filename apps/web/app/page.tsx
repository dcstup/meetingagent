"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type {
  ActionItem,
  DebugEventPayload,
  MeetingState,
  ServerEvent,
  TranscriptLine
} from "../lib/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8080/ws";
const API_BASE_URL = toHttpBase(WS_URL);

type DiagnosticStatus = "idle" | "running" | "pass" | "warn" | "fail";

interface DiagnosticCheck {
  id: string;
  name: string;
  status: DiagnosticStatus;
  message: string;
  details?: Record<string, unknown>;
  nextSteps?: string[];
  durationMs?: number;
}

interface BackendDiagnosticsResponse {
  ok: boolean;
  generatedAt: string;
  summary?: {
    pass: number;
    warn: number;
    fail: number;
  };
  environment?: Record<string, unknown>;
  checks?: DiagnosticCheck[];
}

interface DebugFeedEntry {
  id: string;
  payload: DebugEventPayload;
}

const emptyMeeting: MeetingState = {
  id: "",
  createdAt: "",
  transcript: [],
  actions: []
};

export default function HomePage() {
  const [meetingId, setMeetingId] = useState("demo-meeting");
  const [meeting, setMeeting] = useState<MeetingState>(emptyMeeting);
  const [manualTranscript, setManualTranscript] = useState("");
  const [connection, setConnection] = useState<"offline" | "connecting" | "online">("offline");
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [diagnosticChecks, setDiagnosticChecks] = useState<DiagnosticCheck[]>([]);
  const [diagnosticLoading, setDiagnosticLoading] = useState(false);
  const [lastDiagnosticsAt, setLastDiagnosticsAt] = useState<string | null>(null);
  const [diagnosticSummary, setDiagnosticSummary] = useState<{
    pass: number;
    warn: number;
    fail: number;
  } | null>(null);
  const [diagnosticEnvironment, setDiagnosticEnvironment] = useState<Record<string, unknown>>({});
  const [debugFeed, setDebugFeed] = useState<DebugFeedEntry[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);

  const sortedActions = useMemo(
    () => [...meeting.actions].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1)),
    [meeting.actions]
  );
  const finalizedTranscript = useMemo(
    () => meeting.transcript.filter((line) => line.isFinal),
    [meeting.transcript]
  );
  const liveInterimLine = useMemo<TranscriptLine | null>(() => {
    for (let i = meeting.transcript.length - 1; i >= 0; i -= 1) {
      const candidate = meeting.transcript[i];
      if (!candidate.isFinal) {
        return candidate;
      }
    }
    return null;
  }, [meeting.transcript]);

  const websocketCheck = useMemo<DiagnosticCheck>(() => {
    if (connection === "online") {
      return {
        id: "websocket",
        name: "WebSocket",
        status: "pass",
        message: "Connected",
        details: { wsUrl: WS_URL, readyState: "open" }
      };
    }

    if (connection === "connecting") {
      return {
        id: "websocket",
        name: "WebSocket",
        status: "running",
        message: "Connecting...",
        details: { wsUrl: WS_URL, readyState: "connecting" }
      };
    }

    return {
      id: "websocket",
      name: "WebSocket",
      status: "warn",
      message: "Disconnected",
      details: { wsUrl: WS_URL, readyState: "closed" },
      nextSteps: [
        "Click Connect in the header",
        `Confirm backend is reachable at ${WS_URL}`
      ]
    };
  }, [connection]);

  useEffect(() => {
    runDiagnostics(false).catch(() => {
      // Error state is represented in checks.
    });

    return () => {
      teardownRecorder();
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  function connect() {
    setError(null);
    setConnection("connecting");

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.addEventListener("open", () => {
      setConnection("online");
      setDebugFeed([]);
      send({ type: "meeting:start", payload: { meetingId } });
    });

    ws.addEventListener("message", (message) => {
      try {
        const parsed = JSON.parse(String(message.data)) as ServerEvent;
        if (parsed.type === "meeting:state") {
          setMeeting(parsed.payload);
          return;
        }

        if (parsed.type === "debug:event") {
          setDebugFeed((previous) => [
            {
              id: `${parsed.payload.provider}-${parsed.payload.operation}-${parsed.payload.ts}-${previous.length}`,
              payload: parsed.payload
            },
            ...previous
          ]);
          return;
        }

        if (parsed.type === "error") {
          setError(parsed.payload.message);
        }
      } catch {
        setError("Received malformed payload from server");
      }
    });

    ws.addEventListener("close", () => {
      setConnection("offline");
      setRecording(false);
    });

    ws.addEventListener("error", () => {
      setError("WebSocket connection error");
      setConnection("offline");
    });
  }

  function disconnect() {
    wsRef.current?.close();
    wsRef.current = null;
    setConnection("offline");
    teardownRecorder();
    setRecording(false);
  }

  function send(payload: unknown) {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }
    wsRef.current.send(JSON.stringify(payload));
  }

  async function toggleRecording() {
    if (recording) {
      teardownRecorder();
      setRecording(false);
      return;
    }

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Connect to a meeting before recording");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      const mimeType = chooseRecorderMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;

      recorder.ondataavailable = async (event) => {
        if (!event.data || event.data.size === 0) {
          return;
        }
        const chunkBase64 = await blobToBase64(event.data);
        send({
          type: "audio:chunk",
          payload: {
            meetingId,
            chunkBase64,
            mimeType: event.data.type || mimeType || "audio/webm"
          }
        });
      };

      recorder.start(300);
      setRecording(true);
    } catch {
      setError("Microphone permission denied or unavailable");
      teardownRecorder();
      setRecording(false);
    }
  }

  function injectTranscript() {
    const text = manualTranscript.trim();
    if (!text) {
      return;
    }

    send({
      type: "transcript:inject",
      payload: {
        meetingId,
        text,
        speaker: "Speaker 1"
      }
    });

    setManualTranscript("");
  }

  function onApprove(actionId: string) {
    send({ type: "action:approve", payload: { meetingId, actionId } });
  }

  function onDeny(actionId: string) {
    send({ type: "action:deny", payload: { meetingId, actionId } });
  }

  function onEdit(action: ActionItem) {
    const title = window.prompt("Action title", action.title);
    if (!title) {
      return;
    }

    const owner = window.prompt("Owner", action.owner) || action.owner;
    const dueDate = window.prompt("Due date (ISO or empty)", action.dueDate || "") || undefined;

    send({
      type: "action:edit",
      payload: { meetingId, actionId: action.id, title, owner, dueDate }
    });
  }

  async function runDiagnostics(requestMicrophone: boolean) {
    setDiagnosticLoading(true);

    const checks: DiagnosticCheck[] = [];
    checks.push(await getMicrophoneCheck(requestMicrophone));

    try {
      const response = await fetch(`${API_BASE_URL}/diagnostics`);
      if (!response.ok) {
        checks.push({
          id: "backend-diagnostics",
          name: "Backend diagnostics",
          status: "fail",
          message: `Request failed (${response.status})`,
          details: { baseUrl: API_BASE_URL, statusCode: response.status },
          nextSteps: [
            `Confirm backend is running at ${API_BASE_URL}`,
            "Check CORS/network restrictions in the browser devtools"
          ]
        });
        setDiagnosticSummary(null);
        setDiagnosticEnvironment({});
      } else {
        const payload = (await response.json()) as BackendDiagnosticsResponse;
        if (Array.isArray(payload.checks)) {
          checks.push(...payload.checks);
          setDiagnosticSummary(payload.summary ?? null);
          setDiagnosticEnvironment(payload.environment ?? {});
        } else {
          checks.push({
            id: "backend-diagnostics",
            name: "Backend diagnostics",
            status: "fail",
            message: "Unexpected diagnostics payload",
            details: { baseUrl: API_BASE_URL },
            nextSteps: ["Inspect backend /diagnostics response payload"]
          });
          setDiagnosticSummary(null);
          setDiagnosticEnvironment({});
        }
      }
    } catch (diagError) {
      checks.push({
        id: "backend-diagnostics",
        name: "Backend diagnostics",
        status: "fail",
        message: `Cannot reach backend: ${stringifyError(diagError)}`,
        details: { baseUrl: API_BASE_URL },
        nextSteps: [
          `Start backend and confirm ${API_BASE_URL}/diagnostics is reachable`,
          "Check local firewall/VPN if connection is refused"
        ]
      });
      setDiagnosticSummary(null);
      setDiagnosticEnvironment({});
    }

    setDiagnosticChecks(checks);
    setLastDiagnosticsAt(new Date().toISOString());
    setDiagnosticLoading(false);
  }

  async function testMicrophoneAccess() {
    await runDiagnostics(true);
  }

  function teardownRecorder() {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    recorderRef.current = null;

    if (mediaStreamRef.current) {
      for (const track of mediaStreamRef.current.getTracks()) {
        track.stop();
      }
    }
    mediaStreamRef.current = null;
  }

  const mergedChecks = [websocketCheck, ...diagnosticChecks];
  const unresolvedChecks = mergedChecks.filter(
    (check) => check.status === "warn" || check.status === "fail"
  );
  const recommendedSteps = Array.from(
    new Set(
      unresolvedChecks
        .flatMap((check) => check.nextSteps ?? [])
        .map((step) => step.trim())
        .filter(Boolean)
    )
  );
  const openaiInputFeed = debugFeed.filter(
    (item) => item.payload.provider === "openai" && item.payload.stage === "input"
  );
  const openaiOutputFeed = debugFeed.filter(
    (item) => item.payload.provider === "openai" && item.payload.stage === "output"
  );
  const composioInputFeed = debugFeed.filter(
    (item) => item.payload.provider === "composio" && item.payload.stage === "input"
  );
  const composioOutputFeed = debugFeed.filter(
    (item) => item.payload.provider === "composio" && item.payload.stage === "output"
  );

  return (
    <main className="shell">
      <section className="panel header-panel">
        <h1>Meeting Agent</h1>
        <p>Real-time AI chief of staff: transcript to approved execution.</p>

        <div className="controls-row">
          <label>
            Meeting ID
            <input value={meetingId} onChange={(e) => setMeetingId(e.target.value)} />
          </label>

          {connection !== "online" ? (
            <button onClick={connect}>Connect</button>
          ) : (
            <button className="danger" onClick={disconnect}>
              Disconnect
            </button>
          )}

          <button
            className={recording ? "danger" : "secondary"}
            onClick={toggleRecording}
            disabled={connection !== "online"}
          >
            {recording ? "Stop mic" : "Start mic"}
          </button>

          <div className={`pill ${connection}`}>{connection}</div>
          <Link href="/settings" className="settings-link">
            Composio settings
          </Link>
        </div>

        {error && <p className="error">{error}</p>}
      </section>

      <section className="panel action-items-panel">
        <h2>Action Items</h2>
        <p className="muted">
          {meeting.lastExtractedAt
            ? `Last extracted ${new Date(meeting.lastExtractedAt).toLocaleTimeString()}`
            : "Awaiting extracted actions"}
        </p>

        <div className="action-strip">
          {sortedActions.length === 0 ? (
            <div className="action-card empty">
              <p className="muted">No actions yet.</p>
            </div>
          ) : (
            sortedActions.map((action) => (
              <div key={action.id} className="action-card">
                <div className="action-head">
                  <h3>{action.title}</h3>
                  <span className={`status ${action.status}`}>{action.status}</span>
                </div>

                <div className="action-content">
                  <p>{action.description}</p>

                  <div className="meta-row">
                    <span>Owner: {action.owner}</span>
                    <span>Confidence: {Math.round(action.confidence * 100)}%</span>
                    <span>{action.dueDate ? `Due ${action.dueDate}` : "No due date"}</span>
                  </div>

                  {action.executionResult && <p className="result">{action.executionResult}</p>}
                  {action.error && <p className="error">{action.error}</p>}
                </div>

                <div className="controls-row">
                  <button onClick={() => onApprove(action.id)} disabled={action.status !== "suggested"}>
                    Approve
                  </button>
                  <button
                    className="secondary"
                    onClick={() => onEdit(action)}
                    disabled={action.status === "completed" || action.status === "executing"}
                  >
                    Edit
                  </button>
                  <button
                    className="danger"
                    onClick={() => onDeny(action.id)}
                    disabled={action.status !== "suggested" && action.status !== "approved"}
                  >
                    Deny
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="workspace">
        <article className="panel transcript-panel">
          <h2>Transcript</h2>
          <div className="transcript-list">
            {finalizedTranscript.length === 0 && !liveInterimLine ? (
              <p className="muted">No transcript yet. Use mic or inject text below.</p>
            ) : (
              <>
                {liveInterimLine && (
                  <div key={`${liveInterimLine.id}-live`} className="transcript-line interim">
                    <span className="speaker">{liveInterimLine.speaker} (live)</span>
                    <span>{liveInterimLine.text}</span>
                  </div>
                )}
                {finalizedTranscript
                  .slice()
                  .reverse()
                  .map((line) => (
                    <div key={line.id} className="transcript-line">
                      <span className="speaker">{line.speaker}</span>
                      <span>{line.text}</span>
                    </div>
                  ))}
              </>
            )}
          </div>

          <div className="inject-row">
            <input
              placeholder="Inject transcript line for demo"
              value={manualTranscript}
              onChange={(e) => setManualTranscript(e.target.value)}
            />
            <button className="secondary" onClick={injectTranscript}>
              Inject
            </button>
          </div>
        </article>

        <aside className="panel diagnostics-panel">
          <h2>System Checks (Temp)</h2>
          <p className="muted">Verifies keys/services plus browser microphone access.</p>

          <div className="controls-row">
            <button className="secondary" onClick={() => runDiagnostics(false)} disabled={diagnosticLoading}>
              {diagnosticLoading ? "Running..." : "Run checks"}
            </button>
            <button className="secondary" onClick={testMicrophoneAccess} disabled={diagnosticLoading}>
              Test mic access
            </button>
          </div>

          {lastDiagnosticsAt && (
            <p className="muted small-text">
              Last run: {new Date(lastDiagnosticsAt).toLocaleTimeString()}
            </p>
          )}

          {diagnosticSummary && (
            <div className="diagnostic-item">
              <div className="diagnostic-head">
                <span>Backend Summary</span>
              </div>
              <p className="muted small-text">
                pass {diagnosticSummary.pass} | warn {diagnosticSummary.warn} | fail {diagnosticSummary.fail}
              </p>
            </div>
          )}

          {recommendedSteps.length > 0 && (
            <div className="diagnostic-item">
              <div className="diagnostic-head">
                <span>How To Clear Warnings</span>
              </div>
              <ol className="step-list">
                {recommendedSteps.map((step) => (
                  <li key={step} className="small-text">
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          )}

          <div className="diagnostic-list">
            {mergedChecks.map((check) => (
              <div key={check.id} className="diagnostic-item">
                <div className="diagnostic-head">
                  <span>{check.name}</span>
                  <span className={`diag-chip ${check.status}`}>{check.status}</span>
                </div>
                <p className="muted small-text">{check.message}</p>
                {typeof check.durationMs === "number" && (
                  <p className="muted tiny-text">duration: {check.durationMs}ms</p>
                )}
                {check.nextSteps && check.nextSteps.length > 0 && (
                  <ol className="step-list">
                    {check.nextSteps.map((step) => (
                      <li key={step} className="small-text">
                        {step}
                      </li>
                    ))}
                  </ol>
                )}
                {check.details && (
                  <details className="debug-details">
                    <summary>debug details</summary>
                    <pre className="debug-pre">{JSON.stringify(check.details, null, 2)}</pre>
                  </details>
                )}
              </div>
            ))}
          </div>

          <div className="diagnostic-item">
            <div className="diagnostic-head">
              <span>Live OpenAI Input Payloads</span>
              <span className="muted small-text">{openaiInputFeed.length}</span>
            </div>
            {openaiInputFeed.length === 0 ? (
              <p className="muted small-text">Waiting for OpenAI-bound requests...</p>
            ) : (
              <div className="api-debug-list">
                {openaiInputFeed.map((entry) => (
                  <details key={entry.id} className="debug-details" open>
                    <summary>
                      {entry.payload.operation} • {new Date(entry.payload.ts).toLocaleTimeString()}
                    </summary>
                    <pre className="debug-pre">{JSON.stringify(entry.payload.input, null, 2)}</pre>
                  </details>
                ))}
              </div>
            )}
          </div>

          <div className="diagnostic-item">
            <div className="diagnostic-head">
              <span>Live OpenAI Output Payloads</span>
              <span className="muted small-text">{openaiOutputFeed.length}</span>
            </div>
            {openaiOutputFeed.length === 0 ? (
              <p className="muted small-text">Waiting for OpenAI responses...</p>
            ) : (
              <div className="api-debug-list">
                {openaiOutputFeed.map((entry) => (
                  <details key={entry.id} className="debug-details" open>
                    <summary>
                      {entry.payload.operation} • {new Date(entry.payload.ts).toLocaleTimeString()}
                    </summary>
                    <pre className="debug-pre">{JSON.stringify(entry.payload.input, null, 2)}</pre>
                  </details>
                ))}
              </div>
            )}
          </div>

          <div className="diagnostic-item">
            <div className="diagnostic-head">
              <span>Live Composio Input Payloads</span>
              <span className="muted small-text">{composioInputFeed.length}</span>
            </div>
            {composioInputFeed.length === 0 ? (
              <p className="muted small-text">Waiting for Composio-bound requests...</p>
            ) : (
              <div className="api-debug-list">
                {composioInputFeed.map((entry) => (
                  <details key={entry.id} className="debug-details" open>
                    <summary>
                      {entry.payload.operation} • {new Date(entry.payload.ts).toLocaleTimeString()}
                    </summary>
                    <pre className="debug-pre">{JSON.stringify(entry.payload.input, null, 2)}</pre>
                  </details>
                ))}
              </div>
            )}
          </div>

          <div className="diagnostic-item">
            <div className="diagnostic-head">
              <span>Live Composio Output Payloads</span>
              <span className="muted small-text">{composioOutputFeed.length}</span>
            </div>
            {composioOutputFeed.length === 0 ? (
              <p className="muted small-text">Waiting for Composio responses...</p>
            ) : (
              <div className="api-debug-list">
                {composioOutputFeed.map((entry) => (
                  <details key={entry.id} className="debug-details" open>
                    <summary>
                      {entry.payload.operation} • {new Date(entry.payload.ts).toLocaleTimeString()}
                    </summary>
                    <pre className="debug-pre">{JSON.stringify(entry.payload.input, null, 2)}</pre>
                  </details>
                ))}
              </div>
            )}
          </div>

          {Object.keys(diagnosticEnvironment).length > 0 && (
            <div className="diagnostic-item">
              <div className="diagnostic-head">
                <span>Server Debug Snapshot</span>
              </div>
              <pre className="debug-pre">{JSON.stringify(diagnosticEnvironment, null, 2)}</pre>
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}

async function getMicrophoneCheck(requestAccess: boolean): Promise<DiagnosticCheck> {
  if (typeof navigator === "undefined") {
    return {
      id: "microphone",
      name: "Microphone",
      status: "warn",
      message: "Navigator unavailable",
      details: { hasNavigator: false }
    };
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    return {
      id: "microphone",
      name: "Microphone",
      status: "fail",
      message: "Browser does not support getUserMedia",
      details: { hasMediaDevices: Boolean(navigator.mediaDevices) },
      nextSteps: ["Use Chrome/Edge/Safari with microphone permissions enabled"]
    };
  }

  if (requestAccess) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      return {
        id: "microphone",
        name: "Microphone",
        status: "pass",
        message: "Microphone permission granted and stream opened",
        details: { requestedAccess: true, streamOpened: true }
      };
    } catch (error) {
      return {
        id: "microphone",
        name: "Microphone",
        status: "fail",
        message: `Microphone access failed: ${stringifyError(error)}`,
        details: { requestedAccess: true, streamOpened: false },
        nextSteps: [
          "Allow microphone access in browser site permissions",
          "Confirm no OS-level microphone block is enabled",
          "Re-run 'Test mic access'"
        ]
      };
    }
  }

  if (!navigator.permissions?.query) {
    return {
      id: "microphone",
      name: "Microphone",
      status: "warn",
      message: "Permissions API unavailable. Use 'Test mic access'",
      details: { hasPermissionsApi: false }
    };
  }

  try {
    const permissionStatus = await navigator.permissions.query({ name: "microphone" as PermissionName });
    if (permissionStatus.state === "granted") {
      return {
        id: "microphone",
        name: "Microphone",
        status: "pass",
        message: "Permission granted",
        details: { permissionState: permissionStatus.state, requestedAccess: false }
      };
    }

    if (permissionStatus.state === "prompt") {
      return {
        id: "microphone",
        name: "Microphone",
        status: "warn",
        message: "Permission not decided yet",
        details: { permissionState: permissionStatus.state, requestedAccess: false },
        nextSteps: ["Click 'Test mic access' to trigger permission prompt"]
      };
    }

    return {
      id: "microphone",
      name: "Microphone",
      status: "fail",
      message: "Permission denied",
      details: { permissionState: permissionStatus.state, requestedAccess: false },
      nextSteps: [
        "Open browser site settings and allow microphone",
        "Re-run 'Test mic access'"
      ]
    };
  } catch {
    return {
      id: "microphone",
      name: "Microphone",
      status: "warn",
      message: "Could not inspect permission state. Use 'Test mic access'",
      details: { requestedAccess: false },
      nextSteps: ["Click 'Test mic access' to verify live microphone usage"]
    };
  }
}

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

function toHttpBase(wsUrl: string): string {
  if (wsUrl.startsWith("wss://")) {
    return wsUrl.replace("wss://", "https://").replace(/\/ws$/, "");
  }

  if (wsUrl.startsWith("ws://")) {
    return wsUrl.replace("ws://", "http://").replace(/\/ws$/, "");
  }

  return "http://localhost:8080";
}

function chooseRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") {
    return undefined;
  }

  const preferred = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus"
  ];

  for (const candidate of preferred) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }

  return undefined;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Could not encode audio chunk"));
        return;
      }
      const content = result.split(",")[1];
      resolve(content ?? "");
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}
