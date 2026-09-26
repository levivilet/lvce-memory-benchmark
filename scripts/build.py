import json
from pathlib import Path
import shutil
import html
from metrics import summarize

ROOT = Path(__file__).resolve().parent.parent
source = ROOT / 'results/results.json'
data = json.loads(source.read_text())
assert data['schemaVersion'] == 1
assert data['trials'], 'Refusing to publish an empty benchmark'
data['summaries'] = summarize(data['trials'], data['protocol']['repeats'], data['protocol']['budgets'])
output = ROOT / '.tmp/pages'
shutil.copytree(ROOT / 'site', output, dirs_exist_ok=True)
(output / 'results.json').write_text(json.dumps(data) + '\n')
history_path = ROOT / 'results/history.json'
history = json.loads(history_path.read_text()) if history_path.exists() else dict(
    schemaVersion=1, metric='median PSS of three successful normal-memory trials', unit='bytes',
    attempted=0, succeeded=0, failed=0, versions={'lvce': [], 'vscode': []})
(output / 'history.json').write_text(json.dumps(history) + '\n')
template = (ROOT / 'site/history.html').read_text()
for editor, filename, name in [('lvce', 'lvce-history.html', 'LVCE Editor'),
                               ('vscode', 'vscode-history.html', 'VS Code')]:
    page = template.replace('{{EDITOR_ID}}', editor).replace('{{EDITOR_NAME}}', html.escape(name))
    (output / filename).write_text(page)
print(f'Built {output} from {len(data["trials"])} real trials')
