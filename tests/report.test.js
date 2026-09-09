import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { test } from 'node:test'
import { chromium } from 'playwright'

test('measured report renders and responds to filters on desktop and mobile', async () => {
  const server = spawn('python3', ['-m', 'http.server', '8765', '--bind', '127.0.0.1', '--directory', '.tmp/pages'], {stdio:'ignore'})
  let browser
  try {
    for (let i=0;i<50;i++) {try {if((await fetch('http://127.0.0.1:8765/')).ok) break} catch {} await delay(100)}
    browser=await chromium.launch()
    const page=await browser.newPage({viewport:{width:1440,height:1000}})
    const errors=[]
    page.on('pageerror',e=>errors.push(e.message))
    await page.goto('http://127.0.0.1:8765/')
    await page.waitForSelector('#normal-table tr')
    const data = await (await fetch('http://127.0.0.1:8765/results.json')).json()
    assert.equal(await page.locator('#normal-table tr').count(), data.editors.length)
    assert.equal(await page.locator('#trial option').count(), data.trials.length)
    if (data.hosts) {
      assert.ok((await page.locator('#meta').textContent()).includes(`${data.editors.length} separate editor runners`))
      const environment = JSON.parse(await page.locator('#environment').textContent())
      assert.deepEqual(environment.hosts, data.hosts)
      assert.deepEqual(Object.keys(environment.hosts).sort(), data.editors.map(e => e.id).sort())
    }
    const before=await page.locator('#normal-chart').innerHTML()
    await page.selectOption('#metric','rss')
    assert.notEqual(await page.locator('#normal-chart').innerHTML(),before)
    const count=await page.locator('#trial option').count()
    await page.selectOption('#trial',String(count-1))
    assert.ok((await page.locator('#trial-detail').textContent()).includes('samples'))
    assert.ok(await page.locator('a[download]').count())
    await page.setViewportSize({width:390,height:844})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth))
    assert.deepEqual(errors,[])
    await page.screenshot({path:'.tmp/report-mobile.png',fullPage:true})
    await page.setViewportSize({width:1440,height:1000})
    await page.screenshot({path:'.tmp/report-desktop.png',fullPage:true})
  } finally {
    await browser?.close()
    server.kill()
  }
})
