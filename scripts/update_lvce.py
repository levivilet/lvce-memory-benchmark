"""Update the checksum-pinned LVCE Editor entry from an official release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = 'lvce-editor/lvce-editor'
API_ROOT = f'https://api.github.com/repos/{REPOSITORY}'
TAG_PATTERN = re.compile(r'^v\d+\.\d+\.\d+$')
LVCE_BINARY = 'usr/lib/lvce/lvce'


class UpdateError(RuntimeError):
    """Raised when release metadata or the downloaded archive is invalid."""


def normalize_tag(version):
    tag = version if version.startswith('v') else f'v{version}'
    if not TAG_PATTERN.fullmatch(tag):
        raise UpdateError(f'Expected a stable semantic version, got {version!r}')
    return tag


def fetch_json(url):
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'lvce-memory-benchmark',
    })
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise UpdateError(f'Could not read release metadata from {url}: {error}') from error


def release_metadata(version=None):
    if version is None:
        url = f'{API_ROOT}/releases/latest'
    else:
        tag = normalize_tag(version)
        url = f'{API_ROOT}/releases/tags/{urllib.parse.quote(tag, safe="")}'
    release = fetch_json(url)
    if not isinstance(release, dict):
        raise UpdateError(f'Release metadata from {url} is not an object')
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
        raise UpdateError(f'Release metadata has an invalid tag_name: {tag!r}')
    if release.get('draft') or release.get('prerelease'):
        raise UpdateError(f'Release {tag} is not a stable published release')
    if version is not None and tag != normalize_tag(version):
        raise UpdateError(f'Release metadata tag {tag} does not match requested version {version!r}')
    return release


def find_asset(release):
    tag = release['tag_name']
    expected_name = f'lvce-{tag}_amd64.deb'
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise UpdateError(f'Release {tag} has no asset list')
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get('name') == expected_name]
    if len(matches) != 1:
        raise UpdateError(f'Release {tag} must contain exactly one {expected_name} asset')
    asset = matches[0]
    url = asset.get('browser_download_url')
    expected_url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{expected_name}'
    if url != expected_url:
        raise UpdateError(f'Asset {expected_name} has an unexpected download URL')
    return expected_name, url


def download(url, destination):
    request = urllib.request.Request(url, headers={'User-Agent': 'lvce-memory-benchmark'})
    try:
        with urllib.request.urlopen(request) as response, destination.open('wb') as output:
            shutil.copyfileobj(response, output)
    except (urllib.error.URLError, OSError) as error:
        raise UpdateError(f'Could not download {url}: {error}') from error


def checksum(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def validate_archive(path):
    try:
        result = subprocess.run(
            ['dpkg-deb', '--contents', str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise UpdateError(f'LVCE archive is not a readable Debian package: {error}') from error
    paths = {line.rsplit(' ', 1)[-1].lstrip('./') for line in result.stdout.splitlines()}
    if LVCE_BINARY not in paths:
        raise UpdateError(f'LVCE archive does not contain {LVCE_BINARY}')


def load_lockfile(path):
    try:
        editors = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise UpdateError(f'Could not read lockfile {path}: {error}') from error
    if not isinstance(editors, list):
        raise UpdateError(f'Lockfile {path} must contain an editor list')
    matches = [editor for editor in editors if isinstance(editor, dict) and editor.get('id') == 'lvce']
    if len(matches) != 1:
        raise UpdateError('Lockfile must contain exactly one lvce editor entry')
    return editors


def update_lockfile(path, release, archive_name, archive_url, archive_sha256):
    editors = load_lockfile(path)
    updated = json.loads(json.dumps(editors))
    entry = next(editor for editor in updated if editor.get('id') == 'lvce')
    entry.update({
        'version': release['tag_name'],
        'archive': archive_name,
        'url': archive_url,
        'sha256': archive_sha256,
    })
    content = json.dumps(updated, indent=2) + '\n'
    if content == path.read_text():
        return False
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=f'.{path.name}.', delete=False) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise
    return True


def update(version=None, lockfile=None):
    path = Path(lockfile) if lockfile else ROOT / 'editors.lock.json'
    release = release_metadata(version)
    archive_name, archive_url = find_asset(release)
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / archive_name
        download(archive_url, archive)
        validate_archive(archive)
        digest = checksum(archive)
    changed = update_lockfile(path, release, archive_name, archive_url, digest)
    state = 'Updated' if changed else 'Already up to date'
    print(f'{state} LVCE Editor {release["tag_name"]} ({archive_name}, sha256:{digest})')
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', help='Stable LVCE version to update to (default: latest published release)')
    parser.add_argument('--lockfile', type=Path, default=ROOT / 'editors.lock.json', help='Lockfile to update')
    args = parser.parse_args()
    try:
        update(args.version, args.lockfile)
    except UpdateError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
