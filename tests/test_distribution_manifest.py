"""Catch README links that an explicit source-distribution allowlist omits."""
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def test_readme_local_references_are_distributed():
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    includes = config['tool']['hatch']['build']['targets']['sdist']['include']
    for target in re.findall(r'\]\(([^)]+)\)', (ROOT / 'README.md').read_text()):
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path:
            continue
        path = unquote(url.path)
        assert (ROOT / path).is_file(), path
        assert any(path == item or path.startswith(item.rstrip('/') + '/') for item in includes), path
