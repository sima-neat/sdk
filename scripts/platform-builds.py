"""Shared Modalix build identity; all channels compete for 21 image slots."""
import re

# Keep existing daily branch names readable, but allow only master pre-release and release builds.
BUILD = re.compile(r'3\.0\.0_(?:daily_[A-Za-z0-9_-]+|(?:pre-release|release)_master)_B([0-9]+)\Z')


def channel(build):
    if not BUILD.fullmatch(build):
        raise ValueError(f'Invalid platform build: {build}')
    if build.startswith('3.0.0_release_master_'):
        return 'release'
    return 'pre-release' if build.startswith('3.0.0_pre-release_master_') else 'daily'
