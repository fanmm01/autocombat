const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { loadTs } = require('./load-ts.cjs');

const ROOT = path.resolve(__dirname, '../..');
const nav = loadTs(path.join(ROOT, 'frontend/src/navigation.ts'));

test('classicPages excludes autochess and route classifiers separate the two realms', () => {
  assert.ok(!nav.classicPages.includes('autochess'));
  assert.equal(nav.autochessPage, 'autochess');
  assert.equal(nav.isAutoChessPage('autochess'), true);
  for (const p of nav.classicPages) {
    assert.equal(nav.isAutoChessPage(p), false);
    assert.equal(nav.pageFromPath(nav.pageUrl(p)), p);
  }
  assert.equal(nav.pageFromPath(nav.pageUrl('autochess')), 'autochess');
});

test('ClassicApp removes autochess sidebar/cards and connects via a single switch button', () => {
  const mainSrc = fs.readFileSync(path.join(ROOT, 'frontend/src/main.tsx'), 'utf8');
  const classicStart = mainSrc.indexOf('function ClassicApp(');
  const rootStart = mainSrc.indexOf('function RootApp(');
  assert.ok(classicStart !== -1 && rootStart > classicStart);
  const classicBody = mainSrc.slice(classicStart, rootStart);

  // Classic sidebar nav-stack and home mode-grid must not list autochess
  assert.doesNotMatch(classicBody, /\{id:\s*['"]autochess['"]/);
  assert.doesNotMatch(classicBody, /AUTO-CHESS/);
  assert.doesNotMatch(classicBody, /<AutoChessPage\b/);
  assert.doesNotMatch(classicBody, /navigate\(['"]autochess['"]\)/);

  // Classic side exposes only one click handler into Auto-Chess (in the topbar)
  const switchClicks = classicBody.match(/onClick=\{handleSwitchToAutoChess\}/g) || [];
  assert.equal(switchClicks.length, 1);
  assert.match(classicBody, /className="button subtle compact-button classic-ac-switch"/);
});

test('AutoChessApp has no classic shell or classic routes and exposes only one switch button back', () => {
  const acAppSrc = fs.readFileSync(path.join(ROOT, 'frontend/src/autochess/AutoChessApp.tsx'), 'utf8');
  const acPageSrc = fs.readFileSync(path.join(ROOT, 'frontend/src/autochess/AutoChessPage.tsx'), 'utf8');

  // AutoChessApp renders an isolated shell without classic sidebar/catalog/settings API calls or room restore
  assert.doesNotMatch(
    acAppSrc,
    /className="sidebar"|className="nav-stack"|['"]\/(?:catalog|presets|settings)['"]|combat-room/,
  );
  const backClicks = acAppSrc.match(/onClick=\{onSwitchToClassic\}/g) || [];
  assert.equal(backClicks.length, 1);
  assert.match(acAppSrc, /返回经典模式/);

  // AutoChess files never navigate into classic routes
  for (const fname of ['AutoChessPage.tsx', 'AutoChessAuthModal.tsx', 'AutoChessTokenModal.tsx', 'AutoChessVfxLayer.tsx']) {
    const src = fs.readFileSync(path.join(ROOT, 'frontend/src/autochess', fname), 'utf8');
    assert.doesNotMatch(src, /\/ui\/(home|setup|battle|sim|library|editor|tournament|settings|story)/);
  }
});

test('Auto-Chess CSS supports portrait ordering, horizontal board scrolling, tokens, VFX, and small screens', () => {
  const css = fs.readFileSync(path.join(ROOT, 'frontend/src/autochess/autochess.css'), 'utf8');
  assert.match(css, /@media\s*\(max-width:\s*1080px\)[\s\S]*?\.ac-center-col\s*\{[^}]*order:\s*1/);
  assert.match(css, /\.ac-board-scroll\s*\{[^}]*overflow-x:\s*auto/);
  assert.match(css, /@media\s*\(max-width:\s*640px\)[\s\S]*?\.ac-board-svg\s*\{[^}]*--ac-cols/);
  assert.match(css, /@media\s*\(max-width:\s*420px\)/);
  assert.match(css, /@media\s*\(max-width:\s*360px\)/);
  assert.match(css, /\.ac-unit-group\s*\{[^}]*transition:\s*transform/);
  assert.match(css, /\.ac-vfx-popup\b/);
  assert.match(css, /\.ac-room-wait-card\b/);
});

test('Auto-Chess wiki is completely isolated from main encyclopedia and uses 1.5s hover delay', () => {
  const acDir = path.join(ROOT, 'frontend/src/autochess');
  const files = fs.readdirSync(acDir).filter(f => /\.(ts|tsx)$/.test(f));
  const forbidden = /encyclopedia|KnowledgeUI|\/knowledge\b|\/ui\/library|\/ui\/help\/|[?&](?:character|term)=/;
  for (const f of files) {
    const src = fs.readFileSync(path.join(acDir, f), 'utf8');
    assert.doesNotMatch(src, forbidden, `${f} must not reference classic encyclopedia modules or routes`);
  }

  const hoverSrc = fs.readFileSync(path.join(acDir, 'useHoverWiki.ts'), 'utf8');
  assert.match(hoverSrc, /WIKI_HOVER_DELAY_MS\s*=\s*1500/);

  const pageSrc = fs.readFileSync(path.join(acDir, 'AutoChessPage.tsx'), 'utf8');
  const hoverCalls = pageSrc.match(/hoverWiki\.startHover\(/g) || [];
  assert.ok(hoverCalls.length >= 4, `Expected shop, bench, prep board, and combat board hover bindings; got ${hoverCalls.length}`);
});
