---
name: yeschef-extension
description: "YesChef Chrome MV3 extension architecture and message protocol"
trigger: when working on the Chrome extension, overlay, content scripts, WebSocket messaging, or Meet integration
---

# YesChef Chrome Extension — Full Architecture Reference

This document is a complete reference for subagents working on the YesChef Chrome MV3 extension. All message schemas, DOM selectors, WebSocket endpoints, and flow details are described here. You should NOT need to read source files to work on the extension.

## File Map

All files are in `/Users/tzhao/Projects/meetingagent/apps/extension/`.

| File | Role |
|------|------|
| `manifest.json` | MV3 manifest: permissions, content script registration, service worker, web-accessible resources |
| `config.js` | Single constant `YESCHEF_API_URL` — the only place to change the backend URL |
| `background.js` | Service worker: handles `GET_CONFIG` and `SAVE_CONFIG` messages from popup/content; reads/writes `chrome.storage.local` |
| `content.js` | Injected into `meet.google.com/*` at `document_idle`; injects the toggle button and overlay iframe; handles dragging; displays the artifact popup |
| `overlay.html` | The iframe UI loaded inside the overlay; references `config.js` and `overlay.js` |
| `overlay.js` | All overlay logic: WebSocket lifecycle, message handling, proposal cards, approve/dismiss REST calls, keepalive ping |
| `overlay.css` | CSS for the overlay; uses CSS custom properties; imports Google Fonts (Playfair Display + Inter) — note: the `@import` may be blocked by extension CSP in some contexts |
| `popup.html` | Extension popup UI (320px wide); shows connect buttons, workspace status, manual bot-join form |
| `popup.js` | Popup logic: workspace init, Google OAuth flow, Calendar OAuth flow, bot-join API call, auto-detects current tab's Meet URL |
| `icons/` | 16, 48, 128px PNGs |
| `logo.png` | Used in toggle button (24x24) and overlay header (28x28) |

## Manifest Details

```json
{
  "manifest_version": 3,
  "permissions": ["tabs", "activeTab", "storage"],
  "host_permissions": ["https://meet.google.com/*"],
  "background": { "service_worker": "background.js" },
  "content_scripts": [{
    "matches": ["https://meet.google.com/*"],
    "js": ["content.js"],
    "run_at": "document_idle"
  }],
  "web_accessible_resources": [{
    "resources": ["overlay.html", "overlay.css", "overlay.js", "config.js", "logo.png", "icons/*"],
    "matches": ["https://meet.google.com/*"]
  }]
}
```

The extension has NO `content_security_policy` key in the manifest — it relies on MV3 defaults. Inline scripts are not used anywhere; all JS is in separate files loaded via `<script src="...">`.

## Backend Configuration

`config.js` exports one constant used by both `popup.js` and `overlay.js`:

```js
const YESCHEF_API_URL = 'https://yeschef-api-production.up.railway.app';
```

This is the only place to change the backend URL. The value is also saved into `chrome.storage.local` under `api_url` by `popup.js` on every init, so `overlay.js` can read it even when `config.js` has not yet executed in that context. `overlay.js` reads `config.api_url || YESCHEF_API_URL` as a fallback.

## Storage Schema

All data lives in `chrome.storage.local`. Keys:

| Key | Type | Set by | Description |
|-----|------|--------|-------------|
| `workspace_id` | string (UUID) | popup.js | Workspace identifier returned by `/api/workspace/init` |
| `overlay_token` | string | popup.js | Auth token used for WebSocket authentication |
| `api_url` | string | popup.js | Backend base URL (no trailing slash) |
| `has_google` | boolean | popup.js | Whether Gmail OAuth is connected |
| `has_google_calendar` | boolean | popup.js | Whether Calendar OAuth is connected |

## Background Service Worker Message Protocol

`background.js` handles two message types from any extension context (popup or content script) via `chrome.runtime.onMessage`:

### GET_CONFIG

Request:
```json
{ "type": "GET_CONFIG" }
```

Response (via `sendResponse`):
```json
{
  "workspace_id": "<uuid>",
  "overlay_token": "<token>",
  "api_url": "https://..."
}
```

Fields may be undefined if not yet set.

### SAVE_CONFIG

Request:
```json
{
  "type": "SAVE_CONFIG",
  "workspace_id": "<uuid>",
  "overlay_token": "<token>",
  "api_url": "https://..."
}
```

Response:
```json
{ "ok": true }
```

Both handlers return `true` from the listener to keep the message channel open for async `sendResponse`.

### TOGGLE_OVERLAY

Sent BY the background worker TO the content script (not currently emitted by background.js, but content.js listens for it):

```json
{ "type": "TOGGLE_OVERLAY" }
```

Content script calls `toggle.click()` when received. This is a hook for future use.

## Content Script — Injection and DOM Strategy

`content.js` runs at `document_idle` on all `https://meet.google.com/*` URLs. It uses an IIFE and guards with `document.getElementById('yeschef-overlay-frame')` to prevent double injection.

No shadow DOM is used. Two elements are appended directly to `document.body`:

### Toggle Button (`#yeschef-toggle`)

```
position: fixed
top: 80px
right: 16px
width: 40px, height: 40px
border-radius: 50%
background: #082848
border: 2px solid #C6A559
z-index: 100000
```

Contains an `<img>` loaded via `chrome.runtime.getURL('logo.png')` at 24x24.

The toggle handles click vs. drag via a `mousedown` → `mousemove`/`mouseup` pattern. A drag threshold of 5px distinguishes click from drag. Dragging repositions both the toggle and iframe using `right`/`top` style properties.

### Overlay Iframe (`#yeschef-overlay-frame`)

```
position: fixed
top: 72px
right: 16px
width: 380px
height: calc(100vh - 88px)
border: none
z-index: 99999
border-radius: 8px
box-shadow: 0 4px 24px rgba(8,40,72,0.25)
display: none  (hidden by default)
```

`src` is set to `chrome.runtime.getURL('overlay.html')`. Iframe is shown/hidden via `style.display = 'block' / 'none'`.

### Artifact Popup (`#yeschef-artifact-popup`)

A full-page draggable/resizable popup injected into the Meet page (NOT inside the iframe, so it can span the full viewport). Created on first use, reused afterwards.

Structural IDs inside:
- `#yc-artifact-header` — drag handle
- `#yc-artifact-title` — title text node
- `#yc-artifact-frame` — inner iframe with `sandbox="allow-scripts"`
- `#yc-artifact-resize` — resize handle (bottom-right)
- `#yc-artifact-share` — opens artifact URL in new tab
- `#yc-artifact-close` — hides popup, clears frame src

Initial position: `top: 10%; left: 10%; width: 60vw; height: 70vh`. Min: 400x300.

## postMessage Protocol (Content Script ↔ Iframe)

`content.js` listens on `window.addEventListener('message', ...)` and validates origin:

```js
const extensionOrigin = new URL(chrome.runtime.getURL('')).origin;
if (event.origin !== extensionOrigin && event.origin !== window.location.origin) return;
```

### YESCHEF_CLOSE

Sent by overlay iframe to close itself:

```json
{ "type": "YESCHEF_CLOSE" }
```

Content script sets `visible = false` and `iframe.style.display = 'none'`.

### YESCHEF_SHOW_ARTIFACT

Sent by overlay iframe to open the artifact popup in the Meet page:

```json
{
  "type": "YESCHEF_SHOW_ARTIFACT",
  "url": "https://yeschef-api-production.up.railway.app/api/artifacts/<id>",
  "title": "Artifact title string"
}
```

Content script calls `showArtifactPopup(url, title)`.

Overlay sends this via:
```js
window.parent.postMessage({ type: 'YESCHEF_SHOW_ARTIFACT', url, title }, '*');
```

Note: target origin is `'*'` when sending from overlay to parent. Reception is still origin-validated on the content script side.

## WebSocket Connection (overlay.js)

### Endpoint Construction

```js
const wsUrl = config.api_url
  .replace(/\/+$/, '')
  .replace('https://', 'wss://')
  .replace('http://', 'ws://');
ws = new WebSocket(`${wsUrl}/ws?workspace=${config.workspace_id}`);
```

Example: `wss://yeschef-api-production.up.railway.app/ws?workspace=<uuid>`

### Connection Lifecycle

1. `overlay.js` calls `init()` on page load, with 3 retries at 1.5s intervals if `workspace_id` is not yet in storage.
2. If config is missing, shows "Not configured — open YesChef popup to connect".
3. `connectWebSocket()` is called. Any stale `ws` is closed with `ws.onclose = null` before opening a new one.
4. On `ws.onopen`: status = "Authenticating..."; sends `auth` message.
5. On `ws.onclose`: status = "Reconnecting..."; schedules reconnect with exponential backoff.
6. On `ws.onerror`: status = "Connection error".

### Reconnect Backoff

```js
let reconnectDelay = 3000;
const MAX_RECONNECT_DELAY = 30000;
// on close:
setTimeout(connectWebSocket, reconnectDelay);
reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
// on auth_ok:
reconnectDelay = 3000; // reset
```

### Keepalive Ping

```js
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }));
  }
}, 30000);
```

No response is expected for `ping`. It exists to keep the connection alive through proxies.

### Storage Change Listener

If `workspace_id`, `api_url`, or `overlay_token` changes in storage (e.g., user connects via popup while overlay is open), overlay.js re-calls `init()` only if the WebSocket is not already open:

```js
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if (changes.workspace_id || changes.api_url || changes.overlay_token) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      init();
    }
  }
});
```

## WebSocket Message Protocol (Server → Overlay)

All messages are JSON. Overlay parses with `JSON.parse(event.data)` and dispatches on `msg.type`.

### auth (Client → Server)

```json
{ "type": "auth", "token": "<overlay_token>" }
```

### auth_ok (Server → Client)

```json
{ "type": "auth_ok" }
```

Effect: status text = "Connected ✓", color = `#2E5E4E`. Reconnect delay reset to 3000ms.

### meeting_status (Server → Client)

```json
{
  "type": "meeting_status",
  "data": {
    "status": "active" | "bot_joining" | "ended",
    "title": "Meeting title string"
  }
}
```

Status text effects:
- `active` → `"Live: <title>"` (color reset to default)
- `bot_joining` → `"Bot joining..."` (color reset)
- `ended` → `"Meeting ended"` (color reset)

### utterance (Server → Client)

```json
{
  "type": "utterance",
  "data": {
    "speaker": "Speaker Name",
    "text": "Transcript text",
    "timestamp_ms": 1700000000000
  }
}
```

Rendered as `.yc-utterance` in `#transcript-feed`. Time displayed as `MM:SS` format. Auto-scrolls to bottom.

### proposal_created (Server → Client)

```json
{
  "type": "proposal_created",
  "data": {
    "id": "<uuid>",
    "action_type": "gmail_draft" | "html_artifact" | "generic_draft",
    "title": "Proposal title",
    "body": "Proposal body text",
    "recipient": "email@example.com",
    "gate_evidence_quote": "Relevant quote from transcript",
    "gate_missing_info": ["missing item 1", "missing item 2"],
    "gate_scores": {
      "clarity": 4.0,
      "specificity": 3.5,
      "actionability": 4.5,
      "readiness": 4.0
    },
    "gate_avg_score": 4.0
  }
}
```

Rendered as `.yc-proposal-card` with `id="proposal-<uuid>"` in `#proposals-list`. Includes Approve/Dismiss buttons. `gate_scores` shown in collapsible `<details>` element. `gate_missing_info` shown as `<ul>`.

### proposal_dropped (Server → Client)

Same shape as `proposal_created.data` but rendered as `.yc-dropped-card` in `#dropped-list`. The `#dropped-section` is unhidden on first drop.

```json
{
  "type": "proposal_dropped",
  "data": { /* same fields as proposal_created.data */ }
}
```

### proposal_updated (Server → Client)

```json
{
  "type": "proposal_updated",
  "data": {
    "id": "<uuid>",
    "status": "dismissed" | "approved" | "executing"
  }
}
```

If `status === "dismissed"`: card opacity set to 0.4, actions replaced with `"Dismissed"` text.

### execution_started (Server → Client)

```json
{
  "type": "execution_started",
  "data": {
    "proposal_id": "<uuid>"
  }
}
```

Actions area of the proposal card replaced with `"Executing..."` text (gold color).

### execution_completed (Server → Client)

```json
{
  "type": "execution_completed",
  "data": {
    "proposal_id": "<uuid>",
    "status": "success" | "failed",
    "error": "Error message if failed",
    "result": {
      "type": "gmail_draft" | "html_artifact" | "generic_draft",
      "artifact_url": "/api/artifacts/<id>",
      "title": "Artifact title",
      "body": "Draft body text for generic_draft"
    }
  }
}
```

On success, `"Yes, Chef!"` badge shown plus result-type-specific content:
- `gmail_draft` → link to `https://mail.google.com/mail/#drafts`
- `html_artifact` → "View Artifact" button; clicking sends `YESCHEF_SHOW_ARTIFACT` postMessage with `config.api_url + result.artifact_url`
- `generic_draft` → collapsible `<details>` showing draft body

On failure, `"Failed"` badge + error text.

## REST API Calls from Overlay

`overlay.js` makes direct HTTP calls to the backend (not via the service worker):

### Approve Proposal

```
POST <api_url>/api/proposals/<id>/approve
```

No request body. On error, buttons re-enabled and `_pendingActions` entry deleted. Uses a `Set` to prevent double-submission.

### Dismiss Proposal

```
POST <api_url>/api/proposals/<id>/dismiss
```

Same pattern as approve.

## REST API Calls from Popup

`popup.js` makes HTTP calls using `YESCHEF_API_URL` from `config.js`:

### Init / Check Workspace

```
POST <api_url>/api/workspace/init
```

Response:
```json
{
  "workspace_id": "<uuid>",
  "overlay_token": "<token>",
  "has_google": true | false,
  "has_google_calendar": true | false
}
```

Called on popup open and polled every 3 seconds during OAuth flow.

### Start Google OAuth

```
GET <api_url>/api/workspace/oauth/google
```

Response:
```json
{ "auth_url": "https://accounts.google.com/o/oauth2/..." }
```

Popup opens this URL in a new tab via `chrome.tabs.create({ url: auth_url })`.

### Start Calendar OAuth

```
POST <api_url>/api/workspace/oauth/google-calendar
```

Response:
```json
{ "url": "https://accounts.google.com/o/oauth2/..." }
```

### Join Meeting (Send Bot)

```
POST <api_url>/api/meeting/join
Content-Type: application/json

{ "meet_url": "https://meet.google.com/abc-defg-hij" }
```

Response:
```json
{ "bot_id": "<uuid>" }
```

Popup shows first 8 chars of `bot_id` as confirmation. Auto-detects current tab's Meet URL on popup open.

## Overlay HTML Structure

```html
<div class="yc-shell">
  <header class="yc-header">
    <img src="logo.png" class="yc-header-logo">   <!-- 28x28 -->
    <h1 class="yc-header-title">YesChef</h1>
    <span id="yc-status" class="yc-header-status">Connecting...</span>
    <button id="yc-close" class="yc-header-close">&times;</button>
  </header>
  <div class="yc-content">
    <section id="transcript-section">
      <h2 class="yc-section-title">Live Transcript</h2>
      <div id="transcript-feed" class="yc-transcript-feed">
        <!-- .yc-utterance elements appended here -->
      </div>
    </section>
    <section id="proposals-section">
      <h2 class="yc-section-title">Action Items</h2>
      <div id="proposals-list" class="yc-proposals-list">
        <!-- .yc-proposal-card elements appended here -->
      </div>
    </section>
    <div id="dropped-section" style="display:none">
      <div id="dropped-toggle">Dropped Items ▸</div>
      <div id="dropped-list" style="display:none">
        <!-- .yc-dropped-card elements appended here -->
      </div>
    </div>
  </div>
</div>
```

## CSS Design Tokens

```css
--yc-navy:    #082848   /* primary bg, header */
--yc-gold:    #C6A559   /* accent, speaker names, approve button */
--yc-pearl:   #F5F0EB   /* content area bg */
--yc-white:   #FAFAFA   /* card bg, text */
--yc-charcoal:#1A1A2E   /* body text */
--yc-muted:   #8A8A9A   /* secondary text, labels */
--yc-red:     #9B2335   /* error states */
--yc-green:   #2E5E4E   /* success states, connected badge */
```

## Extension State Machine

```
UNCONFIGURED
  → user opens popup → POST /api/workspace/init → storage written
  → if needs OAuth → opens tab → polls every 3s → storage updated

CONFIGURED (storage has workspace_id + overlay_token)
  → user navigates to meet.google.com
  → content.js runs → toggle + iframe injected
  → overlay.js init() → connectWebSocket()
  → ws.onopen → sends auth message
  → server sends auth_ok → status "Connected ✓"

CONNECTED
  → server sends meeting_status, utterance, proposal_created, etc.
  → user clicks Approve → POST /api/proposals/<id>/approve
  → server sends execution_started, execution_completed

DISCONNECTED
  → ws.onclose fires → reconnect with exponential backoff (3s → 6s → 12s → ... → 30s max)
```

## CSP Considerations

- No `content_security_policy` key in manifest.json — MV3 default applies.
- MV3 default CSP for extension pages: `script-src 'self'; object-src 'self'`. No inline scripts allowed.
- All JS is in external files (`config.js`, `overlay.js`, `popup.js`). No `eval`, no `new Function`, no inline handlers.
- The overlay makes fetch calls to `YESCHEF_API_URL` and WebSocket connections. These are allowed because extension pages are not subject to the Meet page's CSP; they run in their own origin (`chrome-extension://<id>`).
- `overlay.css` has `@import url('https://fonts.googleapis.com/...')` — this may fail silently due to CSP restrictions on extension pages. System font fallbacks (`-apple-system, sans-serif`) are defined on all elements, so the UI degrades gracefully.
- The artifact popup iframe uses `sandbox="allow-scripts"` (no `allow-same-origin`), restricting the artifact content.

## Common Gotchas

1. **Extension context invalidation**: After the extension is reloaded/updated, `chrome.runtime.id` becomes undefined in the old content script. `content.js` guards all `chrome.runtime` calls with `isContextValid()`. If you add new runtime calls in content.js, wrap them with this guard.

2. **Storage race on fresh install**: `overlay.js` retries `init()` up to 3 times with 1.5s delays if `workspace_id` is not in storage yet, because the popup may not have been opened yet.

3. **WebSocket URL scheme**: `config.api_url` starts with `https://`. The overlay replaces `https://` with `wss://` using string replace — not URL parsing. If `api_url` is ever `http://` (local dev), it correctly becomes `ws://`.

4. **Deduplication guard**: `_pendingActions` is a `Set` in overlay.js that prevents double-approve/dismiss if the user clicks rapidly. Buttons are also disabled immediately on click.

5. **No workspace_id in WebSocket URL is intentional security**: The `overlay_token` is sent via the first WebSocket message (not in the URL query param) to keep it out of server logs. The `workspace` query param is only the workspace UUID (not secret).

6. **Drag implementation note**: The toggle button and iframe are positioned with `right` (not `left`). During drag, `newRight = window.innerWidth - mouseX - 20`. After drop, the iframe's right is synced to the toggle's right.

## Loading the Extension (Development)

1. Open `chrome://extensions`
2. Enable Developer mode
3. "Load unpacked" → select `/Users/tzhao/Projects/meetingagent/apps/extension/`
4. No build step required — all files are plain JS/HTML/CSS
5. After any change to `background.js` or `manifest.json`: click the refresh icon on the extension card
6. After changes to `content.js`, `overlay.js`, `overlay.html`, `overlay.css`, or `popup.*`: reload the Meet tab (content script re-injects); for popup changes just close/reopen the popup
