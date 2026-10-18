"use strict";

// Mock-only R07 browser fixture. All /api responses are synthetic; no Elasticsearch or model download is contacted.
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");

function allocatePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "r07-mock-browser-"));
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const python = process.env.PYTHON || (fs.existsSync(path.join(root, ".venv", "bin", "python")) ? path.join(root, ".venv", "bin", "python") : "python3");
  const child = spawn(python, ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root, env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(tempDir, "test.sqlite3"), HOME: tempDir }, stdio: "ignore",
  });
  let browser;
  try {
    const deadline = Date.now() + 12000;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new Error(`workbench exited: ${child.exitCode}`);
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 60));
    }
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const calls = [];
    let modelReady = false;
    let searchRerankFails = false;
    await page.route("**/api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch {}
      calls.push({ path: url.pathname, method: request.method(), body });
      const json = (value, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated: true, csrf_token: "mock-csrf", user: { id: "mock-user", username: "mock", display_name: "Mock", role: "user" } });
      if (url.pathname === "/api/health") return json({ version: "1.12.0" });
      if (url.pathname === "/api/codebase-status") return json({ indexed: false });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/embedding-profiles") return json({ profiles: [] });
      if (url.pathname === "/api/reranker/status") return json({ ready: modelReady, runtime: { installed: true, version: "mock-1" }, cache: { ready: modelReady }, loaded: false, device: "cpu", max_length: 512, activation: "identity", interpretation: "raw score" });
      if (url.pathname === "/api/reranker/prepare") {
        if (body.consent !== true) return json({ error: "explicit consent required" }, 400);
        modelReady = true;
        return json({ ready: true, runtime: { installed: true, version: "mock-1" }, cache: { ready: true }, loaded: false, device: "cpu", max_length: 512, activation: "identity", interpretation: "raw score", model: "mock-cross-encoder", revision: "mock-revision" });
      }
      if (url.pathname === "/api/search" && body.rerank && searchRerankFails) return json({ error: "synthetic reranker load failure" }, 503);
      if (url.pathname === "/api/search") return json({
        mode: body.mode, total: 1, took_ms: 8,
        reranker: body.rerank ? { model: "mock-cross-encoder", revision: "mock-revision", runtime: "mock-runtime", device: "cpu", max_length: 512, elapsed_ms: 4, candidate_count: 1, score_interpretation: "raw uncalibrated diagnostic score, not probability" } : undefined,
        query: { rank_constant: body.rank_constant, candidate_pool: body.candidate_pool, boosts: body.boosts, filters: body.filters, profile_id: body.profile_id },
        hits: [{ _index: "concrete-target-a", _id: "same-id", _score: 0.0345,
          retrieval_scores: { bm25: 12.5, vector: 0.82 }, retrieval_ranks: { bm25: 3, vector: 2, rrf: 1 }, rrf_score: 0.0345,
          reranker: { before_rank: 1, after_rank: 1, score: -1.25, truncated: false },
          _source: { summary: "Synthetic fixture search result" } }],
      });
      return json({});
    });
    await page.goto(base);
    await page.waitForFunction(() => !document.querySelector("#workbench-layout").classList.contains("hidden"));
    await page.locator('[data-tab="search-panel"]').click();
    const require = (condition, message) => { if (!condition) throw new Error(message); };
    await page.waitForFunction(() => document.querySelector("#reranker-status")?.dataset.state === "unavailable");
    require(await page.locator("#candidate-pool").inputValue() === "50", "browser candidate pool default was not 50");
    require(await page.locator("#reranker-prepare").isDisabled(), "model preparation was available before explicit consent");
    await page.locator("#reranker-consent").check();
    require(!(await page.locator("#reranker-prepare").isDisabled()), "consent did not enable preparation");
    await page.locator("#reranker-prepare").click();
    await page.waitForFunction(() => document.querySelector("#reranker-enabled")?.disabled === false);
    const nestedStatus = await page.locator("#reranker-status").innerText();
    require(nestedStatus.includes("mock-1") && nestedStatus.includes("캐시 ready") && nestedStatus.includes("런타임 ready"), `nested readiness fields were not rendered: ${nestedStatus}`);
    const preparation = calls.find(call => call.path === "/api/reranker/prepare");
    require(preparation?.method === "POST" && preparation.body.consent === true, `prepare did not submit explicit consent: ${JSON.stringify(preparation)}`);
    await page.locator("#reranker-enabled").check();
    await page.evaluate(() => {
      state.connected = true;
      state.sharedProfileId = "fixture-profile";
      state.filters = [{ field: "status", value: "Open" }];
      document.querySelector("#search-button").disabled = false;
      document.querySelector("#index-name").value = "fixture-alias";
      document.querySelector("#search-query").value = "mock query";
      document.querySelector("#search-mode").value = "hybrid";
      document.querySelector("#search-size").value = "7";
      document.querySelector("#candidate-pool").value = "23";
      document.querySelector("#rank-constant").value = "35";
    });
    await page.locator("#search-button").click();
    await page.locator(".hit-card").waitFor();
    const search = calls.find(call => call.path === "/api/search");
    require(search?.method === "POST", "search API was not POST");
    require(search.body.mode === "hybrid" && search.body.size === 7 && search.body.candidate_pool === 23 && search.body.rerank === true, `search controls missing: ${JSON.stringify(search.body)}`);
    require(search.body.rank_constant === 35 && search.body.profile_id === "fixture-profile", `RRF/profile settings were dropped: ${JSON.stringify(search.body)}`);
    require(JSON.stringify(search.body.filters).includes("status") && Object.keys(search.body.boosts || {}).length > 0, `filters/boosts were dropped: ${JSON.stringify(search.body)}`);
    const visible = await page.locator(".hit-card").innerText();
    for (const text of ["concrete-target-a", "same-id", "bm25", "#3", "12.5000", "vector", "0.8200", "재순위화", "-1.2500", "확률 아님"]) {
      require(visible.toLowerCase().includes(text.toLowerCase()), `result evidence is missing ${text}: ${visible}`);
    }
    const rerankerSummary = await page.locator("#search-summary").innerText();
    for (const text of ["mock-cross-encoder", "mock-revision", "mock-runtime", "512", "1 candidates", "4 ms", "not probability"]) require(rerankerSummary.toLowerCase().includes(text.toLowerCase()), `top-level reranker evidence is missing ${text}: ${rerankerSummary}`);
    require(visible.includes("잘림 false"), "per-result truncation evidence is missing");
    require((await page.locator(".score-label").innerText()).includes("원점수 진단"), "main result score is not labeled as a raw diagnostic");
    await page.locator("#ui-language").selectOption("en");
    require((await page.locator("label[for=candidate-pool]").innerText()).includes("Candidate pool"), "candidate-pool control did not switch to English");
    require((await page.locator(".hit-card").innerText()).includes("concrete-target-a"), "result evidence disappeared after locale switch");
    searchRerankFails = true;
    await page.locator("#search-button").click();
    await page.locator("#search-results .notice-error").waitFor();
    require((await page.locator("#search-results").innerText()).includes("Reranking request failed"), "reranker request failure was not explicit in English");
    require(await page.locator("#search-mode").inputValue() === "hybrid", "failed reranking silently changed the selected mode");
    const bounds = await page.evaluate(() => {
      document.querySelector("#search-size").value = "50";
      document.querySelector("#search-size").dispatchEvent(new Event("change"));
      return { min: document.querySelector("#candidate-pool").min, value: document.querySelector("#candidate-pool").value };
    });
    require(bounds.min === "50" && Number(bounds.value) >= 50, `candidate pool did not follow top-K: ${JSON.stringify(bounds)}`);
    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    require(mobile.scroll <= mobile.width, `mobile layout overflows: ${JSON.stringify(mobile)}`);
    console.log(JSON.stringify({ ok: true, mockOnly: true, searchBody: search.body, resultEvidence: visible, mobile }));
  } finally {
    await browser?.close();
    if (child.pid && child.exitCode === null && child.signalCode === null) {
      child.kill("SIGTERM");
      await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once("exit", resolve));
    }
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
