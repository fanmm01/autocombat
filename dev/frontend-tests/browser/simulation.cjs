const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const base = process.env.UI_BASE_URL || 'http://127.0.0.1:8895';

(async () => {
  const browser = await chromium.launch({channel: process.env.UI_BROWSER_CHANNEL || 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    const browserErrors = [];
    page.on('pageerror', error => browserErrors.push(error.message));
    let releaseSession;
    const sessionGate = new Promise(resolve => { releaseSession = resolve; });
    await page.route('**/api/ui/session', async route => {
      await sessionGate;
      await route.continue();
    });
    await page.goto(base + '/ui/settings', {waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: '正在连接星序引擎'}).waitFor();
    releaseSession();
    await page.getByRole('button', {name: '账号与权限', exact: true}).click();
    await page.getByText('游客身份', {exact: false}).waitFor();

    await page.evaluate(() => localStorage.setItem('combat-simulation', 'missing-release-job'));
    await page.getByRole('button', {name: '模拟实验室', exact: true}).click();
    const lab = page.locator('.simulation-expanded');
    await lab.getByRole('alert').filter({hasText: '上次模拟任务已不存在'}).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('combat-simulation')), null);

    await lab.getByLabel('模式').selectOption('single');
    await lab.getByLabel('场数', {exact: true}).fill('1001');
    await lab.getByRole('button', {name: '运行模拟'}).click();
    await lab.getByRole('alert').filter({hasText: '启动模拟失败'}).waitFor();

    const jobRoute = /\/api\/ui\/simulations\/[0-9a-f]+$/;
    await page.route(jobRoute, route => route.fulfill({status: 503, json: {message: '暂时取不到进度'}}), {times: 1});
    await lab.getByLabel('场数', {exact: true}).fill('2');
    await lab.getByLabel('并发数').fill('2');
    await lab.getByLabel('种子（空为随机）').fill('42');
    await lab.getByRole('button', {name: '运行模拟'}).click();
    await lab.getByRole('alert').filter({hasText: '读取模拟进度失败，正在重试'}).waitFor();
    await lab.getByRole('status').filter({hasText: '模拟已完成'}).waitFor({timeout: 30000});
    await lab.getByRole('link', {name: '导出 CSV'}).waitFor();

    const jobId = await page.evaluate(() => localStorage.getItem('combat-simulation'));
    const completed = await (await page.request.get(base + '/api/ui/simulations/' + jobId)).json();
    assert.equal(completed.completed, 2);
    await page.route(jobRoute, route => route.fulfill({json: {
      ...completed, status: 'failed', completed: 0, result: null, message: '工作进程异常退出（代码 1）',
    }}), {times: 1});
    await page.reload();
    await lab.getByRole('alert').filter({hasText: '工作进程异常退出'}).waitFor();
    assert.deepEqual(browserErrors, []);
    console.log('Simulation browser: fresh-session allowlist, stale job, failed startup, polling retry and worker failure passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
