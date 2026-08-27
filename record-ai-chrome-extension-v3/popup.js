// RECORD-AI Popup v5.0 — Launcher minimalista

const panels = {
  launch: document.querySelector('.main-panel'),
  status: document.getElementById('status-panel'),
  config: document.getElementById('config-panel'),
};

const navButtons = {
  record: document.getElementById('nav-record'),
  status: document.getElementById('nav-status'),
  config: document.getElementById('nav-config'),
};

const statusDetail = document.getElementById('status-detail');
const configMsg = document.getElementById('config-msg');

let config = {};
const MODE_DEFAULT = 'meeting';

// Carrega config
chrome.storage.local.get(['apiUrl', 'apiKey', 'hashId', 'mode'], (data) => {
  config = data;
  if (data.apiUrl) {
    document.getElementById('api-url').value = data.apiUrl;
  }
  if (data.apiKey) {
    document.getElementById('api-key').value = data.apiKey;
  }
  if (data.hashId) {
    document.getElementById('hash-id').value = data.hashId;
  }
  updateModeUI(data.mode || MODE_DEFAULT);
});

// Mode switch
function updateModeUI(mode) {
  document.querySelectorAll('.mode-option').forEach(el => {
    el.classList.toggle('active', el.dataset.mode === mode);
  });
}

document.getElementById('mode-switch').addEventListener('click', (e) => {
  const option = e.target.closest('.mode-option');
  if (!option) return;
  const mode = option.dataset.mode;
  chrome.storage.local.set({ mode }, () => {
    config.mode = mode;
    updateModeUI(mode);
  });
});

// Navegação
function showPanel(name) {
  Object.values(panels).forEach(p => p.classList.add('hidden'));
  Object.values(navButtons).forEach(b => b.classList.remove('active'));
  panels[name].classList.remove('hidden');
  navButtons[name].classList.add('active');

  if (name === 'status') {
    checkHealth();
  }
}

document.getElementById('nav-record').addEventListener('click', () => showPanel('launch'));
document.getElementById('nav-status').addEventListener('click', () => showPanel('status'));
document.getElementById('nav-config').addEventListener('click', () => showPanel('config'));

// Abrir gravador
document.getElementById('btn-open-recorder').addEventListener('click', () => {
  // Obtém o streamId da aba ativa para permitir captura de áudio sem picker
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const activeTab = tabs[0];
    if (!activeTab || activeTab.url?.startsWith('chrome://')) {
      openRecorderWindow();
      return;
    }

    chrome.tabCapture.getMediaStreamId({ targetTabId: activeTab.id }, (result) => {
      if (chrome.runtime.lastError) {
        console.error(chrome.runtime.lastError);
        openRecorderWindow();
        return;
      }
      openRecorderWindow(result.streamId);
    });
  });
});

function openRecorderWindow(streamId) {
  let url = chrome.runtime.getURL('window.html');
  if (streamId) {
    url += `?streamId=${encodeURIComponent(streamId)}`;
  }
  chrome.windows.create({
    url: url,
    type: 'popup',
    width: 340,
    height: 260,
    focused: true
  });
  window.close();
}

// Configuração
document.getElementById('save-config').addEventListener('click', () => {
  const url = document.getElementById('api-url').value.trim();
  const key = document.getElementById('api-key').value.trim();
  const hashId = document.getElementById('hash-id').value.trim();

  if (!url) {
    configMsg.textContent = 'Informe a URL!';
    configMsg.className = 'msg error';
    return;
  }

  const cleanUrl = url.endsWith('/') ? url.slice(0, -1) : url;

  chrome.storage.local.set({ apiUrl: cleanUrl, apiKey: key, hashId: hashId }, () => {
    config = { apiUrl: cleanUrl, apiKey: key, hashId: hashId };
    configMsg.textContent = '✅ Salvo!';
    configMsg.className = 'msg success';
    checkHealth();
    setTimeout(() => {
      configMsg.textContent = '';
      showPanel('launch');
    }, 800);
  });
});

// Health check
document.getElementById('btn-refresh-status').addEventListener('click', checkHealth);

async function checkHealth() {
  statusDetail.textContent = 'Verificando...';

  if (!config.apiUrl) {
    statusDetail.textContent = '⚠️ URL da API não configurada.\n\nVá em "Config" e informe a URL.';
    return;
  }

  try {
    const headers = {};
    if (config.apiKey) headers['X-API-Key'] = config.apiKey;

    const response = await fetch(`${config.apiUrl}/health`, { headers });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();

    statusDetail.textContent =
      `✅ API online (v${data.version || '?'})
` +
      `${data.transcription && data.whisper_loaded ? '✅' : '❌'} Transcrição: ${data.transcription && data.whisper_loaded ? 'ok' : 'off'}
` +
      `${data.bot_configured ? '✅' : '❌'} Bot: ${data.bot_configured ? 'ok' : 'off'}`;
  } catch (err) {
    statusDetail.textContent = `❌ API offline\n\n${config.apiUrl}\n${err.message}`;
  }
}
