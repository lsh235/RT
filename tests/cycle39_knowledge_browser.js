"use strict";

// Cycle 39 browser behavior with every API response mocked in-page. This is UI
// evidence only; backend isolation and FTS behavior are covered separately.
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");

function allocatePort() {
  return new Promise((resolve, reject) => {
    const socket = net.createServer(); socket.once("error", reject);
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
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle39-knowledge-browser-"));
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.PYTHON || "python3", ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(tempDir, "synthetic.sqlite3"), ES_RAG_ACCEPTANCE_ES_URL: "http://127.0.0.1:1" },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer(`${base}/`, child);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CYCLE39_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE39_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE39_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const calls = [], pageErrors = [], consoleErrors = [], requestFailures = [], nonApiRequests = [], responseStatuses = [], previewRequestEvents = [];
    const requestIds = new WeakMap();
    let nextRequestId = 1, pageRouteRegistrations = 0;
    const requestId = request => {
      if (!requestIds.has(request)) requestIds.set(request, `request-${nextRequestId++}`);
      return requestIds.get(request);
    };
    const username = "cycle39-admin";
    const password = "Cycle39-browser-login-secret-001!";
    const csrf = "cycle39-browser-csrf-secret";
    const concept = { id: "cycle39-saved-concept", name: "Cycle 39 <script>concept</script>", description: "saved private expansion", aliases: [], related: [], excluded_terms: [],
      corpus: { index: "local-only", text_fields: ["body"] }, settings: { concept_weight: 1, related_weight: 1 },
      queries: [{ id: "q-train", query: "amber report", split: "train" }, { id: "q-check", query: "independent check", split: "validation" }] };
    const hostile = "<img id=cycle39-injected src=x onerror=alert(1)> private excerpt sentinel";
    let loggedIn = false, failPreview = false, currentRating = null, stale = true;
    const response = () => ({
      concept_id: concept.id, query_id: "q-train", query: "amber <b>report</b>", split: "validation",
      corpus_fingerprint: "a".repeat(64),
      baseline: { total: 1, hits: [{ document_id: "private-doc-1", title: "<script>Private title</script>", source_label: "private source", chunk_id: "chunk-1", excerpt: hostile, score: -0.42, rank: 1, matched_groups: ["saved_query"], judgment: { rating: currentRating, stale } }] },
      expanded: { total: 2, hits: [
        { document_id: "private-doc-1", title: "<script>Private title</script>", source_label: "private source", chunk_id: "chunk-1", excerpt: hostile, score: -0.37, rank: 1, matched_groups: ["saved_query", "concept_expressions"], judgment: { rating: currentRating, stale } },
        { document_id: "private-doc-2", title: "Related only title", source_label: "related source", chunk_id: "chunk-2", excerpt: "related cue text", score: -0.2, rank: 2, matched_groups: ["related_terms"], judgment: { rating: currentRating, stale } },
      ] },
      weight_behavior: { concept_weight: 2.5, concept_expression_count: 3, concept_expressions_included: true, related_weight: 0.75, related_terms_total: 4, related_terms_included: 2, numeric_values_affect_ranking: false },
      metrics: { baseline: { k: 20, ndcg_at_k: 1, judged_coverage: 1, known_positive_recall: 1, judged_count: currentRating == null ? 0 : 1, positive_count: currentRating > 0 ? 1 : 0, unjudged_count: currentRating == null ? 1 : 0, stale_count: stale ? 1 : 0, source_counts: {} }, expanded: {} },
      limits: ["FTS5 only; no Elasticsearch or embeddings.", "Scores are lower-is-better and are not probabilities.", "No automated tuning or generalization claim."],
    });
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("console", message => {
      if (message.type() === "error" && !/Failed to load resource:/.test(message.text())) consoleErrors.push(message.text());
    });
    page.on("request", request => {
      const url = new URL(request.url());
      if (!url.pathname.startsWith("/api/")) nonApiRequests.push(request.url());
      if (url.pathname === "/api/knowledge/concept-preview") previewRequestEvents.push({
        event: "request", wallTime: Date.now(), requestObjectId: requestId(request), url: request.url(), method: request.method(),
        resourceType: request.resourceType(), frameUrl: request.frame()?.url(),
        redirectedFrom: request.redirectedFrom()?.url() || null, redirectedTo: request.redirectedTo()?.url() || null,
      });
    });
    page.on("response", response => responseStatuses.push({ path: new URL(response.url()).pathname, status: response.status() }));
    page.on("requestfailed", request => requestFailures.push({ path: new URL(request.url()).pathname, error: request.failure()?.errorText }));
    await page.addInitScript(() => {
      window.confirm = () => true;
      window.__c39FetchCalls = [];
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = typeof input === "string" ? input : input.url;
        if (url.includes("/api/knowledge/concept-preview")) window.__c39FetchCalls.push({ wallTime: Date.now(), performanceTime: performance.now(), stack: new Error().stack });
        return originalFetch(input, init);
      };
    });
    await page.goto("about:blank");
    pageRouteRegistrations += 1;
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const request = route.request();
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch { /* keep safe empty body */ }
      const call = { path: url.pathname, method: request.method(), body, headers: request.headers(), routeRequestObjectId: requestId(request), routeWallTime: Date.now(), fulfillCount: 0 };
      calls.push(call);
      const json = (payload, status = 200, headers = {}) => {
        call.responseStatus = status;
        call.fulfillCount += 1;
        if (call.fulfillCount > 1) throw new Error(`API route fulfilled more than once: ${call.path}`);
        return route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(payload) });
      };
      if (url.pathname === "/api/auth/session") return json(loggedIn
        ? { configured: true, authenticated: true, user: { id: "mock-admin", username, display_name: "Cycle 39 Admin", role: "admin" }, csrf_token: csrf }
        : { configured: true, authenticated: false, csrf_token: "cycle39-login-csrf" }, 200,
        loggedIn ? {} : { "set-cookie": "es_rag_login_nonce=cycle39-nonce; Path=/; HttpOnly; SameSite=Strict" });
      if (url.pathname === "/api/auth/login") {
        if (body.username !== username || body.password !== password) return json({ error: "Invalid username or password" }, 401);
        loggedIn = true;
        return json({ configured: true, authenticated: true, user: { id: "mock-admin", username, display_name: "Cycle 39 Admin", role: "admin" }, csrf_token: csrf }, 200, { "set-cookie": "es_rag_session=opaque-cycle39-session; Path=/; HttpOnly; SameSite=Strict" });
      }
      if (url.pathname === "/api/auth/logout") { loggedIn = false; return json({ authenticated: false }); }
      if (url.pathname === "/api/health") return json({ ok: true, version: "cycle39-browser-fixture" });
      if (url.pathname === "/api/concepts/list") return json({ concepts: [concept], storage: "sqlite" });
      if (url.pathname === "/api/knowledge/concept-preview") {
        if (failPreview) return json({ error: "Saved query or concept not found" }, 404);
        return json(response());
      }
      if (url.pathname === "/api/knowledge/judge") {
        currentRating = body.rating; stale = false;
        return json({ judgment: { concept_id: body.concept_id, query_id: body.query_id, document_id: body.document_id, rating: body.rating, stale: false, updated_at: "2026-10-18T00:00:00+00:00" } });
      }
      if (url.pathname === "/api/admin/accounts/list") return json({ accounts: [] });
      return json({});
    });

    await page.goto(`${base}/`);
    try {
      await page.locator("#login-form").waitFor({ state: "visible", timeout: 5000 });
    } catch (error) {
      console.error(JSON.stringify({ diagnostic: "login state", url: page.url(), authText: await page.locator("#auth-screen").innerText(), loginClass: await page.locator("#login-form").getAttribute("class"), apiSequence: calls.map(({ path, method, responseStatus }) => ({ path, method, responseStatus })), pageErrors, consoleErrors, requestFailures }));
      throw error;
    }
    await page.locator("#login-username").fill(username);
    await page.locator("#login-password").fill(password);
    await page.getByRole("button", { name: "로그인" }).click();
    await page.locator("#workbench-layout").waitFor({ state: "visible" });
    await page.getByRole("tab", { name: /내 지식/ }).click();
    await page.locator("#knowledge-eval-concept").waitFor({ state: "visible" });
    await page.waitForFunction(id => Array.from(document.querySelector("#knowledge-eval-concept").options).some(option => option.value === id), concept.id);
    await page.locator("#knowledge-eval-concept").selectOption(concept.id);
    await page.locator("#knowledge-eval-query").waitFor({ state: "visible" });
    await page.waitForFunction(() => !document.querySelector("#knowledge-eval-query").disabled);
    await page.locator("#knowledge-eval-query").selectOption("q-train");
    const localFlowStart = calls.length;
    await page.locator("#knowledge-eval-run").click();
    try {
      await page.waitForFunction(() => document.querySelectorAll(".knowledge-eval-hit").length >= 2, null, { timeout: 10000 });
    } catch (error) {
      console.error(JSON.stringify({ diagnostic: "preview result", url: page.url(), statusText: await page.locator("#knowledge-eval-status").innerText(), apiSequence: calls.map(({ path, method, responseStatus }) => ({ path, method, responseStatus })), pageErrors, consoleErrors, requestFailures }));
      throw error;
    }
    if (!(await page.locator(".knowledge-eval-stale").first().innerText()).includes("이전")) throw new Error("stale judgment was not surfaced in the preview");
    if (await page.locator("#knowledge-eval-result img, #knowledge-eval-result script, #knowledge-eval-result b").count()) throw new Error("hostile query/document text created HTML elements");
    if (!(await page.locator("#knowledge-eval-result").innerText()).includes(hostile)) throw new Error("hostile excerpt was not retained as visible literal text");
    if (!(await page.locator("#knowledge-eval-result").innerText()).includes("점수는 작을수록")) throw new Error("BM25 lower-is-better score interpretation is missing");
    const cueCaveat = await page.locator("#knowledge-eval-result").innerText();
    for (const marker of ["대표 청크", "어휘 일치 단서", "순위 점수의 원인을 설명하지 않고", "의미상 관련성의 증거도 아닙니다"]) {
      if (!cueCaveat.includes(marker)) throw new Error(`lexical-only caveat omitted: ${marker}`);
    }
    const firstCard = page.locator(".knowledge-eval-hit").filter({ has: page.locator('.knowledge-eval-rating[data-document-id="private-doc-1"]') });
    const firstLaneChildren = await firstCard.locator(".knowledge-eval-ranks > span").allTextContents();
    if (firstLaneChildren.length !== 4
      || !firstLaneChildren[0].includes("기준 질의")
      || firstLaneChildren[1] !== "저장 질의 표현"
      || !firstLaneChildren[2].includes("확장 질의")
      || firstLaneChildren[3] !== "저장 질의 표현저장 개념 표현") {
      throw new Error(`baseline and expanded match badges were not associated with their own rank rows: ${JSON.stringify(firstLaneChildren)}`);
    }
    const secondCard = page.locator(".knowledge-eval-hit").filter({ has: page.locator('.knowledge-eval-rating[data-document-id="private-doc-2"]') });
    const secondLaneChildren = await secondCard.locator(".knowledge-eval-ranks > span").allTextContents();
    if (secondLaneChildren.length !== 3
      || !secondLaneChildren[0].includes("기준 질의 · 결과에 없음")
      || !secondLaneChildren[1].includes("확장 질의")
      || secondLaneChildren[2] !== "저장 관련 표현") {
      throw new Error(`expanded-only related badge was not isolated to expanded lane: ${JSON.stringify(secondLaneChildren)}`);
    }
    const weightSummary = await page.locator("#knowledge-eval-result").innerText();
    for (const marker of ["2.5", "표현 3개 포함", "0.75", "저장 4개 중 2개 포함", "SQLite", "Elasticsearch", "숫자의 크기는 점수나 순위를 바꾸지 않습니다"]) {
      if (!weightSummary.includes(marker)) throw new Error(`weight behavior summary omitted: ${marker}`);
    }

    const rating = page.locator(".knowledge-eval-rating").first();
    await rating.selectOption("0");
    await page.waitForFunction(() => document.querySelector("#knowledge-eval-status")?.textContent.includes("평가를 저장하고 비교 결과"));
    await page.locator(".knowledge-eval-rating").first().selectOption("3");
    await page.waitForFunction(() => document.querySelector("#knowledge-eval-status")?.textContent === "평가를 저장하고 비교 결과와 지표를 갱신했습니다."
      && document.querySelector(".knowledge-eval-rating")?.value === "3"
      && document.querySelector(".knowledge-eval-save-status")?.textContent === "평가를 저장하고 비교 지표를 갱신했습니다.");
    await page.waitForFunction(() => window.__c39FetchCalls.length === 3);
    if (calls.filter(call => call.path === "/api/knowledge/judge").length !== 2
      || calls.filter(call => call.path === "/api/knowledge/concept-preview").length !== 3
      || calls.filter(call => call.path === "/api/knowledge/concept-preview").some(call => call.responseStatus !== 200)) {
      throw new Error("grade 3 judge and its refresh preview were not fully completed before error-flow baseline");
    }
    if (currentRating !== 3 || stale) throw new Error("grade/regrade did not refresh the visible judgment state");
    const judgmentCalls = calls.filter(call => call.path === "/api/knowledge/judge");
    if (judgmentCalls.length !== 2 || judgmentCalls[0].body.rating !== 0 || judgmentCalls[1].body.rating !== 3) throw new Error("grade 0 and regrade 3 were not sent distinctly");
    if (judgmentCalls.some(call => Object.keys(call.body).sort().join(",") !== "concept_id,document_id,query_id,rating")) throw new Error("judgment request contains client-supplied query text or scope overrides");

    failPreview = true;
    const errorFlowStart = calls.length;
    const fetchTraceStart = await page.evaluate(() => window.__c39FetchCalls.length);
    await page.evaluate(() => {
      window.__c39ErrorClickCount = 0;
      document.querySelector("#knowledge-eval-run").addEventListener("click", () => { window.__c39ErrorClickCount += 1; }, true);
    });
    await page.locator("#knowledge-eval-run").click();
    await page.getByText(/저장 개념, 질의 또는 비교할 문서를 찾지 못했습니다/).waitFor();
    const errorFlow = calls.slice(errorFlowStart);
    const errorPreviewCalls = errorFlow.filter(call => call.path === "/api/knowledge/concept-preview");
    if (errorPreviewCalls.length !== 1) {
      const trace = await page.evaluate(start => ({ clickCount: window.__c39ErrorClickCount, fetchCalls: window.__c39FetchCalls.slice(start) }), fetchTraceStart);
      throw new Error(`one error-button click should send one preview request; delta=${JSON.stringify(errorFlow.map(({ path, method, responseStatus, routeRequestObjectId, routeWallTime, fulfillCount }) => ({ path, method, responseStatus, routeRequestObjectId, routeWallTime, fulfillCount })))} previewRequestEvents=${JSON.stringify(previewRequestEvents.slice(-4))} trace=${JSON.stringify(trace)} pageRouteRegistrations=${pageRouteRegistrations}`);
    }
    if (await page.locator(".knowledge-eval-hit").count()) throw new Error("old result remained visible after a preview error");
    const storage = await page.evaluate(() => Object.fromEntries(Array.from({ length: localStorage.length }, (_, index) => {
      const key = localStorage.key(index); return [key, localStorage.getItem(key)];
    })));
    const storageText = JSON.stringify(storage);
    for (const marker of [password, csrf, "opaque-cycle39-session", hostile, "Private title", "private source"]) {
      if (storageText.includes(marker)) throw new Error(`private/auth value appeared in localStorage: ${marker}`);
    }
    const knowledgeCalls = calls.filter(call => call.path.startsWith("/api/knowledge/"));
    if (knowledgeCalls.some(call => call.method === "POST" && call.headers["x-csrf-token"] !== csrf)) throw new Error("knowledge API call omitted the authenticated CSRF token");
    const previews = calls.filter(call => call.path === "/api/knowledge/concept-preview");
    if (previews.some(call => Object.keys(call.body).sort().join(",") !== "concept_id,query_id")) throw new Error("preview request sent a client query or other overrides");
    const localFlowCalls = calls.slice(localFlowStart);
    if (localFlowCalls.some(call => /\/api\/(?:concepts\/(?:preview|tune)|ai\/(?:sessions|jobs)\/)/.test(call.path))) throw new Error("explicit local knowledge flow called Elasticsearch concept or AI session/job routes");
    if (localFlowCalls.some(call => /\/api\/(?:embeddings?|ai\/jobs\/|concepts\/tune)/i.test(call.path))) throw new Error("explicit local knowledge flow called embedding, AI, or tune routes");
    const unexpectedHttpErrors = responseStatuses.filter(({ path, status }) => status >= 400 && !(
      status === 404 && (path === "/api/knowledge/concept-preview" || path === "/favicon.ico")
    ));
    if (unexpectedHttpErrors.length) throw new Error(`unexpected HTTP response errors: ${JSON.stringify(unexpectedHttpErrors)}`);
    if (pageErrors.length || consoleErrors.length || requestFailures.length) throw new Error(`browser errors page=${JSON.stringify(pageErrors)} console=${JSON.stringify(consoleErrors)} requests=${JSON.stringify(requestFailures)}`);
    if (nonApiRequests.some(url => /:9200\b|elasticsearch|openai|embedding/i.test(url))) throw new Error(`provider request observed: ${nonApiRequests.join(", ")}`);
    const allFulfilledOnce = calls.every(call => call.fulfillCount === 1);
    if (!allFulfilledOnce || pageRouteRegistrations !== 1) throw new Error(`mock route integrity failed: fulfilledOnce=${allFulfilledOnce} registrations=${pageRouteRegistrations}`);
    const fetchTrace = await page.evaluate(() => window.__c39FetchCalls);
    console.log(JSON.stringify({ result: "PASS", evidence: "mocked API browser flow; static UI served by isolated loopback workbench", apiCalls: calls.length, apiSequence: calls.map(({ path, method, responseStatus, routeRequestObjectId, routeWallTime, fulfillCount }) => ({ path, method, responseStatus, routeRequestObjectId, routeWallTime, fulfillCount })), previewRequestEvents, fetchTrace, pageRouteRegistrations, allFulfilledOnce, httpErrorResponses: responseStatuses.filter(({ status }) => status >= 400), knowledgeCalls: knowledgeCalls.length, workflow: ["login", "select saved concept/query", "preview", "grade 0", "regrade 3", "stale state", "preview error"], htmlTextRendering: "PASS", localStorage: "no private document or auth markers", externalProviderRequests: "none observed" }));
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null) child.kill("SIGTERM");
    if (child.exitCode === null) await new Promise(resolve => child.once("exit", resolve));
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error.stack || String(error)); process.exitCode = 1; });
