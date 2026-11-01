# telegram-mcp

Telegram Bot API uchun MCP server. AI agentlar (Claude Code va b.) foydalanuvchiga xabar va fayl yuborishi uchun.

## Maqsad
Agent uzoq ishni tugatib natijani Telegramga yuboradi. Token agent kontekstiga tushmaydi, server env'dan o'qiydi.

## MVP vositalar
- `send_message(text, chat_id?)`
- `send_document(path, caption?, chat_id?)`
- `send_photo(path, caption?, chat_id?)`
- keyinroq: `get_updates` (agent foydalanuvchidan javob kutishi uchun)

## Texnik qarorlar
- Python + rasmiy `mcp` SDK (FastMCP), transport stdio
- Telegram bilan `httpx` orqali Bot API (qo'shimcha kutubxona yo'q)
- Ulash: `claude mcp add telegram -- python server.py`

## Xavfsizlik (majburiy)
- `ALLOWED_CHAT_IDS` (env): boshqa chat_id rad etiladi. chat_id berilmasa birinchisi default.
- `send_document`/`send_photo`: faqat `ALLOWED_DIRS` (env) ichidagi fayllar. Yo'l `realpath` bilan tekshiriladi (symlink/`..` hiylasiga qarshi). `~/.ssh`, `.env` kabilar hech qachon.
- Fayl hajmi <= 50 MB (Bot API chegarasi).
- Token faqat env'da (`TELEGRAM_BOT_TOKEN`), loglarga va xato matniga chiqmasin.

## Env o'zgaruvchilar
`TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_IDS` (vergul bilan), `ALLOWED_DIRS` (vergul bilan)
Namuna `.env.example` ga yoziladi; haqiqiy `.env` git'ga kirmaydi.

## Fon
Bot Bot API orqali `curl` bilan sendMessage/sendDocument ishlashi tekshirilgan (HTTP 200). Sinov uchun foydalanuvchi o'z botini beradi.

## Keyingi qadam
MVP tayyor (security, telegram, server, test). Qoldi: real bot bilan sinov, PyPI.
