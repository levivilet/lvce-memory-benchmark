"""Discover, run and combine checksum-recorded historical editor benchmarks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

import update_lvce

ROOT = Path(__file__).resolve().parent.parent
VERSIONS_URL = 'https://update.code.visualstudio.com/api/releases/stable'
VS_CODE_DOWNLOAD = 'https://update.code.visualstudio.com/{version}/linux-x64/stable'
VS_CODE_VERSION = re.compile(r'^\d+\.\d+\.\d+$')


def fetch_json(url):
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'lvce-memory-benchmark',
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f'Could not read official release metadata from {url}: {error}') from error


def release_inventory(limit):
    if limit < 1 or limit > 100:
        raise ValueError('Historical inventory limit must be between 1 and 100')
    releases = []
    for page in range(1, 6):
        rows = fetch_json(f'{update_lvce.API_ROOT}/releases?per_page=100&page={page}')
        if not isinstance(rows, list):
            raise RuntimeError('LVCE release response is not a list')
        releases.extend(row for row in rows if isinstance(row, dict))
        if len(rows) < 100:
            break
    lvce = []
    seen = set()
    for release in sorted(releases, key=lambda row: row.get('published_at') or '', reverse=True):
        tag = release.get('tag_name')
        if (isinstance(tag, str) and update_lvce.TAG_PATTERN.fullmatch(tag)
                and not release.get('draft') and not release.get('prerelease') and tag not in seen):
            seen.add(tag)
            archive = f'lvce-{tag}_amd64.deb'
            archive_url = f'https://github.com/{update_lvce.REPOSITORY}/releases/download/{tag}/{archive}'
            lvce.append(dict(editor='lvce', version=tag, archiveUrl=archive_url))
    vscode_limit = min(limit, 60) if limit == 100 else limit
    versions = fetch_json(VERSIONS_URL)
    if not isinstance(versions, list):
        raise RuntimeError('VS Code stable release response is not a list')
    vscode = []
    seen.clear()
    for version in versions:
        if isinstance(version, str) and VS_CODE_VERSION.fullmatch(version) and version not in seen:
            seen.add(version)
            vscode.append(dict(editor='vscode', version=version,
                               archiveUrl=VS_CODE_DOWNLOAD.format(version=urllib.parse.quote(version, safe='.'))))
    if len(lvce) < limit or len(vscode) < vscode_limit:
        raise RuntimeError(f'Official sources returned too few versions: LVCE {len(lvce)}, VS Code {len(vscode)}, required {limit}/{vscode_limit}')
    return lvce[:limit] + vscode[:vscode_limit]


def download(url, destination):
    request = urllib.request.Request(url, headers={'User-Agent': 'lvce-memory-benchmark'})
    try:
        with urllib.request.urlopen(request, timeout=300) as response, destination.open('wb') as output:
            shutil.copyfileobj(response, output)
            return response.geturl()
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(f'Could not download official release {url}: {error}') from error


def checksum(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def resolve(editor, version, root, archive_url=None):
    if editor == 'lvce':
        tag = update_lvce.normalize_tag(version)
        archive = f'lvce-{tag}_amd64.deb'
        url = f'https://github.com/{update_lvce.REPOSITORY}/releases/download/{tag}/{archive}'
        if archive_url and archive_url != url:
            raise ValueError(f'LVCE inventory URL does not match the official release asset for {tag}')
        url = archive_url or url
        entry = dict(id='lvce', name='LVCE Editor', version=version, archive=archive,
                     url=url, binary=update_lvce.LVCE_BINARY,
                     runtimePolicy='Use the Electron runtime bundled with this release; do not replace it.')
    elif editor == 'vscode':
        if not VS_CODE_VERSION.fullmatch(version):
            raise ValueError(f'Invalid VS Code stable version {version!r}')
        archive = f'vscode-{version}-linux-x64.tar.gz'
        url = VS_CODE_DOWNLOAD.format(version=urllib.parse.quote(version, safe='.'))
        if archive_url and archive_url != url:
            raise ValueError(f'VS Code inventory URL does not match the official stable download for {version}')
        url = archive_url or url
        entry = dict(id='vscode', name='VS Code', version=version, archive=archive,
                     url=url, binary='VSCode-linux-x64/code',
                     runtimePolicy='Use the Electron runtime bundled with this release; do not replace it.')
    else:
        raise ValueError(f'Unknown editor {editor!r}')
    root.mkdir(parents=True, exist_ok=True)
    archive_root = ROOT / '.tmp/apps'
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_path = archive_root / archive
    download(url, archive_path)
    if editor == 'lvce':
        update_lvce.validate_archive(archive_path)
    else:
        with tarfile.open(archive_path, 'r:gz') as package:
            if not any(member.name == entry['binary'] for member in package.getmembers()):
                raise RuntimeError(f'VS Code archive does not contain {entry["binary"]}')
    entry['sha256'] = checksum(archive_path)
    lockfile = root / f'{editor}-{version}.json'
    lockfile.write_text(json.dumps([entry], indent=2) + '\n')
    return lockfile


def initialize(editor, version, root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'status.json').write_text(json.dumps(dict(editor=editor, version=version,
        status='attempted', startedAt=datetime.now(timezone.utc).isoformat()), indent=2) + '\n')


def finalize(editor, version, root, exit_code, prepare_outcome='unknown', install_outcome='unknown', benchmark_outcome='unknown'):
    status_path = root / 'status.json'
    try:
        status = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        status = dict(editor=editor, version=version, status='failed')
    status.update(prepareOutcome=prepare_outcome, installOutcome=install_outcome,
                  benchmarkOutcome=benchmark_outcome)
    result_path = root / 'results.json'
    error = None
    if exit_code != 0:
        status['status'] = 'failed'
        error = f'Benchmark command exited with status {exit_code}'
    elif not result_path.is_file():
        status['status'] = 'failed'
        error = 'Benchmark produced no result file'
    else:
        data = json.loads(result_path.read_text())
        normal = [trial for trial in data.get('trials', []) if trial.get('budgetMiB') is None]
        if len(normal) != 3 or any(trial.get('status') != 'passed' for trial in normal):
            status['status'] = 'failed'
            error = 'Historical release did not complete all three normal-memory trials'
        else:
            status['status'] = 'succeeded'
            metadata = data['editors'][0]
            try:
                lockfile = root / f'{editor}-{version}.json'
                entry = json.loads(lockfile.read_text())[0]
                binary = ROOT / '.tmp/apps' / editor / entry['binary']
                runtime = subprocess.run([str(binary), '-p', 'process.versions.electron'],
                    env={**os.environ, 'ELECTRON_RUN_AS_NODE': '1'}, check=True,
                    capture_output=True, text=True, timeout=30).stdout.strip()
                status.update(archiveUrl=metadata['url'], sha256=metadata['sha256'],
                              runtime=f'Electron {runtime} (bundled; not overridden)',
                              runtimePolicy=entry['runtimePolicy'], result='results.json')
            except (OSError, StopIteration, json.JSONDecodeError, subprocess.SubprocessError) as runtime_error:
                status['status'] = 'failed'
                error = f'Could not verify bundled runtime metadata: {runtime_error}'
    if error:
        status['error'] = error
    status['completedAt'] = datetime.now(timezone.utc).isoformat()
    status_path.write_text(json.dumps(status, indent=2) + '\n')
    print(f'{editor} {version}: {status["status"]}' + (f' ({error})' if error else ''))


def version_key(version):
    return tuple(int(part) for part in re.findall(r'\d+', version))


def combine(input_path, output_path, inventory_path=None):
    statuses = []
    results = []
    for path in sorted(input_path.rglob('status.json')):
        status = json.loads(path.read_text())
        statuses.append(status)
        if status.get('status') != 'succeeded':
            continue
        result_path = path.parent / 'results.json'
        if not result_path.is_file():
            status.update(status='failed', error='Successful status has no result artifact')
            continue
        result = json.loads(result_path.read_text())
        summary = next((item for item in result.get('summaries', []) if item.get('editor') == status['editor']), None)
        normal = next((group for group in summary.get('groups', []) if group.get('budgetMiB') is None), None) if summary else None
        metric = normal.get('metrics', {}).get('pss') if normal else None
        if not normal or not normal.get('qualified') or not metric or metric.get('median') is None:
            status.update(status='failed', error='Result has no qualified normal-memory PSS measurement')
            continue
        results.append(dict(editor=status['editor'], version=status['version'],
                            medianPssBytes=metric['median'], minPssBytes=metric['min'],
                            maxPssBytes=metric['max'], runtime=status.get('runtime'),
                            runtimePolicy=status.get('runtimePolicy'),
                            archiveUrl=status.get('archiveUrl'), sha256=status.get('sha256')))
    if inventory_path and inventory_path.is_file():
        inventory = json.loads(inventory_path.read_text())
        observed = {(status.get('editor'), status.get('version')) for status in statuses}
        for item in inventory.get('include', []):
            identity = (item.get('editor'), item.get('version'))
            if identity not in observed:
                statuses.append(dict(editor=identity[0], version=identity[1], status='failed',
                                     error='No per-version result artifact was produced'))
    entries = {editor: sorted((row for row in results if row['editor'] == editor), key=lambda row: version_key(row['version']))
               for editor in ('lvce', 'vscode')}
    data = dict(schemaVersion=1, metric='median PSS of three successful normal-memory trials',
                unit='bytes', attempted=len(statuses), succeeded=sum(row['status'] == 'succeeded' for row in statuses),
                failed=sum(row['status'] != 'succeeded' for row in statuses), versions=entries,
                failures=[{key: row[key] for key in ('editor', 'version', 'error', 'prepareOutcome',
                    'installOutcome', 'benchmarkOutcome') if row.get(key) is not None}
                    for row in statuses if row['status'] != 'succeeded'])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + '\n')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    inventory = subparsers.add_parser('inventory')
    inventory.add_argument('--limit', type=int, default=100)
    inventory.add_argument('--output', type=Path)
    prepare = subparsers.add_parser('prepare')
    prepare.add_argument('--editor', required=True, choices=['lvce', 'vscode'])
    prepare.add_argument('--version', required=True)
    prepare.add_argument('--url')
    prepare.add_argument('--root', type=Path, default=ROOT / '.tmp/historical')
    initialize_parser = subparsers.add_parser('initialize')
    initialize_parser.add_argument('--editor', required=True, choices=['lvce', 'vscode'])
    initialize_parser.add_argument('--version', required=True)
    initialize_parser.add_argument('--root', type=Path, default=ROOT / '.tmp/historical')
    finish = subparsers.add_parser('finalize')
    finish.add_argument('--editor', required=True, choices=['lvce', 'vscode'])
    finish.add_argument('--version', required=True)
    finish.add_argument('--root', type=Path, default=ROOT / '.tmp/historical')
    finish.add_argument('--exit-code', type=int, default=0)
    finish.add_argument('--prepare-outcome', default='unknown')
    finish.add_argument('--install-outcome', default='unknown')
    finish.add_argument('--benchmark-outcome', default='unknown')
    combine_parser = subparsers.add_parser('combine')
    combine_parser.add_argument('--input', type=Path, default=ROOT / 'results/history-artifacts')
    combine_parser.add_argument('--output', type=Path, default=ROOT / 'results/history.json')
    combine_parser.add_argument('--inventory', type=Path)
    args = parser.parse_args()
    if args.command == 'inventory':
        data = release_inventory(args.limit)
        rendered = json.dumps({'include': data}, separators=(',', ':'))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + '\n')
        print(rendered)
    elif args.command == 'prepare':
        print(resolve(args.editor, args.version, args.root, args.url))
    elif args.command == 'initialize':
        initialize(args.editor, args.version, args.root)
    elif args.command == 'finalize':
        finalize(args.editor, args.version, args.root, args.exit_code,
                 args.prepare_outcome, args.install_outcome, args.benchmark_outcome)
    else:
        data = combine(args.input, args.output, args.inventory)
        print(f'Historical versions: {data["succeeded"]}/{data["attempted"]} succeeded; {data["failed"]} omitted')


if __name__ == '__main__':
    main()
