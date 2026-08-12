// RECORD-AI Floating Window — Apenas envia áudio, o Telegram informa o status

let mediaRecorder = null;
let audioChunks = [];
let timerInterval = null;
let startTime = null;
let stream = null;
let currentWindowId = null;

const states = {
  source: document.getElementById('state-source'),
  selecting: document.getElementById('state-selecting'),
  recording: document.getElementById('state-recording'),
  sending: document.getElementById('state-sending'),
  success: document.getElementById('state-success'),
  error: document.getElementById('state-error'),
};

const timerEl = document.getElementById('timer');
const progressEl = document.getElementById('progress');
const errorMsg = document.getElementById('error-msg');

let config = {};

const urlParams = new URLSearchParams(window.location.search);
const tabStreamId = urlParams.get('streamId');

chrome.storage.local.get(['apiUrl', 'apiKey', 'hashId'], (data) => {
  config = data;
  if (!config.apiUrl) {
    showError('URL da API não configurada. Configure no popup da extensão.');
  }
});

chrome.windows.getCurrent((win) => {
  currentWindowId = win.id;
});

function showState(name) {
  Object.values(states).forEach(el => el.classList.add('hidden'));
  states[name].classList.remove('hidden');
}

function resizeWindow(width, height) {
  if (currentWindowId) {
    chrome.windows.update(currentWindowId, { width, height });
  }
}

document.getElementById('btn-mic').addEventListener('click', startMicRecording);
document.getElementById('btn-tab').addEventListener('click', startTabRecording);
document.getElementById('btn-pause').addEventListener('click', stopRecording);
document.getElementById('btn-close').addEventListener('click', () => window.close());
document.getElementById('btn-retry').addEventListener('click', () => {
  showState('source');
  resizeWindow(340, 260);
});

async function startMicRecording() {
  try {
    if (!config.apiUrl) throw new Error('URL da API não configurada.');
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    beginRecording(stream);
  } catch (err) {
    console.error(err);
    showError(err.message || 'Erro no microfone');
  }
}

async function startTabRecording() {
  try {
    if (!config.apiUrl) throw new Error('URL da API não configurada.');

    if (tabStreamId) {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          mandatory: {
            chromeMediaSource: 'tab',
            chromeMediaSourceId: tabStreamId
          }
        },
        video: false
      });
      beginRecording(stream);
    } else {
      // Picker do Chrome: amplia a janela e mostra instruções enquanto o usuário escolhe
      showState('selecting');
      resizeWindow(480, 340);

      stream = await navigator.mediaDevices.getDisplayMedia({
        audio: true,
        video: true
      });
      if (stream.getAudioTracks().length === 0) {
        stream.getTracks().forEach(t => t.stop());
        throw new Error('Marque "Compartilhar áudio" no picker do Chrome.');
      }
      stream.oninactive = () => stopRecording();
      beginRecording(stream);
    }
  } catch (err) {
    console.error(err);
    if (err.name === 'NotAllowedError') {
      // Usuário cancelou o seletor — volta para a escolha de fonte
      showState('source');
      resizeWindow(340, 260);
      return;
    }
    showError(err.message || 'Erro ao capturar áudio');
  }
}

function beginRecording(mediaStream) {
  const audioTracks = mediaStream.getAudioTracks();
  if (audioTracks.length === 0) {
    throw new Error('Nenhuma faixa de áudio.');
  }
  const audioOnlyStream = new MediaStream(audioTracks);

  const options = { mimeType: 'audio/webm;codecs=opus' };
  mediaRecorder = new MediaRecorder(audioOnlyStream, options);
  audioChunks = [];

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  };

  mediaRecorder.onstop = () => {
    const recordedBlob = new Blob(audioChunks, { type: 'audio/ogg' });
    sendToApi(recordedBlob);
  };

  mediaRecorder.start(100);

  showState('recording');
  resizeWindow(220, 160);
  startTime = Date.now();
  timerInterval = setInterval(updateTimer, 1000);
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  cleanupRecording();
}

function cleanupRecording() {
  if (stream) {
    stream.getTracks().forEach(t => t.stop());
  }
  if (timerInterval) clearInterval(timerInterval);
}

function updateTimer() {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');
  timerEl.textContent = `${mins}:${secs}`;
}

function showError(msg) {
  errorMsg.textContent = msg;
  showState('error');
  resizeWindow(340, 240);
}

async function sendToApi(audioBlob) {
  showState('sending');
  resizeWindow(340, 220);
  progressEl.style.width = '30%';

  const formData = new FormData();
  formData.append('file', audioBlob, `record-ai_${Date.now()}.ogg`);

  const headers = {};
  if (config.apiKey) {
    headers['X-API-Key'] = config.apiKey;
  }
  if (config.hashId) {
    headers['X-Hash-Id'] = config.hashId;
  }

  try {
    const response = await fetch(`${config.apiUrl}/upload-and-transcribe`, {
      method: 'POST',
      headers: headers,
      body: formData,
    });

    progressEl.style.width = '100%';

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Erro ${response.status}`);
    }

    showState('success');
    resizeWindow(340, 240);
  } catch (err) {
    console.error(err);
    showError(err.message);
  }
}
