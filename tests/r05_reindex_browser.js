"use strict";

// Mock-only R05 browser contract test. Synthetic fixtures prove UI flow only; no Elasticsearch request is made.
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.once("error", reject).listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "r05-reindex-browser-"));
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const python = process.env.PYTHON || path.join(root, ".venv", "bin", "python");
  const child = spawn(python, ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root, env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(temp, "state.sqlite3"), HOME: temp }, stdio: "ignore",
  });
  let browser;
  try {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new Error(`workbench exited ${child.exitCode}`);
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const calls = [];
    let jobState = "queued";
    let latestCalls = 0;
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      let body = {};
      try { if (route.request().method() === "POST") body = route.request().postDataJSON(); } catch {}
      calls.push({ path: url.pathname, body });
      const json = value => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated: true, csrf_token: "mock-csrf", user: { id: "synthetic-account", username: "synthetic", display_name: "Synthetic", role: "user" } });
      if (url.pathname === "/api/health") return json({ version: "1.12.0" });
      if (url.pathname === "/api/codebase-status") return json({ indexed: false });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/concepts/list") return json({ concepts: [] });
      if (url.pathname === "/api/knowledge/list") return json({ documents: [{ document_id: "synthetic-doc", title: "Synthetic document", source_label: "fixture", revision: 1 }], usage: { documents: 1, bytes: 4 } });
      if (url.pathname === "/api/knowledge/chunks/policy/get") return json({ policy: { strategy: "character", size: 1800, overlap: 200 }, policy_sha256: "synthetic-policy" });
      if (url.pathname === "/api/knowledge/reindex/latest") {
        latestCalls += 1;
        return json({ job: latestCalls === 1 ? null : { job_id: "synthetic-interrupted", state: "interrupted", completed: 0, total: 1, failed_documents: [], generation: "esrag-private-synthetic-g2", safe_error: "The server stopped before publication. Retry this job." } });
      }
      if (url.pathname === "/api/knowledge/es-status") return json({ state: "stale", vector_state: "not_indexed", local_documents: 1, local_chunks: 1, indexed_chunks: 0, tokenizer: { available: false } });
      if (url.pathname === "/api/knowledge/chunks/preview") return json({ policy: body, chunks: [{ ordinal: 0, start_offset: 0, end_offset: 12, content: "synthetic body", token_count: 3 }] });
      if (url.pathname === "/api/knowledge/chunks/policy") return json({ policy: body.policy, policy_sha256: "synthetic-policy" });
      if (url.pathname === "/api/knowledge/reindex/start") return json({ job_id: "synthetic-job", state: "queued", total: 1, generation: "esrag-private-synthetic-g2" });
      if (url.pathname === "/api/knowledge/reindex/retry") return json({ job_id: "synthetic-retried", state: "queued", total: 1, generation: "esrag-private-synthetic-g3" });
      if (url.pathname === "/api/knowledge/reindex/status") { jobState = "complete"; return json({ job_id: "synthetic-job", state: jobState, completed: 1, total: 1, failed_documents: [], generation: "esrag-private-synthetic-g2", safe_error: "" }); }
      if (url.pathname === "/api/knowledge/import/preview") return json({ valid_records: [], errors: [], usage: { documents: 1, bytes: 4 } });
      return json({});
    });
    await page.goto(base);
    await page.getByRole("tab", { name: /내 지식/ }).click();
    await page.locator("#knowledge-chunk-strategy").selectOption("character");
    await page.locator("#knowledge-chunk-size").fill("12");
    await page.locator("#knowledge-chunk-overlap").fill("2");
    await page.locator("#es-url").fill("http://127.0.0.1:32790");
    await page.locator("#knowledge-title").fill("Synthetic note");
    await page.locator("#knowledge-content").fill("synthetic body");
    await page.locator("#knowledge-preview-button").click();
    await page.getByText(/character 정책/).waitFor();
    if (!(await page.locator("#knowledge-chunk-preview").innerText()).includes("3 tokens")) throw new Error("actual synthetic token count not rendered");
    await page.locator("#knowledge-reindex-start").click();
    await page.getByText(/complete · 문서 1\/1 완료/).waitFor({ timeout: 5000 });
    if (!calls.some(call => call.path === "/api/knowledge/reindex/start")) throw new Error("start route not called");
    await page.reload();
    await page.getByRole("tab", { name: /내 지식/ }).click();
    await page.getByText(/interrupted · 문서 0\/1 완료/).waitFor({ timeout: 5000 });
    if (await page.locator("#knowledge-reindex-retry").isDisabled()) throw new Error("persisted interrupted job did not enable retry");
    await page.locator("#knowledge-reindex-retry").click();
    await page.getByText(/complete · 문서 1\/1 완료/).waitFor({ timeout: 5000 });
    if (!calls.some(call => call.path === "/api/knowledge/reindex/retry" && call.body.job_id === "synthetic-interrupted")) throw new Error("recovered job ID was not sent to retry route");
    if (calls.some(call => /127\.0\.0\.1:9200|:8765/.test(JSON.stringify(call)))) throw new Error("protected shared workbench endpoint was referenced");
    if (await page.locator("body").evaluate(node => node.innerText.includes("Elasticsearch proof"))) throw new Error("mock flow mislabeled as live ES proof");
    console.log("R05 mock-only reindex browser flow passed; synthetic fixture, no Elasticsearch proof.");
  } finally {
    if (browser) await browser.close();
    child.kill("SIGTERM");
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
