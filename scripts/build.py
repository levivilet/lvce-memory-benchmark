import json
from pathlib import Path
import shutil
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
print(f'Built {output} from {len(data["trials"])} real trials')
