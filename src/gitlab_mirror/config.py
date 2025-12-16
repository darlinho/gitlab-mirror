"""Gestion de la configuration de LOGISCO GitLab Mirror."""

import os
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Emplacements de configuration par ordre de priorité
CONFIG_LOCATIONS = [
    Path.cwd() / ".lgm.toml",                    # Répertoire courant
    Path.cwd() / "lgm.toml",                     # Répertoire courant (alt)
    Path.home() / ".config" / "lgm" / "config.toml",  # XDG config
    Path.home() / ".lgm.toml",                   # Home utilisateur
    Path("/etc/lgm/config.toml"),                # Config système (Linux)
]

ENV_LOCATIONS = [
    Path.cwd() / ".env",                         # Répertoire courant
    Path.cwd() / ".lgm.env",                     # Répertoire courant (spécifique)
    Path.home() / ".config" / "lgm" / ".env",    # XDG config
    Path.home() / ".lgm.env",                    # Home utilisateur
]


def find_config_file() -> Optional[Path]:
    """Trouve le fichier de configuration TOML."""
    for path in CONFIG_LOCATIONS:
        if path.exists():
            return path
    return None


def find_env_file() -> Optional[str]:
    """Trouve le fichier .env."""
    for path in ENV_LOCATIONS:
        if path.exists():
            return str(path)
    return None


def load_toml_config() -> dict[str, Any]:
    """Charge la configuration depuis un fichier TOML."""
    config_path = find_config_file()
    if not config_path:
        return {}

    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(config_path, "rb") as f:
                return tomllib.load(f)
        else:
            import tomli
            with open(config_path, "rb") as f:
                return tomli.load(f)
    except Exception:
        return {}


def _load_env_file_manually() -> dict[str, str]:
    """Charge manuellement le fichier .env pour debug."""
    env_file = find_env_file()
    if not env_file:
        return {}
    
    result = {}
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    result[key.strip()] = value.strip()
    except Exception:
        pass
    return result


class Config(BaseSettings):
    """Configuration de LOGISCO GitLab Mirror.

    Variables d'environnement supportées dans le .env :
    - GITLAB_URL : URL de l'instance GitLab
    - GITLAB_TOKEN : Token d'accès GitLab
    - GITLAB_ROOT_DIR : Répertoire racine de synchronisation

    Emplacements du fichier .env (premier trouvé utilisé) :
    - .env ou .lgm.env (répertoire courant)
    - ~/.config/lgm/.env
    - ~/.lgm.env
    """

    model_config = SettingsConfigDict(
        env_prefix="GITLAB_",
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Configuration GitLab - ATTENTION: avec env_prefix="GITLAB_"
    # Le champ "url" correspond à la variable GITLAB_URL
    # Le champ "token" correspond à GITLAB_TOKEN
    url: str = Field(
        default="https://gitlab.com",
        description="URL de l'instance GitLab",
        alias="gitlab_url",
    )
    token: str = Field(
        default="",
        description="Token d'accès GitLab (REQUIS)",
    )

    # Configuration de synchronisation
    # Le champ "root_dir" correspond à GITLAB_ROOT_DIR
    root_dir: Path = Field(
        default=Path.home() / "gitlab-repos",
        description="Répertoire racine pour la synchronisation",
    )
    clone_method: str = Field(
        default="http",
        description="Méthode de clonage : 'http' ou 'ssh'",
    )

    # Options de comportement
    dry_run: bool = Field(
        default=False,
        description="Mode simulation sans modifications",
    )
    update_existing: bool = Field(
        default=True,
        description="Mettre à jour les dépôts existants",
    )
    fetch_only: bool = Field(
        default=True,
        description="Faire seulement un fetch (pas de merge/pull)",
    )

    # Options de politique de mise à jour intelligente
    smart_update: bool = Field(
        default=True,
        description="Vérifier si le repo est vraiment derrière avant de fetch",
    )
    skip_recent_hours: float = Field(
        default=0,
        description="Ne pas mettre à jour si fetch récent (0 = désactivé)",
    )

    # Options de performance
    max_workers: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Nombre de threads pour le clonage/mise à jour parallèle (1-32)",
    )
    git_timeout: int = Field(
        default=300,
        ge=30,
        description="Timeout pour les opérations Git en secondes",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Nombre de tentatives en cas d'échec réseau",
    )

    # Filtres
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="Patterns de projets à exclure (ex: '*/test-*', '*/old-*')",
    )
    include_patterns: list[str] = Field(
        default_factory=list,
        description="Patterns de projets à inclure (si défini, seuls ceux-ci sont sync)",
    )

    # Options de clonage
    clone_depth: int = Field(
        default=0,
        description="Profondeur de clonage (0 = complet, 1 = shallow)",
    )
    single_branch: bool = Field(
        default=False,
        description="Cloner uniquement la branche par défaut (plus rapide)",
    )
    filter_blobs: bool = Field(
        default=False,
        description="Partial clone: télécharge les blobs à la demande (pour gros repos)",
    )
    prune: bool = Field(
        default=False,
        description="Supprimer les branches distantes supprimées (git fetch --prune)",
    )

    # Filtres avancés
    include_archived: bool = Field(
        default=False,
        description="Inclure les projets archivés",
    )
    since_days: int = Field(
        default=0,
        description="Sync seulement les projets modifiés depuis N jours (0=tous)",
    )

    # Logging
    log_file: str = Field(
        default="",
        description="Fichier de log (vide = pas de fichier)",
    )

    # Options de sortie
    json_output: bool = Field(
        default=False,
        description="Afficher le résultat en JSON",
    )

    # Options d'affichage
    verbose: bool = Field(
        default=False,
        description="Mode verbeux",
    )
    debug: bool = Field(
        default=False,
        description="Mode debug",
    )

    # Options API
    api_timeout: int = Field(
        default=30,
        description="Timeout pour les requêtes API (secondes)",
    )

    @property
    def gitlab_url(self) -> str:
        """Alias pour compatibilité - retourne l'URL GitLab."""
        return self.url

    @gitlab_url.setter
    def gitlab_url(self, value: str) -> None:
        """Setter pour compatibilité."""
        self.url = value

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Valide que le token est présent."""
        if not v or v.strip() == "":
            # En mode validation, on accepte un token vide
            # La vérification réelle se fera à l'exécution
            pass
        return v

    @field_validator("root_dir")
    @classmethod
    def validate_root_dir(cls, v: Path) -> Path:
        """Convertit en Path absolu."""
        return v.expanduser().resolve()

    @field_validator("clone_method")
    @classmethod
    def validate_clone_method(cls, v: str) -> str:
        """Valide la méthode de clonage."""
        if v.lower() not in ["http", "ssh"]:
            raise ValueError("clone_method doit être 'http' ou 'ssh'")
        return v.lower()

    def ensure_token(self) -> None:
        """Vérifie que le token est présent, sinon lève une exception."""
        if not self.token or self.token.strip() == "":
            raise ValueError(
                "Token GitLab requis. "
                "Définissez la variable d'environnement GITLAB_TOKEN "
                "ou utilisez l'option --token."
            )

    def create_root_dir(self) -> None:
        """Crée le répertoire racine s'il n'existe pas."""
        self.root_dir.mkdir(parents=True, exist_ok=True)


def load_config(
    gitlab_url: Optional[str] = None,
    token: Optional[str] = None,
    root_dir: Optional[Path] = None,
    dry_run: bool = False,
    verbose: bool = False,
    debug: bool = False,
    clone_method: Optional[str] = None,
    update_existing: bool = True,
    smart_update: bool = True,
    skip_recent_hours: float = 0,
    max_workers: int = 4,
    exclude_patterns: Optional[list[str]] = None,
    include_patterns: Optional[list[str]] = None,
    clone_depth: int = 0,
    single_branch: bool = False,
    filter_blobs: bool = False,
    json_output: bool = False,
    prune: bool = False,
    include_archived: bool = False,
    since_days: int = 0,
    log_file: str = "",
    git_timeout: int = 300,
) -> Config:
    """Charge la configuration avec priorité aux arguments CLI."""
    # Charger la config de base depuis les variables d'environnement / fichier
    config = Config()

    # Surcharger avec les arguments CLI fournis
    if gitlab_url is not None:
        config.url = gitlab_url
    if token is not None:
        config.token = token
    if root_dir is not None:
        config.root_dir = root_dir.expanduser().resolve()
    if clone_method is not None:
        config.clone_method = clone_method

    config.dry_run = dry_run
    config.verbose = verbose or debug
    config.debug = debug
    config.update_existing = update_existing
    config.smart_update = smart_update
    config.skip_recent_hours = skip_recent_hours
    config.max_workers = max_workers
    config.clone_depth = clone_depth
    config.single_branch = single_branch
    config.filter_blobs = filter_blobs
    config.json_output = json_output
    config.prune = prune
    config.include_archived = include_archived
    config.since_days = since_days
    config.log_file = log_file
    config.git_timeout = git_timeout
    if exclude_patterns:
        config.exclude_patterns = list(exclude_patterns)
    if include_patterns:
        config.include_patterns = list(include_patterns)

    return config


def debug_config() -> dict[str, Any]:
    """Retourne les informations de debug sur la configuration."""
    env_file = find_env_file()
    env_vars = _load_env_file_manually() if env_file else {}
    
    return {
        "env_file_found": env_file,
        "env_file_contents": env_vars,
        "env_GITLAB_URL": os.environ.get("GITLAB_URL"),
        "env_GITLAB_TOKEN": "***" if os.environ.get("GITLAB_TOKEN") else None,
        "env_GITLAB_ROOT_DIR": os.environ.get("GITLAB_ROOT_DIR"),
    }
