const $ = (id) => document.getElementById(id)
const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
const mib = (value) => value / 1048576
const number = (value) => Number.isFinite(value) ? value.toLocaleString('en', {maximumFractionDigits: 1}) : '—'
const color = (id) => ({lvce:'#823cc6',vscode:'#3284c7',zed:'#4d837c',geany:'#c18c3b',eclipse:'#57469a',idea:'#d34a70',atom:'#438658',lapce:'#246c9c',theia:'#14858a','basic-electron':'#b85c2f'}[id] || '#778195')
const svg = (title, width, height, content) => `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(title)}"><title>${escape(title)}</title>${content}</svg>`
const fmt = (metric) => metric ? number(mib(metric.median)) : '—'
function bars(rows, title, unit = 'MiB') {
  if (!rows.length) return '<p class="empty">No qualifying measurements available.</p>'
  const width = 900, left = 180, plot = 595, height = rows.length * 54 + 36
  const max = Math.max(1, ...rows.map(r => r.max ?? r.value)) * 1.08
  const scale = (v) => left + v / max * plot
  let content = Array.from({length:5}, (_,i) => {const value=max*i/4;return `<path d="M${scale(value)} 0V${height-25}" stroke="#eceef3"/><text class="axis" x="${scale(value)}" y="${height-6}" text-anchor="middle">${number(value)}</text>`}).join('')
  rows.forEach((r, i) => {const y=i*54+10;content += `<text x="0" y="${y+20}">${escape(r.label)}</text><rect x="${left}" y="${y}" width="${r.value/max*plot}" height="30" rx="4" fill="${color(r.id)}"/><text x="${scale(r.value)+12}" y="${y+20}">${r.prefix || ''}${number(r.value)} ${unit}</text>`;if (r.min !== undefined) content+=`<path d="M${scale(r.min)} ${y+15}H${scale(r.max)} M${scale(r.min)} ${y+9}v12 M${scale(r.max)} ${y+9}v12" stroke="#292037" stroke-width="1.5"/>`})
  return svg(title, width, height, content)
}
async function main() {
  const response = await fetch('results.json')
  if (!response.ok) throw new Error(`Results request failed (${response.status})`)
  const data = await response.json()
  if (data.schemaVersion !== 1 || !data.trials?.length) throw new Error('No compatible measured trials found')
  const names = Object.fromEntries(data.editors.map(e => [e.id,e.name]))
  const normal = (s) => s.groups.find(g => g.budgetMiB === null)
  const limited = (s) => s.groups.find(g => g.budgetMiB === s.lowestTestedBudgetMiB && g.budgetMiB !== null)
  const failures = data.trials.filter(t => t.budgetMiB === null && t.status !== 'passed')
  $('status').textContent = failures.length ? `${failures.length} normal-memory trial(s) failed. Successful measurements below are partial; inspect the raw results and logs.` : data.protocol.repeats < 3 ? 'Smoke run: fewer than three repeats. No minimum-memory claim is made.' : ''
  const hostDescription = data.hosts ? `${Object.keys(data.hosts).length} separate editor runners · host details below` : `${data.host.arch} · ${data.host.logicalCpus} logical CPUs · ${number(data.host.memory.MemTotal / 1048576)} GiB host RAM`
  $('meta').textContent = `${data.capturedAt.slice(0,10)} · ${hostDescription} · ${data.protocol.repeats} repeats per condition · MiB throughout`
  const lvce = data.summaries.find(s=>s.editor==='lvce')
  const idle = lvce && normal(lvce)?.metrics.pss
  const low = lvce?.lowestTestedBudgetMiB
  $('highlights').innerHTML = [
    ['LVCE / NORMAL PSS', idle ? `${fmt(idle)} MiB` : 'Not measured', 'Median whole-application proportional memory.'],
    ['LVCE / LOWEST PASSING BUDGET', low ? `${lvce.atLowerBoundary?'≤ ':''}${low} MiB` : 'Not established', 'Launch + edit + save; every repeat must pass.'],
    ['MEASURED, NOT ESTIMATED', `${data.trials.length} trials`, `${data.editors.length} desktop editors · raw data, versions, and failed attempts included.`]
  ].map(([label,value,detail])=>`<div class="card"><div class="label">${escape(label)}</div><div class="value">${escape(value)}</div><div class="detail">${escape(detail)}</div></div>`).join('')
  function drawNormal() {
    const key=$('metric').value
    const rows=data.summaries.flatMap(s=>{const g=normal(s), m=g?.metrics[key];return m?[{id:s.editor,label:names[s.editor]+(g.qualified?'':' *'),value:mib(m.median),min:mib(m.min),max:mib(m.max)}]:[]}).sort((a,b)=>a.value-b.value)
    $('normal-chart').innerHTML=bars(rows,`Normal memory comparison: ${key}. MiB. Asterisk means incomplete or failed repeats.`)
  }
  $('metric').addEventListener('change',drawNormal);drawNormal()
  $('normal-table').innerHTML=data.summaries.map(s=>{const g=normal(s), e=data.editors.find(e=>e.id===s.editor);return `<tr><td>${escape(e.name)}<small>${escape(e.version)}</small></td><td>${g.passed}/${g.attempted}</td>${['pss','uss','rss','current'].map(k=>`<td>${fmt(g.metrics[k])}</td>`).join('')}<td>${fmt(g.peak)}</td></tr>`}).join('')
  $('budget-chart').innerHTML=bars(data.summaries.filter(s=>s.lowestTestedBudgetMiB!==null).map(s=>({id:s.editor,label:names[s.editor],value:s.lowestTestedBudgetMiB,prefix:s.atLowerBoundary?'≤ ':''})).sort((a,b)=>a.value-b.value),'Lowest tested passing application memory budget, MiB')
  $('budget-summary').innerHTML=data.summaries.map(s=>{const g=limited(s);return `<tr><td>${escape(names[s.editor])}</td><td>${g?`${s.atLowerBoundary?'≤ ':''}${g.budgetMiB}`:'—'}</td><td>${fmt(g?.metrics.pss)}</td><td>${fmt(g?.peak)}</td></tr>`}).join('')
  $('budget-head').innerHTML=`<tr><th>Editor</th>${data.summaries[0].groups.filter(g=>g.budgetMiB!==null).map(g=>g.budgetMiB).map(b=>`<th>${b} MiB</th>`).join('')}</tr>`
  $('budget-table').innerHTML=data.summaries.map(s=>`<tr><td>${escape(names[s.editor])}</td>${s.groups.filter(g=>g.budgetMiB!==null).map(g=>`<td><span class="badge ${!g.attempted?'':g.qualified?'pass':g.passed?'partial':'fail'}">${g.attempted?`${g.passed}/${g.attempted}`:'—'}</span></td>`).join('')}</tr>`).join('')
  const maxComponent=Math.max(1,...data.summaries.map(s=>['anon','file','kernel'].reduce((sum,k)=>sum+(normal(s)?.metrics[k]?.median||0),0)))
  $('composition').innerHTML=svg('Cgroup anonymous, file cache, and kernel memory. MiB.',520,data.summaries.length*64,data.summaries.map((s,i)=>{const g=normal(s);let x=165;return `<text x="0" y="${i*64+28}">${escape(names[s.editor])}</text>`+['anon','file','kernel'].map((k,j)=>{const v=g.metrics[k]?.median||0,w=v/maxComponent*260;const rect=`<rect x="${x}" y="${i*64+8}" width="${w}" height="27" fill="${['#823cc6','#c6a9e5','#dfe4ea'][j]}"/>`;x+=w;return rect}).join('')+`<text class="axis" x="165" y="${i*64+50}">${['anon','file','kernel'].map(k=>`${k}: ${fmt(g.metrics[k])}`).join(' · ')}</text>`}).join(''))
  const ms=(d)=>d?`${number(d.median)}<small>${number(d.min)}–${number(d.max)}</small>`:'—'
  $('latency-table').innerHTML=data.summaries.map(s=>`<tr><td>${escape(names[s.editor])}</td><td>${ms(normal(s).probeMs)}</td><td>${ms(limited(s)?.probeMs)}</td></tr>`).join('')
  $('trial').innerHTML=data.trials.map((t,i)=>`<option value="${i}">${escape(names[t.editor])} · ${t.budgetMiB?`${t.budgetMiB} MiB`:'normal'} · run ${t.repeat} · ${t.status}</option>`).join('')
  function timeline() {
    const t=data.trials[Number($('trial').value)], samples=t.samples
    $('trial-detail').textContent=`${t.status.toUpperCase()} · ${samples.length} complete samples · ${t.invalidSamples} discarded samples · ${t.error || 'Exact edit/save contents verified.'}`
    if (!samples.length) {$('timeline').innerHTML='<p class="empty">This trial failed before complete memory samples were available.</p>';return}
    const w=900,h=230,left=65,bottom=195,max=Math.max(...samples.map(s=>Math.max(s.pss,s.current)))*1.15,maxTime=Math.max(...samples.map(s=>s.seconds),1)
    const x=v=>left+v/maxTime*790,y=v=>bottom-v/max*170
    let content=Array.from({length:5},(_,i)=>{const value=max*i/4;return `<path d="M${left} ${y(value)}H855" stroke="#eceef3"/><text class="axis" x="55" y="${y(value)+4}" text-anchor="end">${number(mib(value))}</text><text class="axis" x="${x(maxTime*i/4)}" y="220" text-anchor="middle">${number(maxTime*i/4)} s</text>`}).join('')
    for(const [k,c] of [['pss','#823cc6'],['current','#3284c7']]) content+=`<polyline fill="none" stroke="${c}" stroke-width="2" points="${samples.map(s=>`${x(s.seconds)},${y(s[k])}`).join(' ')}"/>`+samples.map(s=>`<circle cx="${x(s.seconds)}" cy="${y(s[k])}" r="3" fill="${c}"><title>${escape(`${s.phase}: ${number(s.seconds)} s · ${k} ${number(mib(s[k]))} MiB`)}</title></circle>`).join('')
    content+='<text x="65" y="13">MiB</text><text x="650" y="13">Purple: PSS · Blue: cgroup</text>'
    $('timeline').innerHTML=svg('Memory timeline for the selected trial',w,h,content)
  }
  $('trial').addEventListener('change',timeline);timeline()
  $('environment').textContent=JSON.stringify({host:data.host,hosts:data.hosts,capturedAtByEditor:data.capturedAtByEditor,protocol:data.protocol,editors:data.editors,commit:data.commit,fixtureSha256:data.fixtureSha256},null,2)
  if (data.runUrl?.startsWith('https://github.com/levivilet/lvce-memory-benchmark/actions/runs/')) { $('run-link').href=data.runUrl; $('run-link').hidden=false }
}
main().catch(error=>{$('status').textContent=`Could not load benchmark results: ${error.message}. No example or estimated values are displayed.`; console.error(error)})
