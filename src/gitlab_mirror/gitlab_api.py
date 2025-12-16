"""Client API GitLab pour la découverte des groupes et projets."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabError, GitlabGetError

from .config import Config
from .logger import logger
from .models import GitLabGroup, GitLabProject


class GitLabClient:
    """Client pour interagir avec l'API GitLab."""

    def __init__(self, config: Config) -> None:
        """Initialise le client GitLab.

        Args:
            config: Configuration de l'application

        Raises:
            ValueError: Si le token n'est pas fourni
            GitlabAuthenticationError: Si l'authentification échoue
        """
        self.config = config
        config.ensure_token()

        try:
            self.client = gitlab.Gitlab(
                url=config.gitlab_url,
                private_token=config.token,
                timeout=config.api_timeout,
            )
            # Tester l'authentification
            self.client.auth()
            logger.info(f"Connecté à GitLab: {config.gitlab_url}")
        except GitlabAuthenticationError as e:
            logger.error("Échec d'authentification GitLab")
            raise ValueError(
                f"Authentification GitLab échouée: {e}. Vérifiez votre token."
            ) from e
        except GitlabError as e:
            logger.error(f"Erreur de connexion à GitLab: {e}")
            raise

    def resolve_group(self, group_identifier: str) -> Optional[GitLabGroup]:
        """Résout un groupe à partir de son ID ou chemin.

        Args:
            group_identifier: ID numérique ou chemin complet du groupe

        Returns:
            GitLabGroup si trouvé, None sinon
        """
        try:
            if group_identifier.isdigit():
                gl_group = self.client.groups.get(int(group_identifier))
            else:
                gl_group = self.client.groups.get(group_identifier)

            group = GitLabGroup(
                id=gl_group.id,
                name=gl_group.name,
                full_path=gl_group.full_path,
                parent_id=getattr(gl_group, "parent_id", None),
                web_url=gl_group.web_url,
            )
            logger.debug(f"Groupe trouvé: {group.full_path} (ID: {group.id})")
            return group

        except GitlabGetError as e:
            logger.error(f"Groupe non trouvé: {group_identifier} - {e}")
            return None
        except GitlabError as e:
            logger.error(f"Erreur lors de la résolution du groupe {group_identifier}: {e}")
            return None

    def get_all_projects_fast(self, group_id: int) -> list[GitLabProject]:
        """Récupère TOUS les projets d'un groupe ET ses sous-groupes en UNE requête.

        OPTIMISATION: Utilise include_subgroups=True pour éviter de scanner
        chaque sous-groupe individuellement.

        Filtres appliqués:
        - archived: inclus seulement si config.include_archived=True
        - since_days: filtre par dernière activité si > 0

        Args:
            group_id: ID du groupe racine

        Returns:
            Liste de tous les projets (incluant sous-groupes)
        """
        projects: list[GitLabProject] = []

        try:
            gl_group = self.client.groups.get(group_id)

            # Options de requête
            list_kwargs: dict[str, Any] = {
                "all": True,
                "include_subgroups": True,
                "with_shared": False,
            }

            # Filtre archived
            if not self.config.include_archived:
                list_kwargs["archived"] = False

            # Filtre par date de dernière activité
            if self.config.since_days > 0:
                since_date = datetime.now(timezone.utc) - timedelta(days=self.config.since_days)
                list_kwargs["last_activity_after"] = since_date.isoformat()

            gl_projects = gl_group.projects.list(**list_kwargs)

            # Logging avec filtres actifs
            filters_info = []
            if not self.config.include_archived:
                filters_info.append("non-archivés")
            if self.config.since_days > 0:
                filters_info.append(f"actifs depuis {self.config.since_days}j")

            filter_str = f" ({', '.join(filters_info)})" if filters_info else ""
            logger.info(f"  → {len(gl_projects)} projet(s) trouvé(s){filter_str}")

            for gp in gl_projects:
                project = self._convert_project_from_list(gp)
                projects.append(project)

        except GitlabError as e:
            logger.error(f"Erreur lors de la récupération des projets: {e}")

        return projects

    def discover_all_projects(self, group_identifiers: list[str]) -> list[GitLabProject]:
        """Découvre tous les projets à partir d'une liste de groupes.

        VERSION OPTIMISÉE: Une seule requête par groupe racine au lieu de
        scanner chaque sous-groupe.

        Args:
            group_identifiers: Liste d'IDs ou chemins de groupes

        Returns:
            Liste de tous les projets trouvés
        """
        all_projects: list[GitLabProject] = []
        processed_group_ids: set[int] = set()

        for identifier in group_identifiers:
            logger.info(f"Résolution du groupe: {identifier}")
            group = self.resolve_group(identifier)

            if not group:
                logger.warning(f"Groupe ignoré (non trouvé): {identifier}")
                continue

            if group.id in processed_group_ids:
                continue

            processed_group_ids.add(group.id)
            logger.info(f"Scan du groupe: {group.full_path} (avec tous les sous-groupes)")

            # UNE SEULE requête pour tous les projets du groupe et sous-groupes
            projects = self.get_all_projects_fast(group.id)
            all_projects.extend(projects)

        # Dédupliquer par ID de projet
        unique_projects = {p.id: p for p in all_projects}.values()
        return list(unique_projects)

    def _convert_project_from_list(self, gp: Any) -> GitLabProject:
        """Convertit un projet de la liste en modèle interne.

        OPTIMISATION: Utilise les données directement de la liste sans
        requête supplémentaire.

        Args:
            gp: Projet GitLab de la liste

        Returns:
            Instance de GitLabProject
        """
        # Les données sont disponibles directement dans l'objet de la liste
        return GitLabProject(
            id=gp.id,
            name=gp.name,
            path=gp.path,
            path_with_namespace=gp.path_with_namespace,
            ssh_url_to_repo=gp.ssh_url_to_repo,
            http_url_to_repo=gp.http_url_to_repo,
            web_url=gp.web_url,
            namespace_id=gp.namespace["id"],
            namespace_path=gp.namespace["full_path"],
            description=getattr(gp, "description", None),
        )
