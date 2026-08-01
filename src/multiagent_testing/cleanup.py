from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path


IGNORED_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "generated_tests"}
GENERATED_TEST_PATTERN = "*.generated.TC-*.test.*"


def cleanup_generated_test_files(repo_path: str) -> int:
    root = Path(repo_path).resolve()
    if not root.exists() or not root.is_dir():
        return 0

    deleted = 0
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [dirname for dirname in dirnames if dirname.lower() not in IGNORED_DIRS]
        for filename in filenames:
            if not fnmatch.fnmatch(filename, GENERATED_TEST_PATTERN):
                continue
            path = Path(current_root) / filename
            if not path.is_file() or _is_ignored(path, root):
                continue
            try:
                path.unlink()
            except OSError:
                continue
            deleted += 1
    return deleted


def cleanup_temp_dir(temp_dir: str | None) -> None:
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    return bool({part.lower() for part in rel_parts} & IGNORED_DIRS)
