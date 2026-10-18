"use strict";

// Deterministic UI smoke for Cycle 42 controls. All API responses are local mocks.
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
    try { if ((await fetch(url)).ok) return; } catch { /* wait for listener */ }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("workbench did not become ready");
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle42-private-browser-"));
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
      ...(process.env.CYCLE42_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE42_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE42_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const calls = [];
    const pageErrors = [];
    const username = "cycle42-browser";
    const password = "Cycle42-browser-password-001!";
    const csrf = "cycle42-browser-csrf";
    let authenticated = false;
    let syncAttempts = 0;
    let syncState = "not_synced";
    let privateSearchState = "stale";
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.addInitScript(() => { window.confirm = () => true; });
    await page.goto("about:blank");
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const request = route.request();
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch { /* empty body */ }
      calls.push({ path: url.pathname, method: request.method(), body });
      const json = (payload, status = 200, headers = {}) => route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(payload) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated, ...(authenticated ? { user: { id: "cycle42-owner", username, display_name: "Cycle 42", role: "admin" }, csrf_token: csrf } : { csrf_token: "login-csrf" }) });
      if (url.pathname === "/api/auth/login") {
        if (body.username !== username || body.password !== password) return json({ error: "Invalid username or password" }, 401);
        authenticated = true;
        return json({ configured: true, authenticated: true, user: { id: "cycle42-owner", username, display_name: "Cycle 42", role: "admin" }, csrf_token: csrf });
      }
      if (url.pathname === "/api/auth/logout") { authenticated = false; return json({ authenticated: false }); }
      if (url.pathname === "/api/health") return json({ ok: true, version: "cycle42-ui-fixture" });
      if (url.pathname === "/api/knowledge/es-status") return json({ state: syncState, local_documents: syncState === "not_synced" ? 0 : 1, local_chunks: syncState === "not_synced" ? 0 : 1, indexed_chunks: syncState === "in_sync" ? 1 : 0, last_synced_at: syncState === "in_sync" ? "2026-10-18T00:00:00+00:00" : null, error: syncState === "error" ? "fixture sync failed; retry available" : "" });
      if (url.pathname === "/api/knowledge/es-sync") {
        syncAttempts += 1;
        if (syncAttempts === 1) { syncState = "error"; return json({ error: "fixture sync failed; retry available" }, 503); }
        syncState = "in_sync";
        privateSearchState = "in_sync";
        return json({ state: "in_sync", indexed_chunks: 1, last_synced_at: "2026-10-18T00:00:00+00:00" });
      }
      if (url.pathname === "/api/knowledge/list") return json({ documents: [] });
      if (url.pathname === "/api/connect") return json({
        cluster_name: "cycle42-mock", version: "mock", indices: [{ index: "jira-grpc-issues" }],
        selected_index: "jira-grpc-issues", selected_index_exists: true, selected_index_count: 1,
        sample_expected_count: 0, sample_data_metadata_count: 0,
        embedding: { mapping_available: true, mapping_dimensions: 1024, vector_count: 1, document_count: 1, runtime_installed: true, model_cached: true, model_name: "fixture" },
      });
      if (url.pathname === "/api/search") {
        const mode = body.mode || "bm25";
        const privateOnly = body.query === "private-only";
        const emptyLibrary = syncState === "not_synced";
        return json({ mode, total: 1, took_ms: 1, query: { rank_constant: 60 },
          hits: privateOnly ? [] : [{ _id: "shared-1", _index: "jira-grpc-issues", _score: 99, _source: { issue_key: "GRPC-42", summary: "Shared fixture result", description: "Shared lane evidence", issue_type: "Bug", status: "Open" } }],
          private_knowledge: mode === "bm25"
            ? emptyLibrary
              ? { state: "not_synced", local_chunks: 0, results: [] }
              : privateSearchState === "in_sync"
              ? { state: "in_sync", results: [{ _id: "private-1", _score: 0.001, _source: { title: "Private fixture result", source_label: "manual", rag_chunk_text: "Private lane evidence", ordinal: 0 } }] }
              : { state: privateSearchState, message: "Private results withheld; synchronize or retry.", results: [] }
            : { state: "not_indexed", mode, message: "Private vectors are not indexed; explicit vector sync is required.", results: [] },
        });
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
    await page.getByText("아직 비공개 문서가 없습니다").waitFor();
    if ((await page.locator("#knowledge-es-status").innerText()).includes("동기화 필요")) throw new Error("empty local library was incorrectly shown as requiring sync");
    await page.getByRole("tab", { name: /검색 실험/ }).click();
    await page.locator("#connect-button").click();
    await page.getByText("연결됨").waitFor();
    await page.locator("#search-query").fill("empty-library");
    await page.locator("#search-button").click();
    await page.getByText("아직 비공개 문서가 없습니다. 내 지식 화면에서 문서를 추가하세요.").waitFor();
    if (await page.locator("#search-results .notice").count()) throw new Error("empty local library was shown as withheld/stale");
    await page.getByRole("tab", { name: /내 지식/ }).click();
    await page.locator("#knowledge-es-sync").click();
    try { await page.getByText(/fixture sync failed/).waitFor({ timeout: 5000 }); }
    catch { throw new Error(`sync failure text missing: ${await page.locator("#knowledge-es-status").innerText()}; calls=${JSON.stringify(calls)}`); }
    if (await page.locator("#knowledge-es-sync").isDisabled()) throw new Error("sync retry control remained disabled after a failed request");
    await page.locator("#knowledge-es-sync").click();
    await page.getByText(/동기화 완료/).waitFor();
    if (syncAttempts !== 2) throw new Error(`expected retry to issue two sync requests; saw ${syncAttempts}`);

    await page.getByRole("tab", { name: /검색 실험/ }).click();
    await page.locator("#search-query").fill("fixture query");
    privateSearchState = "stale";
    await page.locator("#search-button").click();
    try { await page.locator("#search-results .notice").filter({ hasText: "결과를 숨겼습니다" }).waitFor({ timeout: 5000 }); }
    catch { throw new Error(`stale private lane notice missing: ${await page.locator("#search-results").innerText()}; calls=${JSON.stringify(calls)}`); }
    if (await page.locator(".hit-card").filter({ hasText: "Private fixture result" }).count()) throw new Error("stale private result was rendered");
    privateSearchState = "in_sync";
    await page.locator("#search-button").click();
    await page.getByText("선택한 공유 인덱스").waitFor();
    await page.getByText("내 비공개 지식 · BM25").waitFor();
    await page.getByText("Shared fixture result").waitFor();
    await page.getByText("Private fixture result").waitFor();
    await page.locator("#search-results .helper-text").filter({ hasText: "별도 계정 비공개 lane" }).waitFor();

    await page.locator("#search-query").fill("private-only");
    await page.locator("#search-button").click();
    await page.getByText("선택한 공유 Elasticsearch 인덱스에서 결과가 없습니다.").waitFor();
    await page.getByText("Private fixture result").waitFor();
    if (!(await page.locator(".evidence-section").count())) throw new Error("separate Shared/My private knowledge sections are missing");
    await page.locator("#search-query").fill("fixture query");

    for (const mode of ["vector", "hybrid"]) {
      await page.locator("#search-mode").selectOption(mode);
      await page.locator("#search-button").click();
      try { await page.getByText(/결과를 숨겼습니다/).waitFor({ timeout: 5000 }); }
      catch { throw new Error(`${mode} not-indexed private status missing: ${await page.locator("#search-results").innerText()}; readiness=${await page.locator("#search-mode-readiness").innerText()}; calls=${JSON.stringify(calls.slice(-3))}`); }
      if (await page.locator(".hit-card").filter({ hasText: "Private fixture result" }).count()) throw new Error(`${mode} mode displayed private BM25 hits`);
      await page.getByText("Shared fixture result").waitFor();
    }
    if (pageErrors.length) throw new Error(`browser page errors: ${pageErrors.join(" | ")}`);
    const required = ["/api/knowledge/es-status", "/api/knowledge/es-sync", "/api/connect", "/api/search"];
    for (const path of required) if (!calls.some(call => call.path === path)) throw new Error(`missing API call: ${path}`);
    console.log(JSON.stringify({ result: "PASS", evidence: "mocked API UI smoke; static UI served by isolated loopback workbench", syncAttempts, searchModes: ["bm25", "vector", "hybrid"], separateLanes: true, privateVectorHybrid: "not-indexed state shown; no private hits rendered", externalProviderRequests: "none observed" }));
  } finally {
    if (browser) await browser.close();
    child.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
