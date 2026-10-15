/** BrowserWindow may outlive its WebContents during close/quit. */
function liveContents(window) {
  if (window.isDestroyed()) return null;
  const contents = window.webContents;
  return contents && !contents.isDestroyed() ? contents : null;
}

function sendToWindow(window, channel, ...args) {
  const contents = liveContents(window);
  if (!contents) return false;
  contents.send(channel, ...args);
  return true;
}

module.exports = { liveContents, sendToWindow };
