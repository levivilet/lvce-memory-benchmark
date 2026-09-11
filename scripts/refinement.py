"""Bounded midpoint search below the lowest repeat-qualified sweep budget."""


def next_budget(trials, repeats):
    budgets = sorted({t['budgetMiB'] for t in trials if t['budgetMiB'] is not None})
    passing = []
    for budget in budgets:
        runs = [t for t in trials if t['budgetMiB'] == budget]
        if (len(runs) == repeats and {t['repeat'] for t in runs} == set(range(1, repeats + 1))
                and all(t['status'] == 'passed' for t in runs)):
            passing.append(budget)
    if not passing:
        return None
    upper = min(passing)
    lower = max((b for b in budgets if b < upper), default=0)
    return (lower + upper) // 2 if upper - lower > 1 else None


def validate_trials(trials, editor, protocol):
    """Replay adaptive choices so truncated or invented results cannot be published."""
    repeats = protocol['repeats']
    sweep = {None, *protocol['budgets']}
    initial = [t for t in trials if t['budgetMiB'] in sweep]
    expected = {(editor, b, r) for b in sweep for r in range(1, repeats + 1)}
    actual = [(t['editor'], t['budgetMiB'], t['repeat']) for t in initial]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError(f'Incomplete or duplicate trials for {editor}')
    remaining = trials[len(initial):]
    if trials[:len(initial)] != initial:
        raise ValueError('Sweep must finish before refinement')
    completed = list(initial)
    for _ in range(protocol.get('refinement_iterations', 0)):
        budget = next_budget(completed, repeats)
        if budget is None:
            break
        batch, remaining = remaining[:repeats], remaining[repeats:]
        actual = [(t['editor'], t['budgetMiB'], t['repeat']) for t in batch]
        if actual != [(editor, budget, r) for r in range(1, repeats + 1)]:
            raise ValueError(f'Incomplete or unexpected refinement trials for {editor}')
        completed.extend(batch)
    if remaining:
        raise ValueError(f'Unexpected extra trials for {editor}')
