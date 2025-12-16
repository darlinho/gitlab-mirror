"""Interface en ligne de commande pour LOGISCO GitLab Mirror."""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

import click
import git
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import Config, debug_config, find_config_file, find_env_file, load_config
from .logger import logger, setup_logger
from .models import ProjectStatus, SyncSummary
from .sync import ProjectSynchronizer

console = Console()


# ============================================================================
# GROUPE PRINCIPAL
# ============================================================================


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="LOGISCO GitLab Mirror")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """LOGISCO GitLab Mirror - Synchronisation GitLab → Filesystem.

    \b
    Commandes disponibles:
      init    Initialiser la configuration (première utilisation)
      sync    Synchroniser des groupes GitLab
      status  Vérifier l'état de synchronisation
      clean   Nettoyer les dossiers orphelins
      config  Afficher la configuration actuelle

    \b
    Première utilisation:
      lgm init              # Configure token, URL, répertoire

    \b
    Exemples:
      lgm sync -g mon-groupe
      lgm status -g mon-groupe
      lgm clean --dry-run
      lgm config

    \b
    Configuration:
      Fichier: ~/.config/lgm/.env (créé par lgm init)
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def create_progress_bar() -> Progress:
    """Crée une barre de progression Rich."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TextColumn("[dim]{task.fields[status]}"),
        console=console,
        transient=True,
    )


def print_banner() -> None:
    """Affiche la bannière de l'application."""
    banner = Text()
    banner.append("LOGISCO GitLab Mirror", style="bold cyan")
    banner.append(f" v{__version__}", style="dim")
    console.print(Panel(banner, subtitle="Synchronisation GitLab → Filesystem"))


def print_config(config: Config) -> None:
    """Affiche la configuration utilisée."""
    table = Table(title="Configuration", show_header=False, box=None)
    table.add_column("Paramètre", style="cyan")
    table.add_column("Valeur")

    table.add_row("Instance GitLab", config.gitlab_url)
    table.add_row("Répertoire racine", str(config.root_dir))
    table.add_row("Méthode de clonage", config.clone_method.upper())
    table.add_row("Mise à jour", "Oui" if config.update_existing else "Non")
    table.add_row("Mode", "DRY-RUN" if config.dry_run else "Synchronisation")

    console.print(table)
    console.print()


def print_summary(summary: SyncSummary, config: Config, elapsed: float = 0) -> None:
    """Affiche le résumé de la synchronisation.

    Args:
        summary: Résumé de la synchronisation
        config: Configuration utilisée
        elapsed: Temps écoulé en secondes
    """
    console.print()
    console.print("=" * 70)
    console.print()

    # Tableau de résumé
    table = Table(title="📊 Résumé de la synchronisation", show_header=True)
    table.add_column("Métrique", style="cyan")
    table.add_column("Valeur", justify="right")

    table.add_row("Groupes traités", str(summary.total_groups))
    table.add_row("Projets trouvés", str(summary.total_projects))
    table.add_row("", "")

    # Colorier selon le statut
    table.add_row(
        "✓ Clonés",
        f"[green]{summary.cloned}[/green]" if summary.cloned > 0 else "0",
    )
    table.add_row(
        "↑ Mis à jour",
        f"[blue]{summary.updated}[/blue]" if summary.updated > 0 else "0",
    )
    table.add_row(
        "= Déjà à jour",
        f"[dim]{summary.already_up_to_date}[/dim]" if summary.already_up_to_date > 0 else "0",
    )
    table.add_row(
        "⊘ Ignorés",
        f"[yellow]{summary.ignored}[/yellow]" if summary.ignored > 0 else "0",
    )
    table.add_row(
        "⊖ Exclus",
        f"[dim]{summary.excluded}[/dim]" if summary.excluded > 0 else "0",
    )
    table.add_row(
        "✗ Erreurs",
        f"[red]{summary.errors}[/red]" if summary.errors > 0 else "0",
    )

    if summary.total_projects > 0:
        table.add_row("", "")
        success_rate = summary.success_rate
        color = "green" if success_rate >= 90 else "yellow" if success_rate >= 70 else "red"
        table.add_row("Taux de réussite", f"[{color}]{success_rate:.1f}%[/{color}]")

    # Afficher le temps
    if elapsed > 0:
        table.add_row("", "")
        if elapsed < 60:
            time_str = f"{elapsed:.1f}s"
        else:
            mins = int(elapsed // 60)
            secs = elapsed % 60
            time_str = f"{mins}m {secs:.0f}s"
        table.add_row("⏱ Durée", f"[cyan]{time_str}[/cyan]")

    console.print(table)

    # Afficher les erreurs si présentes
    if summary.errors > 0:
        console.print()
        error_table = Table(title="❌ Erreurs détaillées", show_header=True)
        error_table.add_column("Projet", style="cyan")
        error_table.add_column("Erreur", style="red")

        for result in summary.results:
            if result.status == ProjectStatus.ERROR and result.error_message:
                error_table.add_row(
                    result.project.path_with_namespace,
                    result.error_message[:80],
                )

        console.print(error_table)

    # Afficher les projets exclus par pattern
    if summary.excluded > 0 and config.verbose:
        console.print()
        excluded_table = Table(title="⊖ Projets exclus par pattern", show_header=True)
        excluded_table.add_column("Projet", style="cyan")
        excluded_table.add_column("Pattern", style="dim")

        for result in summary.results:
            if result.status == ProjectStatus.EXCLUDED:
                excluded_table.add_row(
                    result.project.path_with_namespace,
                    result.error_message or "",
                )

        console.print(excluded_table)

    # Afficher les projets ignorés (conflits) si présents
    if summary.ignored > 0 and config.verbose:
        console.print()
        ignored_table = Table(title="⊘ Projets ignorés (conflits)", show_header=True)
        ignored_table.add_column("Projet", style="cyan")
        ignored_table.add_column("Raison", style="yellow")

        for result in summary.results:
            if result.status == ProjectStatus.IGNORED:
                ignored_table.add_row(
                    result.project.path_with_namespace,
                    result.error_message or "Conflit avec dossier existant",
                )

        console.print(ignored_table)

    console.print()

    if config.dry_run:
        console.print("[yellow]Mode DRY-RUN: Aucune modification n'a été effectuée[/yellow]")
    else:
        console.print(f"[green]✓ Synchronisation terminée ![/green] " f"Dossier: {config.root_dir}")

    console.print()


@cli.command("sync")
@click.option(
    "--group",
    "-g",
    "groups",
    multiple=True,
    required=True,
    help="Groupe GitLab à synchroniser (ID ou chemin complet). Peut être spécifié plusieurs fois.",
)
@click.option(
    "--root-dir",
    "-r",
    type=click.Path(path_type=Path),
    help="Répertoire racine pour la synchronisation (défaut: ./gitlab-repos)",
)
@click.option(
    "--instance-url",
    "-u",
    help="URL de l'instance GitLab (défaut: https://gitlab.com)",
)
@click.option(
    "--token",
    "-t",
    help="Token d'accès GitLab (ou définir GITLAB_TOKEN)",
)
@click.option(
    "--clone-method",
    "-m",
    type=click.Choice(["http", "ssh"], case_sensitive=False),
    help="Méthode de clonage: http ou ssh (défaut: http)",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help="Mode simulation sans modifications",
)
@click.option(
    "--no-update",
    is_flag=True,
    help="Ne pas mettre à jour les dépôts existants",
)
@click.option(
    "--skip-recent",
    "-s",
    type=float,
    default=0,
    help="Ne pas MAJ si fetch récent (heures, 0=désactivé, ex: 4 pour 4h)",
)
@click.option(
    "--no-smart",
    is_flag=True,
    help="Désactiver la vérification intelligente avant fetch",
)
@click.option(
    "--threads",
    "-j",
    type=int,
    default=None,
    help="Nombre de threads parallèles (défaut: depuis config.toml ou 4)",
)
@click.option(
    "--exclude",
    "-e",
    "excludes",
    multiple=True,
    help="Pattern de projets à exclure (ex: '*/test-*'). Peut être répété.",
)
@click.option(
    "--include",
    "-i",
    "includes",
    multiple=True,
    help="Pattern de projets à inclure (si défini, seuls ceux-ci). Peut être répété.",
)
@click.option(
    "--depth",
    type=int,
    default=0,
    help="Profondeur de clonage (0=complet, 1=shallow). Shallow clone plus rapide.",
)
@click.option(
    "--single-branch",
    is_flag=True,
    help="Cloner uniquement la branche par défaut (plus rapide).",
)
@click.option(
    "--filter",
    "filter_blobs",
    is_flag=True,
    help="Partial clone: télécharge blobs à la demande (pour très gros repos).",
)
@click.option(
    "--prune",
    is_flag=True,
    help="Supprimer les branches distantes supprimées (git fetch --prune).",
)
@click.option(
    "--archived",
    is_flag=True,
    help="Inclure les projets archivés.",
)
@click.option(
    "--since",
    type=int,
    default=0,
    help="Sync seulement les projets modifiés depuis N jours (0=tous).",
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    help="Timeout pour les opérations Git en secondes (défaut: 300).",
)
@click.option(
    "--log-file",
    type=click.Path(),
    default="",
    help="Fichier de log (ex: sync.log).",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Afficher le résultat en JSON (pour intégration CI).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Mode verbeux",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    help="Mode debug",
)
def sync_cmd(
    groups: tuple[str, ...],
    root_dir: Optional[Path],
    instance_url: Optional[str],
    token: Optional[str],
    clone_method: Optional[str],
    dry_run: bool,
    no_update: bool,
    skip_recent: float,
    no_smart: bool,
    threads: Optional[int],
    excludes: tuple[str, ...],
    includes: tuple[str, ...],
    depth: int,
    single_branch: bool,
    filter_blobs: bool,
    prune: bool,
    archived: bool,
    since: int,
    timeout: int,
    log_file: str,
    json_output: bool,
    verbose: bool,
    debug: bool,
) -> None:
    """Synchronise des groupes GitLab vers le filesystem.

    \b
    Exemples:
      lgm sync -g mon-groupe
      lgm sync -g groupe1 -g groupe2 -j 8
      lgm sync -g groupe --depth 1 --prune
      lgm sync -g groupe -e "*/test-*" --json

    """
    try:
        # Afficher la bannière (sauf en mode JSON)
        if not json_output:
            print_banner()

        # Configurer le logger (silencieux en mode JSON, avec fichier si demandé)
        setup_logger(
            verbose=verbose and not json_output,
            debug=debug and not json_output,
            log_file=log_file if log_file else None,
        )

        # Charger la configuration
        try:
            config = load_config(
                gitlab_url=instance_url,
                token=token,
                root_dir=root_dir,
                dry_run=dry_run,
                verbose=verbose,
                debug=debug,
                clone_method=clone_method,
                update_existing=not no_update,
                smart_update=not no_smart,
                skip_recent_hours=skip_recent,
                max_workers=threads,
                exclude_patterns=list(excludes) if excludes else None,
                include_patterns=list(includes) if includes else None,
                clone_depth=depth,
                single_branch=single_branch,
                filter_blobs=filter_blobs,
                json_output=json_output,
                prune=prune,
                include_archived=archived,
                since_days=since,
                log_file=log_file,
                git_timeout=timeout,
            )
            config.ensure_token()
        except ValueError as e:
            console.print(f"[red]Erreur de configuration: {e}[/red]")
            sys.exit(1)

        # Afficher la configuration
        if verbose or debug:
            print_config(config)

        # Créer le synchroniseur
        synchronizer = ProjectSynchronizer(config)

        # Lancer la synchronisation
        if not json_output:
            console.print("[cyan]🚀 Démarrage de la synchronisation...[/cyan]\n")

        # Mesurer le temps
        start_time = time.time()

        # Synchroniser (les logs sont gérés par le logger)
        summary = synchronizer.sync_groups(list(groups))

        # Calculer le temps écoulé
        elapsed = time.time() - start_time

        # Sortie JSON ou affichage classique
        if json_output:
            output = {
                "total_groups": summary.total_groups,
                "total_projects": summary.total_projects,
                "cloned": summary.cloned,
                "updated": summary.updated,
                "already_up_to_date": summary.already_up_to_date,
                "ignored": summary.ignored,
                "excluded": summary.excluded,
                "errors": summary.errors,
                "success_rate": summary.success_rate,
                "elapsed_seconds": round(elapsed, 2),
                "root_dir": str(config.root_dir),
            }
            print(json.dumps(output, indent=2))
        else:
            print_summary(summary, config, elapsed)

        # Code de sortie
        if summary.errors > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interruption par l'utilisateur[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Erreur fatale: {e}[/red]")
        if debug:
            console.print_exception()
        sys.exit(1)


@cli.command("status")
@click.option(
    "--group",
    "-g",
    "groups",
    multiple=True,
    required=True,
    help="Groupe GitLab à vérifier (requis).",
)
@click.option(
    "--root-dir",
    "-r",
    type=click.Path(path_type=Path),
    help="Répertoire racine (défaut: ./gitlab-repos)",
)
@click.option(
    "--token",
    "-t",
    help="Token d'accès GitLab (ou définir GITLAB_TOKEN)",
)
@click.option(
    "--instance-url",
    "-u",
    help="URL de l'instance GitLab",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Sortie JSON.",
)
def status_cmd(
    groups: tuple[str, ...],
    root_dir: Optional[Path],
    token: Optional[str],
    instance_url: Optional[str],
    json_output: bool,
) -> None:
    """Compare l'état GitLab vs local pour un groupe."""
    from .gitlab_api import GitLabClient

    try:
        # Charger la config
        config = load_config(
            gitlab_url=instance_url,
            token=token,
            root_dir=root_dir,
        )
        config.ensure_token()

        if not json_output:
            print_banner()
            console.print(f"\n[cyan]📡 Connexion à GitLab...[/cyan]")

        # Connexion GitLab
        gitlab_client = GitLabClient(config)

        # Récupérer les projets GitLab
        gitlab_projects = gitlab_client.discover_all_projects(list(groups))
        gitlab_paths = {p.path_with_namespace for p in gitlab_projects}

        if not json_output:
            console.print(f"[green]✓ {len(gitlab_projects)} projets trouvés sur GitLab[/green]\n")

        # Scanner les repos locaux
        local_paths: set[str] = set()
        local_repos: dict[str, dict] = {}

        if config.root_dir.exists():
            for git_path in config.root_dir.rglob(".git"):
                repo_path = git_path.parent
                try:
                    rel_path = str(repo_path.relative_to(config.root_dir))
                    local_paths.add(rel_path)

                    repo = git.Repo(repo_path)
                    local_repos[rel_path] = {
                        "branch": repo.active_branch.name if not repo.head.is_detached else "DETACHED",
                        "dirty": repo.is_dirty(untracked_files=True),
                    }
                except Exception:
                    local_repos[rel_path] = {"error": True}

        # Classifier les projets
        synced = []  # Sur GitLab ET en local
        missing = []  # Sur GitLab mais PAS en local
        orphans = []  # En local mais PAS sur GitLab

        for project in gitlab_projects:
            path = project.path_with_namespace
            if path in local_paths:
                info = local_repos.get(path, {})
                synced.append({
                    "path": path,
                    "branch": info.get("branch", "?"),
                    "dirty": info.get("dirty", False),
                    "error": info.get("error", False),
                })
            else:
                missing.append({"path": path})

        for local_path in local_paths:
            if local_path not in gitlab_paths:
                info = local_repos.get(local_path, {})
                orphans.append({
                    "path": local_path,
                    "branch": info.get("branch", "?"),
                })

        # Sortie
        if json_output:
            output = {
                "root_dir": str(config.root_dir),
                "gitlab_projects": len(gitlab_projects),
                "synced": len(synced),
                "missing": len(missing),
                "orphans": len(orphans),
                "details": {
                    "synced": synced,
                    "missing": missing,
                    "orphans": orphans,
                },
            }
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[cyan]📁 Répertoire:[/cyan] {config.root_dir}\n")

            # Tableau synced
            if synced:
                table = Table(title=f"[green]✓ Synchronisés ({len(synced)})[/green]")
                table.add_column("Projet", style="cyan")
                table.add_column("Branche", style="blue")
                table.add_column("État", justify="center")

                for repo in sorted(synced, key=lambda x: x["path"]):
                    if repo.get("error"):
                        table.add_row(repo["path"], "-", "[red]ERREUR[/red]")
                    else:
                        status = "[green]✓[/green]" if not repo["dirty"] else "[yellow]●[/yellow]"
                        table.add_row(repo["path"], repo["branch"], status)
                console.print(table)
                console.print()

            # Tableau missing
            if missing:
                table = Table(title=f"[red]✗ Non clonés ({len(missing)})[/red]")
                table.add_column("Projet GitLab", style="red")

                for repo in sorted(missing, key=lambda x: x["path"]):
                    table.add_row(repo["path"])
                console.print(table)
                console.print()

            # Tableau orphans
            if orphans:
                table = Table(title=f"[yellow]? Orphelins ({len(orphans)})[/yellow]")
                table.add_column("Projet local", style="yellow")
                table.add_column("Branche", style="dim")

                for repo in sorted(orphans, key=lambda x: x["path"]):
                    table.add_row(repo["path"], repo.get("branch", "?"))
                console.print(table)
                console.print()

            # Résumé
            console.print("=" * 50)
            total = len(synced) + len(missing)
            sync_pct = (len(synced) / total * 100) if total > 0 else 0
            color = "green" if sync_pct == 100 else "yellow" if sync_pct >= 80 else "red"
            console.print(f"[{color}]Synchronisation: {len(synced)}/{total} ({sync_pct:.0f}%)[/{color}]")

            if missing:
                console.print(f"[red]→ {len(missing)} projet(s) à cloner avec: lgm sync -g {' -g '.join(groups)}[/red]")
            if orphans:
                console.print(f"[yellow]→ {len(orphans)} projet(s) orphelin(s) (supprimés de GitLab ?)[/yellow]")

    except ValueError as e:
        console.print(f"[red]Erreur: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Erreur: {e}[/red]")
        sys.exit(1)


@cli.command("config")
@click.option("--debug", "-d", is_flag=True, help="Afficher les informations de debug.")
def config_cmd(debug: bool) -> None:
    """Affiche la configuration actuelle et les fichiers utilisés."""
    print_banner()

    # Fichiers de configuration trouvés
    console.print("\n[bold cyan]📁 Fichiers de configuration[/bold cyan]\n")

    config_file = find_config_file()
    env_file = find_env_file()

    table = Table(show_header=True, box=None)
    table.add_column("Type", style="cyan")
    table.add_column("Fichier")
    table.add_column("État")

    if config_file:
        table.add_row("TOML", str(config_file), "[green]✓ Trouvé[/green]")
    else:
        table.add_row("TOML", "-", "[dim]Non trouvé[/dim]")

    if env_file:
        table.add_row(".env", env_file, "[green]✓ Trouvé[/green]")
    else:
        table.add_row(".env", "-", "[dim]Non trouvé[/dim]")

    console.print(table)

    # Mode debug : afficher le contenu du fichier .env
    if debug and env_file:
        console.print("\n[bold yellow]🔍 Debug: Contenu du fichier .env[/bold yellow]\n")
        debug_info = debug_config()
        if debug_info.get("env_file_contents"):
            for key, value in debug_info["env_file_contents"].items():
                # Masquer les tokens
                if "TOKEN" in key.upper():
                    value = "***" + value[-4:] if len(value) > 4 else "***"
                console.print(f"  [cyan]{key}[/cyan] = {value}")
        else:
            console.print("  [dim]Fichier vide ou illisible[/dim]")

    # Charger et afficher la configuration
    try:
        config = load_config()

        console.print("\n[bold cyan]⚙️ Configuration active[/bold cyan]\n")

        table = Table(show_header=False, box=None)
        table.add_column("Paramètre", style="cyan", width=25)
        table.add_column("Valeur")

        # Masquer le token
        token_display = "***" + config.token[-4:] if len(config.token) > 4 else "[red]Non défini[/red]"

        table.add_row("URL GitLab", config.gitlab_url)
        table.add_row("Token", token_display)
        table.add_row("Répertoire racine", str(config.root_dir))
        table.add_row("Méthode de clonage", config.clone_method.upper())
        table.add_row("Workers parallèles", str(config.max_workers))
        table.add_row("Smart update", "Oui" if config.smart_update else "Non")

        if config.exclude_patterns:
            table.add_row("Patterns exclus", ", ".join(config.exclude_patterns))
        if config.include_patterns:
            table.add_row("Patterns inclus", ", ".join(config.include_patterns))

        console.print(table)

        console.print("\n[bold cyan]📍 Emplacements recherchés[/bold cyan]\n")
        console.print("[dim]Fichiers TOML (par ordre de priorité) :[/dim]")
        from .config import CONFIG_LOCATIONS
        for loc in CONFIG_LOCATIONS:
            exists = "[green]✓[/green]" if loc.exists() else "[dim]✗[/dim]"
            console.print(f"  {exists} {loc}")

        console.print("\n[dim]Fichiers .env (par ordre de priorité) :[/dim]")
        from .config import ENV_LOCATIONS
        for loc in ENV_LOCATIONS:
            exists = "[green]✓[/green]" if loc.exists() else "[dim]✗[/dim]"
            console.print(f"  {exists} {loc}")

    except Exception as e:
        console.print(f"[red]Erreur lors du chargement: {e}[/red]")

    console.print()


@cli.command("init")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Écraser la configuration existante.",
)
def init_cmd(force: bool) -> None:
    """Initialise la configuration de LGM.

    Crée les fichiers de configuration dans ~/.config/lgm/
    """
    print_banner()
    console.print("\n[bold cyan]🔧 Initialisation de LOGISCO GitLab Mirror[/bold cyan]\n")

    config_dir = Path.home() / ".config" / "lgm"
    env_file = config_dir / ".env"
    toml_file = config_dir / "config.toml"

    # Vérifier si config existe déjà
    if env_file.exists() and not force:
        console.print(f"[yellow]⚠ Configuration existante trouvée: {env_file}[/yellow]")
        console.print("[dim]Utilisez --force pour écraser[/dim]")
        if not click.confirm("\nVoulez-vous continuer et écraser ?"):
            console.print("[yellow]Annulé[/yellow]")
            return

    # Créer le dossier
    config_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓[/green] Dossier créé: {config_dir}")

    # Demander les informations
    console.print("\n[bold]Configuration requise:[/bold]\n")

    gitlab_url = click.prompt(
        "URL GitLab",
        default="https://gitlab.com",
        show_default=True,
    )

    token = click.prompt(
        "Token GitLab (glpat-...)",
        hide_input=True,
    )

    root_dir = click.prompt(
        "Répertoire de synchronisation",
        default="~/gitlab-repos",
        show_default=True,
    )

    # Créer le fichier .env
    env_content = f"""# LOGISCO GitLab Mirror - Configuration
# Généré automatiquement par: lgm init
# Variables avec préfixe GITLAB_

# URL de l'instance GitLab
GITLAB_URL={gitlab_url}

# Token d'accès GitLab (scope: read_api)
GITLAB_TOKEN={token}

# Répertoire racine de synchronisation
GITLAB_ROOT_DIR={root_dir}
"""

    env_file.write_text(env_content)
    env_file.chmod(0o600)  # Permissions restrictives pour le token
    console.print(f"[green]✓[/green] Fichier créé: {env_file} [dim](permissions: 600)[/dim]")

    # Créer le fichier TOML avec options avancées
    toml_content = """# LOGISCO GitLab Mirror - Configuration avancée
# Documentation: lgm --help

[performance]
# Nombre de threads parallèles (1-32)
max_workers = 8

# Timeout pour les opérations Git (secondes)
git_timeout = 300

[smart_update]
# Vérifier si vraiment derrière avant de fetch
enabled = true

# Ne pas MAJ si fetch récent (heures, 0 = désactivé)
skip_recent_hours = 4

[clone]
# Profondeur de clonage (0 = complet, 1 = shallow)
depth = 0

# Prune des branches supprimées lors du fetch
prune = true

[filters]
# Patterns de projets à exclure (fnmatch)
# exclude = ["*/archived-*", "*/test-*"]

# Patterns de projets à inclure
# include = ["*/prod-*"]
"""

    toml_file.write_text(toml_content)
    console.print(f"[green]✓[/green] Fichier créé: {toml_file}")

    # Test de connexion
    console.print("\n[cyan]🔌 Test de connexion...[/cyan]")
    try:
        import gitlab
        gl = gitlab.Gitlab(gitlab_url, private_token=token)
        gl.auth()
        user = gl.user
        console.print(f"[green]✓[/green] Connecté en tant que: [bold]{user.username}[/bold]")  # type: ignore
    except Exception as e:
        console.print(f"[red]✗ Erreur de connexion: {e}[/red]")
        console.print("[dim]Vérifiez votre token et l'URL GitLab[/dim]")
        return

    # Résumé
    console.print("\n" + "=" * 50)
    console.print("\n[bold green]✓ Configuration terminée ![/bold green]\n")
    console.print("Fichiers créés:")
    console.print(f"  • {env_file}")
    console.print(f"  • {toml_file}")
    console.print("\nCommandes utiles:")
    console.print("  [cyan]lgm config[/cyan]      - Voir la configuration")
    console.print("  [cyan]lgm sync -g G[/cyan]   - Synchroniser le groupe G")
    console.print("  [cyan]lgm status -g G[/cyan] - Voir l'état du groupe G")
    console.print()


@cli.command("clean")
@click.option(
    "--root-dir",
    "-r",
    type=click.Path(path_type=Path, exists=True),
    help="Répertoire racine à nettoyer (défaut: ./gitlab-repos)",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help="Mode simulation sans suppression.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Supprimer sans confirmation.",
)
def clean_cmd(root_dir: Optional[Path], dry_run: bool, force: bool) -> None:
    """Supprime les dépôts qui ne sont plus sur GitLab ou les dossiers vides."""
    # Déterminer le répertoire
    if root_dir is None:
        config = load_config()
        root_dir = config.root_dir

    if not root_dir.exists():
        console.print(f"[red]Répertoire non trouvé: {root_dir}[/red]")
        sys.exit(1)

    print_banner()
    console.print(f"\n[cyan]🧹 Nettoyage de:[/cyan] {root_dir}\n")

    # Trouver les dossiers vides (exclure .git)
    empty_dirs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
        path = Path(dirpath)
        if path == root_dir:
            continue
        # Ignorer tout ce qui est dans .git
        if ".git" in path.parts:
            continue
        # Dossier vide (ou contient seulement des dossiers vides)
        if not filenames and not dirnames:
            empty_dirs.append(path)

    # Trouver les dépôts avec remote invalide
    invalid_repos: list[Path] = []
    for git_path in root_dir.rglob(".git"):
        repo_path = git_path.parent
        try:
            repo = git.Repo(repo_path)
            if "origin" in [r.name for r in repo.remotes]:
                # Vérifier si le remote existe encore (optionnel, peut être lent)
                pass
        except Exception:
            invalid_repos.append(repo_path)

    # Afficher ce qui sera supprimé
    to_delete = empty_dirs + invalid_repos
    if not to_delete:
        console.print("[green]✓ Rien à nettoyer ![/green]")
        return

    table = Table(title="🗑️ Éléments à supprimer")
    table.add_column("Chemin", style="cyan")
    table.add_column("Type")

    for path in empty_dirs:
        table.add_row(str(path.relative_to(root_dir)), "[dim]Dossier vide[/dim]")
    for path in invalid_repos:
        table.add_row(str(path.relative_to(root_dir)), "[yellow]Repo invalide[/yellow]")

    console.print(table)
    console.print(f"\n[bold]Total: {len(to_delete)} élément(s)[/bold]")

    if dry_run:
        console.print("\n[yellow]Mode DRY-RUN: Aucune suppression effectuée[/yellow]")
        return

    # Confirmation
    if not force:
        if not click.confirm("\nSupprimer ces éléments ?"):
            console.print("[yellow]Annulé[/yellow]")
            return

    # Suppression
    deleted = 0
    for path in to_delete:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted += 1
        except Exception as e:
            console.print(f"[red]Erreur: {path}: {e}[/red]")

    console.print(f"\n[green]✓ {deleted} élément(s) supprimé(s)[/green]")


# Alias pour compatibilité avec l'ancien point d'entrée
def main() -> None:
    """Point d'entrée principal."""
    cli()


if __name__ == "__main__":
    cli()
