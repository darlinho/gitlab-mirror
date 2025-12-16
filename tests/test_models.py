"""Tests pour le module models."""

from gitlab_mirror.models import (
    GitLabGroup,
    GitLabProject,
    ProjectStatus,
    SyncResult,
    SyncSummary,
)


def test_gitlab_group_creation() -> None:
    """Test la création d'un groupe GitLab."""
    group = GitLabGroup(
        id=1,
        name="test",
        full_path="org/test",
        parent_id=10,
    )

    assert group.id == 1
    assert group.name == "test"
    assert group.full_path == "org/test"
    assert group.parent_id == 10


def test_gitlab_project_creation() -> None:
    """Test la création d'un projet GitLab."""
    project = GitLabProject(
        id=100,
        name="my-app",
        path="my-app",
        path_with_namespace="org/team/my-app",
        ssh_url_to_repo="git@gitlab.com:org/team/my-app.git",
        http_url_to_repo="https://gitlab.com/org/team/my-app.git",
        web_url="https://gitlab.com/org/team/my-app",
        namespace_id=50,
        namespace_path="org/team",
    )

    assert project.id == 100
    assert project.path_with_namespace == "org/team/my-app"


def test_sync_result_creation(sample_project: GitLabProject) -> None:
    """Test la création d'un résultat de sync."""
    result = SyncResult(
        project=sample_project,
        status=ProjectStatus.CLONED,
        local_path="/tmp/test-group/my-project",
    )

    assert result.status == ProjectStatus.CLONED
    assert result.error_message is None


def test_sync_summary_success_rate() -> None:
    """Test le calcul du taux de réussite."""
    summary = SyncSummary(
        total_groups=2,
        total_projects=10,
        cloned=5,
        updated=3,
        already_up_to_date=1,
        ignored=0,
        excluded=0,
        errors=1,
        results=[],
    )

    # (5 + 3 + 1) / 10 * 100 = 90%
    assert summary.success_rate == 90.0


def test_sync_summary_with_exclusions() -> None:
    """Test le calcul du taux avec exclusions (ne pénalisent pas)."""
    summary = SyncSummary(
        total_groups=1,
        total_projects=10,
        cloned=4,
        updated=0,
        already_up_to_date=4,
        ignored=0,
        excluded=2,  # 2 exclus volontairement
        errors=0,
        results=[],
    )

    # Taux = (4 + 0 + 4) / (10 - 2) = 8/8 = 100%
    assert summary.success_rate == 100.0


def test_sync_summary_zero_projects() -> None:
    """Test le résumé avec zéro projet."""
    summary = SyncSummary(
        total_groups=1,
        total_projects=0,
        cloned=0,
        updated=0,
        already_up_to_date=0,
        ignored=0,
        excluded=0,
        errors=0,
        results=[],
    )

    assert summary.success_rate == 100.0
