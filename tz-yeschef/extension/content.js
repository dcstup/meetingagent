// YesChef Content Script — injects overlay into Google Meet
(function() {
  if (document.getElementById('yeschef-overlay-frame')) return;

  // Toggle button
  const toggle = document.createElement('button');
  toggle.id = 'yeschef-toggle';
  toggle.innerHTML = '<img src="' + chrome.runtime.getURL('logo.png') + '" style="width:24px;height:24px;border-radius:4px">';
  toggle.style.cssText = `
    position: fixed;
    top: 80px;
    right: 16px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: #082848;
    border: 2px solid #C6A559;
    cursor: pointer;
    z-index: 100000;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(8,40,72,0.3);
    transition: transform 0.2s, right 0.3s ease;
    padding: 0;
  `;

  // Overlay iframe
  const iframe = document.createElement('iframe');
  iframe.id = 'yeschef-overlay-frame';
  iframe.src = chrome.runtime.getURL('overlay.html');
  iframe.style.cssText = `
    position: fixed;
    top: 72px;
    right: 16px;
    width: 380px;
    height: calc(100vh - 88px);
    border: none;
    z-index: 99999;
    border-radius: 8px;
    box-shadow: 0 4px 24px rgba(8, 40, 72, 0.25);
    transition: transform 0.3s ease, opacity 0.3s ease;
    display: none;
  `;

  let visible = false;
  let isDragging = false;

  toggle.addEventListener('mousedown', (e) => {
    const startX = e.clientX, startY = e.clientY;
    let moved = false;

    const onMouseMove = (me) => {
      const dx = me.clientX - startX;
      const dy = me.clientY - startY;
      if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
        moved = true;
        isDragging = true;

        const newRight = Math.max(0, window.innerWidth - me.clientX - 20);
        const newTop = Math.max(0, me.clientY - 20);

        toggle.style.right = newRight + 'px';
        toggle.style.top = newTop + 'px';

        if (visible) {
          iframe.style.right = newRight + 'px';
          iframe.style.top = newTop + 'px';
        }
      }
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);

      if (!moved) {
        // It was a click, not a drag — toggle visibility
        visible = !visible;
        iframe.style.display = visible ? 'block' : 'none';
        if (visible) {
          iframe.style.right = (parseInt(toggle.style.right) || 16) + 'px';
          iframe.style.top = toggle.style.top;
        }
      }
      isDragging = false;
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    e.preventDefault();
  });

  document.body.appendChild(iframe);
  document.body.appendChild(toggle);

  // Guard against extension context invalidation (after extension reload/update)
  function isContextValid() {
    try { return !!chrome.runtime?.id; } catch { return false; }
  }

  // Listen for toggle from background
  chrome.runtime.onMessage.addListener((msg) => {
    if (!isContextValid()) return;
    if (msg.type === 'TOGGLE_OVERLAY') {
      toggle.click();
    }
  });

  // Listen for messages from overlay iframe (verify origin)
  window.addEventListener('message', (event) => {
    if (!isContextValid()) return;
    const extensionOrigin = new URL(chrome.runtime.getURL('')).origin;
    if (event.origin !== extensionOrigin && event.origin !== window.location.origin) return;
    if (event.data?.type === 'YESCHEF_CLOSE') {
      visible = false;
      iframe.style.display = 'none';
    }
    if (event.data?.type === 'YESCHEF_SHOW_ARTIFACT') {
      showArtifactPopup(event.data.url, event.data.title);
    }
  });

  // Artifact popup (injected into Meet page, not inside iframe, for full viewport dragging)
  function showArtifactPopup(url, title) {
    let popup = document.getElementById('yeschef-artifact-popup');
    if (!popup) {
      popup = document.createElement('div');
      popup.id = 'yeschef-artifact-popup';
      popup.style.cssText = `
        position: fixed; top: 10%; left: 10%; width: 60vw; height: 70vh;
        min-width: 400px; min-height: 300px; background: #fff;
        border-radius: 8px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        z-index: 200000; display: flex; flex-direction: column; overflow: hidden;
      `;
      popup.innerHTML = `
        <div id="yc-artifact-header" style="
          display:flex; align-items:center; justify-content:space-between;
          padding:10px 16px; background:#082848; color:#C6A559; cursor:grab;
          font-family:-apple-system,sans-serif; font-size:14px; font-weight:600; user-select:none;
        ">
          <span id="yc-artifact-title"></span>
          <div style="display:flex;gap:8px;align-items:center">
            <button id="yc-artifact-share" style="
              background:#C6A559;color:#082848;border:none;border-radius:4px;
              padding:4px 12px;font-size:12px;font-weight:600;cursor:pointer;
            ">Share</button>
            <button id="yc-artifact-close" style="
              background:none;border:none;color:#8A8A9A;font-size:20px;cursor:pointer;
            ">&times;</button>
          </div>
        </div>
        <iframe id="yc-artifact-frame" style="flex:1;border:none;width:100%;height:100%"
          sandbox="allow-scripts"></iframe>
        <div id="yc-artifact-resize" style="
          position:absolute;bottom:0;right:0;width:16px;height:16px;
          cursor:nwse-resize;
        "></div>
      `;
      document.body.appendChild(popup);

      // Dragging
      const header = popup.querySelector('#yc-artifact-header');
      let dragX, dragY, startLeft, startTop;
      header.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'BUTTON') return;
        dragX = e.clientX; dragY = e.clientY;
        startLeft = popup.offsetLeft; startTop = popup.offsetTop;
        const onMove = (me) => {
          popup.style.left = (startLeft + me.clientX - dragX) + 'px';
          popup.style.top = (startTop + me.clientY - dragY) + 'px';
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        e.preventDefault();
      });

      // Resizing
      const resizeHandle = popup.querySelector('#yc-artifact-resize');
      resizeHandle.addEventListener('mousedown', (e) => {
        const startW = popup.offsetWidth, startH = popup.offsetHeight;
        const sx = e.clientX, sy = e.clientY;
        const onMove = (me) => {
          popup.style.width = Math.max(400, startW + me.clientX - sx) + 'px';
          popup.style.height = Math.max(300, startH + me.clientY - sy) + 'px';
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        e.preventDefault();
      });

      // Close
      popup.querySelector('#yc-artifact-close').addEventListener('click', () => {
        popup.style.display = 'none';
        popup.querySelector('#yc-artifact-frame').src = '';
      });

      // Share
      popup.querySelector('#yc-artifact-share').addEventListener('click', () => {
        const frameUrl = popup.querySelector('#yc-artifact-frame').src;
        if (frameUrl) window.open(frameUrl, '_blank');
      });
    }

    popup.style.display = 'flex';
    popup.querySelector('#yc-artifact-title').textContent = title || 'Artifact';
    popup.querySelector('#yc-artifact-frame').src = url;
  }
})();
