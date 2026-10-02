"""Theatre and root-file discovery (FR-002).

A theatre is a directory whose configuration lives in exactly one of
``<theatre>/.troupe/troupe.yml`` or ``<theatre>/.troupe/troupe.yaml``. Discovery only reads the
filesystem; it never creates anything.
"""

from dataclasses import dataclass
from pathlib import Path

from troupe.errors import LoadError

STATE_DIR_NAME = ".troupe"
ROOT_FILE_NAMES = ("troupe.yml", "troupe.yaml")


@dataclass(frozen=True)
class Theatre:
    """A located theatre.

    Attributes:
        directory: The theatre directory (resolved, absolute).
        state_dir: ``directory / ".troupe"``.
        config_file: The single root configuration file.
    """

    directory: Path
    state_dir: Path
    config_file: Path


def locate(directory: Path) -> Theatre:
    """Find the theatre's single root configuration file.

    Args:
        directory: The ``--theatre`` directory, relative or absolute.

    Returns:
        The located theatre.

    Raises:
        LoadError: If the directory does not exist, no root file exists, or both exist.
    """
    resolved = directory.resolve()
    if not resolved.is_dir():
        raise LoadError(f"theatre directory does not exist: {resolved}")
    state_dir = resolved / STATE_DIR_NAME
    yml, yaml = (state_dir / name for name in ROOT_FILE_NAMES)
    present = [candidate for candidate in (yml, yaml) if candidate.is_file()]
    if not present:
        raise LoadError(f"no configuration file: {yml} (or {yaml.name})")
    if len(present) > 1:
        raise LoadError(f"both {yml} and {yaml} exist; remove one")
    return Theatre(directory=resolved, state_dir=state_dir, config_file=present[0])
