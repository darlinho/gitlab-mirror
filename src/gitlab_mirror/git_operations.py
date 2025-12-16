"""Opérations Git pour le clonage et la mise à jour des dépôts."""

import os
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, Tuple, TypeVar

import git
from git.exc import GitCommandError, InvalidGitRepositoryError

from .config import Config
from .logger import logger
from .models import GitLabProject

T = TypeVar("T")


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (GitCommandError, OSError),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Décorateur pour retry automatique avec backoff exponentiel.

    Args:
        max_retries: Nombre maximum de tentatives
        delay: Délai initial entre tentatives (secondes)
        backoff: Multiplicateur de délai entre tentatives
        exceptions: Types d'exceptions à intercepter

    Returns:
        Décorateur
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.debug(
                            f"Tentative {attempt + 1}/{max_retries + 1} échouée: {e}. "
                            f"Retry dans {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.debug(f"Toutes les tentatives échouées: {e}")

            raise last_exception  # type: ignore

        return wrapper

    return decorator


@dataclass
class UpdateStatus:
    """Résultat détaillé d'une vérification de mise à jour."""

    needs_update: bool
    reason: str
    commits_behind: int = 0
    last_fetch_hours: float = 0


class GitOperations:
    """Gère les opérations Git (clone, fetch, etc.)."""

    def __init__(self, config: Config) -> None:
        """Initialise les opérations Git.

        Args:
            config: Configuration de l'application
        """
        self.config = config

    def get_clone_url(self, project: GitLabProject) -> str:
        """Retourne l'URL de clonage selon la méthode configurée.
        
        Pour HTTP, retourne l'URL SANS token pour des raisons de sécurité.
        Le token sera fourni via GIT_ASKPASS ou credential helper.
        """
        if self.config.clone_method == "ssh":
            return project.ssh_url_to_repo

        # Pour HTTP, retourner l'URL sans token (plus sécuritaire)
        # Le token sera fourni via GIT_ASKPASS ou credential helper
        return project.http_url_to_repo

    def is_git_repository(self, path: Path) -> bool:
        """Vérifie si un chemin est un dépôt Git valide."""
        try:
            git.Repo(path)
            return True
        except (InvalidGitRepositoryError, git.NoSuchPathError):
            return False

    def get_repository_remote_url(self, path: Path) -> Optional[str]:
        """Récupère l'URL du remote 'origin' d'un dépôt."""
        try:
            repo = git.Repo(path)
            if "origin" in repo.remotes:
                return repo.remotes.origin.url
            return None
        except (InvalidGitRepositoryError, git.NoSuchPathError):
            return None

    def matches_project(self, path: Path, project: GitLabProject) -> bool:
        """Vérifie si un dépôt local correspond au projet GitLab."""
        if not self.is_git_repository(path):
            return False

        remote_url = self.get_repository_remote_url(path)
        if not remote_url:
            return False

        project_urls = [
            self._normalize_url(project.http_url_to_repo),
            self._normalize_url(project.ssh_url_to_repo),
        ]
        normalized_remote = self._normalize_url(remote_url)

        return normalized_remote in project_urls

    def _normalize_url(self, url: str) -> str:
        """Normalise une URL Git pour la comparaison.
        
        Supprime les credentials (user:pass@) et normalise l'URL pour permettre
        la comparaison entre URLs avec/sans token.
        
        Exemples:
        - https://oauth2:TOKEN@gitlab.com/groupe/projet.git -> https://gitlab.com/groupe/projet
        - git@gitlab.com:groupe/projet.git -> git@gitlab.com:groupe/projet
        """
        import re
        
        # Supprimer les credentials des URLs HTTP/HTTPS (format: user:pass@)
        # Ex: https://oauth2:TOKEN@gitlab.com/... -> https://gitlab.com/...
        normalized = re.sub(r"://[^@]+@", "://", url)
        
        # Normaliser la fin de l'URL
        normalized = normalized.rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        
        return normalized.lower()

    def get_last_fetch_time(self, path: Path) -> Optional[float]:
        """Retourne le timestamp du dernier fetch.

        Args:
            path: Chemin du dépôt

        Returns:
            Timestamp du dernier fetch ou None
        """
        fetch_head = path / ".git" / "FETCH_HEAD"
        if fetch_head.exists():
            return fetch_head.stat().st_mtime
        return None

    def hours_since_last_fetch(self, path: Path) -> float:
        """Calcule le nombre d'heures depuis le dernier fetch.

        Args:
            path: Chemin du dépôt

        Returns:
            Nombre d'heures depuis le dernier fetch (inf si jamais fetch)
        """
        last_fetch = self.get_last_fetch_time(path)
        if last_fetch is None:
            return float("inf")
        hours = (time.time() - last_fetch) / 3600
        return hours

    def check_if_behind_remote(self, path: Path) -> UpdateStatus:
        """Vérifie intelligemment si le repo a besoin d'une mise à jour.

        POLITIQUE INTELLIGENTE:
        1. Si jamais fetch → besoin de mise à jour
        2. Si fetch récent (< skip_recent_hours) → pas besoin
        3. Sinon → vérifier le nombre de commits de retard

        Args:
            path: Chemin du dépôt

        Returns:
            UpdateStatus avec les détails
        """
        try:
            repo = git.Repo(path)

            # Vérifier le temps depuis le dernier fetch
            hours_ago = self.hours_since_last_fetch(path)

            # Si skip_recent_hours est configuré et le fetch est récent
            if self.config.skip_recent_hours > 0 and hours_ago < self.config.skip_recent_hours:
                return UpdateStatus(
                    needs_update=False,
                    reason=f"Fetch récent ({hours_ago:.1f}h < {self.config.skip_recent_hours}h)",
                    last_fetch_hours=hours_ago,
                )

            # Vérifier s'il y a des modifications locales
            if repo.is_dirty(untracked_files=True):
                return UpdateStatus(
                    needs_update=False,
                    reason="Modifications locales non commitées",
                    last_fetch_hours=hours_ago,
                )

            # Si HEAD détaché, on ne peut pas facilement vérifier
            if repo.head.is_detached:
                return UpdateStatus(
                    needs_update=True,
                    reason="HEAD détaché, fetch recommandé",
                    last_fetch_hours=hours_ago,
                )

            # Mode smart: faire un fetch léger (ls-remote) pour vérifier
            if self.config.smart_update:
                behind = self._count_commits_behind(repo)
                if behind == 0:
                    return UpdateStatus(
                        needs_update=False,
                        reason="Déjà à jour avec remote",
                        commits_behind=0,
                        last_fetch_hours=hours_ago,
                    )
                return UpdateStatus(
                    needs_update=True,
                    reason=f"{behind} commit(s) de retard",
                    commits_behind=behind,
                    last_fetch_hours=hours_ago,
                )

            # Mode par défaut: toujours mettre à jour
            return UpdateStatus(
                needs_update=True,
                reason="Mise à jour planifiée",
                last_fetch_hours=hours_ago,
            )

        except Exception as e:
            logger.debug(f"Erreur lors de la vérification: {e}")
            return UpdateStatus(
                needs_update=True,
                reason="Vérification impossible, mise à jour par précaution",
            )

    def _count_commits_behind(self, repo: git.Repo) -> int:
        """Compte le nombre de commits de retard par rapport au remote.

        Args:
            repo: Instance du dépôt Git

        Returns:
            Nombre de commits de retard (0 si à jour ou erreur)
        """
        try:
            # Faire un fetch dry-run rapide pour vérifier
            origin = repo.remotes.origin

            # Récupérer les refs du remote sans télécharger
            current_branch = repo.active_branch.name
            local_commit = repo.head.commit.hexsha

            # Fetch pour mettre à jour les refs remote (léger)
            origin.fetch(dry_run=False, verbose=False)

            # Comparer avec le remote
            remote_ref = f"origin/{current_branch}"
            if remote_ref in repo.refs:
                remote_commit = repo.refs[remote_ref].commit.hexsha
                if local_commit == remote_commit:
                    return 0

                # Compter les commits de différence
                behind_commits = list(
                    repo.iter_commits(f"{local_commit}..{remote_commit}")
                )
                return len(behind_commits)

            return 0
        except Exception:
            return 0

    def clone_repository(
        self, project: GitLabProject, target_path: Path
    ) -> Tuple[bool, Optional[str]]:
        """Clone un dépôt GitLab avec retry automatique.

        Args:
            project: Projet à cloner
            target_path: Chemin de destination

        Returns:
            Tuple (succès, message_erreur)
        """
        clone_url = self.get_clone_url(project)

        if self.config.dry_run:
            logger.info(f"[DRY-RUN] Clonerait: {clone_url} → {target_path}")
            return True, None

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Clonage de {project.path_with_namespace}...")

            # Utiliser retry interne
            return self._clone_with_retry(clone_url, target_path)

        except Exception as e:
            error_msg = f"Erreur inattendue lors du clonage: {e}"
            return False, error_msg

    def _create_askpass_script(self) -> Optional[Path]:
        """Crée un script GIT_ASKPASS temporaire pour fournir le token de manière sécurisée.
        
        Returns:
            Chemin du script temporaire ou None si pas de token
        """
        if not self.config.token or self.config.clone_method == "ssh":
            return None
        
        # Créer un script temporaire qui retourne le token
        fd, script_path = tempfile.mkstemp(prefix="lgm_askpass_", suffix=".sh", text=True)
        try:
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/sh\n")
                f.write(f'echo "{self.config.token}"\n')
            
            # Rendre le script exécutable
            os.chmod(script_path, stat.S_IRUSR | stat.S_IXUSR)
            return Path(script_path)
        except Exception as e:
            logger.debug(f"Erreur lors de la création du script askpass: {e}")
            try:
                os.unlink(script_path)
            except Exception:
                pass
            return None

    def _setup_credential_helper(self, repo_path: Path) -> None:
        """Configure le credential helper pour un dépôt après clonage.
        
        Nettoie aussi le remote pour enlever le token s'il y en a un.
        
        Args:
            repo_path: Chemin du dépôt cloné
        """
        try:
            repo = git.Repo(repo_path)
            
            # Nettoyer le remote pour enlever le token s'il y en a un
            if "origin" in repo.remotes:
                remote = repo.remotes.origin
                remote_url = remote.url
                
                # Si l'URL contient des credentials, les enlever
                import re
                clean_url = re.sub(r"://[^@]+@", "://", remote_url)
                
                if clean_url != remote_url:
                    logger.debug(f"Nettoyage du remote pour {repo_path}")
                    remote.set_url(clean_url)
                    
                    # Configurer le credential helper pour ce dépôt
                    # Utiliser credential.helper store pour ce repo spécifique
                    repo.git.config("credential.helper", "store", local=True)
                    
                    # Stocker le credential de manière sécurisée
                    self._store_credential(repo_path, clean_url)
        except Exception as e:
            logger.debug(f"Erreur lors de la configuration du credential helper: {e}")

    def _store_credential(self, repo_path: Path, url: str) -> None:
        """Stocke les credentials dans le credential store de Git.
        
        Args:
            repo_path: Chemin du dépôt
            url: URL du remote (sans credentials)
        """
        try:
            # Extraire l'host de l'URL
            import re
            match = re.search(r"://([^/]+)", url)
            if not match:
                return
            
            host = match.group(1)
            credential_line = f"https://oauth2:{self.config.token}@{host}\n"
            
            # Utiliser le credential store Git
            # Git cherche ~/.git-credentials par défaut
            git_credentials = Path.home() / ".git-credentials"
            git_credentials.parent.mkdir(parents=True, exist_ok=True)
            
            # Lire les credentials existants
            existing = set()
            if git_credentials.exists():
                with open(git_credentials) as f:
                    existing = set(line.strip() for line in f if line.strip())
            
            # Ajouter le nouveau credential
            existing.add(credential_line.strip())
            
            # Écrire avec permissions restrictives
            with open(git_credentials, "w") as f:
                f.write("\n".join(sorted(existing)) + "\n")
            
            # Permissions restrictives (lecture/écriture pour le propriétaire uniquement)
            os.chmod(git_credentials, stat.S_IRUSR | stat.S_IWUSR)
            
        except Exception as e:
            logger.debug(f"Erreur lors du stockage du credential: {e}")

    def _clone_with_retry(
        self, clone_url: str, target_path: Path
    ) -> Tuple[bool, Optional[str]]:
        """Clone avec retry automatique et gestion sécurisée des credentials.

        Args:
            clone_url: URL de clonage (sans token)
            target_path: Chemin de destination

        Returns:
            Tuple (succès, message_erreur)
        """
        last_error: Optional[str] = None
        askpass_script: Optional[Path] = None

        try:
            # Créer le script askpass si nécessaire (pour HTTP avec token)
            if self.config.clone_method == "http" and self.config.token:
                askpass_script = self._create_askpass_script()
            
            for attempt in range(self.config.max_retries + 1):
                try:
                    # Options de clonage avec timeout
                    env = os.environ.copy()
                    env["GIT_HTTP_CONNECT_TIMEOUT"] = str(self.config.git_timeout)
                    
                    # Utiliser GIT_ASKPASS pour fournir le token de manière sécurisée
                    if askpass_script:
                        env["GIT_ASKPASS"] = str(askpass_script)
                        env["GIT_TERMINAL_PROMPT"] = "0"  # Désactiver les prompts interactifs
                    
                    clone_kwargs: dict[str, Any] = {"progress": None, "env": env}

                    # Shallow clone
                    if self.config.clone_depth > 0:
                        clone_kwargs["depth"] = self.config.clone_depth

                    # Single branch (clone uniquement la branche par défaut)
                    if self.config.single_branch:
                        clone_kwargs["single_branch"] = True

                    # Partial clone (filter blobs) - pour les très gros repos
                    if self.config.filter_blobs:
                        clone_kwargs["filter"] = "blob:none"

                    git.Repo.clone_from(clone_url, target_path, **clone_kwargs)
                    
                    # Après clonage réussi, nettoyer le remote et configurer credential helper
                    if self.config.clone_method == "http" and self.config.token:
                        self._setup_credential_helper(target_path)
                    
                    return True, None

                except GitCommandError as e:
                    last_error = str(e)
                    # Nettoyer le dossier partiel si créé
                    if target_path.exists():
                        import shutil
                        shutil.rmtree(target_path, ignore_errors=True)

                    if attempt < self.config.max_retries:
                        delay = 2 ** attempt  # Backoff exponentiel
                        logger.debug(f"Clone échoué, retry {attempt + 1} dans {delay}s...")
                        time.sleep(delay)

            return False, f"Échec après {self.config.max_retries + 1} tentatives: {last_error}"
        
        finally:
            # Nettoyer le script temporaire
            if askpass_script and askpass_script.exists():
                try:
                    askpass_script.unlink()
                except Exception:
                    pass

    def update_repository(
        self, path: Path, project: GitLabProject
    ) -> Tuple[bool, Optional[str], bool]:
        """Met à jour un dépôt existant avec politique intelligente et retry.

        Args:
            path: Chemin du dépôt local
            project: Projet GitLab correspondant

        Returns:
            Tuple (succès, message_erreur, vraiment_mis_à_jour)
        """
        if not self.config.update_existing:
            logger.debug(f"Mise à jour désactivée pour {project.path_with_namespace}")
            return True, None, False

        if self.config.dry_run:
            logger.info(f"[DRY-RUN] Mettrait à jour: {path}")
            return True, None, False

        try:
            # Vérification intelligente
            status = self.check_if_behind_remote(path)

            if not status.needs_update:
                return True, status.reason, False

            # Mise à jour avec retry
            return self._update_with_retry(path, project)

        except Exception as e:
            error_msg = f"Erreur inattendue: {e}"
            return False, error_msg, False

    def _update_with_retry(
        self, path: Path, project: GitLabProject
    ) -> Tuple[bool, Optional[str], bool]:
        """Met à jour avec retry automatique.

        Args:
            path: Chemin du dépôt
            project: Projet GitLab

        Returns:
            Tuple (succès, message_erreur, vraiment_mis_à_jour)
        """
        last_error: Optional[str] = None

        for attempt in range(self.config.max_retries + 1):
            try:
                repo = git.Repo(path)
                origin = repo.remotes.origin

                # Options de fetch
                fetch_kwargs: dict[str, Any] = {}
                if self.config.prune:
                    fetch_kwargs["prune"] = True

                if self.config.fetch_only:
                    origin.fetch(**fetch_kwargs)
                else:
                    # Pull si sur une branche
                    if not repo.head.is_detached:
                        current_branch = repo.active_branch
                        origin.pull(current_branch.name, **fetch_kwargs)
                    else:
                        origin.fetch(**fetch_kwargs)

                return True, None, True

            except GitCommandError as e:
                last_error = str(e)
                if attempt < self.config.max_retries:
                    delay = 2 ** attempt
                    logger.debug(f"Update échoué, retry {attempt + 1} dans {delay}s...")
                    time.sleep(delay)

        return False, f"Échec après {self.config.max_retries + 1} tentatives: {last_error}", False

    def check_git_available(self) -> bool:
        """Vérifie que Git est disponible sur le système."""
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug(f"Git disponible: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("Git n'est pas installé ou n'est pas dans le PATH")
            return False

    def clean_remote_url(self, repo_path: Path) -> bool:
        """Nettoie l'URL du remote pour enlever les credentials.
        
        Utile pour migrer les dépôts existants qui ont encore le token dans l'URL.
        
        Args:
            repo_path: Chemin du dépôt
            
        Returns:
            True si le remote a été nettoyé, False sinon
        """
        try:
            repo = git.Repo(repo_path)
            if "origin" not in repo.remotes:
                return False
            
            remote = repo.remotes.origin
            remote_url = remote.url
            
            # Vérifier si l'URL contient des credentials
            import re
            clean_url = re.sub(r"://[^@]+@", "://", remote_url)
            
            if clean_url != remote_url:
                logger.debug(f"Nettoyage du remote pour {repo_path}")
                remote.set_url(clean_url)
                
                # Configurer le credential helper si on a un token
                if self.config.token and self.config.clone_method == "http":
                    repo.git.config("credential.helper", "store", local=True)
                    self._store_credential(repo_path, clean_url)
                
                return True
            
            return False
        except Exception as e:
            logger.debug(f"Erreur lors du nettoyage du remote: {e}")
            return False
