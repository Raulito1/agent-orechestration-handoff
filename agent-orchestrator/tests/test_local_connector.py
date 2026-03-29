import pytest

from connectors.local_connector import LocalConnector

_APPS = [
    {
        "id": "peekr",
        "local": {"api_path": "/fake/peekr-api", "web_path": "/fake/peekr-web"},
        "bitbucket": {"workspace": "ws-b", "api_repo": "peekr-api", "web_repo": "peekr-web"},
    }
]


@pytest.fixture()
def connector(tmp_path):
    # Build a small fake repo on disk under tmp_path.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("# util", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Peekr", encoding="utf-8")

    apps = [
        {
            "id": "peekr",
            "local": {"api_path": str(tmp_path), "web_path": "/fake/peekr-web"},
        }
    ]
    return LocalConnector(apps)


async def test_get_file_returns_content(connector):
    content = await connector.get_file("peekr-api", "src/main.py")
    assert content == "print('hello')"


async def test_get_file_returns_none_for_missing(connector):
    result = await connector.get_file("peekr-api", "does/not/exist.py")
    assert result is None


async def test_list_files_no_filter(connector):
    files = await connector.list_files("peekr-api", "src")
    assert "src/main.py" in files
    assert "src/util.py" in files


async def test_list_files_extension_filter(connector):
    files = await connector.list_files("peekr-api", "src", extension=".py")
    assert all(f.endswith(".py") for f in files)
    assert len(files) == 2


async def test_list_files_returns_empty_for_missing_dir(connector):
    files = await connector.list_files("peekr-api", "nonexistent")
    assert files == []


async def test_post_pr_comment_is_noop(connector):
    result = await connector.post_pr_comment("peekr-api", "42", "LGTM")
    assert result is True


def test_unknown_repo_raises():
    c = LocalConnector(_APPS)
    with pytest.raises(KeyError):
        import asyncio
        asyncio.run(c.get_file("unknown-repo", "file.py"))
