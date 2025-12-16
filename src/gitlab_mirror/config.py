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
    dry_run: Optional[bool] = None,
    verbose: Optional[bool] = None,
    debug: Optional[bool] = None,
    clone_method: Optional[str] = None,
    update_existing: Optional[bool] = None,
    smart_update: Optional[bool] = None,
    skip_recent_hours: Optional[float] = None,
    max_workers: Optional[int] = None,
    exclude_patterns: Optional[list[str]] = None,
    include_patterns: Optional[list[str]] = None,
    clone_depth: Optional[int] = None,
    single_branch: Optional[bool] = None,
    filter_blobs: Optional[bool] = None,
    json_output: Optional[bool] = None,
    prune: Optional[bool] = None,
    include_archived: Optional[bool] = None,
    since_days: Optional[int] = None,
    log_file: Optional[str] = None,
    git_timeout: Optional[int] = None,
) -> Config:
    """Charge la configuration avec priorité aux arguments CLI.
    
    Ordre de priorité (du plus faible au plus fort) :
    1. Valeurs par défaut de la classe Config
    2. Variables d'environnement / fichier .env
    3. Fichier TOML (config.toml, .lgm.toml, etc.)
    4. Arguments CLI
    """
    # Charger la config de base depuis les variables d'environnement / fichier .env
    config = Config()
    
    # Charger le fichier TOML et appliquer les valeurs
    toml_config = load_toml_config()
    if toml_config:
        # Support des clés au niveau racine (pour compatibilité)
        if "gitlab_url" in toml_config:
            config.url = toml_config["gitlab_url"]
        if "url" in toml_config:
            config.url = toml_config["url"]
        if "token" in toml_config:
            config.token = toml_config["token"]
        if "root_dir" in toml_config:
            config.root_dir = Path(toml_config["root_dir"]).expanduser().resolve()
        if "clone_method" in toml_config:
            config.clone_method = toml_config["clone_method"]
        if "dry_run" in toml_config:
            config.dry_run = toml_config["dry_run"]
        if "update_existing" in toml_config:
            config.update_existing = toml_config["update_existing"]
        
        # Section [performance]
        if "performance" in toml_config:
            perf = toml_config["performance"]
            if "max_workers" in perf:
                config.max_workers = perf["max_workers"]
            if "git_timeout" in perf:
                config.git_timeout = perf["git_timeout"]
        
        # Section [smart_update]
        if "smart_update" in toml_config:
            smart = toml_config["smart_update"]
            if "enabled" in smart:
                config.smart_update = smart["enabled"]
            if "skip_recent_hours" in smart:
                config.skip_recent_hours = smart["skip_recent_hours"]
        
        # Section [clone]
        if "clone" in toml_config:
            clone = toml_config["clone"]
            if "depth" in clone:
                config.clone_depth = clone["depth"]
            if "prune" in clone:
                config.prune = clone["prune"]
            if "single_branch" in clone:
                config.single_branch = clone["single_branch"]
            if "filter_blobs" in clone:
                config.filter_blobs = clone["filter_blobs"]
        
        # Section [filters]
        if "filters" in toml_config:
            filters = toml_config["filters"]
            if "exclude" in filters:
                patterns = filters["exclude"]
                config.exclude_patterns = patterns if isinstance(patterns, list) else [patterns]
            if "include" in filters:
                patterns = filters["include"]
                config.include_patterns = patterns if isinstance(patterns, list) else [patterns]
        
        # Autres clés au niveau racine (pour compatibilité, seulement si pas dans une section)
        # Note: Les sections ont la priorité, donc on ne surcharge que si la clé n'est pas une section
        if "smart_update" in toml_config and not isinstance(toml_config["smart_update"], dict):
            config.smart_update = toml_config["smart_update"]
        if "skip_recent_hours" in toml_config and "smart_update" not in toml_config:
            # Seulement si pas déjà défini dans la section smart_update
            config.skip_recent_hours = toml_config["skip_recent_hours"]
        if "max_workers" in toml_config and "performance" not in toml_config:
            # Seulement si pas déjà défini dans la section performance
            config.max_workers = toml_config["max_workers"]
        if "clone_depth" in toml_config and "clone" not in toml_config:
            # Seulement si pas déjà défini dans la section clone
            config.clone_depth = toml_config["clone_depth"]
        if "single_branch" in toml_config and "clone" not in toml_config:
            config.single_branch = toml_config["single_branch"]
        if "filter_blobs" in toml_config and "clone" not in toml_config:
            config.filter_blobs = toml_config["filter_blobs"]
        if "prune" in toml_config and "clone" not in toml_config:
            config.prune = toml_config["prune"]
        if "git_timeout" in toml_config and "performance" not in toml_config:
            config.git_timeout = toml_config["git_timeout"]
        if "json_output" in toml_config:
            config.json_output = toml_config["json_output"]
        if "include_archived" in toml_config:
            config.include_archived = toml_config["include_archived"]
        if "since_days" in toml_config:
            config.since_days = toml_config["since_days"]
        if "log_file" in toml_config:
            config.log_file = toml_config["log_file"]
        if "exclude_patterns" in toml_config and "filters" not in toml_config:
            patterns = toml_config["exclude_patterns"]
            config.exclude_patterns = patterns if isinstance(patterns, list) else [patterns]
        if "include_patterns" in toml_config and "filters" not in toml_config:
            patterns = toml_config["include_patterns"]
            config.include_patterns = patterns if isinstance(patterns, list) else [patterns]

    # Surcharger avec les arguments CLI fournis (priorité la plus haute)
    if gitlab_url is not None:
        config.url = gitlab_url
    if token is not None:
        config.token = token
    if root_dir is not None:
        config.root_dir = root_dir.expanduser().resolve()
    if clone_method is not None:
        config.clone_method = clone_method
    if dry_run is not None:
        config.dry_run = dry_run
    if verbose is not None:
        config.verbose = verbose
    if debug is not None:
        config.debug = debug
        if debug:
            config.verbose = True  # debug implique verbose
    if update_existing is not None:
        config.update_existing = update_existing
    if smart_update is not None:
        config.smart_update = smart_update
    if skip_recent_hours is not None:
        config.skip_recent_hours = skip_recent_hours
    if max_workers is not None:
        config.max_workers = max_workers
    if clone_depth is not None:
        config.clone_depth = clone_depth
    if single_branch is not None:
        config.single_branch = single_branch
    if filter_blobs is not None:
        config.filter_blobs = filter_blobs
    if json_output is not None:
        config.json_output = json_output
    if prune is not None:
        config.prune = prune
    if include_archived is not None:
        config.include_archived = include_archived
    if since_days is not None:
        config.since_days = since_days
    if log_file is not None:
        config.log_file = log_file
    if git_timeout is not None:
        config.git_timeout = git_timeout
    if exclude_patterns is not None:
        config.exclude_patterns = list(exclude_patterns)
    if include_patterns is not None:
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
