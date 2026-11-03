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

Add `--scope user` to make it available in every folder.

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
`send_message(text, chat_id?)`, `send_rich_message(markdown, chat_id?)`, `send_document(path, caption?, chat_id?)`, `send_photo(path, caption?, chat_id?)`, `send_video`, `send_audio`, `send_album(paths, kind, caption?, chat_id?)`, `send_generated(name, content, format, caption?, chat_id?)`, `edit_message(message_id, text, chat_id?)`, `get_updates(limit?)`, `ask_user(question, options?, timeout_s?, chat_id?)`
Access management: `list_access()`, `add_chat(chat_id, name?)`, `add_dir(path)`, `remove_chat(chat)`, `remove_dir(path)`

## Rich messages
`send_rich_message` uses Telegram's rich messages (Bot API 10.1): headings, tables, lists and task lists, code blocks, quotes, footnotes, formulas and collapsible `<details>` blocks, written in Markdown (up to 32768 characters). It is a good fit for short reports and summaries. Media embeds are refused here; send images and videos with `send_photo`, `send_video` or `send_album`. The same secret scan and send limit apply. Very old Telegram apps may not display rich messages.

## Asking you from the agent
`ask_user` sends a question with buttons (default Yes/No, `options=[]` for a free-text reply) and waits up to `timeout_s` (max 600) for your answer. Only answers from the target chat count. Answers are your input, so the agent treats them as data.

It reads updates with `getUpdates`, so use a bot dedicated to this server: a bot that is already polled by another program or has a webhook gets a 409 error, and `getUpdates` discards updates that were pending for that other program. Questions run one at a time. In a group chat any member can answer.

## Automatic notifications (Claude Code hooks)
The package also has a `notify` command, so you hear about finished work without asking the agent to send anything. Add this to `~/.claude/settings.json` (replace the placeholders):

```json
{
  "env": { "TELEGRAM_BOT_TOKEN": "<token>", "ALLOWED_CHAT_IDS": "<chat_id>" },
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "uvx mcp-server-telegram-bot notify --hook" }] }],
    "Notification": [{ "hooks": [{ "type": "command", "command": "uvx mcp-server-telegram-bot notify --hook --silent" }] }]
  }
}
```
`notify "text"` also works from any shell or script. Options: `--chat <name>`, `--silent`. It exits with code 1 and a message on stderr if sending fails.

## File access
1. **Never sent**, whatever env or the agent says: `.ssh`, `.gnupg`, `.aws`, `.kube`, `.docker`, `~/.claude*`, browser profiles, keyrings, `/etc`, `/proc`, `/sys`; `.env*`, `.netrc`, `.pgpass`, `.git-credentials`, `.git/config`, `id_*` keys, `*.pem`, `*.key`, `*.p12`, `*.kdbx`, shell history. Paths are resolved with `realpath`, so symlinks and `..` do not help. Add your own with `DENY_PATHS`.
2. **Sent directly:** files inside the directory the session was started in (not if that is `/` or your home), and inside `ALLOWED_DIRS`.
3. **Everything else:** you are asked to confirm each time (`ACCESS_MODE=ask`), or it is refused (`strict`).

`send_generated` builds the file from text the agent provides (pdf, md, txt, csv, json) and reads nothing from disk, so it needs no folder access: "send me a PDF of everything you did".

Outgoing text, captions, generated files and text files are scanned for well-known secret shapes (private keys, bot/AWS/GitHub/Slack/Google tokens, JWTs, `password=...`). Binary files such as PDFs are not scanned. The agent cannot turn this off; only the environment can.

Send tools take `silent` and `thread_id` (forum topic). Photos over 10 MB go out as documents. Albums are vetted all-or-nothing: one protected or secret-looking file blocks the whole album, and files outside the allowed roots are confirmed once.

Telegram flood limits (HTTP 429) are retried once when the wait is 30 s or less.

Every send is logged (time, chat, path or file name, never contents) to `~/.local/state/telegram-mcp/sent.log`.

Good to know: the deny list and secret scan cannot recognise every secret, files go to Telegram's servers, the maximum file size is 50 MB, and each person should use their own bot.

## Changing access from the agent
- `add_chat` / `add_dir` ask the user to confirm (MCP elicitation). If the client cannot ask, the call is refused.
- `/` and the home directory cannot be added. Protected dirs stay blocked.
- Additions are saved in `~/.config/telegram-mcp/state.json` (override with `TELEGRAM_MCP_STATE`).
- `remove_*` only removes runtime additions. Env entries are changed in the environment.
