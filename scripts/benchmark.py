"""Benchmark packaged desktop editors in isolated systemd cgroup-v2 services.

Run the observer with sudo on a dedicated X11 display. Applications always run
as the invoking non-root user. No global memory pressure or cache dropping.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import random
import shutil
import subprocess
import tempfile
import time
import uuid

from metrics import counters, pids, sample, summarize

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = 'Memory benchmark fixture.\n' * 100


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, **kwargs).stdout.strip()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def profile_config(editor, home):
    data = home / 'profile'
    settings = {'telemetry.telemetryLevel': 'off', 'update.mode': 'none',
                'workbench.startupEditor': 'none', 'security.workspace.trust.enabled': False,
                'extensions.autoUpdate': False, 'extensions.autoCheckUpdates': False,
                'files.autoSave': 'off', 'onboarding.enabled': False, 'chat.disableAIFeatures': True}
    write_json(data / 'User/settings.json', settings)
    zed = {'telemetry': {'diagnostics': False, 'metrics': False}, 'auto_update': False,
           'disable_ai': True, 'autosave': 'off', 'session': {'trust_all_worktrees': True}}
    write_json(data / 'config/settings.json', zed)
    write_json(home / '.config/zed/settings.json', zed)
    if editor['id'] == 'vscode':
        return ['--user-data-dir', data, '--extensions-dir', home / 'extensions', '--disable-extensions', '--skip-welcome', '--skip-release-notes', '--new-window', '--no-sandbox', '--ozone-platform=x11']
    if editor['id'] == 'lvce':
        return ['--user-data-dir', data, '--no-sandbox', '--ozone-platform=x11']
    if editor['id'] == 'zed':
        return ['--user-data-dir', data]
    return ['--new-instance', '--no-session', '--config', data]


def window_for(group):
    candidates = set(pids(group))
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '.'], text=True, capture_output=True, timeout=5)
    for window in result.stdout.split():
        try:
            if int(run(['xdotool', 'getwindowpid', window])) in candidates:
                geometry = run(['xdotool', 'getwindowgeometry', '--shell', window])
                if 'WIDTH=' in geometry and int(geometry.split('WIDTH=')[1].split()[0]) > 300:
                    return window
        except (ValueError, subprocess.SubprocessError):
            continue
    return None


def probe(window, file, marker, timeout):
    started = time.monotonic()
    run(['xdotool', 'windowactivate', '--sync', window])
    run(['xdotool', 'mousemove', '--window', window, '600', '250', 'click', '1'])
    run(['xdotool', 'key', '--clearmodifiers', 'Escape', 'ctrl+Home'])
    time.sleep(.15)
    run(['xdotool', 'type', '--clearmodifiers', '--delay', '10', marker])
    run(['xdotool', 'key', '--clearmodifiers', 'ctrl+s'])
    while time.monotonic() - started < timeout:
        if file.read_text() == marker + FIXTURE:
            return (time.monotonic() - started) * 1000
        time.sleep(.05)
    raise TimeoutError('Edit/save did not produce the exact expected file within the deadline')


def restore(file, marker, timeout):
    run(['xdotool', 'key', '--clearmodifiers', 'ctrl+Home'])
    run(['xdotool', 'key', '--clearmodifiers', '--repeat', len(marker), '--repeat-delay', '1', 'shift+Right'])
    run(['xdotool', 'key', '--clearmodifiers', 'BackSpace', 'ctrl+s'])
    deadline = time.monotonic() + timeout
    while file.read_text() != FIXTURE and time.monotonic() < deadline:
        time.sleep(.05)
    if file.read_text() != FIXTURE:
        raise RuntimeError('Could not restore exact fixture after probe')


def observe(group, result):
    for attempt in range(5):
        try:
            return sample(group)
        except (FileNotFoundError, ProcessLookupError):
            result['invalidSamples'] += 1
            if attempt == 4:
                raise
            time.sleep(.05)


def trial(editor, budget, repeat, args, user):
    identity = f"{editor['id']}-{budget or 'normal'}-{repeat}"
    unit = f'lvce-memory-{uuid.uuid4().hex}.service'
    result = dict(editor=editor['id'], budgetMiB=budget, repeat=repeat, status='failed',
                  samples=[], probeMs=[], invalidSamples=0, error=None)
    artifact = args.output.parent / identity
    artifact.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lvce-memory-') as temporary:
        home = Path(temporary)
        file = home / 'memory-benchmark.txt'
        file.write_text(FIXTURE)
        command = [editor['command'], *profile_config(editor, home), file]
        for path in [home, *home.rglob('*')]:
            os.chown(path, user.pw_uid, user.pw_gid)
        env = {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
               'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_CACHE_HOME': str(home / '.cache'),
               'DISPLAY': os.environ['DISPLAY'], 'XAUTHORITY': os.environ['XAUTHORITY'],
               'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'LIBGL_ALWAYS_SOFTWARE': '1', 'GALLIUM_DRIVER': 'llvmpipe',
               'ZED_ALLOW_EMULATED_GPU': '1', 'ELECTRON_OZONE_PLATFORM_HINT': 'x11'}
        launch = ['systemd-run', '--quiet', '--unit', unit, '--service-type=exec',
                  '-p', f'User={user.pw_name}', '-p', 'ExitType=cgroup', '-p', 'RemainAfterExit=yes',
                  '-p', 'MemoryAccounting=yes', '-p', 'MemorySwapMax=0', '-p', 'OOMPolicy=stop',
                  '-p', 'TimeoutStopSec=5', '-p', f'RuntimeMaxSec={args.startup_timeout + args.settle_seconds + args.sample_seconds + 2 * (args.probes + 1) * args.probe_timeout + 30}',
                  '-p', f'MemoryMax={budget * 1024 * 1024 if budget else "infinity"}',
                  '-p', f'WorkingDirectory={home}']
        for key, value in env.items():
            launch.append(f'--setenv={key}={value}')
        group = None
        started = time.monotonic()
        try:
            run([*launch, '--', *command])
            relative = run(['systemctl', 'show', unit, '-p', 'ControlGroup', '--value'])
            if not relative.startswith('/') or relative == '/':
                raise RuntimeError('Missing application cgroup')
            group = Path('/sys/fs/cgroup') / relative.lstrip('/')
            if (group / 'memory.swap.max').read_text().strip() != '0':
                raise RuntimeError('Swap limit was not applied')
            expected = str(budget * 1024 * 1024) if budget else 'max'
            if (group / 'memory.max').read_text().strip() != expected:
                raise RuntimeError('Memory budget was not applied')
            window = None
            while time.monotonic() - started < args.startup_timeout:
                window = window_for(group)
                if window:
                    break
                if not pids(group):
                    raise RuntimeError('Application exited before opening a window')
                time.sleep(.25)
            if not window:
                raise TimeoutError('No application-owned window before startup deadline')
            result['windowMs'] = (time.monotonic() - started) * 1000
            run(['xdotool', 'windowsize', window, '1280', '720'])
            # Same fixed settling period for every application, then verify actual editing.
            time.sleep(args.settle_seconds)
            marker = 'ready-' + uuid.uuid4().hex
            result['probeMs'].append(probe(window, file, marker, args.probe_timeout))
            result['readyMs'] = (time.monotonic() - started) * 1000
            restore(file, marker, args.probe_timeout)
            end = time.monotonic() + args.sample_seconds
            while time.monotonic() < end:
                try:
                    result['samples'].append(dict(phase='idle', seconds=time.monotonic() - started, **observe(group, result)))
                except (FileNotFoundError, ProcessLookupError):
                    pass
                time.sleep(1)
            if len(result['samples']) < max(2, args.sample_seconds // 2) or result['invalidSamples'] > len(result['samples']):
                raise RuntimeError('Insufficient complete memory samples')
            for index in range(args.probes):
                marker = f'probe-{index}-' + uuid.uuid4().hex
                result['probeMs'].append(probe(window, file, marker, args.probe_timeout))
                result['samples'].append(dict(phase='editing', seconds=time.monotonic() - started, **observe(group, result)))
                restore(file, marker, args.probe_timeout)
            result['events'] = counters((group / 'memory.events').read_text())
            result['final'] = observe(group, result)
            result['pressure'] = (group / 'memory.pressure').read_text()
            if result['events'].get('oom', 0) or result['events'].get('oom_kill', 0):
                raise RuntimeError('OOM event invalidates trial even if the UI survived')
            if any(s['swap'] or s['swapPss'] for s in result['samples']):
                raise RuntimeError('Swap used despite the no-swap protocol')
            result['status'] = 'passed'
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            result['error'] = str(error)
            (artifact / 'saved-file.txt').write_text(file.read_text())
            if isinstance(error, subprocess.CalledProcessError):
                result['error'] += '\n' + error.stderr
        finally:
            result['durationSeconds'] = time.monotonic() - started
            try:
                if group and group.exists():
                    result['events'] = counters((group / 'memory.events').read_text())
                result['service'] = run(['systemctl', 'show', unit, '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'MemoryPeak'])
                log = run(['journalctl', '-u', unit, '--no-pager', '-n', '80', '-o', 'cat'])
                (artifact / 'application.log').write_text(log.replace(str(home), '<profile>'))
                subprocess.run(['import', '-window', 'root', str(artifact / 'screen.png')], check=True, capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError) as error:
                result['diagnosticError'] = str(error)
            finally:
                # Cleanup is mandatory even when screenshot/log collection fails.
                # A failed stop aborts the benchmark to avoid overlapping applications.
                run(['systemctl', 'stop', unit])
                subprocess.run(['systemctl', 'reset-failed', unit], capture_output=True, timeout=15)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editors', default='lvce,vscode,zed,geany')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--budgets', default='64,128,192,256,320,384,512,768,1024')
    parser.add_argument('--settle-seconds', type=int, default=10)
    parser.add_argument('--sample-seconds', type=int, default=10)
    parser.add_argument('--probes', type=int, default=3)
    parser.add_argument('--startup-timeout', type=int, default=25)
    parser.add_argument('--probe-timeout', type=int, default=5)
    parser.add_argument('--seed', type=int, default=1729)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/results.json')
    args = parser.parse_args()
    budgets = sorted(set(int(n) for n in args.budgets.split(',') if n))
    if any(n <= 0 for n in [args.repeats, args.settle_seconds, args.sample_seconds, args.probes, args.startup_timeout, args.probe_timeout, *budgets]) or args.sample_seconds < 2:
        parser.error('Counts, durations and budgets must be positive; sampling requires at least 2 seconds')
    if os.geteuid() != 0 or not os.environ.get('SUDO_USER') or os.environ['SUDO_USER'] == 'root':
        parser.error('Use sudo from a non-root account; only the observer runs as root')
    for key in ['DISPLAY', 'XAUTHORITY']:
        if not os.environ.get(key):
            parser.error(f'Missing {key}; use scripts/run.sh on a dedicated Xvfb display')
    user = pwd.getpwnam(os.environ['SUDO_USER'])
    editors = json.loads((ROOT / 'editors.lock.json').read_text())
    for editor in editors:
        editor['command'] = str(ROOT / '.tmp/apps' / editor['id'] / editor['binary'])
    if shutil.which('geany'):
        editors.append(dict(id='geany', name='Geany', version=run(['dpkg-query', '-W', '-f=${Version}', 'geany']),
                            command=shutil.which('geany'), source='Ubuntu distribution package'))
    ids = args.editors.split(',')
    if len(set(ids)) != len(ids) or set(ids) - {e['id'] for e in editors}:
        parser.error('Unknown, duplicate, or uninstalled editor')
    editors = [e for e in editors if e['id'] in ids]
    for editor in editors:
        if not Path(editor['command']).is_file():
            parser.error(f"Missing {editor['command']}; run scripts/install.py first")
    protocol = {key: value for key, value in vars(args).items() if key != 'output'}
    protocol['budgets'] = budgets
    data = dict(schemaVersion=1, capturedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                commit=os.environ.get('BENCHMARK_COMMIT', 'local'), runUrl=os.environ.get('BENCHMARK_RUN_URL'),
                protocol=protocol, editors=editors, fixtureSha256=hashlib.sha256(FIXTURE.encode()).hexdigest(),
                host=dict(kernel=platform.release(), arch=platform.machine(),
                          os=Path('/etc/os-release').read_text(), cpu=next(line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
                          logicalCpus=os.cpu_count(), memory=counters(Path('/proc/meminfo').read_text()),
                          graphics=run(['glxinfo', '-B']), display='Xvfb 1280x720x24, software rendering',
                          cachePolicy='OS cache retained, not reset; fresh application profile; no drop_caches'), trials=[])
    # Randomize once, retain exact execution order, run only one editor at a time.
    jobs = [(editor, budget, repeat) for editor in editors for budget in [None, *budgets] for repeat in range(1, args.repeats + 1)]
    random.Random(args.seed).shuffle(jobs)
    for editor, budget, repeat in jobs:
        print(f"{editor['name']} / {budget or 'normal'} MiB / repeat {repeat}", flush=True)
        outcome = trial(editor, budget, repeat, args, user)
        data['trials'].append(outcome)
        data['summaries'] = summarize(data['trials'], args.repeats, budgets)
        write_json(args.output, data)
        print(outcome['status'], outcome['error'] or '', flush=True)
    # Low-budget failures are expected observations. A broken baseline is a CI failure.
    if any(t['status'] != 'passed' for t in data['trials'] if t['budgetMiB'] is None):
        raise SystemExit('At least one normal-memory baseline failed; inspect artifacts before publishing claims')


if __name__ == '__main__':
    main()
