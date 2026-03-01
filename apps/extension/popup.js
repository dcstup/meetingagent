const statusEl = document.getElementById('status');
const connectBtn = document.getElementById('connect-btn');
const connectedBadge = document.getElementById('connected-badge');
const connectCalBtn = document.getElementById('connect-cal-btn');
const calConnectedBadge = document.getElementById('cal-connected-badge');
const connectLinearBtn = document.getElementById('connect-linear-btn');
const linearConnectedBadge = document.getElementById('linear-connected-badge');
const apiUrl = YESCHEF_API_URL;

async function init() {
  // Ensure api_url is always set in storage for overlay.js
  await new Promise(r => chrome.storage.local.set({ api_url: apiUrl }, r));

  const data = await new Promise(r =>
    chrome.storage.local.get(['workspace_id', 'overlay_token', 'has_google', 'has_google_calendar', 'has_linear'], r)
  );

  if (data.has_google) {
    connectedBadge.style.display = 'flex';
    connectBtn.textContent = 'Reconnect Google';
    statusEl.textContent = 'Ready for meetings';
    document.getElementById('join-section').style.display = 'block';

    if (data.has_google_calendar) {
      calConnectedBadge.style.display = 'flex';
      connectCalBtn.style.display = 'none';
    } else {
      connectCalBtn.style.display = 'block';
    }

    if (data.has_linear) {
      linearConnectedBadge.style.display = 'flex';
      connectLinearBtn.style.display = 'none';
    } else {
      connectLinearBtn.style.display = 'block';
    }
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
          await new Promise(r => chrome.storage.local.set({
            has_google: true,
            has_google_calendar: checkData.has_google_calendar || false,
          }, r));
          connectedBadge.style.display = 'flex';
          statusEl.textContent = 'Ready for meetings';
          connectBtn.textContent = 'Reconnect Google';
          document.getElementById('join-section').style.display = 'block';
          if (checkData.has_google_calendar) {
            calConnectedBadge.style.display = 'flex';
          } else {
            connectCalBtn.style.display = 'block';
          }
          if (checkData.has_linear) {
            linearConnectedBadge.style.display = 'flex';
          } else {
            connectLinearBtn.style.display = 'block';
          }
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

// Connect Google Calendar
connectCalBtn.addEventListener('click', async () => {
  connectCalBtn.disabled = true;
  statusEl.textContent = 'Starting Calendar connection...';

  try {
    const resp = await fetch(`${apiUrl}/api/workspace/oauth/google-calendar`, { method: 'POST' });
    if (!resp.ok) throw new Error('Failed to start Calendar OAuth');
    const { url } = await resp.json();

    chrome.tabs.create({ url });
    statusEl.textContent = 'Complete Calendar sign-in in the new tab';
    connectCalBtn.disabled = false;

    // Poll for completion
    const pollInterval = setInterval(async () => {
      try {
        const checkResp = await fetch(`${apiUrl}/api/workspace/init`, { method: 'POST' });
        const checkData = await checkResp.json();
        if (checkData.has_google_calendar) {
          clearInterval(pollInterval);
          await new Promise(r => chrome.storage.local.set({ has_google_calendar: true }, r));
          calConnectedBadge.style.display = 'flex';
          connectCalBtn.style.display = 'none';
          statusEl.textContent = 'Ready for meetings';
        }
      } catch (e) {}
    }, 3000);
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    connectCalBtn.disabled = false;
  }
});

// Connect Linear
connectLinearBtn.addEventListener('click', async () => {
  connectLinearBtn.disabled = true;
  statusEl.textContent = 'Starting Linear connection...';

  try {
    const resp = await fetch(`${apiUrl}/api/workspace/oauth/linear`, { method: 'POST' });
    if (!resp.ok) throw new Error('Failed to start Linear OAuth');
    const { url } = await resp.json();

    chrome.tabs.create({ url });
    statusEl.textContent = 'Complete Linear sign-in in the new tab';
    connectLinearBtn.disabled = false;

    const pollInterval = setInterval(async () => {
      try {
        const checkResp = await fetch(`${apiUrl}/api/workspace/init`, { method: 'POST' });
        const checkData = await checkResp.json();
        if (checkData.has_linear) {
          clearInterval(pollInterval);
          await new Promise(r => chrome.storage.local.set({ has_linear: true }, r));
          linearConnectedBadge.style.display = 'flex';
          connectLinearBtn.style.display = 'none';
          statusEl.textContent = 'Ready for meetings';
        }
      } catch (e) {}
    }, 3000);
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    connectLinearBtn.disabled = false;
  }
});

init();
