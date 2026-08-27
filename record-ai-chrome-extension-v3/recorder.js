// RECORD-AI Recorder Page v3.0 — Envia para API (não direto pro Telegram)

let mediaRecorder = null;
let audioChunks = [];
let audioContext = null;
let analyser = null;
let dataArray = null;
let animationId = null;
let timerInterval = null;
let startTime = null;
let stream = null;
let recordedBlob = null;

const states = {
  permission: document.getElementById('state-permission'),
  recording: document.getElementById('state-recording'),
  review: document.getElementById('state-review'),
  sending: document.getElementById('state-sending'),
  success: document.getElementById('state-success'),
  error: document.getElementById('state-error'),
};

const timerEl = document.getElementById('rec-timer');
const vizCanvas = document.getElementById('viz');
const vizCtx = vizCanvas.getContext('2d');
const sendProgress = document.getElementById('send-progress');
const sendText = document.getElementById('send-text');
const errorMsg = document.getElementById('error-msg');
const displayApiUrl = document.getElementById('display-api-url');
const displayMode = document.getElementById('display-mode');
const configStatus = document.getElementById('config-status');

let config = {};
const MODE_LABELS = {
  meeting: '1️⃣ Reunião',
  ideas: '2️⃣ Organizador de Ideias'
};

// Carrega config da extensão
chrome.storage.local.get(['apiUrl', 'apiKey', 'hashId', 'mode'], (data) => {
  config = data;
  if (data.apiUrl) {
    displayApiUrl.textContent = data.apiUrl;
    configStatus.textContent = '✅ API configurada';
    configStatus.style.color = '#4ade80';
  } else {
    displayApiUrl.textContent = '—';
    configStatus.textContent = '⚠️ Configure a API no popup';
    configStatus.style.color = '#ffaa00';
  }
  config.mode = data.mode || 'meeting';
  displayMode.textContent = MODE_LABELS[config.mode] || MODE_LABELS.meeting;
});

function showState(name) {
  Object.values(states).forEach(el => el.classList.add('hidden'));
  states[name].classList.remove('hidden');
}

document.getElementById('close-btn').addEventListener('click', () => {
  window.close();
});

document.getElementById('btn-record-mic').addEventListener('click', startMicRecording);
document.getElementById('btn-record-tab').addEventListener('click', startTabRecording);
document.getElementById('btn-stop').addEventListener('click', stopRecording);
document.getElementById('btn-send').addEventListener('click', () => {
  if (recordedBlob) sendToApi(recordedBlob);
});
document.getElementById('btn-cancel').addEventListener('click', discardRecording);
document.getElementById('btn-new').addEventListener('click', () => showState('permission'));
document.getElementById('btn-retry').addEventListener('click', () => showState('permission'));

async function startMicRecording() {
  try {
    if (!checkApiConfig()) return;
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    await beginRecording(stream);
  } catch (err) {
    console.error(err);
    errorMsg.textContent = err.message || 'Erro ao acessar microfone';
    showState('error');
  }
}

async function startTabRecording() {
  try {
    if (!checkApiConfig()) return;

    // Abre o picker do Chrome para o usuário escolher a aba/janela com áudio.
    // video: true é necessário para que o picker mostre a opção de compartilhar áudio.
    stream = await navigator.mediaDevices.getDisplayMedia({
      audio: true,
      video: true
    });

    // Verifica se o usuário realmente escolheu compartilhar o áudio
    if (stream.getAudioTracks().length === 0) {
      stream.getTracks().forEach(t => t.stop());
      throw new Error(
        'Nenhuma faixa de áudio foi capturada. No picker do Chrome, escolha a aba da reunião e marque a opção "Compartilhar áudio".'
      );
    }

    // Se o usuário parar o compartilhamento pelo Chrome, encerra a gravação
    stream.oninactive = () => stopRecording();

    await beginRecording(stream);
  } catch (err) {
    console.error(err);
    errorMsg.textContent = err.message || 'Erro ao capturar áudio da aba';
    showState('error');
  }
}

function checkApiConfig() {
  if (!config.apiUrl) {
    alert('⚠️ Configure a URL da API no popup da extensão primeiro!');
    return false;
  }
  return true;
}

async function beginRecording(mediaStream) {
  // Usa apenas as faixas de áudio para não gravar vídeo desnecessário
  const audioTracks = mediaStream.getAudioTracks();
  if (audioTracks.length === 0) {
    throw new Error('Nenhuma faixa de áudio encontrada na fonte selecionada.');
  }
  const audioOnlyStream = new MediaStream(audioTracks);

  audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(audioOnlyStream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);
  dataArray = new Uint8Array(analyser.frequencyBinCount);

  const options = { mimeType: 'audio/webm;codecs=opus' };
  mediaRecorder = new MediaRecorder(audioOnlyStream, options);
  audioChunks = [];

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  };

  mediaRecorder.onstop = async () => {
    recordedBlob = new Blob(audioChunks, { type: 'audio/ogg' });
    showState('review');
  };

  mediaRecorder.start(100);

  showState('recording');
  startTime = Date.now();
  timerInterval = setInterval(updateTimer, 1000);
  drawVisualizer();
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
  if (audioContext) {
    audioContext.close();
  }
  if (timerInterval) clearInterval(timerInterval);
  if (animationId) cancelAnimationFrame(animationId);
}

function discardRecording() {
  recordedBlob = null;
  audioChunks = [];
  cleanupRecording();
  showState('permission');
}

function updateTimer() {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');
  timerEl.textContent = `${mins}:${secs}`;
}

function drawVisualizer() {
  if (!analyser) return;
  animationId = requestAnimationFrame(drawVisualizer);
  analyser.getByteFrequencyData(dataArray);

  vizCtx.fillStyle = '#111';
  vizCtx.fillRect(0, 0, vizCanvas.width, vizCanvas.height);

  const barWidth = (vizCanvas.width / dataArray.length) * 2.5;
  let x = 0;

  for (let i = 0; i < dataArray.length; i++) {
    const barHeight = (dataArray[i] / 255) * vizCanvas.height * 0.8;
    const r = 255;
    const g = 68 + (dataArray[i] / 255) * 100;
    const b = 68 + (dataArray[i] / 255) * 50;

    vizCtx.fillStyle = `rgb(${r},${g},${b})`;
    vizCtx.fillRect(x, vizCanvas.height - barHeight, barWidth, barHeight);
    x += barWidth + 1;
  }
}

async function sendToApi(audioBlob) {
  showState('sending');
  sendProgress.style.width = '20%';
  sendText.textContent = 'Preparando áudio...';

  const formData = new FormData();
  formData.append('file', audioBlob, `record-ai_${Date.now()}.ogg`);

  const headers = {};
  if (config.apiKey) {
    headers['X-API-Key'] = config.apiKey;
  }
  if (config.hashId) {
    headers['X-Hash-Id'] = config.hashId;
  }
  headers['X-Mode'] = config.mode || 'meeting';

  sendProgress.style.width = '50%';
  sendText.textContent = 'Transcrevendo e enviando...';

  try {
    const response = await fetch(`${config.apiUrl}/upload-and-transcribe`, {
      method: 'POST',
      headers: headers,
      body: formData,
    });

    sendProgress.style.width = '100%';

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `Erro ${response.status}`);
    }

    const result = await response.json();

    if (result.ok) {
      showState('success');
    } else {
      throw new Error(result.detail || 'Erro no envio');
    }
  } catch (err) {
    console.error(err);
    errorMsg.textContent = err.message;
    showState('error');
  }
}