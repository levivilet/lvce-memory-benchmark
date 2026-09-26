const $ = (id) => document.getElementById(id)
const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
const mib = (bytes) => bytes / 1048576
const fmt = (value) => Number(value).toLocaleString('en', {maximumFractionDigits: 1})
const svg = (title, width, height, body) => `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(title)}"><title>${escape(title)}</title>${body}</svg>`
async function main() {
  const editor = document.body.dataset.editor
  const response = await fetch('history.json')
  if (!response.ok) throw new Error(`History request failed (${response.status})`)
  const data = await response.json()
  if (data.schemaVersion !== 1 || !['lvce', 'vscode'].includes(editor)) throw new Error('No compatible historical data found')
  const rows = data.versions?.[editor] || []
  $('history-meta').textContent = `${rows.length} successful releases · ${data.attempted} attempted · ${data.failed} omitted · three normal-memory runs per release · bundled runtime`
  const failedVersions = (data.failures || []).map(row => `${row.editor} ${row.version}${row.error ? `: ${row.error}` : ''}`).join('; ')
  $('history-diagnostics').textContent = `${data.succeeded} releases produced qualifying measurements. ${data.failed} release attempts were omitted after benchmark, download, or setup failures.${failedVersions ? ` Omitted versions: ${failedVersions}.` : ''}`
  $('history-status').textContent = rows.length ? '' : 'No successful historical measurements are available yet. Attempted versions and failures are recorded in the downloaded data.'
  const points = rows.map((row, index) => ({...row, index, value: mib(row.medianPssBytes)}))
  if (points.length) {
    const width = Math.max(760, points.length * 24), height = 420, left = 64, right = 22, top = 22, bottom = 82
    const min = Math.min(...points.map(row => row.value)), max = Math.max(...points.map(row => row.value))
    const span = Math.max(max - min, max * .1, 1), lo = Math.max(0, min - span * .12), hi = max + span * .12
    const x = (index) => left + index * (width - left - right) / Math.max(points.length - 1, 1)
    const y = (value) => top + (hi - value) / (hi - lo) * (height - top - bottom)
    let body = Array.from({length:5}, (_, i) => {const value=lo+(hi-lo)*i/4;return `<path d="M${left} ${y(value)}H${width-right}" stroke="#eceef3"/><text class="axis" x="${left-8}" y="${y(value)+4}" text-anchor="end">${fmt(value)} MiB</text>`}).join('')
    body += `<polyline fill="none" stroke="#823cc6" stroke-width="3" points="${points.map(row=>`${x(row.index)},${y(row.value)}`).join(' ')}"/>`
    body += points.map(row => {const title=`${row.version}: ${fmt(row.value)} MiB median PSS; range ${fmt(mib(row.minPssBytes))}–${fmt(mib(row.maxPssBytes))} MiB; runtime ${row.runtime || 'bundled'}`;return `<circle cx="${x(row.index)}" cy="${y(row.value)}" r="5" fill="#823cc6" tabindex="0" aria-label="${escape(title)}"><title>${escape(title)}</title></circle>`}).join('')
    for (const index of [...new Set([0, Math.floor((points.length-1)/2), points.length-1])]) body += `<text class="axis" x="${x(index)}" y="${height-56}" text-anchor="middle">${escape(points[index].version)}</text>`
    body += `<text x="${left}" y="${height-16}" class="axis">Older release</text><text x="${width-right}" y="${height-16}" class="axis" text-anchor="end">Newer release</text>`
    $('history-chart').innerHTML = svg('Historical median PSS memory by release version, MiB', width, height, body)
  } else $('history-chart').innerHTML = '<p class="empty">No successful release measurements to chart.</p>'
  $('history-table').innerHTML = [...rows].reverse().map(row => `<tr><td>${escape(row.version)}<small>${escape(row.archiveUrl || '')}</small></td><td>${fmt(mib(row.medianPssBytes))} MiB</td><td>${fmt(mib(row.minPssBytes))}–${fmt(mib(row.maxPssBytes))} MiB</td><td>${escape(row.runtime || 'Bundled release runtime')}<small>SHA-256 ${escape(row.sha256 || 'unavailable')}</small></td></tr>`).join('')
}
main().catch(error => {$('history-status').textContent=`Could not load historical measurements: ${error.message}`;console.error(error)})
