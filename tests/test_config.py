"""Tests pour le module config."""

from pathlib import Path

import pytest

from gitlab_mirror.config import Config, load_config


def test_config_default_values() -> None:
    """Test les valeurs par défaut de la configuration."""
    config = Config(token="test-token")

    assert config.gitlab_url == "https://gitlab.com"
    assert config.token == "test-token"
    assert config.clone_method == "http"
    assert config.dry_run is False
    assert config.update_existing is True


def test_config_token_validation() -> None:
    """Test la validation du token."""
    config = Config(token="")

    with pytest.raises(ValueError, match="Token GitLab requis"):
        config.ensure_token()


def test_config_clone_method_validation() -> None:
    """Test la validation de la méthode de clonage."""
    with pytest.raises(ValueError, match="clone_method doit être"):
        Config(token="test", clone_method="ftp")


def test_config_root_dir_expansion(tmp_path: Path) -> None:
    """Test l'expansion du répertoire racine."""
    config = Config(token="test", root_dir=tmp_path / "repos")

    assert config.root_dir.is_absolute()
    assert config.root_dir == (tmp_path / "repos").resolve()


def test_load_config_with_overrides(tmp_path: Path) -> None:
    """Test le chargement de la config avec des surcharges."""
    config = load_config(
        gitlab_url="https://gitlab.custom.com",
        token="custom-token",
        root_dir=tmp_path / "custom",
        dry_run=True,
        verbose=True,
    )

    assert config.gitlab_url == "https://gitlab.custom.com"
    assert config.token == "custom-token"
    assert config.root_dir == (tmp_path / "custom").resolve()
    assert config.dry_run is True
    assert config.verbose is True


def test_config_create_root_dir(tmp_path: Path) -> None:
    """Test la création du répertoire racine."""
    root = tmp_path / "new-repos"
    config = Config(token="test", root_dir=root)

    assert not root.exists()
    config.create_root_dir()
    assert root.exists()
    assert root.is_dir()
