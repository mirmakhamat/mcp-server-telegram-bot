# telegram-mcp

MCP server that lets AI agents send Telegram messages and files through your own bot.
The token is read from the environment and never reaches the agent.

## Setup
1. Create a bot with @BotFather and copy its token.
2. Send `/start` to your bot from the chat that should receive messages.
3. Install and register (replace the placeholders):

```
claude mcp add telegram \
  -e TELEGRAM_BOT_TOKEN=<token> \
  -e ALLOWED_CHAT_IDS=<chat_id> \
  -e ALLOWED_DIRS=<dir1>,<dir2> \
  -- uvx telegram-mcp
```

Don't know your chat id? Register with a temporary `ALLOWED_CHAT_IDS=0`, ask the agent to run `get_updates`, then re-register with the real id.

## Environment
| Variable | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token (required) |
| `ALLOWED_CHAT_IDS` | Comma-separated chat ids; first is default (required) |
| `ALLOWED_DIRS` | Comma-separated directories files may be sent from. Empty = file sending disabled |

## Tools
`send_message(text, chat_id?)`, `send_document(path, caption?, chat_id?)`, `send_photo(path, caption?, chat_id?)`, `get_updates(limit?)`

## Safety
- Other chat ids are rejected.
- Paths are resolved with `realpath` (blocks `..` and symlinks) and must be inside `ALLOWED_DIRS`.
- `.env*`, `.ssh`, `.gnupg`, `.aws` are never sent. Max file size 50 MB.
- Use one bot per user: two programs polling `getUpdates` on one bot interfere.

## Development
```
uv sync && uv run pytest
```
