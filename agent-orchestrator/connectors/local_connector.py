import logging
from pathlib import Path

from connectors.base_connector import BaseConnector

logger = logging.getLogger(__name__)


class LocalConnector(BaseConnector):
    """Reads files from local disk paths resolved via apps config."""

    def __init__(self, apps: list[dict]) -> None:
        # Build repo_id → local path index for both api and web repos.
        # Each app exposes two logical "repos": {id}-api and {id}-web.
        self._paths: dict[str, Path] = {}
        for app in apps:
            local = app.get("local", {})
            app_id = app["id"]
            if api_path := local.get("api_path"):
                self._paths[f"{app_id}-api"] = Path(api_path)
            if web_path := local.get("web_path"):
                self._paths[f"{app_id}-web"] = Path(web_path)

    def _resolve(self, repo_id: str) -> Path:
        if repo_id not in self._paths:
            raise KeyError(f"Unknown repo_id '{repo_id}'. Available: {list(self._paths)}")
        return self._paths[repo_id]

    async def get_file(self, repo_id: str, file_path: str) -> str | None:
        base = self._resolve(repo_id)
        full_path = base / file_path
        if not full_path.exists():
            return None
        return full_path.read_text(encoding="utf-8")

    async def list_files(
        self, repo_id: str, directory: str, extension: str | None = None
    ) -> list[str]:
        base = self._resolve(repo_id)
        target = base / directory
        if not target.exists():
            return []
        paths = target.rglob(f"*{extension}" if extension else "*")
        return [str(p.relative_to(base)) for p in paths if p.is_file()]

    async def post_pr_comment(self, repo_id: str, pr_id: str, body: str) -> bool:
        # No-op locally — log the comment body so it's visible during development.
        logger.info("[LOCAL] PR comment on %s PR#%s:\n%s", repo_id, pr_id, body)
        return True
