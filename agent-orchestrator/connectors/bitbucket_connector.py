import asyncio
import logging
import os
from pathlib import PurePosixPath

import httpx

from connectors.base_connector import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_COMMIT = "HEAD"
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


class BitbucketConnector(BaseConnector):
    """Reads files via the Bitbucket Cloud REST API v2 and posts PR comments."""

    def __init__(self, apps: list[dict]) -> None:
        self._base_url = os.environ["BITBUCKET_BASE_URL"].rstrip("/")
        self._auth = (
            os.environ["BITBUCKET_USERNAME"],
            os.environ["BITBUCKET_APP_PASSWORD"],
        )
        # repo_id → {workspace, repo_slug} for both api and web repos
        self._repos: dict[str, dict] = {}
        for app in apps:
            bb = app.get("bitbucket", {})
            app_id = app["id"]
            workspace = bb.get("workspace", "")
            if api_repo := bb.get("api_repo"):
                self._repos[f"{app_id}-api"] = {"workspace": workspace, "slug": api_repo}
            if web_repo := bb.get("web_repo"):
                self._repos[f"{app_id}-web"] = {"workspace": workspace, "slug": web_repo}

    def _resolve(self, repo_id: str) -> dict:
        if repo_id not in self._repos:
            raise KeyError(f"Unknown repo_id '{repo_id}'. Available: {list(self._repos)}")
        return self._repos[repo_id]

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(auth=self._auth, timeout=30.0)

    async def _get_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response | None:
        """GET with exponential backoff on 429. Returns None on 404."""
        for attempt in range(_MAX_RETRIES):
            response = await client.get(url)
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("Rate limited. Retrying in %.1fs (attempt %d/%d).", delay, attempt + 1, _MAX_RETRIES)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            return response
        # Exhausted retries
        logger.error("Exhausted %d retries for %s", _MAX_RETRIES, url)
        return None

    async def get_file(self, repo_id: str, file_path: str) -> str | None:
        repo = self._resolve(repo_id)
        path = PurePosixPath(file_path)
        url = f"{self._base_url}/repositories/{repo['workspace']}/{repo['slug']}/src/{_DEFAULT_COMMIT}/{path}"
        async with self._make_client() as client:
            response = await self._get_with_retry(client, url)
        if response is None:
            return None
        return response.text

    async def list_files(
        self, repo_id: str, directory: str, extension: str | None = None
    ) -> list[str]:
        repo = self._resolve(repo_id)
        dir_path = PurePosixPath(directory)
        url = f"{self._base_url}/repositories/{repo['workspace']}/{repo['slug']}/src/{_DEFAULT_COMMIT}/{dir_path}/"
        async with self._make_client() as client:
            response = await self._get_with_retry(client, url)
        if response is None:
            return []
        data = response.json()
        paths: list[str] = []
        for entry in data.get("values", []):
            if entry.get("type") == "commit_file":
                p = entry["path"]
                if extension is None or p.endswith(extension):
                    paths.append(p)
        return paths

    async def post_pr_comment(self, repo_id: str, pr_id: str, body: str) -> bool:
        repo = self._resolve(repo_id)
        url = f"{self._base_url}/repositories/{repo['workspace']}/{repo['slug']}/pullrequests/{pr_id}/comments"
        payload = {"content": {"raw": body}}
        async with self._make_client() as client:
            response = await client.post(url, json=payload)
        if response.status_code in (200, 201):
            return True
        logger.error("Failed to post PR comment: %s %s", response.status_code, response.text)
        return False
