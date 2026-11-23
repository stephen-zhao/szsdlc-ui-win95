// End-to-end smoke test, driven by tests/test_frontend.py when node playwright is present.
// Walks the main surfaces against a live server and fails on any page or console error.
const { chromium } = require('playwright');

(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1366, height: 860 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.addInitScript(() => { try { localStorage.setItem('szv:welcome', '0'); } catch { /* ignore */ } });
  const W = '.window.active';
  const step = async (name, fn) => { try { await fn(); } catch (e) { throw new Error(`${name}: ${e.message}`); } };

  await step('open item by link', async () => {
    await page.goto(base + '#proj--WI-0001');
    await page.waitForSelector(`${W} .item-page h2:has-text("Render the tree")`);
  });
  await step('checklist tab', async () => {
    await page.click(`${W} .item-page .tab:has-text("Plan")`);
    const done = await page.textContent(`${W} .cl-summary b.big`);
    if (!/2 of 3 done/.test(done)) throw new Error(`checklist says "${done}"`);
  });
  await step('relations graph', async () => {
    await page.click(`${W} .item-page .tab:has-text("Relations")`);
    await page.waitForSelector(`${W} .graph svg .gnode.center`);
  });
  await step('out-of-tree document', async () => {
    await page.click(`${W} .item-page .tab:has-text("Documents")`);
    await page.dblclick(`${W} .item-page .lv tr:has-text("docs/guide.md")`);
    await page.waitForSelector('.window:has-text("guide.md - Document Viewer") .md h1:has-text("Guide")');
    await page.click('.window:has-text("guide.md - Document Viewer") .tb-btn.close');
  });
  await step('parent keeps the path', async () => {
    await page.click(`${W} .crumb-fill`);
    await page.fill(`${W} .crumb-edit`, 'proj/Epics/EPIC-0001');
    await page.keyboard.press('Enter');
    await page.waitForSelector(`${W} .item-page .tab:has-text("Children")`);
    await page.dblclick(`${W} .item-page .lv tr:has-text("WI-0002")`);
    await page.waitForSelector(`${W} .item-page h2:has-text("Draw the graph")`);
    const crumbs = await page.$$eval(`${W} .crumb`, (cs) => cs.map((c) => c.textContent));
    if (crumbs.join('/') !== 'proj/Epics/EPIC-0001/WI-0002') throw new Error(`crumbs: ${crumbs.join('/')}`);
  });
  await step('board and hide closed', async () => {
    await page.click(`${W} .crumb:has-text("proj")`);
    await page.locator(`${W} .tree .node:visible`, { hasText: 'Work items' }).first().click();
    await page.waitForSelector(`${W} .board .bcol`);
    const label = (await page.textContent(`${W} .check-tb`)).trim();
    if (label !== 'Hide closed') throw new Error(`toolbar toggle says "${label}"`);
    await page.click(`${W} .check-tb`);
    await page.waitForSelector(`${W} .board .card`);
  });
  await step('roadmap', async () => {
    await page.locator(`${W} .tree .node:visible`, { hasText: 'Roadmap' }).first().click();
    await page.waitForSelector(`${W} .board .bcol header b:has-text("Now")`);
  });
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('smoke ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
