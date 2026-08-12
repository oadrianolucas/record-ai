# 🖥️ RECORD-AI API — Proxy Seguro + Transcrição + Notion

API FastAPI que recebe áudio da extensão Chrome (ou do bot do Telegram), transcreve localmente com **Whisper**, organiza a ata com **DeepSeek** e cria a página no **Notion**.
O **token do bot, chat IDs e chaves ficam no servidor** — nunca no navegador.

## 🚀 Subir com Docker (recomendado)

```bash
# 1. Entre na pasta
cd record-ai-api

# 2. Configure
cp .env.example .env
# Edite o .env com seu token, chat ID, API key, DeepSeek e Notion

# 3. Suba
docker-compose up -d

# 4. Verifique
curl http://localhost/health
```

> O `docker-compose.yml` expõe a API na porta **80**. Para usar outra porta, ajuste o mapeamento `"8000:80"` e use `http://localhost:8000` na extensão.

Sem Docker: `pip install -r requirements.txt` (requer **ffmpeg** instalado) e `uvicorn main:app --port 80`.

## 🔧 Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `TELEGRAM_BOT_TOKEN` | Sim | Token do BotFather |
| `TELEGRAM_CHAT_ID` | Sim | Chat ID da conversa padrão (usada quando o cliente não envia hash) |
| `HASH_ID` | Sim | Alias público da conversa padrão — a extensão usa este valor, nunca o chat_id real |
| `TELEGRAM_CHAT_ID_1` + `HASH_ID_1`, `_2`, ... | Não | Conversas adicionais no mesmo bot. O webhook aceita áudio de qualquer uma; a extensão escolhe via campo "HASH ID" (header `X-Hash-Id`) |
| `RECORD-AI_API_KEY` | Recomendada | Chave secreta pra extensão autenticar |
| `ENABLE_TRANSCRIPTION` | Sim (para o fluxo de ata) | `true` para habilitar o Whisper no servidor |
| `WHISPER_MODEL_SIZE` | Não | `tiny`, `base`, `small`, `medium`, `large` (padrão: `small`) |
| `DEEPSEEK_API_KEY` | Sim (para o fluxo de ata) | Chave da API DeepSeek — organiza a transcrição em ata |
| `NOTION_API_KEY` | Não | Token da integração do Notion — cria a página com a ata |
| `NOTION_PARENT_PAGE_ID` | Não | Página pai onde as atas são criadas |
| `TELEGRAM_WEBHOOK_SECRET` | Não | Token para validar chamadas do webhook do Telegram |
| `HF_TOKEN` | Não | Token do Hugging Face para download mais rápido dos modelos Whisper |

## 📡 Endpoints

### `GET /health`
Health check: versão, se o Whisper está carregado e quais integrações estão configuradas.
```bash
curl http://localhost/health
```

### `POST /upload`
Recebe áudio e envia como **voice note** pro Telegram (fluxo simples, sem transcrição).
```bash
curl -X POST "http://localhost/upload" \
  -H "X-API-Key: sua-chave" \
  -H "X-Hash-Id: seu-hash-id" \
  -F "file=@gravacao.ogg"
```

### `POST /upload-and-transcribe`
**Fluxo completo de ata de reunião** (usado pela extensão): responde imediatamente e processa em background — transcreve com Whisper, organiza com DeepSeek, cria a página no Notion e envia os status no Telegram.
```bash
curl -X POST "http://localhost/upload-and-transcribe" \
  -H "X-API-Key: sua-chave" \
  -H "X-Hash-Id: seu-hash-id" \
  -F "file=@gravacao.ogg"
```

Requer `ENABLE_TRANSCRIPTION=true` e `DEEPSEEK_API_KEY`. Sem `NOTION_API_KEY`, a ata não é criada no Notion, mas os status continuam indo pro Telegram.

O header `X-Hash-Id` é opcional nos dois endpoints: sem ele, vai para a conversa padrão (`TELEGRAM_CHAT_ID`); com ele, o valor precisa bater com um `HASH_ID` configurado no servidor (`HASH_ID`, `HASH_ID_1`, ...). Assim o chat_id real do Telegram nunca sai do servidor.

### `POST /webhook/telegram`
Webhook para o Telegram. Quando um **chat autorizado** (`TELEGRAM_CHAT_ID` ou qualquer `TELEGRAM_CHAT_ID_N`) envia um áudio para o bot, o mesmo fluxo completo de ata é disparado em background.

Configure no Telegram:
```bash
curl -X POST "https://api.telegram.org/bot<SEU_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://sua-api.com/webhook/telegram",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET>"
  }'
```

Requer `ENABLE_TRANSCRIPTION=true`. Mensagens de outros chats são ignoradas.

## 🔒 Segurança

- Token do bot **nunca sai do servidor**
- API Key opcional para autenticar a extensão
- `HASH_ID` como alias público das conversas — o chat_id real fica só no `.env`
- CORS habilitado (restrinja em produção)
