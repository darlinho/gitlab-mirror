"""Configuration du système de logging."""

import logging
import sys
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """Formatter avec couleurs pour le terminal."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Vert
        "WARNING": "\033[33m",  # Jaune
        "ERROR": "\033[31m",  # Rouge
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Formate un enregistrement de log avec des couleurs."""
        if sys.stdout.isatty():
            levelname = record.levelname
            color = self.COLORS.get(levelname, self.COLORS["RESET"])
            record.levelname = f"{color}{levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logger(
    name: str = "gitlab_mirror",
    verbose: bool = False,
    debug: bool = False,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Configure et retourne un logger.

    Args:
        name: Nom du logger
        verbose: Active le mode verbeux (INFO)
        debug: Active le mode debug (DEBUG)
        log_file: Chemin optionnel vers un fichier de log

    Returns:
        Logger configuré
    """
    logger = logging.getLogger(name)

    # Éviter les duplications de handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Définir le niveau de log
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    logger.setLevel(level)

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Format pour la console
    console_format = "%(levelname)s - %(message)s"
    if debug:
        console_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    console_formatter = ColoredFormatter(console_format, datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Handler fichier optionnel
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        file_formatter = logging.Formatter(file_format, datefmt="%Y-%m-%d %H:%M:%S")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


# Logger global par défaut
logger = setup_logger()
