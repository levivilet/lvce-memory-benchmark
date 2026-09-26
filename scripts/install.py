"""Download only the exact, checksum-verified official builds in config/editors.lock.json."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import os
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def install_runtime(editor, target, destination):
    runtime = editor.get('runtime')
    if not runtime:
        return
    archive = target / runtime['archive']
    if not archive.exists():
        subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--output', str(archive), runtime['url']], check=True)
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != runtime['sha256']:
        raise ValueError(f'Runtime checksum mismatch: {archive}')
    runtime_dir = destination / runtime['directory']
    # Preserve application bytes, replace the complete runtime to avoid stale libraries.
    with tempfile.TemporaryDirectory(dir=target) as temporary:
        app = Path(temporary) / 'app'
        shutil.move(runtime_dir / 'resources/app', app)
        shutil.rmtree(runtime_dir)
        runtime_dir.mkdir(parents=True)
        with zipfile.ZipFile(archive) as source:
            source.extractall(runtime_dir)
        shutil.move(app, runtime_dir / 'resources/app')
    binary = destination / editor['binary']
    (runtime_dir / 'electron').rename(binary)
    binary.chmod(binary.stat().st_mode | 0o111)
    actual = subprocess.run([str(binary), '-p', 'process.versions.electron'],
                            env={**os.environ, 'ELECTRON_RUN_AS_NODE': '1'},
                            check=True, capture_output=True, text=True).stdout.strip()
    if f'Electron {actual}' != runtime['version']:
        raise ValueError(f'Unexpected runtime version: {actual}')
    print('Verified runtime', actual, digest, flush=True)


def install():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editors', default='lvce,vscode,zed,geany,eclipse,idea,atom,lapce,theia,basic-electron')
    parser.add_argument('--lockfile', type=Path, default=ROOT / 'config/editors.lock.json')
    args = parser.parse_args()
    editors = json.loads(args.lockfile.read_text())
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
        elif archive.suffix == '.zip':
            with zipfile.ZipFile(archive) as source:
                source.extractall(destination)
            binary = destination / editor['binary']
            binary.chmod(binary.stat().st_mode | 0o111)
        else:
            subprocess.run(['tar', '-xf', str(archive), '-C', str(destination)], check=True)
        print('Verified', editor['id'], digest, flush=True)
        install_runtime(editor, target, destination)


if __name__ == '__main__':
    install()
