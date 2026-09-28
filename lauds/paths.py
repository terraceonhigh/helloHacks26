"""Where lauds keeps things. Data: ~/.local/share/lauds/lauds.db; sessions and
config: ~/.config/lauds/. Dirs 0700, files 0600. `LAUDS_HOME=<dir>` puts
everything (db, sessions, config) under that one directory - tests and
throwaway runs use it.
"""
import json
import os
from pathlib import Path

# ponytail: no XDG_DATA_HOME / XDG_CONFIG_HOME support - fixed ~/.local/share
# and ~/.config. Honour the XDG vars here if someone's layout needs it.


def _home_override() -> Path | None:
    v = os.environ.get("LAUDS_HOME")
    return Path(v).expanduser() if v else None


def data_dir() -> Path:
    return _home_override() or Path.home() / ".local" / "share" / "lauds"


def config_dir() -> Path:
    return _home_override() or Path.home() / ".config" / "lauds"


def db_path() -> Path:
    return data_dir() / "lauds.db"


def state_path(site: str) -> Path:
    """Saved browser session (Playwright storage_state) for one adapter."""
    return config_dir() / f"{site}-state.json"


def ensure_dir(path: Path) -> Path:
    """mkdir -p with 0700 on the dirs we create (an existing dir is left alone)."""
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.chmod(0o700)  # mkdir's mode is masked by umask
        except OSError:  # e.g. /sdcard (no POSIX modes) - best effort
            pass
    return path


def secure_file(path: Path) -> Path:
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def secure_write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Write `text` to `path`, 0600 from the moment the file is created -
    never `write_text()` then `secure_file()`, which leaves the process
    umask's (often world-readable) mode on disk for the instant between the
    two calls. Not usable for a path a non-Python process (e.g. Playwright's
    own driver) writes to directly; `touch_secure` below covers that case
    instead."""
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, text.encode(encoding))
        finally:
            os.close(fd)
    except OSError:
        path.write_text(text, encoding=encoding)  # e.g. /sdcard: no POSIX modes
        secure_file(path)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    """The whole `~/.config/lauds/config.json` store: `{"<source>": {"<key>":
    "<value>", ...}, ...}` (per-adapter config, `lauds config set
    <source>.<key> <value>` / `lauds login <source> --opt k=v`) plus any
    older flat `<key>: <value>` entry from before that (`docs/cli.md`'s
    original `config set canvas-feed-url <url>` example) - callers that want
    one adapter's config use `adapter_config()` below, which only looks at
    the nested shape. Missing or unreadable comes back as `{}`, same as an
    adapter with nothing configured."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def adapter_config(source: str) -> dict:
    """One source's own config keys, `{}` if it has none configured."""
    val = load_config().get(source)
    return dict(val) if isinstance(val, dict) else {}


def save_adapter_config(source: str, opts: dict) -> Path:
    """Merge `opts` into `source`'s own config keys and write the store back,
    0600. Never removes a key `opts` doesn't mention."""
    path = config_path()
    ensure_dir(path.parent)
    data = load_config()
    existing = data.get(source)
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(opts)
    data[source] = merged
    secure_write_text(path, json.dumps(data, indent=2, sort_keys=True))
    return path


def touch_secure(path: Path) -> Path:
    """Ensure `path` exists and is 0600, without touching its content -
    for a file some other process (Playwright's driver, writing
    storage_state) will overwrite in place: opening an existing file for
    write doesn't reset its mode bits, only *creating* one does, so
    pre-creating it 0600 here closes the same race `secure_write_text`
    closes for our own writes."""
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
    except OSError:
        if not path.exists():
            path.touch()
    secure_file(path)
    return path
