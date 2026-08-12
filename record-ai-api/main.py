from fastapi import FastAPI, File, Header, Request, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
import tempfile
from datetime import datetime
from faster_whisper import WhisperModel
from typing import Optional
from openai import OpenAI
import traceback

app = FastAPI(title="RECORD-AI API", version="3.0.0")

# CORS — permite a extensão Chrome chamar a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # em produção, restrinja ao ID da extensão
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configs via variáveis de ambiente (nunca no navegador!)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def _load_telegram_conversations() -> list[dict]:
    """Carrega as conversas: TELEGRAM_CHAT_ID/HASH_ID (padrão) + pares numerados _1, _2, ..."""
    conversations = []
    base_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if base_chat_id:
        conversations.append({
            "chat_id": base_chat_id,
            "hash_id": os.getenv("HASH_ID")
        })

    index = 1
    while True:
        chat_id = os.getenv(f"TELEGRAM_CHAT_ID_{index}")
        if not chat_id:
            break
        if chat_id not in [c["chat_id"] for c in conversations]:
            conversations.append({
                "chat_id": chat_id,
                "hash_id": os.getenv(f"HASH_ID_{index}")
            })
        index += 1

    return conversations


# Mesmo bot, várias conversas: TELEGRAM_CHAT_ID/HASH_ID (padrão) + pares numerados _1, _2, ...
# O cliente nunca vê o chat_id real do Telegram — seleciona a conversa pelo HASH_ID,
# que pode ser trocado no env sem expor nem alterar o chat_id.
TELEGRAM_CONVERSATIONS = _load_telegram_conversations()
TELEGRAM_CHAT_IDS = [c["chat_id"] for c in TELEGRAM_CONVERSATIONS]
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else None
API_KEY = os.getenv("RECORD-AI_API_KEY", "")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
ENABLE_TRANSCRIPTION = os.getenv("ENABLE_TRANSCRIPTION", "false").lower() == "true"
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID")

# Carrega Whisper se habilitado
whisper_model = None
if ENABLE_TRANSCRIPTION:
    print(f"🔄 Carregando Whisper ({WHISPER_MODEL_SIZE})...")
    whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    print("✅ Whisper pronto!")

# Cliente DeepSeek (compatível com OpenAI)
deepseek_client = None
if DEEPSEEK_API_KEY:
    deepseek_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )


def verify_api_key(x_api_key: Optional[str] = None):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida")


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    """Health check da imagem/deploy."""
    return {
        "status": "ok",
        "version": "3.0.0",
        "transcription": ENABLE_TRANSCRIPTION,
        "whisper_loaded": whisper_model is not None,
        "bot_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS),
        "conversations_configured": len(TELEGRAM_CONVERSATIONS),
        "api_key_required": bool(API_KEY),
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "notion_configured": bool(NOTION_API_KEY)
    }


@app.get("/status-telegram")
def status_telegram():
    """Consulta o getWebhookInfo do Telegram e resume o estado do webhook do bot."""
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN não configurado")

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"
        resp = requests.get(url, timeout=30)
        result = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Telegram: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("description", "Erro Telegram"))

    info = result.get("result", {})
    webhook_url = info.get("url", "")
    return {
        "webhook_registered": bool(webhook_url),
        "webhook_url": webhook_url,
        "pending_update_count": info.get("pending_update_count", 0),
        "last_error_message": info.get("last_error_message"),
        "last_error_date": info.get("last_error_date"),
        "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "conversations_configured": len(TELEGRAM_CONVERSATIONS),
        "hint": (
            f"Webhook registrado, mas o Telegram recebeu erro: {info['last_error_message']}"
            if webhook_url and info.get("last_error_message")
            else "Webhook registrado e sem erro recente."
            if webhook_url
            else "Webhook NÃO registrado. Acesse /sync-telegram para registrar."
        )
    }


@app.get("/sync-telegram")
def sync_telegram(request: Request):
    """Registra o webhook do Telegram apontando para esta mesma API (/webhook/telegram).
    A URL pública é derivada da própria requisição (host + scheme), funcionando atrás de proxy reverso."""
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN não configurado")

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if not host:
        raise HTTPException(status_code=500, detail="Não foi possível determinar o host público")

    webhook_url = f"{proto}://{host}/webhook/telegram"
    payload = {"url": webhook_url, "drop_pending_updates": False}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        resp = requests.post(url, json=payload, timeout=30)
        result = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao registrar webhook: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("description", "Erro Telegram"))

    return {
        "ok": True,
        "webhook_url": webhook_url,
        "telegram_response": result.get("description"),
        "hint": "Webhook registrado. Verifique em /status-telegram."
    }


def _telegram_send_message(chat_id, text: str, parse_mode: str = "Markdown") -> dict:
    """Envia uma mensagem de texto para um chat do Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    resp = requests.post(url, json=payload, timeout=30)
    return resp.json()


def _telegram_send_status(status_text: str):
    """Envia mensagem de status para o chat padrão configurado."""
    if TELEGRAM_CHAT_ID:
        _telegram_send_message(TELEGRAM_CHAT_ID, status_text)


def _resolve_chat_id(hash_id: Optional[str]) -> str:
    """Resolve o HASH_ID enviado pelo cliente para o chat_id real; sem hash, usa a conversa padrão."""
    if not TELEGRAM_CONVERSATIONS:
        raise HTTPException(status_code=500, detail="Bot não configurado no servidor")
    if not hash_id:
        return TELEGRAM_CONVERSATIONS[0]["chat_id"]
    for conversation in TELEGRAM_CONVERSATIONS:
        if conversation["hash_id"] and conversation["hash_id"] == hash_id:
            return conversation["chat_id"]
    raise HTTPException(status_code=400, detail="hash_id não configurado no servidor")


def _transcribe_audio(file_path: str) -> tuple[str, list, str]:
    """Transcreve o áudio com Whisper local. Retorna transcrição completa, segments e idioma."""
    if not whisper_model:
        raise RuntimeError("Transcrição não habilitada")

    segments_iter, info = whisper_model.transcribe(file_path, language="pt", beam_size=5)
    segments = list(segments_iter)
    transcription = " ".join([seg.text.strip() for seg in segments])
    return transcription, segments, info.language


def _split_transcription_into_chunks(segments: list, chunk_duration_seconds: int = 600) -> list[str]:
    """Divide a transcrição em chunks baseados no tempo (padrão: 10 minutos)."""
    if not segments:
        return []

    chunks = []
    current_chunk = []
    current_start = 0

    for seg in segments:
        if seg.start >= current_start + chunk_duration_seconds:
            if current_chunk:
                chunks.append(" ".join([s.text.strip() for s in current_chunk]))
            current_chunk = [seg]
            current_start = seg.start
        else:
            current_chunk.append(seg)

    if current_chunk:
        chunks.append(" ".join([s.text.strip() for s in current_chunk]))

    return chunks


def _summarize_chunk_with_deepseek(chunk_text: str, chunk_index: int, total_chunks: int, meeting_datetime: str) -> str:
    """Resume um chunk da reunião com DeepSeek."""
    if not deepseek_client:
        raise RuntimeError("DeepSeek não configurado")

    system_prompt = (
        "Você é um assistente especialista em atas de reuniões. "
        "Resuma o trecho fornecido de forma estruturada em Markdown. "
        "Inclua apenas: tópicos discutidos, decisões tomadas, próximos passos com responsáveis e prazos, "
        "e observações importantes. Não invente informações. Use português. "
        f"A reunião ocorreu em {meeting_datetime}."
    )

    response = deepseek_client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Trecho {chunk_index + 1} de {total_chunks}:\n\n{chunk_text}"}
        ],
        stream=False,
        reasoning_effort="medium"
    )

    return response.choices[0].message.content


def _consolidate_summaries_with_deepseek(summaries: list[str], full_transcription: str, meeting_datetime: str) -> str:
    """Combina os resumos parciais em um documento final coeso."""
    if not deepseek_client:
        raise RuntimeError("DeepSeek não configurado")

    combined = "\n\n---\n\n".join(
        [f"### Trecho {i + 1}\n\n{s}" for i, s in enumerate(summaries)]
    )

    system_prompt = (
        "Você é um assistente especialista em atas de reuniões. "
        "Combine os resumos parciais abaixo em um único documento Markdown bem estruturado e coeso. "
        "Inclua: título da reunião, data/hora, participantes (inferir se possível), "
        "resumo executivo, tópicos discutidos, decisões tomadas, próximos passos com responsáveis e prazos, "
        "e observações importantes. Elimine repetições e organize por tema. Use linguagem clara e objetiva em português. "
        f"A reunião ocorreu em {meeting_datetime}. Use esta data/hora exata no documento."
    )

    response = deepseek_client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Resumos parciais:\n\n{combined}\n\nTranscrição completa para referência:\n\n{full_transcription[:4000]}"}
        ],
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    return response.choices[0].message.content


def _organize_with_deepseek(transcription: str, segments: list = None, meeting_datetime: str = "") -> str:
    """Organiza a transcrição da reunião com DeepSeek, dividindo em chunks se necessário."""
    if not deepseek_client:
        raise RuntimeError("DeepSeek não configurado")

    meeting_datetime = meeting_datetime or datetime.now().strftime("%d/%m/%Y às %H:%M")

    # Se a transcrição for curta, processa de uma vez
    if len(transcription) <= 6000:
        system_prompt = (
            "Você é um assistente especialista em organizar atas de reuniões. "
            "Receba a transcrição bruta de uma reunião e organize-a em um documento Markdown bem estruturado. "
            "Inclua: título da reunião, data/hora, participantes (inferir se possível), "
            "resumo executivo, tópicos discutidos, decisões tomadas, próximos passos com responsáveis e prazos, "
            "e observações importantes. Use linguagem clara e objetiva em português. "
            f"A reunião ocorreu em {meeting_datetime}. Use esta data/hora exata no documento."
        )

        response = deepseek_client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcrição bruta:\n\n{transcription}"}
            ],
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}}
        )
        return response.choices[0].message.content

    # Transcrição longa: divide em chunks de 10 minutos
    if not segments:
        segments = []

    chunks = _split_transcription_into_chunks(segments, chunk_duration_seconds=600)
    summaries = []

    for i, chunk in enumerate(chunks):
        summary = _summarize_chunk_with_deepseek(chunk, i, len(chunks), meeting_datetime)
        summaries.append(summary)

    return _consolidate_summaries_with_deepseek(summaries, transcription, meeting_datetime)


def _generate_meeting_title(transcription: str, meeting_label: str) -> str:
    """Gera um título curto e descritivo para a reunião usando DeepSeek."""
    if not deepseek_client:
        return f"Reunião {meeting_label}"

    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente que cria títulos curtos e claros para reuniões. "
                        "Com base na transcrição, gere um título de no máximo 60 caracteres que resuma o tema principal. "
                        "Não use aspas, markdown ou data. Apenas o título em português."
                    )
                },
                {
                    "role": "user",
                    "content": f"Crie um título para esta reunião:\n\n{transcription[:2000]}"
                }
            ],
            stream=False,
            reasoning_effort="low"
        )
        title = response.choices[0].message.content.strip().strip('"').strip("'")
        if len(title) > 80:
            title = title[:77] + "..."
        return f"{title} — {meeting_label}"
    except Exception as e:
        print(f"Erro ao gerar título: {e}")
        return f"Reunião {meeting_label}"


def _parse_inline_formatting(text: str) -> list[dict]:
    """Converte texto simples com **negrito** em rich_text do Notion."""
    parts = []
    remaining = text
    while True:
        start = remaining.find("**")
        if start == -1:
            if remaining:
                parts.append({"type": "text", "text": {"content": remaining}})
            break

        if start > 0:
            parts.append({"type": "text", "text": {"content": remaining[:start]}})

        end = remaining.find("**", start + 2)
        if end == -1:
            parts.append({"type": "text", "text": {"content": remaining}})
            break

        bold_text = remaining[start + 2:end]
        parts.append({
            "type": "text",
            "text": {"content": bold_text},
            "annotations": {"bold": True}
        })
        remaining = remaining[end + 2:]

    return parts


def _parse_table_row(line: str) -> list[str]:
    """Parseia uma linha de tabela Markdown em células."""
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _is_table_separator(line: str) -> bool:
    """Verifica se a linha é um separador de tabela Markdown (|------|------|)."""
    if not line.startswith("|"):
        return False
    parts = line.strip().strip("|").split("|")
    return all(part.strip().replace("-", "").replace(":", "") == "" for part in parts)


def _markdown_to_notion_blocks(markdown_content: str) -> list[dict]:
    """Converte conteúdo Markdown simples em blocos nativos do Notion."""
    blocks = []
    lines = markdown_content.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Tabela Markdown
        if line.startswith("|") and not _is_table_separator(line):
            table_rows = []
            header = _parse_table_row(line)
            table_rows.append(header)
            i += 1

            # Pula linha separadora
            if i < len(lines) and _is_table_separator(lines[i]):
                i += 1

            # Coleta linhas de dados
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = _parse_table_row(lines[i].strip())
                # Completa células vazias para manter o alinhamento
                while len(row) < len(header):
                    row.append("")
                table_rows.append(row[:len(header)])
                i += 1

            if table_rows:
                table_width = len(table_rows[0])
                children = []
                for row in table_rows:
                    cells = [[{"type": "text", "text": {"content": cell}}] for cell in row]
                    children.append({
                        "type": "table_row",
                        "table_row": {"cells": cells}
                    })

                blocks.append({
                    "object": "block",
                    "type": "table",
                    "table": {
                        "table_width": table_width,
                        "has_column_header": True,
                        "has_row_header": False,
                        "children": children
                    }
                })
            continue

        # Heading 1
        if line.startswith("# "):
            text = line[2:].strip()
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": _parse_inline_formatting(text)}
            })
            i += 1
            continue

        # Heading 2
        if line.startswith("## "):
            text = line[3:].strip()
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _parse_inline_formatting(text)}
            })
            i += 1
            continue

        # Heading 3
        if line.startswith("### "):
            text = line[4:].strip()
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _parse_inline_formatting(text)}
            })
            i += 1
            continue

        # Bullet list
        if line.startswith("- "):
            text = line[2:].strip()
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _parse_inline_formatting(text)}
            })
            i += 1
            continue

        # Numbered list (simples)
        if line and line[0].isdigit() and ". " in line[:4]:
            text = line.split(". ", 1)[1].strip()
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": _parse_inline_formatting(text)}
            })
            i += 1
            continue

        # Divider
        if line == "---":
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })
            i += 1
            continue

        # Parágrafo padrão
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _parse_inline_formatting(line)}
        })
        i += 1

    return blocks


def _create_notion_page(markdown_content: str, title: str) -> dict:
    """Cria uma página no Notion com título e blocos rich_text."""
    if not NOTION_API_KEY:
        raise RuntimeError("Notion não configurado")

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    payload = {
        "icon": {"emoji": "📝"},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": _markdown_to_notion_blocks(markdown_content)
    }

    if NOTION_PARENT_PAGE_ID:
        payload["parent"] = {
            "type": "page_id",
            "page_id": NOTION_PARENT_PAGE_ID
        }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _process_meeting(file_path: str, filename: str, api_key: Optional[str] = None, chat_id: Optional[str] = None):
    """Processa a reunião em background: transcreve, organiza, cria no Notion e envia status no Telegram."""
    chat_id = chat_id or TELEGRAM_CHAT_ID
    started_at = datetime.now()
    meeting_label = started_at.strftime("%d/%m/%Y às %H:%M")

    def send_status(text: str):
        if chat_id:
            _telegram_send_message(chat_id, text)

    try:
        # 1. Início
        send_status(f"🎙️ *RECORD-AI*\n\nReunião de *{meeting_label}* iniciada.\n🔄 Transcrevendo o áudio...")
        transcription, segments, detected_language = _transcribe_audio(file_path)

        if not transcription.strip():
            send_status(f"❌ *RECORD-AI*\n\nReunião de *{meeting_label}*:\nnão foi possível transcrever o áudio.")
            return

        # 2. Organizando com DeepSeek
        send_status(f"🎙️ *RECORD-AI*\n\nReunião de *{meeting_label}*:\n🧠 Organizando com IA...")
        organized = _organize_with_deepseek(transcription, segments, meeting_label)

        # 3. Criando no Notion
        notion_url = None
        if NOTION_API_KEY:
            send_status(f"🎙️ *RECORD-AI*\n\nReunião de *{meeting_label}*:\n📄 Criando página no Notion...")
            try:
                title = _generate_meeting_title(transcription, meeting_label)
                notion_page = _create_notion_page(organized, title)
                notion_url = notion_page.get("url")
            except Exception as e:
                print(f"Erro ao criar página no Notion: {e}")
                send_status(f"⚠️ *RECORD-AI*\n\nReunião de *{meeting_label}*:\nErro ao criar no Notion: {str(e)}")

        # 4. Status final no Telegram (apenas status e link, sem o conteúdo)
        if notion_url:
            send_status(
                f"✅ *RECORD-AI*\n\nReunião de *{meeting_label}* finalizada.\n"
                f"📄 *[Ver ata no Notion]({notion_url})*"
            )
        else:
            send_status(f"✅ *RECORD-AI*\n\nReunião de *{meeting_label}* finalizada.")

    except Exception as e:
        error_detail = traceback.format_exc()
        print(error_detail)
        send_status(
            f"❌ *RECORD-AI*\n\nReunião de *{meeting_label}*:\n"
            f"Erro ao processar:\n```{str(e)[:500]}```"
        )
    finally:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Erro ao remover arquivo temporário: {e}")


@app.post("/upload-and-transcribe")
async def upload_and_transcribe(
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None),
    x_hash_id: Optional[str] = Header(None)
):
    """
    Recebe áudio da extensão, confirma o recebimento e processa em background:
    transcreve com Whisper, organiza com DeepSeek e cria a ata no Notion.
    O Telegram recebe apenas status de progresso e erro.
    Header opcional X-Hash-Id escolhe qual conversa configurada recebe os status.
    """
    verify_api_key(x_api_key)

    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot não configurado no servidor")

    target_chat_id = _resolve_chat_id(x_hash_id)

    if not whisper_model:
        raise HTTPException(status_code=503, detail="Transcrição não habilitada. Set ENABLE_TRANSCRIPTION=true")

    if not DEEPSEEK_API_KEY:
        raise HTTPException(status_code=503, detail="DeepSeek não configurado. Set DEEPSEEK_API_KEY")

    suffix = os.path.splitext(file.filename or ".ogg")[1] or ".ogg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    # Notifica recebimento
    now = datetime.now().strftime("%d/%m/%Y às %H:%M")
    _telegram_send_message(target_chat_id, f"🎙️ *RECORD-AI*\n\n📥 Áudio de *{now}* recebido. Iniciando processamento...")

    # Processa em background (sem await, para responder rápido à extensão)
    import threading
    thread = threading.Thread(target=_process_meeting, args=(tmp_path, file.filename, x_api_key, target_chat_id))
    thread.start()

    return {
        "ok": True,
        "message": "Áudio recebido. Acompanhe o processamento no Telegram."
    }


# Endpoints antigos mantidos para compatibilidade
@app.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(None),
    x_hash_id: Optional[str] = Header(None)
):
    """
    Recebe áudio da extensão e envia pro Telegram como voice note.
    Header opcional X-Hash-Id escolhe qual conversa configurada recebe o áudio.
    """
    verify_api_key(x_api_key)

    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot não configurado no servidor")

    target_chat_id = _resolve_chat_id(x_hash_id)

    suffix = os.path.splitext(file.filename or ".ogg")[1] or ".ogg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"
        with open(tmp_path, "rb") as f:
            files = {"voice": (f"RECORD-AI_{os.path.basename(tmp_path)}", f, "audio/ogg")}
            data = {
                "chat_id": target_chat_id,
                "caption": "🎙️ Gravação RECORD-AI"
            }
            resp = requests.post(url, data=data, files=files, timeout=60)

        result = resp.json()
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail=result.get("description", "Erro Telegram"))

        return {"ok": True, "message": "Áudio enviado para o Telegram", "telegram_message_id": result["result"]["message_id"]}

    finally:
        os.remove(tmp_path)


def _telegram_get_file_path(file_id: str) -> str:
    """Obtem o file_path de um arquivo no Telegram via getFile."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
    resp = requests.post(url, json={"file_id": file_id}, timeout=30)
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Erro ao obter arquivo do Telegram"))
    return result["result"]["file_path"]


def _telegram_download_file(file_id: str) -> str:
    """Baixa um arquivo do Telegram e retorna o caminho temporario local."""
    file_path = _telegram_get_file_path(file_id)
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    suffix = os.path.splitext(file_path)[1] or ".ogg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(resp.content)
        return tmp.name


@app.post("/webhook/telegram")
async def telegram_webhook(
    update: dict,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None)
):
    """
    Webhook chamado pelo Telegram quando o bot recebe uma mensagem.
    Se a mensagem contiver áudio, inicia o fluxo completo de organização de reunião.
    """
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot nao configurado no servidor")

    if not TELEGRAM_CHAT_IDS:
        raise HTTPException(status_code=500, detail="TELEGRAM_CHAT_ID nao configurado")

    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return {"ok": True}

    # Aceita áudio de qualquer conversa configurada no env
    if str(chat_id) not in TELEGRAM_CHAT_IDS:
        return {"ok": True}

    audio = message.get("voice") or message.get("audio")
    if not audio:
        return {"ok": True}

    if not whisper_model:
        _telegram_send_message(chat_id, "🤷 Transcrição nao habilitada no servidor.")
        return {"ok": True}

    file_id = audio["file_id"]

    try:
        tmp_path = _telegram_download_file(file_id)

        # Inicia o fluxo completo de reunião em background
        import threading
        thread = threading.Thread(target=_process_meeting, args=(tmp_path, "telegram_audio.ogg", None, str(chat_id)))
        thread.start()

        return {"ok": True, "message": "Áudio recebido. Processamento da reunião iniciado."}

    except Exception as e:
        error_detail = traceback.format_exc()
        print(error_detail)
        _telegram_send_message(chat_id, f"❌ *RECORD-AI*\n\nErro ao receber áudio:\n```{str(e)[:500]}```")
        return {"ok": False, "error": str(e)}
