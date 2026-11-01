import json
import os
from dataclasses import dataclass, field

MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
BLOCKED_DIRS = {".ssh", ".gnupg", ".aws"}


class ConfigError(Exception):
    pass


class DeniedError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str
    chat_ids: tuple[str, ...]
    dirs: tuple[str, ...]
    names: dict = field(default_factory=dict)  # lowercase name -> chat id


def parse_chat(entry: str) -> tuple[str | None, str]:
    """'ali=123' -> ('ali', '123'); '123' -> (None, '123')."""
    name, sep, cid = entry.rpartition("=")
    return (name.strip() or None, cid.strip()) if sep else (None, entry.strip())


def _chats(entries) -> tuple[tuple[str, ...], dict]:
    ids, names = [], {}
    for e in entries:
        name, cid = parse_chat(e)
        if cid not in ids:
            ids.append(cid)
        if name:
            names[name.lower()] = cid
    return tuple(ids), names


def _split(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in value.split(",") if p.strip())


def load_config(env=os.environ) -> Config:
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids, names = _chats(_split(env.get("ALLOWED_CHAT_IDS", "")))
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is not set")
    if not chat_ids:
        raise ConfigError("ALLOWED_CHAT_IDS is not set")
    dirs = tuple(os.path.realpath(os.path.expanduser(d)) for d in _split(env.get("ALLOWED_DIRS", "")))
    return Config(token, chat_ids, dirs, names)


def resolve_chat(cfg: Config, chat_id: str | int | None) -> str:
    if chat_id is None or str(chat_id) == "":
        return cfg.chat_ids[0]
    key = str(chat_id).strip()
    key = cfg.names.get(key.lower(), key)
    if key not in cfg.chat_ids:
        raise DeniedError("chat is not in ALLOWED_CHAT_IDS")
    return key


def check_path(cfg: Config, path: str) -> str:
    if not cfg.dirs:
        raise DeniedError("file sending is disabled: ALLOWED_DIRS is empty")
    real = os.path.realpath(os.path.expanduser(path))
    if not any(os.path.commonpath([real, d]) == d for d in cfg.dirs):
        raise DeniedError("path is outside ALLOWED_DIRS")
    parts = real.split(os.sep)
    if BLOCKED_DIRS & set(parts) or os.path.basename(real).startswith(".env"):
        raise DeniedError("path points to a protected file")
    if not os.path.isfile(real):
        raise DeniedError("not a regular file")
    if os.path.getsize(real) > MAX_BYTES:
        raise DeniedError("file is larger than 50 MB")
    return real


# Runtime additions (added via tools) live in a state file; env values stay the base.
def state_path() -> str:
    return os.path.expanduser(os.environ.get("TELEGRAM_MCP_STATE", "~/.config/telegram-mcp/state.json"))


def load_extra(path: str) -> dict:
    try:
        with open(path) as f:
            d = json.load(f)
        return {"chats": list(d.get("chats", [])), "dirs": list(d.get("dirs", []))}
    except (OSError, ValueError):
        return {"chats": [], "dirs": []}


def save_extra(path: str, extra: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(extra, f)


def merge(base: Config, extra: dict) -> Config:
    ids, names = _chats(extra["chats"])
    chats = base.chat_ids + tuple(c for c in ids if c not in base.chat_ids)
    dirs = base.dirs + tuple(d for d in extra["dirs"] if d not in base.dirs)
    return Config(base.token, chats, dirs, {**names, **base.names})


def validate_chat(chat_id: str) -> str:
    c = str(chat_id).strip()
    if not c.lstrip("-").isdigit():
        raise DeniedError("chat_id must be a numeric id")
    return c


def validate_name(name: str) -> str:
    n = name.strip()
    if not n.replace("_", "").replace("-", "").isalnum():
        raise DeniedError("name may contain only letters, digits, _ and -")
    return n


def validate_dir(path: str) -> str:
    real = os.path.realpath(os.path.expanduser(path))
    if real == os.sep or real == os.path.realpath(os.path.expanduser("~")):
        raise DeniedError("directory is too broad (root or home)")
    if BLOCKED_DIRS & set(real.split(os.sep)):
        raise DeniedError("directory is protected")
    if not os.path.isdir(real):
        raise DeniedError("not a directory")
    return real
