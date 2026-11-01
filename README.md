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
| `ALLOWED_CHAT_IDS` | Comma-separated chats, each `id` or `name=id` (e.g. `me=111,ali=222`); first is default (required) |
| `ALLOWED_DIRS` | Comma-separated directories files may be sent from. Empty = file sending disabled |

## Typical use
- "Send `report.pdf` to me when you finish" -> `send_document(path)` to the default chat.
- "Send the result to Ali" -> `send_message(text, chat_id="ali")`.
- A person can only receive messages after they open the bot and press Start. Telegram blocks the bot otherwise.

## Tools
`send_message(text, chat_id?)`, `send_document(path, caption?, chat_id?)`, `send_photo(path, caption?, chat_id?)`, `get_updates(limit?)`
Access management: `list_access()`, `add_chat(chat_id, name?)`, `add_dir(path)`, `remove_chat(chat)`, `remove_dir(path)`

## Safety
- Other chat ids are rejected.
- Paths are resolved with `realpath` (blocks `..` and symlinks) and must be inside `ALLOWED_DIRS`.
- `.env*`, `.ssh`, `.gnupg`, `.aws` are never sent. Max file size 50 MB.
- Use one bot per user: two programs polling `getUpdates` on one bot interfere.

## Changing access from the agent
- `add_chat` / `add_dir` ask the user to confirm (MCP elicitation). If the client cannot ask, the call is refused.
- `/` and the home directory cannot be added. Protected dirs stay blocked.
- Additions are saved in `~/.config/telegram-mcp/state.json` (override with `TELEGRAM_MCP_STATE`).
- `remove_*` only removes runtime additions. Env entries are changed in the environment.

## Development
```
uv sync && uv run pytest
```
