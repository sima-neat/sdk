"""Shared Modalix build identity; release-master builds are pinned; other channels share 21 slots."""
import re

VERSION_PREFIX = '3.'
# Daily builds can come from any branch; pre-release and release builds must be from master.
BUILD = re.compile(
    rf'(?P<release>{re.escape(VERSION_PREFIX)}[0-9]+\.[0-9]+)_'
    r'(?:(?P<daily>daily)_[A-Za-z0-9_-]+|(?P<master>pre-release|release)_master)'
    r'_B(?P<number>[0-9]+)\Z'
)


def channel(build):
    match = BUILD.fullmatch(build)
    if not match:
        raise ValueError(f'Invalid platform build: {build}')
    return match['master'] or match['daily']
