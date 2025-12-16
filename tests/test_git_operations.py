"""Tests pour le module git_operations."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from gitlab_mirror.config import Config
from gitlab_mirror.git_operations import GitOperations
from gitlab_mirror.models import GitLabProject


def test_get_clone_url_http(test_config: Config, sample_project: GitLabProject) -> None:
    """Test la génération de l'URL de clonage HTTP avec token inclus."""
    test_config.clone_method = "http"
    git_ops = GitOperations(test_config)

    url = git_ops.get_clone_url(sample_project)
    # Le token doit être inclus dans l'URL pour éviter les prompts de credentials
    expected_url = sample_project.http_url_to_repo.replace(
        "https://", f"https://oauth2:{test_config.token}@"
    )
    assert url == expected_url


def test_get_clone_url_http_no_token(sample_project: GitLabProject) -> None:
    """Test l'URL HTTP sans token (fallback à l'URL brute)."""
    config = Config(token="", clone_method="http")
    git_ops = GitOperations(config)

    url = git_ops.get_clone_url(sample_project)
    assert url == sample_project.http_url_to_repo


def test_get_clone_url_ssh(test_config: Config, sample_project: GitLabProject) -> None:
    """Test la génération de l'URL de clonage SSH."""
    test_config.clone_method = "ssh"
    git_ops = GitOperations(test_config)

    url = git_ops.get_clone_url(sample_project)
    assert url == sample_project.ssh_url_to_repo


def test_normalize_url(test_config: Config) -> None:
    """Test la normalisation des URLs Git."""
    git_ops = GitOperations(test_config)

    # Avec .git
    url1 = "https://gitlab.com/group/project.git"
    assert git_ops._normalize_url(url1) == "https://gitlab.com/group/project"

    # Sans .git
    url2 = "https://gitlab.com/group/project"
    assert git_ops._normalize_url(url2) == "https://gitlab.com/group/project"

    # SSH avec .git
    url3 = "git@gitlab.com:group/project.git"
    assert git_ops._normalize_url(url3) == "git@gitlab.com:group/project"


def test_is_git_repository_false(test_config: Config, temp_root_dir: Path) -> None:
    """Test la détection d'un non-dépôt Git."""
    git_ops = GitOperations(test_config)

    # Dossier vide
    empty_dir = temp_root_dir / "empty"
    empty_dir.mkdir()

    assert git_ops.is_git_repository(empty_dir) is False

    # Dossier inexistant
    assert git_ops.is_git_repository(temp_root_dir / "nonexistent") is False


def test_clone_repository_dry_run(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
) -> None:
    """Test le clonage en mode dry-run."""
    test_config.dry_run = True
    git_ops = GitOperations(test_config)

    target_path = temp_root_dir / "test-project"

    success, error = git_ops.clone_repository(sample_project, target_path)

    assert success is True
    assert error is None
    assert not target_path.exists()  # Rien n'a été créé


def test_update_repository_dry_run(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
) -> None:
    """Test la mise à jour en mode dry-run."""
    test_config.dry_run = True
    git_ops = GitOperations(test_config)

    repo_path = temp_root_dir / "existing-repo"
    repo_path.mkdir()

    success, error, was_updated = git_ops.update_repository(repo_path, sample_project)

    assert success is True
    assert error is None
    assert was_updated is False  # Dry-run ne fait rien


def test_check_git_available(test_config: Config, mocker: Any) -> None:
    """Test la vérification de disponibilité de Git."""
    git_ops = GitOperations(test_config)

    # Mock subprocess.run pour simuler Git disponible
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(stdout="git version 2.40.0", returncode=0)

    assert git_ops.check_git_available() is True

    # Simuler Git non disponible
    mock_run.side_effect = FileNotFoundError()
    assert git_ops.check_git_available() is False


def test_hours_since_last_fetch_no_fetch(test_config: Config, temp_root_dir: Path) -> None:
    """Test hours_since_last_fetch sans FETCH_HEAD."""
    git_ops = GitOperations(test_config)
    
    # Créer un faux repo sans FETCH_HEAD
    repo_dir = temp_root_dir / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    
    result = git_ops.hours_since_last_fetch(repo_dir)
    assert result == float("inf")


def test_hours_since_last_fetch_with_fetch(test_config: Config, temp_root_dir: Path) -> None:
    """Test hours_since_last_fetch avec FETCH_HEAD."""
    import time
    
    git_ops = GitOperations(test_config)
    
    # Créer un faux repo avec FETCH_HEAD
    repo_dir = temp_root_dir / "repo"
    repo_dir.mkdir()
    git_dir = repo_dir / ".git"
    git_dir.mkdir()
    fetch_head = git_dir / "FETCH_HEAD"
    fetch_head.write_text("dummy")
    
    result = git_ops.hours_since_last_fetch(repo_dir)
    # Devrait être très proche de 0 (vient d'être créé)
    assert result < 0.1


def test_get_last_fetch_time_none(test_config: Config, temp_root_dir: Path) -> None:
    """Test get_last_fetch_time sans FETCH_HEAD."""
    git_ops = GitOperations(test_config)
    
    repo_dir = temp_root_dir / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    
    result = git_ops.get_last_fetch_time(repo_dir)
    assert result is None


def test_update_repository_disabled(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
) -> None:
    """Test mise à jour désactivée."""
    test_config.update_existing = False
    git_ops = GitOperations(test_config)
    
    repo_path = temp_root_dir / "repo"
    repo_path.mkdir()
    
    success, error, was_updated = git_ops.update_repository(repo_path, sample_project)
    
    assert success is True
    assert error is None
    assert was_updated is False


def test_get_repository_remote_url_not_git(test_config: Config, temp_root_dir: Path) -> None:
    """Test get_repository_remote_url sur un non-dépôt."""
    git_ops = GitOperations(test_config)
    
    non_repo = temp_root_dir / "not-a-repo"
    non_repo.mkdir()
    
    result = git_ops.get_repository_remote_url(non_repo)
    assert result is None


def test_matches_project_not_git(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
) -> None:
    """Test matches_project sur un non-dépôt."""
    git_ops = GitOperations(test_config)
    
    non_repo = temp_root_dir / "not-a-repo"
    non_repo.mkdir()
    
    result = git_ops.matches_project(non_repo, sample_project)
    assert result is False
