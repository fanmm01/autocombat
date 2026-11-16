// Keep development tests outside the distributable frontend source tree.
const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const tests = path.join(root, 'dev/frontend-tests');
const env = { ...process.env, NODE_PATH: [path.join(root, 'frontend/node_modules'), process.env.NODE_PATH].filter(Boolean).join(path.delimiter) };
const args = process.argv.includes('--browser')
  ? [path.join(tests, 'browser/knowledge.cjs')]
  : ['--test', ...fs.readdirSync(tests).filter(name => name.endsWith('.test.cjs')).map(name => path.join(tests, name))];
const result = spawnSync(process.execPath, args, { cwd: path.join(root, 'frontend'), env, stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
