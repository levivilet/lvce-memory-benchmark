"""Combine complete per-editor runs without pooling repeats across runners."""
import argparse
import json
from pathlib import Path

from metrics import summarize

ROOT = Path(__file__).resolve().parent.parent


def combine(results, expected_editors):
    if not results:
        raise ValueError('No editor results found')
    first = results[0]
    protocol = {k: v for k, v in first['protocol'].items() if k != 'editors'}
    shared = ['schemaVersion', 'commit', 'runUrl', 'fixtureSha256']
    if first['schemaVersion'] != 1:
        raise ValueError('Unsupported results schema')
    by_editor = {}
    for data in results:
        if any(data[key] != first[key] for key in shared):
            raise ValueError('Results must share schema, commit, workflow run and fixture')
        if {k: v for k, v in data['protocol'].items() if k != 'editors'} != protocol:
            raise ValueError('Editor protocols differ')
        if len(data['editors']) != 1:
            raise ValueError('Each artifact must contain exactly one editor')
        editor = data['editors'][0]['id']
        if editor in by_editor or editor not in expected_editors:
            raise ValueError(f'Duplicate or unexpected editor: {editor}')
        if data['protocol']['editors'] != editor:
            raise ValueError('Editor selection does not match artifact')
        expected = {(editor, budget, repeat)
                    for budget in [None, *protocol['budgets']]
                    for repeat in range(1, protocol['repeats'] + 1)}
        actual = [(t['editor'], t['budgetMiB'], t['repeat']) for t in data['trials']]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError(f'Incomplete or duplicate trials for {editor}')
        by_editor[editor] = data
    if set(by_editor) != set(expected_editors):
        raise ValueError(f'Missing editor results: {sorted(set(expected_editors) - set(by_editor))}')
    trials = [t for editor in expected_editors for t in by_editor[editor]['trials']]
    return dict(
        **{key: first[key] for key in shared},
        capturedAt=min(data['capturedAt'] for data in results),
        capturedAtByEditor={editor: by_editor[editor]['capturedAt'] for editor in expected_editors},
        hosts={editor: by_editor[editor]['host'] for editor in expected_editors},
        protocol=dict(protocol, editors=','.join(expected_editors)),
        editors=[by_editor[editor]['editors'][0] for editor in expected_editors],
        trials=trials,
        summaries=summarize(trials, protocol['repeats'], protocol['budgets']),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'results/editors')
    parser.add_argument('--output', type=Path, default=ROOT / 'results/results.json')
    parser.add_argument('--editors', default='lvce,vscode,zed,geany')
    args = parser.parse_args()
    results = [json.loads(path.read_text()) for path in sorted(args.input.glob('*/results.json'))]
    data = combine(results, args.editors.split(','))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + '\n')
    print(f'Combined {len(results)} editors and {len(data["trials"])} trials into {args.output}')


if __name__ == '__main__':
    main()
