"""Linux memory accounting and conservative, repeat-aware result summaries."""
from pathlib import Path
import statistics

MIB = 1024 * 1024


def counters(text):
    return {parts[0].rstrip(':'): int(parts[1]) for line in text.splitlines()
            if len(parts := line.split()) >= 2 and parts[1].isdigit()}


def process_memory(text):
    values = counters(text)
    if not {'Pss', 'Rss', 'Private_Clean', 'Private_Dirty', 'SwapPss'} <= values.keys():
        raise ValueError('Incomplete smaps_rollup; refusing an understated sample')
    return {'pss': values['Pss'] * 1024, 'rss': values['Rss'] * 1024,
            'uss': (values['Private_Clean'] + values['Private_Dirty'] + values.get('Private_Hugetlb', 0)) * 1024,
            'swapPss': values['SwapPss'] * 1024}


def pids(group):
    return sorted({int(pid) for file in [group / 'cgroup.procs', *group.glob('**/cgroup.procs')]
                   for pid in file.read_text().split()})


def sample(group):
    before = pids(group)
    if not before:
        raise RuntimeError('Application cgroup has no live processes')
    total = dict(pss=0, rss=0, uss=0, swapPss=0)
    processes = []
    for pid in before:
        # Permission errors are fatal. Exits invalidate the entire sample, never become zero.
        memory = process_memory(Path(f'/proc/{pid}/smaps_rollup').read_text())
        name = Path(f'/proc/{pid}/comm').read_text().strip()
        processes.append(dict(pid=pid, name=name, **memory))
        for key in total:
            total[key] += memory[key]
    if before != pids(group):
        raise ProcessLookupError('Process membership changed during sample')
    stat = counters((group / 'memory.stat').read_text())
    return dict(**total, current=int((group / 'memory.current').read_text()),
                peak=int((group / 'memory.peak').read_text()),
                swap=int((group / 'memory.swap.current').read_text()),
                anon=stat['anon'], file=stat['file'], kernel=stat.get('kernel'),
                processCount=len(before), processes=processes)


def distribution(values):
    ordered = sorted(values)
    return dict(min=ordered[0], median=statistics.median(ordered), max=ordered[-1]) if ordered else None


def summarize(trials, repeats, budgets):
    summaries = []
    for editor in dict.fromkeys(t['editor'] for t in trials):
        rows = [t for t in trials if t['editor'] == editor]
        groups = []
        for budget in [None, *budgets]:
            runs = [r for r in rows if r['budgetMiB'] == budget]
            passed = [r for r in runs if r['status'] == 'passed']
            complete = len(runs) == repeats and len({r['repeat'] for r in runs}) == repeats
            metrics = {}
            for key in ['pss', 'uss', 'rss', 'current', 'anon', 'file', 'kernel', 'processCount']:
                medians = [statistics.median(s[key] for s in r['samples'] if s['phase'] == 'idle' and s[key] is not None) for r in passed]
                metrics[key] = distribution(medians)
            groups.append(dict(budgetMiB=budget, attempted=len(runs), passed=len(passed),
                               qualified=complete and len(passed) == repeats, metrics=metrics,
                               peak=distribution([r['final']['peak'] for r in passed]),
                               probeMs=distribution([p for r in passed for p in r['probeMs']])))
        qualified = [g['budgetMiB'] for g in groups if g['budgetMiB'] is not None and g['qualified']]
        minimum = min(qualified) if qualified and repeats >= 3 else None
        summaries.append(dict(editor=editor, groups=groups, lowestTestedBudgetMiB=minimum,
                              atLowerBoundary=minimum == min(budgets) if minimum else False))
    return summaries
