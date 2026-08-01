from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def materialize_repo(path_or_url: str) -> tuple[str, str | None]:
    if path_or_url.startswith(("http://", "https://", "git@")):
        target = Path(tempfile.mkdtemp(prefix="multiagent_repo_")) / "repo"
        subprocess.run(["git", "clone", "--depth", "1", path_or_url, str(target)], check=True, timeout=300)
        return str(target), str(target.parent)
    return str(Path(path_or_url).resolve()), None
