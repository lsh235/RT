import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from 'playwright';

const root = path.resolve(import.meta.dirname, '..');
const venvPython = process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : path.join(root, '.venv', 'bin', 'python');
const python = process.env.PYTHON || (existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3'));
const temp = await mkdtemp(path.join(os.tmpdir(), 'es-rag-browser-smoke-'));
const db = path.join(temp, 'concepts.sqlite3');
const port = await new Promise((resolve, reject) => {
  const server = net.createServer();
  server.once('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const value = server.address().port;
    server.close(() => resolve(value));
  });
});
const child = spawn(python, ['-m', 'es_rag_tuner', '--host', '127.0.0.1', '--port', String(port)], {
  cwd: root,
  env: { ...process.env, ES_RAG_CONCEPT_DB: db, HOME: temp },
  stdio: 'ignore',
});
let spawnError;
child.on('error', error => { spawnError = error; });
let browser;
try {
  let ready = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (spawnError) throw new Error(`could not start Python interpreter ${python}: ${spawnError.message}`);
    if (child.exitCode !== null) throw new Error(`workbench exited with code ${child.exitCode}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (response.ok) { ready = true; break; }
    } catch {}
    await delay(250);
  }
  if (!ready) throw new Error('workbench did not become ready');
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const response = await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'domcontentloaded' });
  if (!response?.ok()) throw new Error(`home page returned HTTP ${response?.status()}`);
  const initialHtml = await response.text();
  const initialVersion = initialHtml.match(/id="server-version">([^<]+)</)?.[1];
  if (initialVersion !== 'v1.10.0') throw new Error(`static UI version was ${initialVersion || 'missing'}, expected v1.10.0`);
  const health = await page.evaluate(async () => {
    const healthResponse = await fetch('/api/health', { cache: 'no-store' });
    if (!healthResponse.ok) throw new Error(`health endpoint returned HTTP ${healthResponse.status}`);
    return healthResponse.json();
  });
  if (health.version !== '1.10.0') throw new Error(`health version was ${health.version}, expected 1.10.0`);
  await page.locator('body').waitFor();
  await page.waitForFunction(() => document.querySelector('#server-version')?.textContent === 'v1.10.0');
  const displayedVersion = await page.locator('#server-version').textContent();
  if (displayedVersion !== 'v1.10.0') throw new Error(`rendered UI version was ${displayedVersion}, expected v1.10.0`);
  const title = await page.title();
  if (!title) throw new Error('home page has no title');
  console.log(JSON.stringify({ ok: true, title, python, initial_version: initialVersion, health_version: health.version, displayed_version: displayedVersion, url: `http://127.0.0.1:${port}/` }));
} finally {
  await browser?.close();
  if (child.pid && child.exitCode === null && child.signalCode === null) {
    child.kill('SIGTERM');
    await new Promise(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) resolve();
      else child.once('exit', resolve);
    });
  }
  await rm(temp, { recursive: true, force: true });
}
