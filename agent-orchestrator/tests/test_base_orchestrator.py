import pytest

from connectors.bitbucket_connector import BitbucketConnector
from connectors.local_connector import LocalConnector
from orchestrators.base_orchestrator import BaseOrchestrator


@pytest.fixture()
def orchestrator(monkeypatch, tmp_path):
    """Return a BaseOrchestrator pointed at a minimal apps.yaml in tmp_path."""
    apps_yaml = tmp_path / "config" / "apps.yaml"
    apps_yaml.parent.mkdir(parents=True)
    apps_yaml.write_text(
        """
apps:
  - id: peekr
    name: Peekr
    stack: java-react
    local:
      api_path: /fake/peekr-api
      web_path: /fake/peekr-web
    bitbucket:
      workspace: workspace-b
      api_repo: peekr-api
      web_repo: peekr-web
    contexts:
      api: contexts/spring-boot.md
      web: contexts/react.md
""",
        encoding="utf-8",
    )

    # Patch _CONFIG_DIR so BaseOrchestrator reads from tmp_path.
    import orchestrators.base_orchestrator as mod
    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path / "config")
    return orchestrator_factory


def orchestrator_factory(monkeypatch, tmp_path, local_flag: str):
    import orchestrators.base_orchestrator as mod

    apps_yaml = tmp_path / "config" / "apps.yaml"
    apps_yaml.parent.mkdir(parents=True, exist_ok=True)
    apps_yaml.write_text(
        """
apps:
  - id: peekr
    name: Peekr
    stack: java-react
    local:
      api_path: /fake/peekr-api
      web_path: /fake/peekr-web
    bitbucket:
      workspace: workspace-b
      api_repo: peekr-api
      web_repo: peekr-web
    contexts:
      api: contexts/spring-boot.md
      web: contexts/react.md
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setenv("LOCAL", local_flag)
    if local_flag.lower() != "true":
        monkeypatch.setenv("BITBUCKET_BASE_URL", "https://api.bitbucket.org/2.0")
        monkeypatch.setenv("BITBUCKET_USERNAME", "u")
        monkeypatch.setenv("BITBUCKET_APP_PASSWORD", "p")
    return BaseOrchestrator()


def test_local_connector_selected(monkeypatch, tmp_path):
    o = orchestrator_factory(monkeypatch, tmp_path, "true")
    assert isinstance(o.connector, LocalConnector)


def test_bitbucket_connector_selected(monkeypatch, tmp_path):
    o = orchestrator_factory(monkeypatch, tmp_path, "false")
    assert isinstance(o.connector, BitbucketConnector)


def test_get_app_found(monkeypatch, tmp_path):
    o = orchestrator_factory(monkeypatch, tmp_path, "true")
    app = o.get_app("peekr")
    assert app["name"] == "Peekr"


def test_get_app_not_found(monkeypatch, tmp_path):
    o = orchestrator_factory(monkeypatch, tmp_path, "true")
    with pytest.raises(KeyError):
        o.get_app("unknown-app")


def test_load_context(monkeypatch, tmp_path):
    import orchestrators.base_orchestrator as mod

    config_dir = tmp_path / "config"
    ctx_dir = config_dir / "contexts"
    ctx_dir.mkdir(parents=True)
    (ctx_dir / "fastapi.md").write_text("# FastAPI", encoding="utf-8")

    (config_dir / "apps.yaml").write_text(
        "apps:\n  - id: x\n    local: {api_path: /f, web_path: /f}\n    bitbucket: {workspace: w, api_repo: r, web_repo: r}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_CONFIG_DIR", config_dir)
    monkeypatch.setenv("LOCAL", "true")

    o = BaseOrchestrator()
    content = o.load_context("contexts/fastapi.md")
    assert "FastAPI" in content
