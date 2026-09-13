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
from refinement import next_budget

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
    if editor['id'] == 'basic-electron':
        return ['--no-sandbox', '--ozone-platform=x11', ROOT / editor['app']]
    if editor['id'] == 'theia':
        write_json(home / '.theia-ide/settings.json', {
            'workbench.startupEditor': 'none', 'files.autoSave': 'off',
            'updates.checkForUpdates': False, 'security.workspace.trust.enabled': False,
        })
        return ['--electronUserData', data, '--no-sandbox', '--ozone-platform=x11']
    if editor['id'] == 'zed':
        return ['--user-data-dir', data]
    if editor['id'] == 'geany':
        return ['--new-instance', '--no-session', '--config', data]
    if editor['id'] == 'atom':
        write_json(home / '.atom/config.json', {'*': {
            'core': {'telemetryConsent': 'no', 'automaticallyUpdate': False},
            'welcome': {'showOnStartup': False},
            'autosave': {'enabled': False},
        }})
        return ['--new-window', '--no-sandbox']
    if editor['id'] == 'lapce':
        config = home / '.config/lapce-stable/settings.toml'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[core]\nmodal = false\n[editor]\nautosave-interval = 0\nformat-on-save = false\n')
        return ['--new']
    if editor['id'] == 'eclipse':
        configuration = home / 'eclipse-configuration'
        shutil.copytree(Path(editor['command']).parent / 'configuration', configuration)
        preferences = home / 'workspace/.metadata/.plugins/org.eclipse.core.runtime/.settings'
        preferences.mkdir(parents=True)
        (preferences / 'org.eclipse.ui.prefs').write_text('eclipse.preferences.version=1\nshowIntro=false\n')
        (preferences / 'org.eclipse.ui.ide.prefs').write_text('eclipse.preferences.version=1\nSHOW_TIPS_AND_TRICKS=false\n')
        return ['-nosplash', '-skipIntro', '-data', home / 'workspace',
                '-configuration', configuration, '-vm', '/usr/lib/jvm/java-21-openjdk-amd64/bin/java',
                '--launcher.openFile']
    if editor['id'] == 'idea':
        config = home / 'idea-config'
        (config / 'options').mkdir(parents=True)
        (config / 'options/updates.xml').write_text(
            '<application><component name="UpdatesConfigurable">'
            '<option name="CHECK_NEEDED" value="false" /></component></application>')
        # Acknowledge the pinned Community Edition terms and privacy notice.
        # Java filesystem encoding of the "privacy_policy" preferences node.
        privacy_node = '_!(!!cg"p!(}!}@"j!(k!|w"w!\'8!b!"p!\':!e@=='
        preferences = home / '.java/.userPrefs/jetbrains' / privacy_node
        preferences.mkdir(parents=True)
        (preferences / 'prefs.xml').write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE map SYSTEM "http://java.sun.com/dtd/preferences.dtd">'
            '<map MAP_XML_VERSION="1.0"><entry key="accepted_version" value="2.5" />'
            '<entry key="euacommunity_accepted_version" value="1.0" /></map>')
        (home / 'idea.properties').write_text(
            f'idea.config.path={config}\nidea.system.path={home / "idea-system"}\n'
            f'idea.plugins.path={home / "idea-plugins"}\nidea.log.path={home / "idea-log"}\n'
            'idea.initially.ask.config=false\njb.consents.confirmation.enabled=false\n'
            'idea.trust.all.projects=true\n')
        return ['nosplash', 'dontReopenProjects', '-e']
    raise ValueError(f"Unsupported editor: {editor['id']}")


def window_for(group, title=None):
    candidates = set(pids(group))
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '.'], text=True, capture_output=True, timeout=5)
    for window in result.stdout.split():
        try:
            if int(run(['xdotool', 'getwindowpid', window])) in candidates:
                # Startup/splash windows can belong to the editor's PID too.
                if title and title not in run(['xdotool', 'getwindowname', window]):
                    continue
                geometry = run(['xdotool', 'getwindowgeometry', '--shell', window])
                if 'WIDTH=' in geometry and int(geometry.split('WIDTH=')[1].split()[0]) > 300:
                    return window
        except (ValueError, subprocess.SubprocessError):
            continue
    return None


def open_theia_file(group, file, timeout):
    """Open an external file without introducing a workspace/indexing workload."""
    started = time.monotonic()
    window = window_for(group)
    if not window:
        raise TimeoutError('No Theia window for file-open setup')
    run(['xdotool', 'windowactivate', '--sync', window])
    run(['xdotool', 'key', '--clearmodifiers', 'ctrl+o'])
    while not window_for(group, 'Open File'):
        if time.monotonic() - started >= timeout:
            raise TimeoutError('Theia file chooser did not appear')
        time.sleep(.05)
    # GTK's native chooser exposes a location entry with Ctrl+L.
    run(['xdotool', 'key', '--clearmodifiers', 'ctrl+l'])
    run(['xdotool', 'type', '--clearmodifiers', '--delay', '10', str(file)])
    run(['xdotool', 'key', '--clearmodifiers', 'alt+o'])
    while time.monotonic() - started < timeout:
        if window_for(group, file.name):
            return
        time.sleep(.05)
    raise TimeoutError('Theia did not open the fixture before the setup deadline')


def probe(group, file, marker, timeout, window_title=None):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        window = window_for(group, window_title)
        if window:
            try:
                run(['xdotool', 'windowsize', window, '1280', '720'])
                run(['xdotool', 'windowactivate', '--sync', window])
                break
            except subprocess.CalledProcessError:
                # A startup window can disappear between discovery and activation.
                # Retry only before typing; never retry a failed functional check.
                pass
        time.sleep(.05)
    else:
        raise TimeoutError('No activatable fixture window before probe deadline')
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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Saving can expose the bytes before the UI accepts navigation again.
        # Clear stale clipboard data, then verify selection before deleting anything.
        subprocess.run(['xclip', '-selection', 'clipboard', '-in'],
                       input='lvce-memory-selection-pending', text=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        run(['xdotool', 'key', '--clearmodifiers', 'ctrl+Home'])
        run(['xdotool', 'key', '--clearmodifiers', '--repeat', len(marker), '--repeat-delay', '1', 'shift+Right'])
        run(['xdotool', 'key', '--clearmodifiers', 'ctrl+c'])
        time.sleep(.05)
        try:
            selection = subprocess.run(['xclip', '-selection', 'clipboard', '-out'],
                                       text=True, check=True, capture_output=True, timeout=1).stdout
        except subprocess.SubprocessError:
            # Clipboard ownership may still be transferring to the application.
            selection = None
        if selection == marker and time.monotonic() < deadline:
            break
        time.sleep(.05)
    else:
        raise TimeoutError('Could not select exact probe marker before restore deadline')
    run(['xdotool', 'key', '--clearmodifiers', 'BackSpace', 'ctrl+s'])
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
        # IDEA creates transient startup windows; other editors may not title their file.
        window_title = file.name if editor['id'] in ('idea', 'theia') else None
        command = [editor['command'], *profile_config(editor, home)]
        # Theia's positional argument selects a workspace, not an external file.
        if editor['id'] != 'theia':
            command.append(file)
        if editor['id'] == 'eclipse':
            # The native launcher delivers --launcher.openFile through D-Bus.
            # Keep its private session bus inside the measured application cgroup.
            command = ['dbus-run-session', '--', *command]
        for path in [home, *home.rglob('*')]:
            os.chown(path, user.pw_uid, user.pw_gid)
        env = {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
               'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_CACHE_HOME': str(home / '.cache'),
               'DISPLAY': os.environ['DISPLAY'], 'XAUTHORITY': os.environ['XAUTHORITY'],
               'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'LIBGL_ALWAYS_SOFTWARE': '1', 'GALLIUM_DRIVER': 'llvmpipe',
               'ZED_ALLOW_EMULATED_GPU': '1', 'ELECTRON_OZONE_PLATFORM_HINT': 'x11'}
        if editor['id'] in ('eclipse', 'idea'):
            # Java derives user.home from passwd rather than HOME by default.
            env['JAVA_TOOL_OPTIONS'] = f'-Duser.home={home}'
        if editor['id'] == 'idea':
            env['IDEA_PROPERTIES'] = str(home / 'idea.properties')
        if editor['id'] == 'theia':
            env['THEIA_CONFIG_DIR'] = str(home / '.theia-ide')
            env['THEIA_NO_SPLASH'] = '1'
        if editor['id'] == 'atom':
            env['ATOM_HOME'] = str(home / '.atom')
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
                window = window_for(group, None if editor['id'] == 'theia' else window_title)
                if window:
                    break
                if not pids(group):
                    raise RuntimeError('Application exited before opening a window')
                time.sleep(.25)
            if not window:
                raise TimeoutError('No application-owned window before startup deadline')
            result['windowMs'] = (time.monotonic() - started) * 1000
            # Same fixed settling period for every application, then verify actual editing.
            time.sleep(args.settle_seconds)
            if editor['id'] == 'theia':
                open_theia_file(group, file, args.probe_timeout)
            marker = 'ready-' + uuid.uuid4().hex
            result['probeMs'].append(probe(group, file, marker, args.probe_timeout, window_title))
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
                result['probeMs'].append(probe(group, file, marker, args.probe_timeout, window_title))
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
    parser.add_argument('--editors', default='lvce,vscode,zed,geany,eclipse,idea,atom,lapce,theia,basic-electron')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--refinement-iterations', type=int, default=10,
                        help='Midpoint budgets per editor after the sweep (0 disables; stops at 1 MiB precision)')
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
    if not 0 <= args.refinement_iterations <= 10:
        parser.error('Refinement iterations must be between 0 and 10')
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
    for editor in editors:
        if editor['id'] == 'eclipse':
            editor['runtime'] = run(['dpkg-query', '-W', '-f=${Version}', 'openjdk-21-jre-headless'])
        if editor['id'] == 'basic-electron':
            editor['sourceRevision'] = os.environ.get('BENCHMARK_COMMIT', 'local')
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
    for editor in editors:
        for _ in range(args.refinement_iterations):
            rows = [t for t in data['trials'] if t['editor'] == editor['id']]
            budget = next_budget(rows, args.repeats)
            if budget is None:
                break
            for repeat in range(1, args.repeats + 1):
                print(f"{editor['name']} / refinement {budget} MiB / repeat {repeat}", flush=True)
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
