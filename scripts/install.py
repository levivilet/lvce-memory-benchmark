"""Download only the exact, checksum-verified official builds in editors.lock.json."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def install():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editors', default='lvce,vscode,zed,geany,eclipse,idea,atom,lapce')
    args = parser.parse_args()
    editors = json.loads((ROOT / 'editors.lock.json').read_text())
    ids = args.editors.split(',')
    if len(set(ids)) != len(ids) or set(ids) - {e['id'] for e in editors} - {'geany'}:
        parser.error('Unknown or duplicate editor')
    target = ROOT / '.tmp/apps'
    target.mkdir(parents=True, exist_ok=True)
    for editor in editors:
        if editor['id'] not in ids:
            continue
        archive = target / editor['archive']
        if not archive.exists():
            print('Downloading', editor['id'], editor['version'], flush=True)
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--output', str(archive), editor['url']], check=True)
        with archive.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest != editor['sha256']:
            raise ValueError(f"Checksum mismatch: {archive}; remove it and retry")
        destination = target / editor['id']
        destination.mkdir(exist_ok=True)
        if archive.suffix == '.deb':
            subprocess.run(['dpkg-deb', '-x', str(archive), str(destination)], check=True)
        else:
            subprocess.run(['tar', '-xf', str(archive), '-C', str(destination)], check=True)
        print('Verified', editor['id'], digest, flush=True)


if __name__ == '__main__':
    install()
