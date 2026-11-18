"""PIB build identity, embedded by the container publication workflow."""
from pathlib import Path


def build_version(version_file=Path('/etc/pib-version')):
    try:
        return version_file.read_text().strip() or 'unknown-nogit'
    except FileNotFoundError:
        return 'unknown-nogit'


__version__ = build_version()
