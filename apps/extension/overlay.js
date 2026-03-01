// YesChef Overlay Controller
(function() {
  let ws = null;
  let config = {};
  let reconnectDelay = 3000;
  const MAX_RECONNECT_DELAY = 30000;
  const debugMode = typeof DEBUG_MODE !== 'undefined' && DEBUG_MODE;
  const statusEl = document.getElementById('yc-status');
  const transcriptFeed = document.getElementById('transcript-feed');
  const proposalsList = document.getElementById('proposals-list');

  // Debug counters
  const stats = { utterances: 0, extracted: 0, filtered: 0, gateDropped: 0, gatePassed: 0 };

  function updateDebugStats() {
    if (!debugMode) return;
    const el = document.getElementById('debug-stats');
    el.style.display = '';
    document.getElementById('debug-stats-content').innerHTML =
      `<span>Utterances: <b>${stats.utterances}</b></span>` +
      `<span>Passed filter: <b>${stats.extracted}</b></span>` +
      `<span>Filtered out: <b>${stats.filtered}</b></span>` +
      `<span>Gate passed: <b>${stats.gatePassed}</b></span>` +
      `<span>Gate dropped: <b>${stats.gateDropped}</b></span>`;
  }

  async function init(retries = 3) {
    // Get config from extension storage, with YESCHEF_API_URL as fallback
    config = await new Promise(resolve => {
      chrome.storage.local.get(['workspace_id', 'overlay_token', 'api_url'], resolve);
    });
    config.api_url = config.api_url || (typeof YESCHEF_API_URL !== 'undefined' ? YESCHEF_API_URL : '');

    if (!config.workspace_id && retries > 0) {
      // Storage may not be populated yet — retry after short delay
      statusEl.textContent = 'Loading config...';
      setTimeout(() => init(retries - 1), 1500);
      return;
    }

    if (!config.api_url || !config.workspace_id) {
      statusEl.textContent = 'Not configured — open YesChef popup to connect';
      console.warn('YesChef overlay: missing config', { api_url: !!config.api_url, workspace_id: !!config.workspace_id });
      return;
    }

    connectWebSocket();
  }

  function connectWebSocket() {
    // Close stale connection before reconnecting
    if (ws) {
      try { ws.onclose = null; ws.close(); } catch (e) {}
      ws = null;
    }
    const wsUrl = config.api_url.replace(/\/+$/, '').replace('https://', 'wss://').replace('http://', 'ws://');
    ws = new WebSocket(`${wsUrl}/ws?workspace=${config.workspace_id}`);

    ws.onopen = () => {
      statusEl.textContent = 'Authenticating...';
      ws.send(JSON.stringify({ type: 'auth', token: config.overlay_token }));
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        console.warn('YesChef: non-JSON WS message ignored', event.data);
        return;
      }
      handleMessage(msg);
    };

    ws.onclose = () => {
      statusEl.textContent = 'Reconnecting...';
      setTimeout(connectWebSocket, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    };

    ws.onerror = () => {
      statusEl.textContent = 'Connection error';
    };
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case 'auth_ok':
        statusEl.textContent = 'Connected \u2713';
        statusEl.style.color = '#2E5E4E';
        reconnectDelay = 3000; // Reset backoff on success
        break;

      case 'meeting_status':
        handleMeetingStatus(msg.data);
        break;

      case 'utterance':
        addUtterance(msg.data);
        stats.utterances++;
        updateDebugStats();
        break;

      case 'proposal_created':
        addProposal(msg.data);
        stats.gatePassed++;
        stats.extracted++;
        updateDebugStats();
        break;

      case 'proposal_dropped':
        addDroppedProposal(msg.data);
        stats.gateDropped++;
        updateDebugStats();
        break;

      case 'proposal_filtered':
        if (debugMode) addFilteredProposal(msg.data);
        stats.filtered++;
        updateDebugStats();
        break;

      case 'proposal_updated':
        updateProposal(msg.data);
        break;

      case 'execution_started':
        handleExecutionStarted(msg.data);
        break;

      case 'execution_completed':
        handleExecutionCompleted(msg.data);
        break;
    }
  }

  function handleMeetingStatus(data) {
    if (data.status === 'active') {
      statusEl.textContent = `Live: ${data.title || 'Meeting'}`;
      statusEl.style.color = '';
    } else if (data.status === 'bot_joining') {
      statusEl.textContent = 'Bot joining...';
      statusEl.style.color = '';
    } else if (data.status === 'ended') {
      statusEl.textContent = 'Meeting ended';
      statusEl.style.color = '';
    }
  }

  function addUtterance(data) {
    // Clear empty state
    const empty = transcriptFeed.querySelector('.yc-empty');
    if (empty) empty.remove();

    const el = document.createElement('div');
    el.className = 'yc-utterance';

    const timeStr = data.timestamp_ms ?
      new Date(data.timestamp_ms).toLocaleTimeString([], {minute:'2-digit', second:'2-digit'}) : '';

    el.innerHTML = `
      ${timeStr ? `<span class="yc-utterance-time">${timeStr}</span>` : ''}
      <span class="yc-utterance-speaker">${escapeHtml(data.speaker)}</span>
      <span class="yc-utterance-text">${escapeHtml(data.text)}</span>
    `;

    transcriptFeed.appendChild(el);
    transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
  }

  function addProposal(data) {
    // Clear empty state
    const empty = proposalsList.querySelector('.yc-empty');
    if (empty) empty.remove();

    const card = document.createElement('div');
    card.className = 'yc-proposal-card';
    card.id = `proposal-${data.id}`;

    card.innerHTML = `
      <div class="yc-proposal-type">${data.action_type === 'gmail_draft' ? '\u2709 Gmail Draft' : data.action_type === 'design_prototype' ? '\uD83C\uDFA8 Prototype' : data.action_type === 'calendar_action' ? '\uD83D\uDCC5 Calendar' : data.action_type === 'research_query' ? '\uD83D\uDD0D Research' : data.action_type === 'general_agent' ? '\uD83E\uDD16 Agent' : '\uD83D\uDCDD Task'}</div>
      <div class="yc-proposal-title">${escapeHtml(data.title)}</div>
      <div class="yc-proposal-body">${escapeHtml(data.body)}</div>
      ${data.recipient ? `<div class="yc-proposal-recipient">To: ${escapeHtml(data.recipient)}</div>` : ''}
      ${data.gate_evidence_quote ? `<blockquote class="yc-evidence-quote">${escapeHtml(data.gate_evidence_quote)}</blockquote>` : ''}
      ${data.gate_missing_info && data.gate_missing_info.length > 0 ? `<ul class="yc-missing-info">${data.gate_missing_info.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}
      ${data.gate_scores && Object.keys(data.gate_scores).length > 0 ? `<details class="yc-scores-debug"><summary>Scores &#9656;</summary><div class="yc-score-grid">${Object.entries(data.gate_scores).map(([k, v]) => `<span class="yc-score-label">${escapeHtml(k)}</span><span class="yc-score-value">${v}</span>`).join('')}</div>${data.gate_avg_score != null ? `<div class="yc-score-avg"><strong>avg: ${data.gate_avg_score}</strong></div>` : ''}</details>` : ''}
      <div class="yc-proposal-actions">
        <button class="yc-btn-approve" data-proposal-id="${data.id}">Approve</button>
        <button class="yc-btn-dismiss" data-proposal-id="${data.id}">Dismiss</button>
      </div>
    `;

    card.querySelector('.yc-btn-approve').addEventListener('click', () => doApprove(data.id));
    card.querySelector('.yc-btn-dismiss').addEventListener('click', () => doDismiss(data.id));

    proposalsList.appendChild(card);
  }

  function updateProposal(data) {
    const card = document.getElementById(`proposal-${data.id}`);
    if (card) {
      if (data.status === 'dismissed') {
        card.style.opacity = '0.4';
        const actions = card.querySelector('.yc-proposal-actions');
        if (actions) actions.innerHTML = '<span style="color:var(--yc-muted);font-size:12px">Dismissed</span>';
      }
    }
  }

  function handleExecutionStarted(data) {
    // The "Yes, Chef!" + "Executing..." state is already set immediately on approve click.
    // This WS event is a no-op to avoid overwriting the optimistic UI.
  }

  function handleExecutionCompleted(data) {
    const isSuccess = data.status === 'success';
    const result = data.result || {};

    const proposalCard = document.getElementById(`proposal-${data.proposal_id}`);
    if (!proposalCard) return;

    const actions = proposalCard.querySelector('.yc-proposal-actions');
    if (!actions) return;

    if (isSuccess) {
      let inlineContent = '';

      if (result.type === 'gmail_draft') {
        inlineContent = `<a class="yc-result-link" href="https://mail.google.com/mail/#drafts" target="_blank">Open in Gmail \u2192</a>`;
      } else if (result.type === 'design_prototype') {
        if (result.artifact_url) {
          inlineContent = `<button class="yc-btn-artifact" data-url="${escapeHtml(config.api_url + result.artifact_url)}" data-title="${escapeHtml(result.title || 'Artifact')}">View Artifact</button>`;
        } else {
          const fallback = result.result || result.body || 'Artifact generated (no preview available)';
          inlineContent = `<details class="yc-inline-draft"><summary>Show Artifact</summary><div class="yc-inline-draft-text">${escapeHtml(fallback)}</div></details>`;
        }
      } else if (result.type === 'general_agent') {
        if (result.artifact_url) {
          inlineContent = `<button class="yc-btn-artifact" data-url="${escapeHtml(config.api_url + result.artifact_url)}" data-title="${escapeHtml(result.title || 'Result')}">View Result</button>`;
        } else if (result.body) {
          inlineContent = `<details class="yc-inline-draft"><summary>Show Result</summary><div class="yc-inline-draft-text">${escapeHtml(result.body)}</div></details>`;
        } else if (result.result) {
          inlineContent = `<details class="yc-inline-draft"><summary>Show Result</summary><div class="yc-inline-draft-text">${escapeHtml(result.result)}</div></details>`;
        }
      } else if (result.type === 'research_query') {
        if (result.artifact_url) {
          inlineContent = `<button class="yc-btn-artifact" data-url="${escapeHtml(config.api_url + result.artifact_url)}" data-title="${escapeHtml(result.title || 'Research Report')}">View Report</button>`;
        } else {
          const fallback = result.result || result.body || 'Research complete (no report available)';
          inlineContent = `<details class="yc-inline-draft"><summary>Show Report</summary><div class="yc-inline-draft-text">${escapeHtml(fallback)}</div></details>`;
        }
      } else if (result.type === 'calendar_action') {
        const calText = result.body || result.result;
        if (calText) {
          inlineContent = `<details class="yc-inline-draft"><summary>Show Confirmation</summary><div class="yc-inline-draft-text">${escapeHtml(calText)}</div></details>`;
        }
      }

      // Fallback: any result with body/result text but no specific rendering
      if (!inlineContent) {
        const fallbackText = result.body || result.result;
        if (fallbackText) {
          inlineContent = `<details class="yc-inline-draft"><summary>Show Result</summary><div class="yc-inline-draft-text">${escapeHtml(fallbackText)}</div></details>`;
        }
      }

      actions.innerHTML = `
        <div class="yc-inline-result">
          <span class="yc-result-badge success" style="color:var(--yc-gold);background:rgba(198,165,89,0.15)">Yes, Chef!</span>
          ${inlineContent ? `<div class="yc-inline-result-content">${inlineContent}</div>` : ''}
        </div>
      `;

      // Bind artifact button if present
      const artifactBtn = actions.querySelector('.yc-btn-artifact');
      if (artifactBtn) {
        artifactBtn.addEventListener('click', () => {
          const url = artifactBtn.dataset.url;
          const title = artifactBtn.dataset.title;
          window.parent.postMessage({ type: 'YESCHEF_SHOW_ARTIFACT', url, title }, '*');
        });
      }
    } else {
      actions.innerHTML = `
        <div class="yc-inline-result">
          <span class="yc-result-badge failed">Failed</span>
          ${data.error ? `<div style="color:var(--yc-red);font-size:12px;margin-top:4px;padding-left:4px">${escapeHtml(data.error)}</div>` : ''}
        </div>
      `;
    }
  }

  function addDroppedProposal(data) {
    const section = document.getElementById('dropped-section');
    const list = document.getElementById('dropped-list');
    section.style.display = '';

    const card = document.createElement('div');
    card.className = 'yc-dropped-card';

    card.innerHTML = `
      <div class="yc-proposal-title">${escapeHtml(data.title)}</div>
      <div class="yc-proposal-body">${escapeHtml(data.body)}</div>
      ${data.gate_evidence_quote ? `<blockquote class="yc-evidence-quote">${escapeHtml(data.gate_evidence_quote)}</blockquote>` : ''}
      ${data.gate_missing_info && data.gate_missing_info.length > 0 ? `<ul class="yc-missing-info">${data.gate_missing_info.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}
      ${data.gate_scores ? `<div class="yc-score-grid">${Object.entries(data.gate_scores).map(([k, v]) => `<span class="yc-score-label">${escapeHtml(k)}</span><span class="yc-score-value">${v}</span>`).join('')}</div>${data.gate_avg_score != null ? `<div class="yc-score-avg"><strong>avg: ${data.gate_avg_score}</strong></div>` : ''}` : ''}
    `;

    list.appendChild(card);
  }

  function addFilteredProposal(data) {
    const section = document.getElementById('filtered-section');
    const list = document.getElementById('filtered-list');
    section.style.display = '';

    const card = document.createElement('div');
    card.className = 'yc-filtered-card';

    card.innerHTML = `
      <div class="yc-filter-reason">${escapeHtml(data.filter_reason)}</div>
      <div class="yc-proposal-title">${escapeHtml(data.title)}</div>
      <div class="yc-proposal-body">${escapeHtml(data.body)}</div>
      ${data.recipient ? `<div class="yc-proposal-recipient">To: ${escapeHtml(data.recipient)}</div>` : ''}
      <div class="yc-filter-meta">
        confidence: ${data.confidence ?? '?'} &middot; readiness: ${data.readiness ?? '?'} &middot; type: ${escapeHtml(data.action_type || '?')}
      </div>
    `;

    list.appendChild(card);
  }

  // Dropped section toggle
  document.getElementById('dropped-toggle').addEventListener('click', function() {
    const list = document.getElementById('dropped-list');
    const visible = list.style.display !== 'none';
    list.style.display = visible ? 'none' : '';
    this.textContent = visible ? 'Dropped by Gate \u25B8' : 'Dropped by Gate \u25BE';
  });

  // Filtered section toggle
  document.getElementById('filtered-toggle').addEventListener('click', function() {
    const list = document.getElementById('filtered-list');
    const visible = list.style.display !== 'none';
    list.style.display = visible ? 'none' : '';
    this.textContent = visible ? 'Filtered Out (Pre-Gate) \u25B8' : 'Filtered Out (Pre-Gate) \u25BE';
  });

  const _pendingActions = new Set();

  async function doApprove(id) {
    if (_pendingActions.has(id)) return;
    _pendingActions.add(id);
    const card = document.getElementById(`proposal-${id}`);
    // Immediately show "Yes, Chef!" + "Executing..." together, before any API response
    if (card) {
      const actions = card.querySelector('.yc-proposal-actions');
      if (actions) {
        actions.innerHTML = `
          <div class="yc-inline-result">
            <span class="yc-result-badge success" style="color:var(--yc-gold);background:rgba(198,165,89,0.15)">Yes, Chef!</span>
            <div class="yc-inline-result-content">
              <span style="color:var(--yc-gold);font-size:12px">Executing...</span>
            </div>
          </div>
        `;
      }
    }
    try {
      const resp = await fetch(`${config.api_url}/api/proposals/${id}/approve`, { method: 'POST' });
      if (!resp.ok) throw new Error('Approval failed');
      _pendingActions.delete(id);
    } catch (err) {
      console.error('Approve error:', err);
      // On error, restore buttons so the user can retry
      if (card) {
        const actions = card.querySelector('.yc-proposal-actions');
        if (actions) {
          actions.innerHTML = `
            <button class="yc-btn-approve" data-proposal-id="${id}">Approve</button>
            <button class="yc-btn-dismiss" data-proposal-id="${id}">Dismiss</button>
          `;
          actions.querySelector('.yc-btn-approve').addEventListener('click', () => doApprove(id));
          actions.querySelector('.yc-btn-dismiss').addEventListener('click', () => doDismiss(id));
        }
      }
      _pendingActions.delete(id);
    }
  }

  async function doDismiss(id) {
    if (_pendingActions.has(id)) return;
    _pendingActions.add(id);
    const card = document.getElementById(`proposal-${id}`);
    if (card) card.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      const resp = await fetch(`${config.api_url}/api/proposals/${id}/dismiss`, { method: 'POST' });
      if (!resp.ok) throw new Error('Dismiss failed');
      _pendingActions.delete(id);
    } catch (err) {
      console.error('Dismiss error:', err);
      if (card) card.querySelectorAll('button').forEach(b => b.disabled = false);
      _pendingActions.delete(id);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // Close button handler
  document.getElementById('yc-close').addEventListener('click', () => {
    window.parent.postMessage({ type: 'YESCHEF_CLOSE' }, '*');
  });

  // Keepalive ping
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, 30000);

  // Re-init when config is written to storage (e.g. after user connects via popup)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.workspace_id || changes.api_url || changes.overlay_token) {
      // Only re-init if we don't already have a working connection
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        init();
      }
    }
  });

  init();
})();
