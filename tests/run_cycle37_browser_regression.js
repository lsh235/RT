"use strict";

// Runs the C34-C36 browser regressions against a disposable loopback workbench.
// Each fixture starts at about:blank and installs its API routes before navigating.
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");

function allocatePort() {
  return new Promise((resolve, reject) => {
    const socket = net.createServer();
    socket.once("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const port = socket.address().port;
      socket.close(error => error ? reject(error) : resolve(port));
    });
  });
}

async function waitForServer(url, child) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`workbench exited with ${child.exitCode}`);
    try { if ((await fetch(url)).ok) return; } catch { /* listener is starting */ }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("workbench did not become ready");
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const fixtures = [
    "cycle34_mode_comparison_browser.js",
    "cycle35_group_mode_comparison_browser.js",
    "cycle36_group_comparison_readiness_browser.js",
  ];
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle37-browser-regression-"));
  const dbPath = path.join(tempDir, "synthetic.sqlite3");
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.PYTHON || "python3", ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: dbPath, ES_RAG_ACCEPTANCE_ES_URL: "http://127.0.0.1:1" },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer(`${base}/api/health`, child);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CYCLE37_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE37_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE37_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const results = [];
    for (const fixtureName of fixtures) {
      const page = await browser.newPage();
      await page.goto("about:blank");
      await page.route("**/api/**", route => route.fulfill({
        status: 599, contentType: "application/json", body: JSON.stringify({ error: "fixture did not mock API route" }),
      }));
      const source = fs.readFileSync(path.join(__dirname, fixtureName), "utf8");
      const fixture = new Function(`return (${source})`)();
      process.env.CYCLE37_BASE_URL = `${base}/`;
      const result = await fixture(page);
      results.push({ fixture: fixtureName, ...result });
      await page.close();
    }
    console.log(JSON.stringify({ result: "PASS", port, db: "temporary synthetic path", fixtures: results }));
  } finally {
    delete process.env.CYCLE37_BASE_URL;
    if (browser) await browser.close();
    if (child.exitCode === null) child.kill("SIGTERM");
    if (child.exitCode === null) await new Promise(resolve => child.once("exit", resolve));
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch(error => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
