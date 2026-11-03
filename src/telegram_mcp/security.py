import fnmatch
import json
import os
from dataclasses import dataclass, field, replace

MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
# Never sendable, whatever env or the user says.
BLOCKED_DIRS = {".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store"}
BLOCKED_HOME = (
    ".config/gcloud", ".config/telegram-mcp", ".local/state/telegram-mcp", ".local/share/keyrings",
    ".claude", ".mozilla", ".config/google-chrome", ".config/chromium", ".config/BraveSoftware",
)
BLOCKED_ABS = ("/etc", "/proc", "/sys", "/dev", "/boot", "/root")
BLOCKED_NAMES = (
    ".env*", ".netrc", ".pgpass", ".git-credentials", "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", ".bash_history", ".zsh_history", ".claude.json",
    "credentials", "credentials.json",
)


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
    session_dir: str = ""  # auto-allowed; empty when the session runs in / or home
    mode: str = "ask"  # ask = confirm files outside allowed roots, strict = refuse them
    deny: tuple[str, ...] = ()  # extra user-defined blocked paths


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


def load_config(env=os.environ, cwd: str | None = None) -> Config:
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids, names = _chats(_split(env.get("ALLOWED_CHAT_IDS", "")))
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is not set")
    if not chat_ids:
        raise ConfigError("ALLOWED_CHAT_IDS is not set")
    dirs = tuple(os.path.realpath(os.path.expanduser(d)) for d in _split(env.get("ALLOWED_DIRS", "")))
    mode = env.get("ACCESS_MODE", "ask").strip().lower()
    if mode not in ("ask", "strict"):
        raise ConfigError("ACCESS_MODE must be 'ask' or 'strict'")
    session = os.path.realpath(cwd or os.getcwd())
    if session in (os.sep, os.path.realpath(os.path.expanduser("~"))):
        session = ""
    deny = tuple(os.path.realpath(os.path.expanduser(d)) for d in _split(env.get("DENY_PATHS", "")))
    return Config(token, chat_ids, dirs, names, session, mode, deny)


def resolve_chat(cfg: Config, chat_id: str | int | None) -> str:
    if chat_id is None or str(chat_id) == "":
        return cfg.chat_ids[0]
    key = str(chat_id).strip()
    key = cfg.names.get(key.lower(), key)
    if key not in cfg.chat_ids:
        raise DeniedError("chat is not in ALLOWED_CHAT_IDS")
    return key


def _under(real: str, root: str) -> bool:
    return os.path.commonpath([real, root]) == root


def is_blocked(cfg: Config, real: str) -> bool:
    home = os.path.realpath(os.path.expanduser("~"))
    parts = real.split(os.sep)
    if BLOCKED_DIRS & set(parts):
        return True
    if any(_under(real, os.path.join(home, h)) for h in BLOCKED_HOME):
        return True
    if any(_under(real, a) for a in BLOCKED_ABS) or any(_under(real, d) for d in cfg.deny):
        return True
    if any(fnmatch.fnmatch(parts[-1], n) for n in BLOCKED_NAMES):
        return True
    return ".git" in parts[:-1] and parts[-1] == "config"


def check_path(cfg: Config, path: str) -> str:
    """Return the real path, or raise if it is protected, missing or too large."""
    real = os.path.realpath(os.path.expanduser(path))
    if is_blocked(cfg, real):
        raise DeniedError("path points to a protected file")
    if not os.path.isfile(real):
        raise DeniedError("not a regular file")
    if os.path.getsize(real) > MAX_BYTES:
        raise DeniedError("file is larger than 50 MB")
    return real


def is_inside(cfg: Config, real: str) -> bool:
    """True when the file may be sent without asking: ALLOWED_DIRS or the session directory."""
    roots = cfg.dirs + ((cfg.session_dir,) if cfg.session_dir else ())
    return any(_under(real, r) for r in roots)


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
    return replace(base, chat_ids=chats, dirs=dirs, names={**names, **base.names})


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


def validate_dir(cfg: Config, path: str) -> str:
    real = os.path.realpath(os.path.expanduser(path))
    if real == os.sep or real == os.path.realpath(os.path.expanduser("~")):
        raise DeniedError("directory is too broad (root or home)")
    if is_blocked(cfg, real):
        raise DeniedError("directory is protected")
    if not os.path.isdir(real):
        raise DeniedError("not a directory")
    return real
