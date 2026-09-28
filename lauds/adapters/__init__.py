"""Adapter plugins: one module per provider in this package.

The protocol (duck-typed; see `Adapter` below):

- `NAME: str` - the source name, used as `Item.source` and on the command
  line (`lauds login <NAME>`, `lauds sync <NAME>`). By convention the
  module name (e.g. module `canvas_ics`, NAME "canvas_ics").
- `DESCRIPTION: str` (optional) - one line for `lauds status`.
- `login(**opts) -> None` (optional) - interactive login for sites that
  need a session; most use `lauds.session.login`.
- `fetch(**opts) -> lauds.models.Bundle` - the network part: get raw bodies,
  hand them to the parse functions, return one Bundle.
- pure parse functions (names are the adapter's choice, e.g.
  `parse_assignments(raw: str | bytes | dict, ...) -> list[Item]`): no
  network, no clock unless `now=` is passed in, no globals. Parity tests
  replay raw fixtures through these.

Discovery is by module listing: drop a file here and it's an adapter.
Nothing outside this package names a provider.
"""
import importlib
import inspect
import pkgutil
from types import ModuleType
from typing import Callable, Protocol, runtime_checkable

from lauds.models import Bundle


@runtime_checkable
class Adapter(Protocol):
    NAME: str
    fetch: Callable[..., Bundle]


# Modules that failed to import, name -> error string, so one broken adapter
# never takes the CLI down; `lauds status` can show these.
load_errors: dict[str, str] = {}
_cache: dict[str, ModuleType] | None = None


def _discover() -> dict[str, ModuleType]:
    global _cache
    if _cache is not None:
        return _cache
    found: dict[str, ModuleType] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue  # private helpers shared between adapters
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as e:  # noqa: BLE001 - isolate every plugin
            load_errors[info.name] = f"{type(e).__name__}: {e}"
            continue
        name = getattr(mod, "NAME", None)
        if not isinstance(name, str) or not callable(getattr(mod, "fetch", None)):
            load_errors[info.name] = "not an adapter (needs NAME and fetch())"
            continue
        found[name] = mod
    _cache = found
    return found


def names() -> list[str]:
    return sorted(_discover())


def get(name: str) -> ModuleType:
    try:
        return _discover()[name]
    except KeyError:
        err = load_errors.get(name)
        raise KeyError(f"unknown adapter {name!r}" + (f" (failed to load: {err})" if err else "")
                       + f"; known: {', '.join(names()) or 'none'}") from None


def all_adapters() -> dict[str, ModuleType]:
    return dict(_discover())


def needs_login(name: str) -> bool:
    return callable(getattr(get(name), "login", None))


def reset() -> None:
    """Forget discovered modules (tests)."""
    global _cache
    _cache = None
    load_errors.clear()


def fill_kwargs(fn: Callable, cfg: dict) -> tuple[dict, list[str]]:
    """Match a config dict (the CLI's per-source `config set`/`login --opt`
    store) against `fn`'s own parameter names, so `login`/`fetch` get driven
    by real config instead of always being called with zero arguments
    (BRIEF blocker: "9 of its 11 adapters" couldn't be driven at all - every
    adapter has a different `login`/`fetch` signature, and nothing outside
    an adapter is allowed to special-case one, so this reads the signature
    itself rather than a hand-maintained per-adapter key list).

    Returns `(kwargs, missing)`: `kwargs` is `{name: cfg[name]}` for every
    named parameter `fn` accepts that `cfg` also has a value for (`**opts`/
    `*args` are never matched by name, so they're left for the caller);
    `missing` lists parameters with no default and no matching `cfg` entry -
    the caller turns that into a clear "needs config: ..." error instead of
    a bare `TypeError: fetch() missing ... argument`."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}, []
    kwargs: dict = {}
    missing: list[str] = []
    for name, p in params.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if name in cfg:
            kwargs[name] = cfg[name]
        elif p.default is p.empty:
            missing.append(name)
    return kwargs, missing
