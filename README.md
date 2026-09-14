# LVCE Memory Benchmark

Reproducible **desktop application** memory comparisons for LVCE Editor, VS Code,
Zed, Geany, Eclipse SDK, IntelliJ IDEA Community Edition, Atom, Lapce, Eclipse Theia IDE, and a minimal **Basic Electron** text editor, with a [GitHub Pages dashboard](https://levivilet.github.io/lvce-memory-benchmark/).

The report shows normal PSS/USS/RSS, cgroup memory and peak, anonymous/file/kernel
breakdowns, an explicit pass/fail budget sweep, edit/save checks, and per-trial
memory timelines. Downloadable JSON contains every attempt, exact versions,
download URLs and hashes, host details, process samples, OOM counters and protocol.
Screenshots and application logs are in each Actions run's artifact.

Atom 1.60.0 is included as a historical comparison of an archived editor. The
JetBrains entry is **IntelliJ IDEA Community Edition 2025.2.6.3**, not a combined
measurement of all JetBrains products. Eclipse uses the **4.36 SDK** distribution.
Eclipse Theia IDE uses the official **1.75.0 Debian package**, including its bundled
plugins, with a fresh Theia configuration and Electron profile. Automatic update
checks and the startup welcome editor are disabled. It is a separate application
from Eclipse SDK. Its CLI accepts workspaces, so setup opens the external file
through the native file chooser and verifies the filename in the window title
before the common readiness probe. File-open setup has the same five-second
deadline as a probe; its process memory is included in the cgroup peak. [Pinned Theia release](https://download.eclipse.org/theia/ide/1.75.0/linux/latest-linux.yml).
Basic Electron uses the pinned **Electron 40.0.0** Linux x64 runtime and the
checked-in `basic-electron/` app. Its main process reads and writes the single
fixture through a narrow preload API; the renderer contains only a textarea,
Save button, status, and Ctrl+S handler. The benchmark records the source commit
alongside the runtime version. This is a deliberately small Electron baseline,
not a general-purpose editor.
These are single-file measurements, not comparisons of full IDE project workloads.
First-run welcome screens and optional data-sharing prompts are preconfigured;
IntelliJ's bundled Community Edition terms and privacy notice are acknowledged in the disposable profile with
optional data sharing disabled.

Official references: [Atom release](https://github.com/atom/atom/releases/tag/v1.60.0),
[Lapce release](https://github.com/lapce/lapce/releases/tag/v0.4.6),
[Eclipse SDK release](https://archive.eclipse.org/eclipse/downloads/drops4/R-4.36-202505281830/),
[IntelliJ LightEdit](https://www.jetbrains.com/help/idea/lightedit-mode.html).

## What “minimum” means here

**Lowest tested memory budget that successfully launches and edits/saves the same
file in every repeat (at least three), without swap or any OOM event.** This is a
workload-specific operating point, not a universal minimum or a claim about
large projects. All specified sweep budgets are tested. Then up to ten midpoint budgets per editor
refine the interval below its lowest passing budget, stopping at 1 MiB precision.
Each midpoint gets all repeats; one failure moves the lower search bound. If the
lowest sweep budget passes, search continues toward 1 MiB. If no capped budget
passes, no refinement is possible. Binary search guides sampling, but memory
behavior can be nonmonotonic: untested budgets are never inferred to pass or fail.
When the lowest tested value passes, the report says ≤ because lower limits remain
untested. Fewer than three repeats can only generate a smoke report.

The normal benchmark has no application memory cap, but also disables swap.
Comparisons report the median of each successful run's idle median and the range
of those run medians. Failed baseline runs fail CI and are labeled as partial in
the report. Failed constrained runs are expected observations, never zero-memory
results. No sample minimum is presented as the application's memory requirement.

A screenshot showing roughly 277 MB in one session and 900 MB in another is useful
motivation, but is **not benchmark data**. It does not by itself show whether the
change came from caches, heaps, process count, swapping, graphics, or the resource
monitor's accounting method. These results cannot diagnose that difference.

## Protocol

- Linux x86-64, systemd ≥250, cgroup v2 with memory controller, X11. CI pins Ubuntu
  24.04; runner hardware is recorded, not assumed identical across dates.
- Checksum-verified builds pinned in `editors.lock.json`. LVCE keeps its official
  v0.114.2 application resources but uses a pinned Electron 44.3.0 runtime override;
  Basic Electron uses the same 44.3.0 archive. This LVCE entry is not the unmodified
  official binary. Other editors retain their bundled runtimes. Geany comes
  from Ubuntu's package repository and its exact distribution version is recorded.
  To update an official build, update its version, immutable URL, hash and binary
  path together. Downloads never silently follow `latest` during a benchmark.
- One editor per CI runner, with its initial sweep trials shuffled once using recorded seed 1729.
  Adaptive refinement follows the sweep, in decision order.
  Editors run in parallel on separate runners; local runs use one editor at a time.
  A fresh HOME, profile and config per trial; no user-installed extensions. VS Code
  additionally uses `--disable-extensions`; built-in application components remain.
  Eclipse uses an empty workspace and Ubuntu OpenJDK 21 (the package version is recorded).
  Eclipse’s private D-Bus session runs inside its measured cgroup.
  IntelliJ IDEA CE uses LightEdit mode and its bundled JetBrains Runtime.
  Java user settings are isolated too; vendor JVM defaults remain unchanged.
  Telemetry/updaters are disabled where configured. AI features are disabled in VS Code and Zed.
- Each trial opens the same 2,600-byte, 100-line plain-text file. No project folder,
  language server, plugin workload or project indexing. The fixture hash is recorded.
- A dedicated Xvfb display and Openbox, 1280×720 window, Mesa software rendering for
  all applications. Physical GPU VRAM and desktop/compositor memory are excluded.
  Electron sandboxing is disabled in this CI protocol. This is **not** a claim
  about hardware-accelerated desktop performance.
- The application starts inside its own systemd service/cgroup as the invoking
  non-root user. The privileged observer, X server and window manager are outside
  that group. Child processes inherit membership, including reparented helpers.
  Separate profiles prevent forwarding to an existing editor instance.
- `memory.max` is set **before launch**, not lowered after allocating a larger
  startup heap. `memory.swap.max=0` for both normal and constrained runs. Every
  configured cap is verified by reading it back from the kernel. No global
  pressure generator, cache dropping, forced GC, heap cap, or `memory.reclaim`.
- Wait for a visible window owned by a cgroup process
  (25-second deadline), settle 10 seconds, then perform an exact edit/save readiness check.
  Reacquire, resize and activate the window before each check so a replaced
  startup window cannot leave a stale window ID. IntelliJ additionally requires the
  fixture name in the window title to exclude transient startup windows. Retry setup within
  the probe deadline, before injecting any input; failed edits are never retried. Capture
  complete `/proc/PID/smaps_rollup` samples once a second for 10 seconds. Perform
  three further edit/save checks, each with a five-second deadline including
  synthetic typing. Before restoring, copy the selection and require it to equal
  the exact marker before deleting. Retry selection only within the five-second
  restore deadline; the saved fixture must still match exactly. The clipboard helper
  runs outside the measured application cgroup; all editors use the same protocol.
- Permission errors invalidate trials. Process exits or membership changes discard
  the entire sample, never just the missing process. Retry a complete snapshot up
  to five times with 50 ms between attempts, including final/editing snapshots.
  Require at least half the
  requested idle samples (minimum two); reject trials with more discarded than
  complete samples. Any OOM, swap, failed save, or empty process group fails the
  trial. Memory sampling is sequential, not an atomic system-wide snapshot.
- Record kernel cgroup peak from creation (including startup), final OOM/reclaim
  counters and PSI, per-process memory/name/PID, and functional probe wall times.
  Idle timelines start after readiness; they are not startup-memory traces.
- Stop the whole isolated service in cleanup. Keep OS caches as they are; this is
  not a cold-cache test. Page-cache sharing/first-charge effects and background
  host load remain limitations even with randomized trial order.

Default sweep: **64, 128, 192, 256, 320, 384, 512, 768, 1024 MiB**, plus uncapped; three
fresh runs per condition, followed by up to ten refinement budgets per editor.
All editors use the same initial grid, search rule and timing thresholds.
Use `--refinement-iterations 0` to disable refinement (maximum/default: 10).
The probe checks functionality, not typing-to-paint latency; use the
[typing benchmark](https://levivilet.github.io/lvce-typing-benchmark/) for that.

## Memory definitions

| Metric | Meaning | Caveat |
| --- | --- | --- |
| PSS | Private pages plus proportional shares of shared resident pages, across all cgroup processes | Other processes sharing libraries affect attribution |
| USS | Private clean + dirty + private huge pages | Excludes shared costs |
| Summed RSS | Resident pages of each process summed | Shared pages can be counted repeatedly |
| Cgroup current / peak | Memory charged to application cgroup, including file cache and kernel allocations | Shared-page charges differ from PSS; not a minimum host RAM requirement |
| Budget | Enforced cgroup `memory.max`, swap disabled | Includes more than the process working set; startup must also fit |

All charts use **MiB = 1,048,576 bytes**. Virtual address reservations are not
resident RAM. A V8 heap statistic alone excludes the rest of Electron and is not
suitable for comparing Electron to native editors.

Sources: [Linux /proc](https://www.kernel.org/doc/html/latest/filesystems/proc.html),
[cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html),
[Electron process memory](https://www.electronjs.org/docs/latest/api/process#processgetprocessmemoryinfo),
[VS Code CLI](https://code.visualstudio.com/docs/configure/command-line),
[Zed CLI](https://zed.dev/docs/reference/cli).

## Run

Use a dedicated Ubuntu 24.04 machine. The benchmark uses sudo only to manage the
isolated service and read every process's memory; the editors run as your user.
It does not modify your editor profiles or use your desktop display.

```sh
sudo apt-get update
sudo apt-get install -y python3 curl xz-utils xvfb xauth xdotool xclip openbox \
  geany imagemagick mesa-utils mesa-vulkan-drivers libvulkan1 libasound2t64 \
  libgtk-3-0 libnss3 libgbm1 libxss1 libxtst6 openjdk-21-jre dbus
python3 scripts/install.py
bash scripts/run.sh
python3 scripts/build.py
python3 -m http.server 8080 --directory .tmp/pages
```

Focused smoke run:

```sh
bash scripts/run.sh --repeats 1 --budgets '' --settle-seconds 8 --sample-seconds 3 --probes 1
```

`python3 scripts/benchmark.py --help` lists all options, including editor selection,
budgets, durations, seed and output. Use the same protocol for comparisons.
Results are checkpointed atomically after each trial. Do not combine trials from
different hosts or configurations for the same editor to manufacture a passing
minimum. CI combines complete per-editor runs from the same workflow and protocol,
retaining each editor’s host metadata and capture time. Runner hardware can differ
between editors as well as between dates.

## Development & CI

Python's standard library handles measurement; the dashboard is static HTML/CSS/JS
with inline SVG charts and no third-party runtime/CDN dependency. Node and
Playwright are only used to test the report in a real browser.

```sh
nice npm ci
python3 -m unittest discover -s tests
npm run check
npx playwright install chromium
# After creating real results and building the report:
npm run test:browser
```

PRs run metric and interaction tests, three fresh trials per editor at normal memory
and 256/512 MiB plus up to two refinement budgets, report generation and browser checks. Each trial performs ten probes
after readiness to exercise repeated edit/save/restore interactions.
Pushes to main, weekly schedules and manual dispatch run the
full sweep, upload raw evidence, and deploy Pages after the baseline and browser
checks pass. Budget failures do not prevent publication. Baseline failures do.
Official release archives are cached separately per editor, runner OS/architecture,
and that editor's lock entry. Updating one editor leaves the other caches reusable.
Restored archives are still checksum-verified and freshly extracted on every run;
only verified archives are saved, before trials start. Profiles, extracted apps and
results are not cached. Geany continues to be installed through apt.

Each editor has its own parallel matrix job and uploads a separate results artifact,
including screenshots and logs even on failure. A follow-up job waits for all editor
jobs, downloads their artifacts, validates and combines the JSON, builds the charts,
and runs browser checks. Missing or incomplete editor results fail aggregation;
failed baseline trials remain available for diagnosis but block Pages deployment.
Actions runs for the same branch are serialized; editors never compete on the same benchmark runner.

To combine downloaded per-editor artifacts locally, keep each artifact in its own
subdirectory of `results/editors/`, then run `python3 scripts/combine.py` followed by
`python3 scripts/build.py`. The combiner requires all ten editors by default.

The LVCE project maintains this benchmark. It does not predetermine the winner.
