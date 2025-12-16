"""Modèles de données pour GitLab Mirror."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProjectStatus(str, Enum):
    """Statut d'un projet lors de la synchronisation."""

    TO_CLONE = "to_clone"
    CLONED = "cloned"
    UPDATED = "updated"
    ALREADY_UP_TO_DATE = "already_up_to_date"
    IGNORED = "ignored"  # Conflit (dossier existant non-git)
    EXCLUDED = "excluded"  # Exclusion volontaire par pattern
    ERROR = "error"


@dataclass
class GitLabGroup:
    """Représente un groupe GitLab."""

    id: int
    name: str
    full_path: str
    parent_id: Optional[int] = None
    web_url: Optional[str] = None


@dataclass
class GitLabProject:
    """Représente un projet GitLab."""

    id: int
    name: str
    path: str
    path_with_namespace: str
    ssh_url_to_repo: str
    http_url_to_repo: str
    web_url: str
    namespace_id: int
    namespace_path: str
    description: Optional[str] = None


@dataclass
class SyncResult:
    """Résultat de synchronisation d'un projet."""

    project: GitLabProject
    status: ProjectStatus
    local_path: str
    error_message: Optional[str] = None


@dataclass
class SyncSummary:
    """Résumé de la synchronisation."""

    total_groups: int
    total_projects: int
    cloned: int
    updated: int
    already_up_to_date: int
    ignored: int  # Conflits
    excluded: int  # Exclusions volontaires par pattern
    errors: int
    results: list[SyncResult]

    @property
    def success_rate(self) -> float:
        """Calcule le taux de réussite (exclusions ne comptent pas comme échecs)."""
        # Les exclusions volontaires ne sont pas des échecs
        effective_total = self.total_projects - self.excluded
        if effective_total == 0:
            return 100.0
        successful = self.cloned + self.updated + self.already_up_to_date
        return (successful / effective_total) * 100
