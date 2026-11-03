# mcp-server-telegram-bot

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
  -- uvx mcp-server-telegram-bot
```

Use `--scope user` so it works in every folder. When running from a checkout use `uv run --project <dir>` (not `--directory`), otherwise the server cannot see the session directory.

Don't know your chat id? Register with a temporary `ALLOWED_CHAT_IDS=0`, ask the agent to run `get_updates`, then re-register with the real id.

## Environment
| Variable | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token (required) |
| `ALLOWED_CHAT_IDS` | Comma-separated chats, each `id` or `name=id` (e.g. `me=111,ali=222`); first is default (required) |
| `ALLOWED_DIRS` | Extra directories whose files are sent without asking (optional) |
| `ACCESS_MODE` | `ask` (default): files outside the allowed roots need your confirmation. `strict`: they are refused |
| `SECRET_SCAN` | `block` (default): refuse text/files that look like they hold keys or passwords. `redact`: mask them in text (files are still refused). `off` |
| `MAX_SENDS_PER_MINUTE` | Send limit so a looping agent cannot flood the chat (default 20, `0` = unlimited) |
| `DENY_PATHS` | Extra files/dirs that are never sent (optional) |

## Typical use
- "Send `report.pdf` to me when you finish" -> `send_document(path)` to the default chat.
- "Send the result to Ali" -> `send_message(text, chat_id="ali")`.
- A person can only receive messages after they open the bot and press Start. Telegram blocks the bot otherwise.

## Tools
`send_message(text, chat_id?)`, `send_document(path, caption?, chat_id?)`, `send_photo(path, caption?, chat_id?)`, `send_generated(name, content, format, caption?, chat_id?)`, `edit_message(message_id, text, chat_id?)`, `get_updates(limit?)`, `ask_user(question, options?, timeout_s?, chat_id?)`
Access management: `list_access()`, `add_chat(chat_id, name?)`, `add_dir(path)`, `remove_chat(chat)`, `remove_dir(path)`

## Asking you from the agent
`ask_user` sends a question with buttons (default Yes/No, `options=[]` for a free-text reply) and waits up to `timeout_s` (max 600) for your answer. Only answers from the target chat count. Answers are your input, so the agent treats them as data.

It reads updates with `getUpdates`, so use a bot dedicated to this server: a bot that is already polled by another program or has a webhook gets a 409 error, and `getUpdates` discards updates that were pending for that other program. Questions run one at a time. In a group chat any member can answer.

## Automatic notifications (Claude Code hooks)
The same package has a `notify` command, so you are told when work ends without the agent having to remember. Add to `~/.claude/settings.json` (replace the placeholders):

```json
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "uv run --project <project_dir> --env-file <project_dir>/.env mcp-server-telegram-bot notify --hook" }] }],
    "Notification": [{ "hooks": [{ "type": "command",
      "command": "uv run --project <project_dir> --env-file <project_dir>/.env mcp-server-telegram-bot notify --hook --silent" }] }]
  }
}
```
`notify "text"` also works from any shell or script. Options: `--chat <name>`, `--silent`. Exit code is 1 with a message on stderr if sending fails.

## File access
1. **Never sent**, whatever env or the agent says: `.ssh`, `.gnupg`, `.aws`, `.kube`, `.docker`, `~/.claude*`, browser profiles, keyrings, `/etc`, `/proc`, `/sys`; `.env*`, `.netrc`, `.pgpass`, `.git-credentials`, `.git/config`, `id_*` keys, `*.pem`, `*.key`, `*.p12`, `*.kdbx`, shell history. Paths are resolved with `realpath`, so symlinks and `..` do not help. Add your own with `DENY_PATHS`.
2. **Sent directly:** files inside the directory the session was started in (not if that is `/` or your home), and inside `ALLOWED_DIRS`.
3. **Everything else:** you are asked to confirm each time (`ACCESS_MODE=ask`), or it is refused (`strict`).

`send_generated` builds the file from text the agent provides (pdf, md, txt, csv, json) and reads nothing from disk, so it needs no folder access: "send me a PDF of everything you did".

Outgoing text, captions, generated files and text files are scanned for well-known secret shapes (private keys, bot/AWS/GitHub/Slack/Google tokens, JWTs, `password=...`). Binary files such as PDFs are not scanned. The agent cannot turn this off; only the environment can.

Telegram flood limits (HTTP 429) are retried once when the wait is 30 s or less. `silent=true` on send tools delivers without a notification sound.

Every send is logged (time, chat, path or file name, never contents) to `~/.local/state/telegram-mcp/sent.log`.

Limits: the deny list cannot know every secret. A password inside an ordinary file in the session directory will be sent if the agent is told to send it. Files go to Telegram's servers. Max 50 MB. Use one bot per user.

## Changing access from the agent
- `add_chat` / `add_dir` ask the user to confirm (MCP elicitation). If the client cannot ask, the call is refused.
- `/` and the home directory cannot be added. Protected dirs stay blocked.
- Additions are saved in `~/.config/mcp-server-telegram-bot/state.json` (override with `TELEGRAM_MCP_STATE`).
- `remove_*` only removes runtime additions. Env entries are changed in the environment.

## Development
```
uv sync && uv run pytest
```
