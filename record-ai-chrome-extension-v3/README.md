# 🎙️ RECORD-AI Voice Recorder — Chrome Extension v3.0 (API Proxy)

Extensão Chrome que grava áudio e envia para **sua API** — o token do bot fica no servidor, nunca no navegador.

## 🆕 O que mudou na v3.0

| v2.0 | v3.0 |
|------|------|
| Enviava direto pro Telegram (token exposto) | Envia para **sua API** (token seguro no servidor) |
| Token no `chrome.storage` | Só a URL da API + API Key no navegador |

## 📦 Instalação

1. Baixe e extraia
2. Brave/Chrome → `chrome://extensions/` → Modo desenvolvedor → Carregar sem compactação

## ⚙️ Configuração

1. Clique no ícone da extensão
2. Clique em **"⚙️ Configurar API"**
3. Insira:
   - **URL da API**: `http://localhost:8000` (ou seu domínio)
   - **API Key**: a chave que você definiu no `.env` da API
4. Clique em **"Salvar"**

## 🚀 Como usar

1. Clique no ícone → **"🔴 Abrir Gravador"**
2. Na aba do gravador, clique em **"🎙️ Permitir Microfone"**
3. Clique em **"🔴 Iniciar Gravação"**
4. Fale — visualizador de ondas ativo
5. Clique em **"⏹️ Parar Gravação"**
6. Áudio vai para **sua API** → API envia pro Telegram → Bot transcreve

## 🔒 Segurança

- **Bot Token**: só no servidor (`.env` da API)
- **Chat ID**: só no servidor (`.env` da API)
- **Navegador**: só guarda URL da API + API Key
- Mesmo que alguém acesse seu Chrome, não consegue o token do bot
