import sys
import types

import pytest

from lauds import adapters


@pytest.fixture
def fake_pkg(tmp_path, monkeypatch):
    pkg = tmp_path / "plug"
    pkg.mkdir()
    (pkg / "good.py").write_text("NAME = 'good'\ndef fetch(**kw):\n    from lauds.models import Bundle\n    return Bundle()\n"
                                 "def login(**kw):\n    pass\n")
    (pkg / "nologin.py").write_text("NAME = 'nologin'\ndef fetch(**kw):\n    return None\n")
    (pkg / "broken.py").write_text("raise ImportError('missing dep')\n")
    (pkg / "helper.py").write_text("X = 1\n")
    (pkg / "_private.py").write_text("raise SystemExit('never imported')\n")
    monkeypatch.setattr(adapters, "__path__", [str(pkg)])
    monkeypatch.setattr(adapters, "__name__", "plugtest")
    mod = types.ModuleType("plugtest")
    mod.__path__ = [str(pkg)]
    monkeypatch.setitem(sys.modules, "plugtest", mod)
    adapters.reset()
    yield
    adapters.reset()


def test_discovery_by_module_listing(fake_pkg):
    assert adapters.names() == ["good", "nologin"]
    assert adapters.needs_login("good") and not adapters.needs_login("nologin")
    assert set(adapters.load_errors) == {"broken", "helper"}
    assert "missing dep" in adapters.load_errors["broken"]


def test_unknown_adapter_message(fake_pkg):
    with pytest.raises(KeyError, match="failed to load"):
        adapters.get("broken")
    with pytest.raises(KeyError, match="known: good, nologin"):
        adapters.get("nope")


def test_real_package_imports():
    adapters.reset()
    assert isinstance(adapters.names(), list)
