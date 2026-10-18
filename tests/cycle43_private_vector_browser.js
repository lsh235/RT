"use strict";

// Mocked API smoke for explicit private vector consent and lane labels.
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
    try { if ((await fetch(url)).ok) return; } catch { /* wait for local listener */ }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("workbench did not become ready");
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle43-private-browser-"));
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.PYTHON || "python3", ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(tempDir, "browser.sqlite3"), ES_RAG_ACCEPTANCE_ES_URL: "http://127.0.0.1:1" },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer(`${base}/`, child);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CYCLE43_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE43_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE43_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const calls = [];
    const errors = [];
    let authenticated = false;
    let vectorSyncs = 0;
    let vectorState = "not_indexed";
    let sharedAvailable = false;
    const username = "cycle43-browser";
    const password = "Cycle43-browser-password-001!";
    const csrf = "cycle43-browser-csrf";
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("about:blank");
    await page.addInitScript(() => { window.confirm = () => false; });
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const request = route.request();
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch { /* empty body */ }
      calls.push({ path: url.pathname, method: request.method(), body });
      const json = (payload, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated,
        ...(authenticated ? { user: { id: "cycle43-owner", username, display_name: "Cycle 43", role: "admin" }, csrf_token: csrf } : { csrf_token: "login-csrf" }) });
      if (url.pathname === "/api/auth/login") {
        if (body.username !== username || body.password !== password) return json({ error: "Invalid username or password" }, 401);
        authenticated = true;
        return json({ configured: true, authenticated: true, user: { id: "cycle43-owner", username, display_name: "Cycle 43", role: "admin" }, csrf_token: csrf });
      }
      if (url.pathname === "/api/auth/logout") { authenticated = false; return json({ authenticated: false }); }
      if (url.pathname === "/api/health") return json({ ok: true, version: "cycle43-ui-fixture" });
      if (url.pathname === "/api/knowledge/es-status") return json({ state: "in_sync", vector_state: vectorState,
        vector_chunks: vectorState === "in_sync" ? 2 : 0, local_documents: 1, local_chunks: 1, indexed_chunks: 1, error: "",
        tokenizer: { tokenizers_installed: true, cached: true, huggingface_hub_installed: true } });
      if (url.pathname === "/api/token-preview/status") return json({ tokenizers_installed: true, cached: true, huggingface_hub_installed: true });
      if (url.pathname === "/api/knowledge/es-sync") return json({ state: "in_sync", indexed_chunks: 1 });
      if (url.pathname === "/api/knowledge/es-vector-sync") {
        vectorSyncs += 1;
        if (body.allow_model_download === true) {
          vectorState = "in_sync";
          return json({ state: "in_sync", vector_state: "in_sync", vector_chunks: 2 });
        }
        return json({ error: "explicit model download consent required" }, 400);
      }
      if (url.pathname === "/api/knowledge/list") return json({ documents: [{ document_id: "doc", title: "Fixture", content_bytes: 10 }] });
      if (url.pathname === "/api/connect") return json({ cluster_name: "cycle43-mock", version: "mock", indices: [{ index: "shared-fixture" }],
        selected_index: "shared-fixture", selected_index_exists: true, selected_index_count: 1,
        sample_expected_count: 0, sample_data_metadata_count: 0,
        embedding: { mapping_available: sharedAvailable, mapping_dimensions: sharedAvailable ? 1024 : 0, vector_count: sharedAvailable ? 1 : 0, document_count: 1, runtime_installed: sharedAvailable, model_cached: sharedAvailable, model_name: "fixture" } });
      if (url.pathname === "/api/search") {
        const mode = body.mode || "bm25";
        const labels = { bm25: "Private BM25 fixture", vector: "Private E5 fixture", hybrid: "Private RRF fixture" };
        const sharedVector = mode === "vector" || mode === "hybrid";
        return json({ mode, total: sharedVector ? 0 : 1, took_ms: 1, query: { rank_constant: 60 },
          hits: sharedVector ? [] : [{ _id: "shared-bm25", _index: "shared-fixture", _score: 9, _source: { summary: "Shared fixture result" } }],
          ...(sharedVector ? { shared_search: { state: sharedAvailable ? "available" : "unavailable", message: "Fixture shared vector unavailable; private lane continued." } } : {}),
          private_knowledge: { state: "in_sync", mode, results: [{ _id: `private-${mode}`, _index: "private-fixture", _score: 0.1,
            _source: { title: labels[mode], source_label: "manual", rag_chunk_text: "Private lane evidence", ordinal: 0 } }] } });
      }
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/concepts/list") return json({ concepts: [] });
      return json({});
    });

    await page.goto(`${base}/`);
    await page.locator("#login-username").fill(username);
    await page.locator("#login-password").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();
    await page.locator("#workbench-layout").waitFor({ state: "visible" });
    await page.getByRole("tab", { name: /내 지식/ }).click();
    await page.getByText(/벡터 미색인 · BM25만 검색 가능/).waitFor();
    await page.locator("#knowledge-es-vector-sync").click();
    await page.waitForTimeout(250);
    if (vectorSyncs !== 0) throw new Error("vector sync proceeded without explicit user confirmation");
    if (!calls.some(call => call.path === "/api/token-preview/status")) throw new Error("vector flow did not inspect tokenizer requirements");
    await page.evaluate(() => { window.confirm = () => true; });
    await page.locator("#knowledge-es-vector-sync").click();
    try { await page.getByText(/벡터 동기화 완료|벡터 준비 완료/).waitFor({ timeout: 8000 }); }
    catch { throw new Error(`vector sync status missing: ${await page.locator("#knowledge-es-status").innerText()}; calls=${JSON.stringify(calls.slice(-5))}`); }
    const vectorCall = calls.find(call => call.path === "/api/knowledge/es-vector-sync");
    if (!vectorCall || vectorCall.body.allow_model_download !== true) throw new Error(`consented vector request missing explicit flag: ${JSON.stringify(vectorCall)}`);

    await page.getByRole("tab", { name: /검색 실험/ }).click();
    await page.locator("#index-name").fill("shared-fixture");
    await page.locator("#connect-button").click();
    await page.getByText("연결됨").waitFor();
    await page.locator("#search-query").fill("fixture query");
    for (const [mode, label] of [["bm25", "내 비공개 지식 · BM25"], ["vector", "내 비공개 지식 · E5 vector"], ["hybrid", "내 비공개 지식 · RRF hybrid"]]) {
      await page.locator("#search-mode").selectOption(mode);
      await page.locator("#search-button").click();
      await page.getByText(label).waitFor();
      if (mode === "bm25") {
        await page.getByText("Shared fixture result").waitFor();
        await page.getByText("Private BM25 fixture").waitFor();
        continue;
      }
      await page.getByText("Fixture shared vector unavailable; private lane continued.").waitFor();
      await page.getByText(labelsForMode(mode)).waitFor();
      if (await page.getByText("선택한 공유 Elasticsearch 인덱스에서 결과가 없습니다.").count()) throw new Error("unavailable shared lane was mislabeled as a successful empty search");
    }
    sharedAvailable = true;
    await page.locator("#search-mode").selectOption("vector");
    await page.locator("#search-button").click();
    await page.getByText("선택한 공유 Elasticsearch 인덱스에서 결과가 없습니다.").waitFor();
    if (await page.locator("#search-results .notice").filter({ hasText: "Fixture shared vector unavailable" }).count()) throw new Error("successful empty shared search was mislabeled unavailable");
    sharedAvailable = false;
    await page.locator("#search-mode").selectOption("code_rag");
    const readiness = page.locator("#search-mode-readiness");
    await readiness.waitFor({ state: "visible" });
    if (!(await readiness.innerText()).includes("저장 벡터가 없어")) throw new Error(`code_rag readiness gate missing: ${await readiness.innerText()}`);
    const codeCallsBefore = calls.filter(call => call.path === "/api/code-rag").length;
    await page.locator("#search-button").click();
    await page.waitForTimeout(250);
    if (calls.filter(call => call.path === "/api/code-rag").length !== codeCallsBefore) throw new Error("code_rag bypassed the shared vector readiness gate");
    if (errors.length) throw new Error(`browser page errors: ${errors.join(" | ")}`);
    console.log(JSON.stringify({ result: "PASS", evidence: "mocked API browser flow on isolated local workbench", consentRequired: true,
      explicitDownloadFlag: vectorCall.body.allow_model_download, statuses: ["vector not indexed", "vector sync complete"],
      privateModes: ["bm25", "vector", "hybrid"], sharedPrivateLanes: "separate", externalProviderRequests: "none observed" }));
  } finally {
    if (browser) await browser.close();
    child.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

function labelsForMode(mode) {
  return { bm25: "Private BM25 fixture", vector: "Private E5 fixture", hybrid: "Private RRF fixture" }[mode];
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
