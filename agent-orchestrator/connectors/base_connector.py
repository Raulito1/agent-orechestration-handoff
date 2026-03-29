from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Abstract interface that all connectors must implement."""

    @abstractmethod
    async def get_file(self, repo_id: str, file_path: str) -> str | None:
        """Return the contents of a file, or None if not found."""
        ...

    @abstractmethod
    async def list_files(
        self, repo_id: str, directory: str, extension: str | None = None
    ) -> list[str]:
        """Return a list of file paths under directory, optionally filtered by extension."""
        ...

    @abstractmethod
    async def post_pr_comment(self, repo_id: str, pr_id: str, body: str) -> bool:
        """Post a comment on a pull request. Returns True on success."""
        ...
