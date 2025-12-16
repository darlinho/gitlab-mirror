"""Logique de synchronisation GitLab → filesystem."""

import fnmatch
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .git_operations import GitOperations
from .gitlab_api import GitLabClient
from .logger import logger
from .models import GitLabProject, ProjectStatus, SyncResult, SyncSummary


class ProjectSynchronizer:
    """Gère la synchronisation des projets GitLab vers le filesystem."""

    def __init__(self, config: Config) -> None:
        """Initialise le synchroniseur.

        Args:
            config: Configuration de l'application
        """
        self.config = config
        self.gitlab_client = GitLabClient(config)
        self.git_ops = GitOperations(config)

    def get_local_path(self, project: GitLabProject) -> Path:
        """Calcule le chemin local pour un projet.

        Args:
            project: Projet GitLab

        Returns:
            Chemin local pour le projet
        """
        return self.config.root_dir / project.path_with_namespace

    def is_project_excluded(self, project: GitLabProject) -> bool:
        """Vérifie si un projet doit être exclu selon les patterns configurés.

        Args:
            project: Projet GitLab

        Returns:
            True si le projet doit être exclu
        """
        path = project.path_with_namespace

        # Si include_patterns défini, le projet doit matcher un pattern
        if self.config.include_patterns:
            for pattern in self.config.include_patterns:
                if fnmatch.fnmatch(path, pattern):
                    break
            else:
                # Ne matche aucun include pattern → exclu
                return True

        # Vérifier les exclude patterns
        if self.config.exclude_patterns:
            for pattern in self.config.exclude_patterns:
                if fnmatch.fnmatch(path, pattern):
                    return True

        return False

    def _find_matching_pattern(self, project: GitLabProject) -> str:
        """Trouve le pattern qui a exclu un projet.

        Args:
            project: Projet GitLab

        Returns:
            Le pattern qui correspond, ou "unknown"
        """
        path = project.path_with_namespace

        # Vérifier include patterns d'abord
        if self.config.include_patterns:
            matches_include = False
            for pattern in self.config.include_patterns:
                if fnmatch.fnmatch(path, pattern):
                    matches_include = True
                    break
            if not matches_include:
                return f"non inclus (patterns: {', '.join(self.config.include_patterns)})"

        # Puis exclude patterns
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(path, pattern):
                return pattern
        return "unknown"

    def determine_project_action(
        self, project: GitLabProject, local_path: Path
    ) -> ProjectStatus:
        """Détermine l'action à effectuer pour un projet.

        Args:
            project: Projet GitLab
            local_path: Chemin local du projet

        Returns:
            Statut indiquant l'action à effectuer
        """
        # Cas 1: Le chemin n'existe pas → à cloner
        if not local_path.exists():
            return ProjectStatus.TO_CLONE

        # Cas 2: Le chemin existe mais n'est pas un dépôt Git
        if not self.git_ops.is_git_repository(local_path):
            logger.warning(
                f"{project.path_with_namespace}: "
                f"Le dossier existe mais n'est pas un dépôt Git"
            )
            return ProjectStatus.IGNORED

        # Cas 3: C'est un dépôt Git mais ne correspond pas au projet
        if not self.git_ops.matches_project(local_path, project):
            remote_url = self.git_ops.get_repository_remote_url(local_path)
            logger.warning(
                f"{project.path_with_namespace}: "
                f"Le dépôt existe mais ne correspond pas "
                f"(remote: {remote_url})"
            )
            return ProjectStatus.IGNORED

        # Cas 4: Dépôt valide correspondant au projet
        return ProjectStatus.ALREADY_UP_TO_DATE

    def sync_project(self, project: GitLabProject) -> SyncResult:
        """Synchronise un projet GitLab.

        Args:
            project: Projet à synchroniser

        Returns:
            Résultat de la synchronisation
        """
        local_path = self.get_local_path(project)

        # Déterminer l'action à effectuer
        action = self.determine_project_action(project, local_path)

        # Exécuter l'action
        if action == ProjectStatus.TO_CLONE:
            success, error = self.git_ops.clone_repository(project, local_path)
            status = ProjectStatus.CLONED if success else ProjectStatus.ERROR
            return SyncResult(
                project=project,
                status=status,
                local_path=str(local_path),
                error_message=error,
            )

        elif action == ProjectStatus.ALREADY_UP_TO_DATE:
            if self.config.update_existing:
                success, error, was_updated = self.git_ops.update_repository(
                    local_path, project
                )
                if success:
                    status = (
                        ProjectStatus.UPDATED if was_updated else ProjectStatus.ALREADY_UP_TO_DATE
                    )
                else:
                    status = ProjectStatus.ERROR
                return SyncResult(
                    project=project,
                    status=status,
                    local_path=str(local_path),
                    error_message=error,
                )
            return SyncResult(
                project=project,
                status=ProjectStatus.ALREADY_UP_TO_DATE,
                local_path=str(local_path),
            )

        # IGNORED
        return SyncResult(
            project=project,
            status=ProjectStatus.IGNORED,
            local_path=str(local_path),
            error_message="Dossier existant mais non correspondant",
        )

    def sync_groups(
        self,
        group_identifiers: list[str],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> SyncSummary:
        """Synchronise plusieurs groupes GitLab.

        VERSION OPTIMISÉE: Découverte rapide + clonage parallèle.

        Args:
            group_identifiers: Liste d'IDs ou chemins de groupes
            progress_callback: Fonction de callback pour la progression

        Returns:
            Résumé de la synchronisation
        """
        # Vérifier que Git est disponible
        if not self.git_ops.check_git_available():
            raise RuntimeError("Git n'est pas disponible sur ce système")

        # Créer le répertoire racine
        if not self.config.dry_run:
            self.config.create_root_dir()

        # === PHASE 1: DÉCOUVERTE RAPIDE ===
        logger.info("=" * 70)
        logger.info("DÉCOUVERTE DES PROJETS GITLAB")
        logger.info("=" * 70)

        if progress_callback:
            progress_callback("Découverte des projets...")

        projects = self.gitlab_client.discover_all_projects(group_identifiers)

        # Filtrer les projets exclus et créer des résultats pour eux
        excluded_results: list[SyncResult] = []
        if self.config.exclude_patterns or self.config.include_patterns:
            included_projects = []
            for project in projects:
                if self.is_project_excluded(project):
                    # Trouver quel pattern a exclu ce projet
                    matched_pattern = self._find_matching_pattern(project)
                    excluded_results.append(
                        SyncResult(
                            project=project,
                            status=ProjectStatus.EXCLUDED,
                            local_path="",
                            error_message=f"Exclu: {matched_pattern}",
                        )
                    )
                else:
                    included_projects.append(project)
            projects = included_projects
            if excluded_results:
                logger.info(f"⊖ {len(excluded_results)} projet(s) exclus par filtres")

        logger.info("=" * 70)
        logger.info(f"TOTAL: {len(projects)} projet(s) à synchroniser")
        logger.info("=" * 70)

        if not projects:
            logger.warning("Aucun projet trouvé, rien à synchroniser")
            return SyncSummary(
                total_groups=len(group_identifiers),
                total_projects=len(excluded_results),
                cloned=0,
                updated=0,
                already_up_to_date=0,
                ignored=0,
                excluded=len(excluded_results),
                errors=0,
                results=excluded_results,
            )

        # === PHASE 2: SYNCHRONISATION PARALLÈLE ===
        workers = self.config.max_workers
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"SYNCHRONISATION DES PROJETS ({workers} threads)")
        logger.info("=" * 70)

        results = self._sync_projects_parallel(projects, progress_callback)

        # Ajouter les projets exclus aux résultats
        all_results = excluded_results + results

        # Calculer le résumé
        return self._build_summary(group_identifiers, all_results)

    def _sync_projects_parallel(
        self,
        projects: list[GitLabProject],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> list[SyncResult]:
        """Synchronise les projets en parallèle.

        Args:
            projects: Liste des projets à synchroniser
            progress_callback: Callback de progression

        Returns:
            Liste des résultats de synchronisation
        """
        results: list[SyncResult] = []
        completed = 0
        total = len(projects)
        workers = self.config.max_workers

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Soumettre tous les projets
            future_to_project = {
                executor.submit(self.sync_project, project): project
                for project in projects
            }

            # Collecter les résultats au fur et à mesure
            for future in as_completed(future_to_project):
                project = future_to_project[future]
                completed += 1

                try:
                    result = future.result()
                    results.append(result)

                    # Log le résultat
                    status_icon = {
                        ProjectStatus.CLONED: "✓",
                        ProjectStatus.UPDATED: "↑",
                        ProjectStatus.ALREADY_UP_TO_DATE: "=",
                        ProjectStatus.IGNORED: "⊘",
                        ProjectStatus.ERROR: "✗",
                    }.get(result.status, "?")

                    logger.info(
                        f"{status_icon} [{completed}/{total}] {project.path_with_namespace}"
                    )

                    if progress_callback:
                        progress_callback(
                            f"[{completed}/{total}] {project.path_with_namespace}"
                        )

                except Exception as e:
                    logger.error(f"✗ [{completed}/{total}] {project.path_with_namespace}: {e}")
                    results.append(
                        SyncResult(
                            project=project,
                            status=ProjectStatus.ERROR,
                            local_path=str(self.get_local_path(project)),
                            error_message=str(e),
                        )
                    )

        return results

    def _build_summary(
        self, group_identifiers: list[str], results: list[SyncResult]
    ) -> SyncSummary:
        """Construit le résumé de synchronisation.

        Args:
            group_identifiers: Identifiants des groupes traités
            results: Résultats de synchronisation

        Returns:
            Résumé de la synchronisation
        """
        cloned = sum(1 for r in results if r.status == ProjectStatus.CLONED)
        updated = sum(1 for r in results if r.status == ProjectStatus.UPDATED)
        already_up_to_date = sum(
            1 for r in results if r.status == ProjectStatus.ALREADY_UP_TO_DATE
        )
        ignored = sum(1 for r in results if r.status == ProjectStatus.IGNORED)
        excluded = sum(1 for r in results if r.status == ProjectStatus.EXCLUDED)
        errors = sum(1 for r in results if r.status == ProjectStatus.ERROR)

        return SyncSummary(
            total_groups=len(group_identifiers),
            total_projects=len(results),
            cloned=cloned,
            updated=updated,
            already_up_to_date=already_up_to_date,
            ignored=ignored,
            excluded=excluded,
            errors=errors,
            results=results,
        )
