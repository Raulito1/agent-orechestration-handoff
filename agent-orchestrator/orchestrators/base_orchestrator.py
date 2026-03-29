import os
from pathlib import Path

import anthropic
import yaml

from connectors.base_connector import BaseConnector
from connectors.bitbucket_connector import BitbucketConnector
from connectors.local_connector import LocalConnector

_CONFIG_DIR = Path(__file__).parent.parent / "config"


class BaseOrchestrator:
    """Loads apps config and provides shared helpers for all orchestrators."""

    def __init__(self) -> None:
        self._apps: list[dict] = self._load_apps()
        self._connector: BaseConnector = self._pick_connector()

    def _load_apps(self) -> list[dict]:
        apps_path = _CONFIG_DIR / "apps.yaml"
        with apps_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data["apps"]

    def _pick_connector(self) -> BaseConnector:
        if os.environ.get("LOCAL", "").lower() == "true":
            return LocalConnector(self._apps)
        return BitbucketConnector(self._apps)

    @property
    def connector(self) -> BaseConnector:
        return self._connector

    def get_app(self, app_id: str) -> dict:
        """Return the apps.yaml entry for the given app_id, or raise KeyError."""
        for app in self._apps:
            if app["id"] == app_id:
                return app
        raise KeyError(f"Unknown app_id '{app_id}'. Available: {[a['id'] for a in self._apps]}")

    def load_context(self, context_path: str) -> str:
        """Read a context markdown file from config/contexts/."""
        full_path = _CONFIG_DIR / context_path
        return full_path.read_text(encoding="utf-8")

    def get_anthropic_client(self) -> anthropic.Anthropic:
        # API key is read automatically from ANTHROPIC_API_KEY env var by the SDK.
        return anthropic.Anthropic()
