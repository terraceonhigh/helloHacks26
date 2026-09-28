"""Where lauds keeps things. Data: ~/.local/share/lauds/lauds.db; sessions and
config: ~/.config/lauds/. Dirs 0700, files 0600. `LAUDS_HOME=<dir>` puts
everything (db, sessions, config) under that one directory - tests and
throwaway runs use it.
"""
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
