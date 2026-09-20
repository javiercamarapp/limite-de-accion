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


def test_web_entrypoint_assets_and_acceptance_tool_are_declared():
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    assert config['project']['scripts']['limite-app'] == 'laboratorio.web_app:main'
    assets = ROOT / 'src/laboratorio/web_assets'
    assert {p.name for p in assets.iterdir() if p.is_file()} == {'index.html', 'app.js', 'style.css', 'icon.svg'}
    includes = config['tool']['hatch']['build']['targets']['sdist']['include']
    assert 'tools/test_web_browser.py' in includes
    assert 'docs/web-app' in includes
    assert (ROOT / 'docs/web-app/GUIA.md').is_file()
