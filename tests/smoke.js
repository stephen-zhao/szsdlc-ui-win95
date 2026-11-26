// End-to-end smoke test, driven by tests/test_frontend.py when node playwright is present.
// Walks the main surfaces against a live server and fails on any page or console error.
const { chromium } = require('playwright');

(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1366, height: 860 } });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
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
    const badge = (await page.textContent('.window:has-text("guide.md - Document Viewer") .addr .badge')).trim();
    if (badge !== 'Assets') throw new Error(`a document from the asset root is badged "${badge}"`);
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
  await step('refresh redraws in place', async () => {
    await page.click(`${W} .menubar button:has-text("View")`);
    await page.click('.menu button:has-text("Refresh")');
    await page.waitForSelector(`${W} .statusbar:has-text("Refreshed: nothing new")`);
    await page.waitForSelector(`${W} .board .bcol header b:has-text("Now")`);  // still where it was
    await page.keyboard.press('F5');  // the shortcut refreshes too, without reloading the page
    await page.waitForSelector(`${W} .statusbar:has-text("Refreshed: nothing new")`);
  });
  await step('refresh button on the toolbar', async () => {
    await page.click(`${W} .toolbar button[title="Refresh (F5)"]`);
    await page.waitForSelector(`${W} .statusbar:has-text("Refreshed: nothing new")`);
    await page.waitForSelector(`${W} .toolbar button[title="Refresh (F5)"]:not([disabled])`);  // enabled again
  });
  await step('the interval is set from the ▾ beside Refresh, the same in every Explorer', async () => {
    const IV = `${W} .toolbar .tbtn.interval`;
    if ((await page.textContent(IV)).trim() !== '1m▾') throw new Error(`default label is "${(await page.textContent(IV)).trim()}"`);
    await page.click(IV);
    if (!(await page.isVisible('.menu button:has-text("● Every minute")'))) throw new Error('the current interval is not marked');
    await page.click('.menu button:has-text("Every 30 seconds")');
    if ((await page.textContent(IV)).trim() !== '30s▾') throw new Error('label did not follow the choice');
    // A second Explorer agrees.
    await page.click(`${W} .menubar button:has-text("File")`);
    await page.click('.menu button:has-text("New window")');
    await page.waitForFunction(() => document.querySelectorAll('.toolbar .tbtn.interval').length >= 2);
    const labels = await page.$$eval('.toolbar .tbtn.interval', (bs) => bs.map((b) => b.textContent.trim()));
    if (!labels.every((l) => l === '30s▾')) throw new Error(`Explorers disagree: ${labels}`);
    // Keyboard: Enter opens it, and Off turns it off.
    await page.focus(IV);
    await page.keyboard.press('Enter');
    await page.click('.menu button:has-text("Off")');
    if (await page.evaluate(() => localStorage.getItem('szv:autoRefresh')) !== '0') throw new Error('Off did not store 0');
    const off = await page.$$eval('.toolbar .tbtn.interval', (bs) => bs.map((b) => b.textContent.trim()));
    if (!off.every((l) => l === '▾')) throw new Error(`Off still shows a label: ${off}`);
    // Display settings no longer has an interval.
    await page.click('#start');
    await page.click('.menu button:has-text("Display settings")');
    if (await page.isVisible('.window.active legend:has-text("Update automatically")')) throw new Error('Display settings still sets the interval');
    await page.click('.window.active button:has-text("OK")');
  });
  await step('Refresh and its ▾ are one control, and the address bar follows the buttons', async () => {
    const measure = () => page.$eval(W, (win) => {
      const box = (el) => el.getBoundingClientRect();
      const refreshBtn = win.querySelector('.toolbar button[title="Refresh (F5)"]');
      const groupEl = refreshBtn.parentElement;
      const group = box(groupEl);
      const [refresh, interval] = [refreshBtn, groupEl.querySelector('.interval')].map(box);
      const sep = box(groupEl.nextElementSibling);
      const crumbs = box(win.querySelector('.toolbar .crumbbar'));
      return { group: group.width, buttons: refresh.width + interval.width, gap: interval.left - refresh.right,
        after: crumbs.left - sep.right };
    });
    for (const label of ['normal', 'maximized']) {
      const m = await measure();
      if (Math.abs(m.group - m.buttons) > 1) throw new Error(`${label}: the group is ${m.group}px for ${m.buttons}px of buttons`);
      if (Math.abs(m.gap) > 0.5) throw new Error(`${label}: ${m.gap}px between Refresh and its ▾`);
      if (m.after > 8) throw new Error(`${label}: the address bar starts ${m.after}px after the buttons`);
      if (label === 'normal') await page.dblclick(`${W} .titlebar .t`);  // maximize: a wider toolbar
    }
    await page.dblclick(`${W} .titlebar .t`);
  });
  await step('an old doc:code: link still opens the document (WI-0069)', async () => {
    await page.evaluate(() => { location.hash = '#proj--doc:code:docs/guide.md'; });
    await page.waitForSelector('.window:has-text("guide.md - Document Viewer") .md h1:has-text("Guide")');
    await page.click('.window:has-text("guide.md - Document Viewer") .tb-btn.close');
  });
  await step('context menu: View as ▸ from a tree folder', async () => {
    await page.locator(`${W} .tree .node:visible`, { hasText: 'Work items' }).first().click({ button: 'right' });
    await page.waitForSelector('.menu button.default:has-text("Open")');
    await page.hover('.menu button:has-text("View as")');
    await page.click('.menu.submenu button:has-text("Details")');
    await page.waitForSelector(`${W} .lv tr[data-ref="WI-0001"]`);
  });
  await step('context menu: item row → Properties', async () => {
    await page.click(`${W} .lv tr[data-ref="WI-0001"]`, { button: 'right' });
    await page.click('.menu button:has-text("Properties")');
    await page.waitForSelector('.window.dialog:has-text("WI-0001 Properties") dd:has-text("Render the tree")');
    await page.keyboard.press('Escape');
    if (await page.isVisible('.window.dialog')) throw new Error('Escape did not close Properties');
  });
  await step('context menu: tree folder → Open in new window', async () => {
    const before = await page.$$eval('.window', (ws) => ws.length);
    await page.locator(`${W} .tree .node:visible`, { hasText: 'Roadmap' }).first().click({ button: 'right' });
    await page.click('.menu button:has-text("Open in new window")');
    await page.waitForFunction((n) => document.querySelectorAll('.window').length === n + 1, before);
    await page.waitForSelector(`${W} .board .bcol header b:has-text("Now")`);
  });
  await step('context menu: graph node → Copy ID', async () => {
    await page.evaluate(() => { location.hash = '#proj--WI-0001'; });
    await page.waitForSelector(`${W} .item-page h2:has-text("Render the tree")`);
    await page.click(`${W} .item-page .tab:has-text("Relations")`);
    await page.click(`${W} .graph .gnode.center`, { button: 'right' });
    await page.click('.menu button:has-text("Copy ID")');
    await page.waitForSelector(`${W} .statusbar:has-text("Copied: WI-0001")`);
  });
  await step('context menu: Shift+F10 opens it, Escape returns focus', async () => {
    await page.locator(`${W} .tree .node:visible`, { hasText: 'Work items' }).first().focus();
    await page.keyboard.press('Shift+F10');
    await page.waitForSelector('.menu button.default:has-text("Open")');
    if (!(await page.evaluate(() => !!document.activeElement.closest('.menu')))) throw new Error('the menu did not take focus');
    await page.keyboard.press('ArrowDown');
    if ((await page.evaluate(() => document.activeElement.dataset.label)) !== 'Open in new window') throw new Error('ArrowDown did not move');
    await page.keyboard.press('Escape');
    if (await page.isVisible('.menu')) throw new Error('Escape did not close the menu');
    if (!(await page.evaluate(() => document.activeElement.classList.contains('node')))) throw new Error('focus did not return');
  });
  await step('context menu: a text field keeps the browser menu', async () => {
    const prevented = (sel) => page.$eval(sel, (el) => { const e = new MouseEvent('contextmenu', { bubbles: true, cancelable: true }); el.dispatchEvent(e); return e.defaultPrevented; });
    if (await prevented(`${W} input[type=search]`)) throw new Error('the search box lost the browser menu');
    if (await page.isVisible('.menu')) throw new Error('a menu opened over a text field');
    if (!(await prevented(`${W} .tree .node`))) throw new Error('a tree node showed the browser menu');
    await page.keyboard.press('Escape');
  });
  await step('context menu: title bar → Minimize', async () => {
    await page.$eval(W, (el) => { el.dataset.probe = '1'; });
    await page.click(`${W} .titlebar .t`, { button: 'right' });
    await page.click('.menu button:has-text("Minimize")');
    await page.waitForSelector('.window[data-probe="1"].minimized', { state: 'attached' });
  });
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('smoke ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
