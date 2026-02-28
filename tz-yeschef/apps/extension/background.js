// YesChef Service Worker
chrome.runtime.onInstalled.addListener(() => {
  console.log('YesChef installed');
});

// Listen for messages from popup/content scripts
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'GET_CONFIG') {
    chrome.storage.local.get(['workspace_id', 'overlay_token', 'api_url'], (data) => {
      sendResponse(data);
    });
    return true;
  }

  if (msg.type === 'SAVE_CONFIG') {
    chrome.storage.local.set({
      workspace_id: msg.workspace_id,
      overlay_token: msg.overlay_token,
      api_url: msg.api_url,
    }, () => {
      sendResponse({ ok: true });
    });
    return true;
  }
});
