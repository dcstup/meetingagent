const statusEl = document.getElementById('status');
const connectBtn = document.getElementById('connect-btn');
const connectedBadge = document.getElementById('connected-badge');
const apiUrl = YESCHEF_API_URL;

async function init() {
  // Ensure api_url is always set in storage for overlay.js
  await new Promise(r => chrome.storage.local.set({ api_url: apiUrl }, r));

  const data = await new Promise(r =>
    chrome.storage.local.get(['workspace_id', 'overlay_token', 'has_google'], r)
  );

  if (data.has_google) {
    connectedBadge.style.display = 'flex';
    connectBtn.textContent = 'Reconnect Google';
    statusEl.textContent = 'Ready for meetings';
    document.getElementById('join-section').style.display = 'block';
  } else if (data.workspace_id) {
    statusEl.textContent = 'Workspace ready — connect Google to start';
  }
}

connectBtn.addEventListener('click', async () => {
  connectBtn.disabled = true;
  statusEl.textContent = 'Connecting...';

  try {
    // Init workspace
    const initResp = await fetch(`${apiUrl}/api/workspace/init`, { method: 'POST' });
    if (!initResp.ok) throw new Error('Failed to init workspace');
    const workspace = await initResp.json();

    // Save config
    await new Promise(r => chrome.storage.local.set({
      workspace_id: workspace.workspace_id,
      overlay_token: workspace.overlay_token,
      api_url: apiUrl,
      has_google: workspace.has_google,
    }, r));

    if (workspace.has_google) {
      connectedBadge.style.display = 'flex';
      statusEl.textContent = 'Ready for meetings';
      connectBtn.textContent = 'Reconnect Google';
      connectBtn.disabled = false;
      return;
    }

    // Start OAuth
    const oauthResp = await fetch(`${apiUrl}/api/workspace/oauth/google`);
    if (!oauthResp.ok) throw new Error('Failed to start OAuth');
    const { auth_url } = await oauthResp.json();

    // Open OAuth in new tab
    chrome.tabs.create({ url: auth_url });

    statusEl.textContent = 'Complete Google sign-in in the new tab';
    connectBtn.disabled = false;

    // Poll for completion
    const pollInterval = setInterval(async () => {
      try {
        const checkResp = await fetch(`${apiUrl}/api/workspace/init`, { method: 'POST' });
        const checkData = await checkResp.json();
        if (checkData.has_google) {
          clearInterval(pollInterval);
          await new Promise(r => chrome.storage.local.set({ has_google: true }, r));
          connectedBadge.style.display = 'flex';
          statusEl.textContent = 'Ready for meetings';
          connectBtn.textContent = 'Reconnect Google';
        }
      } catch (e) {}
    }, 3000);

  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    connectBtn.disabled = false;
  }
});

// Join meeting
const joinBtn = document.getElementById('join-btn');
const meetUrlInput = document.getElementById('meet-url');
const joinStatus = document.getElementById('join-status');

joinBtn.addEventListener('click', async () => {
  const meetUrl = meetUrlInput.value.trim();
  if (!meetUrl || !meetUrl.includes('meet.google.com')) {
    joinStatus.textContent = 'Enter a valid Google Meet URL';
    return;
  }
  joinBtn.disabled = true;
  joinStatus.textContent = 'Sending bot...';
  try {
    const resp = await fetch(`${apiUrl}/api/meeting/join`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meet_url: meetUrl }),
    });
    if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
    const data = await resp.json();
    joinStatus.textContent = `Bot joining! (${data.bot_id?.slice(0, 8)}...)`;
    joinStatus.style.color = '#2E5E4E';
  } catch (err) {
    joinStatus.textContent = `Error: ${err.message}`;
    joinStatus.style.color = '#9B2335';
  }
  joinBtn.disabled = false;
});

// Also auto-detect Meet URL from current tab
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  if (tabs[0]?.url?.includes('meet.google.com')) {
    meetUrlInput.value = tabs[0].url.split('?')[0];
  }
});

init();
