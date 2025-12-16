"""Tests pour le module sync."""

from pathlib import Path
from typing import Any

import pytest

from gitlab_mirror.config import Config
from gitlab_mirror.models import GitLabProject, ProjectStatus
from gitlab_mirror.sync import ProjectSynchronizer


def test_get_local_path(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test le calcul du chemin local."""
    # Mock du GitLab client pour éviter la connexion réseau
    mocker.patch("gitlab_mirror.sync.GitLabClient")

    sync = ProjectSynchronizer(test_config)

    local_path = sync.get_local_path(sample_project)

    expected = test_config.root_dir / "test-group/my-project"
    assert local_path == expected


def test_determine_project_action_to_clone(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
    mocker: Any,
) -> None:
    """Test la détermination d'action quand le projet n'existe pas."""
    # Mock du GitLab client
    mocker.patch("gitlab_mirror.sync.GitLabClient")

    sync = ProjectSynchronizer(test_config)
    local_path = temp_root_dir / "test-group/my-project"

    # Le chemin n'existe pas
    status = sync.determine_project_action(sample_project, local_path)

    assert status == ProjectStatus.TO_CLONE


def test_determine_project_action_ignored_not_git(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
    mocker: Any,
) -> None:
    """Test la détermination d'action quand le dossier existe mais n'est pas Git."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")

    sync = ProjectSynchronizer(test_config)
    local_path = temp_root_dir / "test-group/my-project"

    # Créer un dossier non-Git
    local_path.mkdir(parents=True)
    (local_path / "file.txt").write_text("test")

    status = sync.determine_project_action(sample_project, local_path)

    assert status == ProjectStatus.IGNORED


def test_sync_project_dry_run(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
    mocker: Any,
) -> None:
    """Test la synchronisation d'un projet en mode dry-run."""
    test_config.dry_run = True

    # Mock du GitLab client
    mocker.patch("gitlab_mirror.sync.GitLabClient")

    sync = ProjectSynchronizer(test_config)

    result = sync.sync_project(sample_project)

    assert result.project == sample_project
    assert result.status == ProjectStatus.CLONED
    # En dry-run, rien n'est créé
    assert not (temp_root_dir / "test-group/my-project").exists()


def test_build_summary(test_config: Config, sample_project: GitLabProject, mocker: Any) -> None:
    """Test la construction du résumé."""
    from gitlab_mirror.models import SyncResult

    mocker.patch("gitlab_mirror.sync.GitLabClient")

    sync = ProjectSynchronizer(test_config)

    results = [
        SyncResult(
            project=sample_project,
            status=ProjectStatus.CLONED,
            local_path="/tmp/project1",
        ),
        SyncResult(
            project=sample_project,
            status=ProjectStatus.UPDATED,
            local_path="/tmp/project2",
        ),
        SyncResult(
            project=sample_project,
            status=ProjectStatus.ERROR,
            local_path="/tmp/project3",
            error_message="Test error",
        ),
    ]

    summary = sync._build_summary(["group1"], results)

    assert summary.total_groups == 1
    assert summary.total_projects == 3
    assert summary.cloned == 1
    assert summary.updated == 1
    assert summary.errors == 1


def test_is_project_excluded_no_patterns(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test is_project_excluded sans patterns."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    test_config.exclude_patterns = []
    test_config.include_patterns = []
    sync = ProjectSynchronizer(test_config)
    
    assert sync.is_project_excluded(sample_project) is False


def test_is_project_excluded_with_exclude_pattern(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test is_project_excluded avec exclude pattern."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    test_config.exclude_patterns = ["*/my-*"]
    test_config.include_patterns = []
    sync = ProjectSynchronizer(test_config)
    
    # sample_project a path_with_namespace = "test-group/my-project"
    assert sync.is_project_excluded(sample_project) is True


def test_is_project_excluded_with_include_pattern_match(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test is_project_excluded avec include pattern qui matche."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    test_config.exclude_patterns = []
    test_config.include_patterns = ["*/my-*"]
    sync = ProjectSynchronizer(test_config)
    
    assert sync.is_project_excluded(sample_project) is False


def test_is_project_excluded_with_include_pattern_no_match(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test is_project_excluded avec include pattern qui ne matche pas."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    test_config.exclude_patterns = []
    test_config.include_patterns = ["*/other-*"]
    sync = ProjectSynchronizer(test_config)
    
    assert sync.is_project_excluded(sample_project) is True


def test_find_matching_pattern_exclude(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test _find_matching_pattern avec exclude pattern."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    test_config.exclude_patterns = ["*/my-*", "*/other-*"]
    test_config.include_patterns = []
    sync = ProjectSynchronizer(test_config)
    
    pattern = sync._find_matching_pattern(sample_project)
    assert pattern == "*/my-*"


def test_find_matching_pattern_include_no_match(
    test_config: Config, sample_project: GitLabProject, mocker: Any
) -> None:
    """Test _find_matching_pattern quand include ne matche pas."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    test_config.exclude_patterns = []
    test_config.include_patterns = ["*/other-*"]
    sync = ProjectSynchronizer(test_config)
    
    pattern = sync._find_matching_pattern(sample_project)
    assert "non inclus" in pattern


def test_sync_project_ignored(
    test_config: Config,
    sample_project: GitLabProject,
    temp_root_dir: Path,
    mocker: Any,
) -> None:
    """Test sync_project quand le dossier existe mais n'est pas git."""
    mocker.patch("gitlab_mirror.sync.GitLabClient")
    
    sync = ProjectSynchronizer(test_config)
    
    # Créer un dossier non-git
    local_path = test_config.root_dir / sample_project.path_with_namespace
    local_path.mkdir(parents=True)
    (local_path / "file.txt").write_text("test")
    
    result = sync.sync_project(sample_project)
    
    assert result.status == ProjectStatus.IGNORED
