const KS_TOKEN_PAGE = 'https://zxty.tuyoo.com/keystone/account/ui-test-agent';
const LOCAL_GM_ORIGINS = new Set([
  'http://localhost:9092',
  'http://127.0.0.1:9092'
]);
const TOKEN_STORAGE_KEYS = ['TOKEN', 'token', 'accessToken', 'access_token'];

function normalizeToken(value) {
  let text = String(value || '').trim();
  if (!text) return '';
  if (/^Bearer\s+/i.test(text)) text = text.replace(/^Bearer\s+/i, '').trim();
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed === 'string') return normalizeToken(parsed);
    if (parsed && typeof parsed === 'object') {
      for (const key of TOKEN_STORAGE_KEYS) {
        const nested = normalizeToken(parsed[key]);
        if (nested) return nested;
      }
    }
  } catch (_) {
    // KS stores the JWT as a plain string in the normal case.
  }
  return text;
}

async function readTokenFromTab(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: keys => {
      for (const key of keys) {
        const localValue = window.localStorage.getItem(key);
        if (localValue) return localValue;
        const sessionValue = window.sessionStorage.getItem(key);
        if (sessionValue) return sessionValue;
      }
      return '';
    },
    args: [TOKEN_STORAGE_KEYS]
  });
  return normalizeToken(results[0] && results[0].result);
}

async function readTokenFromOpenKsTab() {
  const tabs = await chrome.tabs.query({
    url: ['https://zxty.tuyoo.com/keystone/*']
  });
  for (const tab of tabs) {
    if (tab.id == null) continue;
    try {
      const token = await readTokenFromTab(tab.id);
      if (token) return token;
    } catch (_) {
      // A tab can disappear or still be loading while the request is handled.
    }
  }
  return '';
}

function waitForTabComplete(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      if (error) reject(error);
      else resolve();
    };
    const onUpdated = (updatedTabId, changeInfo) => {
      if (updatedTabId === tabId && changeInfo.status === 'complete') finish();
    };
    const timer = setTimeout(() => finish(new Error('KS Token 页面加载超时')), timeoutMs);
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then(tab => {
      if (tab.status === 'complete') finish();
    }).catch(() => finish(new Error('KS Token 页面已关闭')));
  });
}

async function readCurrentKsToken() {
  const openTabToken = await readTokenFromOpenKsTab();
  if (openTabToken) return openTabToken;
  const tab = await chrome.tabs.create({ url: KS_TOKEN_PAGE, active: false });
  try {
    await waitForTabComplete(tab.id, 20000);
    await new Promise(resolve => setTimeout(resolve, 800));
    const currentTab = await chrome.tabs.get(tab.id);
    if (!String(currentTab.url || '').startsWith('https://zxty.tuyoo.com/keystone/')) {
      throw new Error('KS Token 页面跳转到了不受支持的地址');
    }
    const token = await readTokenFromTab(tab.id);
    if (!token) {
      throw new Error('当前浏览器没有 KS Token，请先在同一浏览器登录 KS');
    }
    return token;
  } finally {
    if (tab && tab.id != null) {
      chrome.tabs.remove(tab.id).catch(() => {});
    }
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'GM_KS_TOKEN_READ') return false;
  let senderOrigin = '';
  try {
    senderOrigin = new URL(sender.url || '').origin;
  } catch (_) {
    sendResponse({ ok: false, error: '无法确认 GM 页面来源' });
    return false;
  }
  if (!LOCAL_GM_ORIGINS.has(senderOrigin)) {
    sendResponse({ ok: false, error: '拒绝向非本机 GM 页面提供 Token' });
    return false;
  }
  readCurrentKsToken()
    .then(token => sendResponse({ ok: true, token }))
    .catch(error => sendResponse({ ok: false, error: error.message || 'KS Token 读取失败' }));
  return true;
});
