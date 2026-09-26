import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { test } from 'node:test'
import { chromium } from 'playwright'

test('historical editor pages render real-valued release points and adapt to mobile', async () => {
  const server = spawn('python3', ['-m', 'http.server', '8766', '--bind', '127.0.0.1', '--directory', '.tmp/pages'], {stdio:'ignore'})
  let browser
  try {
    for (let i=0;i<50;i++) {try {if((await fetch('http://127.0.0.1:8766/lvce-history.html')).ok) break} catch {} await delay(100)}
    const history = {schemaVersion:1, attempted:3, succeeded:2, failed:1, versions:{
      lvce:[
        {editor:'lvce',version:'v0.1.0',medianPssBytes:104857600,minPssBytes:100663296,maxPssBytes:109051904,runtime:'Electron 10 (bundled)',sha256:'a'.repeat(64)},
        {editor:'lvce',version:'v0.2.0',medianPssBytes:115343360,minPssBytes:109051904,maxPssBytes:121634816,runtime:'Electron 11 (bundled)',sha256:'b'.repeat(64)},
      ],
      vscode:[
        {editor:'vscode',version:'1.1.0',medianPssBytes:157286400,minPssBytes:150994944,maxPssBytes:163577856,runtime:'Electron 12 (bundled)',sha256:'c'.repeat(64)},
      ],
    },failures:[{editor:'lvce',version:'v0.3.0',error:'benchmark failed'}]}
    browser=await chromium.launch()
    const page=await browser.newPage({viewport:{width:1440,height:1000}})
    const errors=[]
    page.on('pageerror',error=>errors.push(error.message))
    await page.route('**/history.json',route=>route.fulfill({json:history}))
    for (const [file,editor,count] of [['lvce-history.html','lvce',2],['vscode-history.html','vscode',1]]) {
      await page.goto(`http://127.0.0.1:8766/${file}`)
      await page.waitForFunction(() => document.querySelector('#history-meta')?.textContent.includes('successful releases'))
      assert.equal(await page.locator('#history-table tr').count(),count)
      assert.equal(await page.locator('#history-chart circle').count(),count)
      assert.ok((await page.locator('#history-diagnostics').textContent()).includes('v0.3.0'))
      await page.setViewportSize({width:390,height:844})
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth))
    }
    assert.deepEqual(errors,[])
  } finally {
    await browser?.close()
    server.kill()
  }
})
