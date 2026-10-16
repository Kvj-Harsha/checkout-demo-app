"""Point the app at the repository's own pricing module unless a test overrides it."""

from pathlib import Path

import pytest

from app import main


@pytest.fixture(autouse=True)
def repo_pricing(monkeypatch):
    monkeypatch.setattr(main, "PRICING_PATH", Path(main.__file__).resolve().parent / "pricing.py")
    main._PRICING_CACHE.update(stamp=None, module=None)
