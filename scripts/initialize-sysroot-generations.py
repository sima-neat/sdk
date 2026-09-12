#!/usr/bin/env python3
"""Initialize the daily image's generation layout before any builds can run."""
import os
import shutil
from pathlib import Path
import sys
import subprocess

active = Path(sys.argv[1])
if not active.is_symlink():
    generation = Path(str(active) + '.generations') / 'image'
    generation.parent.mkdir(exist_ok=True)
    shutil.move(str(active), str(generation))
    # The installer embeds its extraction path in package configuration files.
    for directory, dirs, files in os.walk(generation):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                target = os.readlink(path)
                if target.startswith(str(active) + '/'):
                    path.unlink()
                    path.symlink_to(str(generation) + target[len(str(active)):])
            elif path.suffix in ('.pc', '.cmake', '.la'):
                text = path.read_text()
                path.write_text(text.replace(str(active), str(generation)))
    subprocess.run(["chmod", "-R", "a+rX,a-w", str(generation)], check=True)
    active.symlink_to(generation)
