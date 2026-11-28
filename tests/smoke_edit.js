// Editing, end to end, driven by tests/test_frontend.py against a project kept in git,
// so unsent changes and Send changes are real. Fails on any page or console error.
const { chromium } = require('playwright');

(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1366, height: 860 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', (d) => d.accept());  // the beforeunload prompt for unsent changes
  // A refusal is a 4xx the page handles; only other console errors count.
  page.on('console', (m) => m.type() === 'error' && !/status of (409|422|400)/.test(m.text()) && errors.push(m.text()));
  await page.addInitScript(() => { try { localStorage.setItem('szv:welcome', '0'); localStorage.setItem('szv:autoRefresh', '0'); } catch { /* ignore */ } });
  const W = '.window.active';
  const step = async (name, fn) => { try { await fn(); } catch (e) { throw new Error(`${name}: ${e.message}`); } };
  const pill = `${W} .item-page .pill.pick`;
  const move = async (to) => {
    await page.click(pill);
    await page.click(`.menu button[data-label^="${to}"]`);
  };
  const pillIs = (status) => page.waitForSelector(`${pill}:has-text("${status}")`);

  const pid = (await (await fetch(base + 'api/projects')).json())[0].id;
  await page.goto(`${base}#${pid}--WI-0002`);
  await page.waitForSelector(`${W} .item-page h2:has-text("Draw the graph")`);

  await step('status moves through the workflow', async () => {
    await move('groomed'); await pillIs('groomed');
    await move('ready'); await pillIs('ready');
    await move('planning'); await pillIs('planning');
  });
  await step('a gate refuses with its remedy', async () => {
    await page.click(pill);
    const label = await page.getAttribute('.menu button[data-label^="planned"]', 'data-label');
    if (!/needs plan\.md/.test(label)) throw new Error(`the menu does not name the gate: "${label}"`);
    await page.click('.menu button[data-label^="planned"]');
    await page.waitForSelector('.window.dialog:has-text("plan.md")');
    await page.click('.window.dialog button:has-text("OK")');
    await pillIs('planning');  // nothing changed
  });
  await step('unsent changes show in the tray and the title', async () => {
    await page.waitForSelector('#tray-unsent:not([hidden])');
    const title = await page.getAttribute('#tray-unsent', 'title');
    if (!/^3 unsent changes/.test(title)) throw new Error(`tray says "${title}"`);
    if (!(await page.title()).startsWith('* ')) throw new Error(`page title is "${await page.title()}"`);
  });
  await step('a tag is added and removed', async () => {
    await page.click(`${W} .item-page .chip.add`);
    await page.fill(`${W} .item-page .tag-field`, 'api');
    await page.keyboard.press('Enter');
    await page.waitForSelector(`${W} .item-page .tagged:has-text("#api")`);
    await page.click(`${W} .item-page .untag[aria-label="Remove tag api"]`);
    await page.waitForSelector(`${W} .item-page .tagged:has-text("#api")`, { state: 'detached' });
  });
  await step('a field is edited inline', async () => {
    await page.click(`${W} .item-page button[aria-label="Edit Opened"]`);
    await page.fill(`${W} .item-page dd.editable input[type=date]`, '2026-01-02');
    await page.keyboard.press('Enter');
    await page.waitForSelector(`${W} .item-page dd.editable:has-text("2026-01-02")`);
  });
  await step('the tray lists the edits and sends them', async () => {
    await page.click('#tray-unsent');
    await page.waitForSelector('.menu button[data-label="WI-0002: status idea → groomed"]');
    await page.click('.menu button[data-label="Send changes"]');
    await page.waitForSelector('#tray-unsent', { state: 'hidden' });
    if ((await page.title()).startsWith('* ')) throw new Error('the title still says unsent');
    await page.waitForSelector(`${W} .statusbar:has-text("Sent")`);
  });
  await step('a change made behind the page is never overwritten', async () => {
    await page.evaluate(async ([p, token]) => {
      const d = await (await fetch(`/api/p/${p}/entities/WI-0002`)).json();
      await fetch(`/api/p/${p}/entities/WI-0002/tag`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Viewer-Token': token },
        body: JSON.stringify({ expect: d.hash, tags: ['behind'] }) });
    }, [pid, await page.getAttribute('meta[name="viewer-token"]', 'content')]);
    await move('dropped');
    await page.waitForSelector('.window.dialog:has-text("This item changed on disk. Reload?")');
    await page.click('.window.dialog button:has-text("Yes")');
    await page.waitForSelector(`${W} .item-page .tagged:has-text("#behind")`);
    await pillIs('planning');
  });
  await step('Other… forces a move, with a reason', async () => {
    await move('Other…');
    await page.selectOption('.window.dialog select', 'idea');
    if (!(await page.isDisabled('.window.dialog button:has-text("Move")'))) throw new Error('Move is enabled without a reason');
    await page.fill('.window.dialog textarea', 'replanned from scratch');
    await page.click('.window.dialog button:has-text("Move")');
    await pillIs('idea');
  });
  await step('Alt+I captures an idea; an empty one is refused inside the editor', async () => {
    await page.evaluate(() => document.activeElement?.blur());  // not in a text field
    await page.keyboard.press('Alt+KeyI');
    const editor = '.window.active:has(.editor-text)';
    await page.waitForSelector(`${editor} .editor-text`);
    await page.click(`${editor} button:has-text("Save")`);
    await page.waitForSelector(`${editor} .editor-msg:has-text("nothing to capture")`);  // szsdlc's own refusal, in the window
    await page.fill(`${editor} .editor-text`, 'Captured in the smoke test\nWith a second line.');
    await page.keyboard.press('Control+Enter');
    await page.waitForSelector('.editor-text', { state: 'detached' });
    await page.waitForSelector('.statusbar:has-text("captured")');
    await page.click('#tray-unsent');  // it is one of the unsent changes
    await page.waitForSelector('.menu button[data-label$="captured: Captured in the smoke test"]');
    await page.keyboard.press('Escape');
  });
  await step('a draft survives a reload, and closing asks before discarding it', async () => {
    await page.click('#start');
    await page.click('.menu button[data-label^="Capture idea"]');
    await page.fill('.window.active .editor-text', 'half a thought');
    await page.reload();  // the unsent capture's beforeunload prompt is accepted below
    await page.waitForSelector('.window.active .toolbar');
    await page.evaluate(() => document.activeElement?.blur());  // not in a text field
    await page.keyboard.press('Alt+KeyI');
    await page.waitForSelector('.window.active .editor-text');
    if ((await page.inputValue('.window.active .editor-text')) !== 'half a thought') throw new Error('the draft was not offered back');
    await page.waitForSelector('.window.active .statusbar:has-text("Draft restored")');
    await page.click('.window.active:has(.editor-text) button:has-text("Cancel")');
    await page.waitForSelector('.window.dialog:has-text("Discard this text?")');
    await page.click('.window.dialog button:has-text("Discard")');
    await page.waitForSelector('.editor-text', { state: 'detached' });
    await page.evaluate(() => document.activeElement?.blur());  // not in a text field
    await page.keyboard.press('Alt+KeyI');
    if ((await page.inputValue('.window.active .editor-text')) !== '') throw new Error('a discarded draft came back');
    await page.click('.window.active:has(.editor-text) button:has-text("Cancel")');  // nothing typed: closes at once
    await page.waitForSelector('.editor-text', { state: 'detached' });
  });
  await step('New… on the Inbox toolbar captures into it, and Send changes sends it', async () => {
    await page.evaluate((p) => { location.hash = `#${p}--inbox`; }, pid);
    await page.click(`${W} .viewbar .tbtn.new`);
    await page.fill('.window.active .editor-text', 'From the Inbox toolbar');
    await page.click('.window.active:has(.editor-text) button:has-text("Save")');
    await page.waitForSelector('.editor-text', { state: 'detached' });
    await page.waitForSelector(`${W} .lv td:has-text("From the Inbox toolbar")`);
    await page.click('#tray-unsent');
    await page.click('.menu button[data-label="Send changes"]');
    await page.waitForSelector('#tray-unsent', { state: 'hidden' });
  });
  await step('findings open from the File menu', async () => {
    await page.click(`${W} .menubar button:has-text("File")`);
    await page.click('.menu button:has-text("Findings…")');
    await page.waitForSelector('.window.active:has-text("Findings") .lv table');
  });
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('edit smoke ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
