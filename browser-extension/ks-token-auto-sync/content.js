const REQUEST_TYPE = 'GM_KS_TOKEN_BRIDGE_REQUEST';
const PROGRESS_TYPE = 'GM_KS_TOKEN_BRIDGE_PROGRESS';
const RESULT_TYPE = 'GM_KS_TOKEN_BRIDGE_RESULT';

window.addEventListener('message', event => {
  if (event.source !== window || event.origin !== window.location.origin) return;
  const request = event.data || {};
  if (request.type !== REQUEST_TYPE || !request.requestId) return;

  window.postMessage({
    type: PROGRESS_TYPE,
    requestId: request.requestId
  }, window.location.origin);

  chrome.runtime.sendMessage({ type: 'GM_KS_TOKEN_READ' }, async response => {
    const runtimeError = chrome.runtime.lastError;
    if (runtimeError || !response || !response.ok || !response.token) {
      window.postMessage({
        type: RESULT_TYPE,
        requestId: request.requestId,
        ok: false,
        error: runtimeError ? runtimeError.message : (response && response.error || 'KS Token 读取失败')
      }, window.location.origin);
      return;
    }
    window.postMessage({
      type: PROGRESS_TYPE,
      requestId: request.requestId,
      message: '已读取 Token，正在同步个人环境与账号...'
    }, window.location.origin);
    let data = null;
    let syncError = '';
    try {
      const syncResponse = await fetch('/api/ks/sync', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: response.token,
          credential_text: response.token
        })
      });
      data = await syncResponse.json();
      if (!syncResponse.ok || !data.ok) syncError = data.msg || 'KS 环境与账号同步失败';
    } catch (error) {
      syncError = error.message || 'KS 环境与账号同步请求失败';
    }
    window.postMessage({
      type: RESULT_TYPE,
      requestId: request.requestId,
      ok: !syncError && !!data,
      data,
      error: syncError
    }, window.location.origin);
  });
});
