"""Fixtures pytest pour les tests."""

from pathlib import Path
from typing import Any

import pytest

from gitlab_mirror.config import Config
from gitlab_mirror.models import GitLabGroup, GitLabProject


@pytest.fixture
def temp_root_dir(tmp_path: Path) -> Path:
    """Crée un répertoire temporaire pour les tests."""
    root = tmp_path / "gitlab-repos"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def test_config(temp_root_dir: Path) -> Config:
    """Crée une configuration de test."""
    return Config(
        gitlab_url="https://gitlab.example.com",
        token="test-token-123",
        root_dir=temp_root_dir,
        dry_run=False,
        verbose=True,
        debug=False,
    )


@pytest.fixture
def sample_group() -> GitLabGroup:
    """Crée un groupe GitLab de test."""
    return GitLabGroup(
        id=100,
        name="test-group",
        full_path="test-group",
        web_url="https://gitlab.example.com/test-group",
    )


@pytest.fixture
def sample_subgroup() -> GitLabGroup:
    """Crée un sous-groupe GitLab de test."""
    return GitLabGroup(
        id=101,
        name="subgroup",
        full_path="test-group/subgroup",
        parent_id=100,
        web_url="https://gitlab.example.com/test-group/subgroup",
    )


@pytest.fixture
def sample_project() -> GitLabProject:
    """Crée un projet GitLab de test."""
    return GitLabProject(
        id=1000,
        name="my-project",
        path="my-project",
        path_with_namespace="test-group/my-project",
        ssh_url_to_repo="git@gitlab.example.com:test-group/my-project.git",
        http_url_to_repo="https://gitlab.example.com/test-group/my-project.git",
        web_url="https://gitlab.example.com/test-group/my-project",
        namespace_id=100,
        namespace_path="test-group",
        description="Test project",
    )


@pytest.fixture
def mock_gitlab_client(mocker: Any) -> Any:
    """Mock du client GitLab."""
    mock = mocker.MagicMock()
    mock.auth.return_value = None
    return mock
