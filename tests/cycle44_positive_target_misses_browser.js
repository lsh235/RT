"use strict";

// Deterministic browser acceptance for saved-tune positive-target misses.
// Every API call is fulfilled locally; no Elasticsearch or provider traffic is used.
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
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle44-positive-misses-"));
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.PYTHON || "python3", ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(tempDir, "browser.sqlite3"), ES_RAG_ACCEPTANCE_ES_URL: "http://127.0.0.1:1" },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer(`${base}/api/health`, child);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CYCLE44_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE44_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE44_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const calls = [];
    const consoleErrors = [];
    const pageErrors = [];
    const requestFailures = [];
    const json = (payload, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(payload) });
    let activeTune = null;
    let holdConnectResponse = false;
    let releaseConnectResponse = null;
    let holdTuneResponse = false;
    let releaseTuneResponse = null;
    const hostileQueryId = 'train-q-<img src=x onerror="window.__cycle44Injected=true">';
    const hostileDocumentId = 'doc-<svg onload="window.__cycle44Injected=true">-hostile';
    const baseJudgments = [
      { query_id: "train-q", document_index: "idx-A", document_id: "train-miss", rating: 3, stale: false },
      { query_id: "train-q", document_index: "idx-A", document_id: "train-boundary", rating: 2, stale: false },
      { query_id: "train-q", document_index: "idx-A", document_id: "cross-query", rating: 1, stale: false },
      { query_id: "train-q", document_index: "idx-B", document_id: "same-id", rating: 1, stale: false },
      { query_id: "train-q", document_index: "idx-C", document_id: "same-id", rating: 1, stale: false },
      { query_id: "train-q", document_index: "idx-X", document_id: "zero-rating", rating: 0, stale: false },
      { query_id: "train-q", document_index: "idx-X", document_id: "null-rating", rating: null, stale: false },
      { query_id: "train-q", document_index: "idx-X", document_id: "invalid-rating", rating: 4, stale: false },
      { query_id: hostileQueryId, document_index: "idx-hostile", document_id: hostileDocumentId, rating: 3, stale: false },
      { query_id: "val-q", document_index: "idx-A", document_id: "cross-query", rating: 3, stale: false },
      { query_id: "val-q", document_index: "idx-V", document_id: "validation-miss", rating: 1, stale: false },
      { query_id: "val-q", document_index: "idx-V", document_id: "validation-present", rating: 3, stale: false },
    ];
    const row = (index, id, rank) => ({ index, id, rank });
    const normalResponse = () => ({
      status: "complete",
      settings: { mode: "bm25", size: 2 },
      input_snapshot: { concept: null, judgments: baseJudgments },
      output_snapshot: {
        train: {
          baseline: {
            "train-q": [row("idx-A", "train-miss", 2), row("idx-A", "train-boundary", 5), row("idx-A", "cross-query", 1), row("idx-B", "same-id", 3), row("idx-C", "same-id", 4)],
            [hostileQueryId]: [row("idx-hostile", hostileDocumentId, 6)],
          },
          tuned: {
            "train-q": [row("idx-A", "train-boundary", 2), row("idx-A", "train-miss", 3), row("idx-A", "cross-query", 3), row("idx-B", "same-id", 4), row("idx-C", "same-id", 5)],
            [hostileQueryId]: [],
          },
        },
        validation: {
          baseline: { "val-q": [row("idx-A", "cross-query", 1), row("idx-V", "validation-miss", 2)] },
          tuned: { "val-q": [row("idx-V", "validation-present", 2), row("idx-V", "validation-miss", 3), row("idx-A", "cross-query", 3)] },
        },
      },
      baseline: { queries: [] }, tuned: { queries: [] }, validation: { baseline: {}, tuned: {} },
    });

    page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("pageerror", error => pageErrors.push(String(error)));
    page.on("requestfailed", request => requestFailures.push({ url: request.url(), error: request.failure()?.errorText }));
    await page.goto("about:blank");
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) {
        requestFailures.push({ url: url.href, error: "fixture blocks non-workbench network traffic" });
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const request = route.request();
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch { /* empty body */ }
      calls.push({ path: url.pathname, method: request.method(), body });
      if (url.pathname === "/api/auth/session") return route.fulfill(json({ configured: true, authenticated: true, user: { id: "cycle44-user", username: "cycle44-fixture", display_name: "Cycle 44", role: "user" }, csrf_token: "cycle44-csrf" }));
      if (url.pathname === "/api/health") return route.fulfill(json({ version: "cycle44-fixture" }));
      if (url.pathname === "/api/codebase-status" || url.pathname === "/api/ai/status") return route.fulfill(json({}));
      if (url.pathname === "/api/concepts/list") return route.fulfill(json({ concepts: [{ id: "cycle44-concept", name: "Cycle 44 fixture" }] }));
      if (url.pathname === "/api/concepts/runs") return route.fulfill(json({ runs: [] }));
      if (url.pathname === "/api/connect") {
        if (holdConnectResponse) await new Promise(resolve => { releaseConnectResponse = resolve; });
        return route.fulfill(json({ cluster_name: "synthetic", version: "mock", selected_index: "cycle44-index", selected_index_exists: true, selected_index_count: 1, indices: [{ index: "cycle44-index", docs_count: 1 }] }));
      }
      if (url.pathname === "/api/corpus/schema") return route.fulfill(json({ index: "cycle44-index", fields: [{ name: "body", type: "text", searchable: true, filterable: false, nested: false }] }));
      if (url.pathname === "/api/concepts/tune") {
        if (holdTuneResponse) await new Promise(resolve => { releaseTuneResponse = resolve; });
        return route.fulfill(json(activeTune || normalResponse()));
      }
      return route.fulfill(json({}));
    });
    await page.goto(`${base}/`);
    try {
      await page.waitForFunction(() => document.querySelector("#server-version")?.textContent.trim() === "vcycle44-fixture", { timeout: 8000 });
    } catch {
      throw new Error(`workbench health UI did not settle: version=${await page.locator("#server-version").textContent()}; api=${JSON.stringify(calls)}; pageErrors=${JSON.stringify(pageErrors)}; requestFailures=${JSON.stringify(requestFailures)}`);
    }
    const concept = {
      id: "cycle44-concept", name: "Cycle 44 fixture", description: "synthetic", aliases: [], related: [], excluded_terms: [],
      corpus: { index: "cycle44-index", title_field: "", text_fields: ["body"], filter_fields: [] }, filters: [],
      settings: { mode: "bm25", size: 2, candidate_size: 20 },
      queries: [
        { id: "train-q", query: "saved train query", split: "train" },
        { id: "train-empty-q", query: "saved train query without judgments", split: "train" },
        { id: hostileQueryId, query: "hostile display query", split: "train" },
        { id: "val-q", query: "saved validation query", split: "validation" },
      ],
    };
    await page.evaluate(conceptValue => {
      state.connected = true;
      state.connectedIndex = "cycle44-index";
      state.connectedIndexExists = true;
      state.schema = [{ name: "body", type: "text", searchable: true, filterable: false, nested: false }];
      populateConcept(conceptValue);
      state.conceptId = conceptValue.id;
      state.savedConceptSnapshot = JSON.stringify(collectConcept());
      const saved = document.querySelector("#saved-concepts");
      saved.replaceChildren(new Option("Cycle 44 fixture", conceptValue.id));
      saved.value = conceptValue.id;
      const querySelect = document.querySelector("#concept-query-select");
      if (querySelect) querySelect.value = "train-q";
      const manualQuery = document.querySelector("#manual-query-id");
      if (manualQuery) {
        manualQuery.replaceChildren(...conceptValue.queries.map(query => {
          const option = document.createElement("option"); option.value = query.id; option.textContent = query.query;
          option.dataset.queryId = query.id; return option;
        }));
      }
      updateManualDocumentActions();
    }, concept);
    const setTune = async response => {
      response.input_snapshot.concept = await page.evaluate(() => collectConcept());
      activeTune = response;
    };
    const runTune = async response => {
      await setTune(response);
      await page.locator("#concept-tune").click();
      await page.waitForFunction(() => document.querySelector("#tune-positive-target-misses"));
      return page.locator("#tune-positive-target-misses");
    };
    const require = (ok, message) => { if (!ok) throw new Error(message); };

    const beforeTuneCalls = calls.filter(call => call.path === "/api/concepts/tune").length;
    const region = await runTune(normalResponse());
    require(calls.filter(call => call.path === "/api/concepts/tune").length === beforeTuneCalls + 1, "expected one explicitly requested synthetic tune call");
    const lanes = region.locator(".tune-misses-lane");
    require(await lanes.count() === 2, "expected separate train and validation lanes");
    const trainLane = lanes.nth(0);
    const validationLane = lanes.nth(1);
    const trainText = await trainLane.innerText();
    const validationText = await validationLane.innerText();
    require(/학습|train/i.test(trainText) && /검증|validation/i.test(validationText), "lane labels do not identify train and validation");
    require(/별도|사용되지|not used to tune|separate/i.test(await region.innerText()), "validation is not described as a separate check");
    require(trainText.includes("train-miss") && !trainText.includes("validation-miss"), "train lane did not isolate its own saved query misses");
    require(!trainText.includes("train-empty-q") && !/학습용 스냅샷이 없거나|판단 대상 질의의 기본 또는 조정 순위 스냅샷이 없어/i.test(trainText), "saved train query without judgments made the train lane inconclusive or appeared as a miss");
    require(validationText.includes("validation-miss") && !validationText.includes("train-miss"), "validation lane did not isolate its own saved query misses");
    require(trainText.includes("cross-query") && validationText.includes("cross-query"), "same document identity under distinct queries was incorrectly merged or omitted");
    require(trainText.includes("인덱스 idx-B · 문서 same-id") && trainText.includes("인덱스 idx-C · 문서 same-id"), `document ID was not kept distinct by index identity: ${trainText}`);
    require(!trainText.includes("zero-rating") && !trainText.includes("null-rating") && !trainText.includes("invalid-rating"), "zero, null, or invalid ratings were included as positive targets");
    require(!trainText.includes("train-boundary"), "a tuned result at rank K was incorrectly counted as a miss");
    require(trainText.includes("기본 순위 2") || /기본 순위\s*2/.test(trainText), "baseline rank context is missing for train-miss");
    require(trainText.includes(hostileDocumentId) && trainText.includes(hostileQueryId), "hostile fixture strings were not rendered as literal text");
    require(await region.locator("img,script,svg").count() === 0, "hostile target strings created injected HTML");
    require(!(await page.evaluate(() => Boolean(window.__cycle44Injected))), "hostile target string executed script");

    const missRows = region.locator('[data-testid="positive-target-miss"]');
    const missCount = await missRows.count();
    require(missCount === 7, `expected 7 misses after rating, identity and K-boundary filtering; got ${missCount}`);
    const trainMiss = trainLane.locator('[data-testid="positive-target-miss"]').filter({ hasText: "train-miss" }).first();
    require(/3점|rating\s*3|grade\s*3/i.test(await trainMiss.innerText()), "displayed target does not show its numeric positive grade");
    const handoff = trainMiss.locator('[data-testid="positive-target-handoff"]');
    require(await handoff.count() === 1 && !(await handoff.isDisabled()), "in-scope exact-document handoff is missing or disabled");
    const beforeHandoffCalls = calls.length;
    await handoff.click();
    require(await page.locator("#manual-document-id").inputValue() === "train-miss", "handoff did not fill exact document ID");
    require(await page.locator("#manual-query-id").inputValue() === "train-q", "handoff did not select exact saved query ID");
    require(await page.evaluate(() => state.manualDocumentIndex) === "idx-A", "handoff did not retain exact document index");
    require(calls.length === beforeHandoffCalls, "handoff automatically called an API instead of waiting for explicit diagnosis");
    require(calls.filter(call => /diagnos|document.*lookup/i.test(call.path)).length === 0, "handoff auto-ran document diagnosis");
    require(!(await page.locator("#diagnose-manual-document").isDisabled()), "explicit diagnosis control did not become available after handoff");

    const indexName = page.locator("#index-name");
    const originalIndexName = await indexName.inputValue();
    await indexName.fill("cycle44-changed-index");
    require(await handoff.isDisabled(), "handoff remained enabled after the selected index name changed");
    await indexName.fill(originalIndexName);
    require(!(await handoff.isDisabled()), "handoff did not return to its valid scope after restoring the selected index");

    await page.evaluate(() => {
      const field = document.querySelector(".saved-query-text");
      field.value += " edited";
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    require(await handoff.isDisabled(), "handoff remained enabled after the saved concept scope changed");

    // Connection origin changes invalidate the old result even if the URL text is restored.
    const urlRegion = await runTune(normalResponse());
    const urlHandoff = urlRegion.locator('[data-testid="positive-target-miss"]').filter({ hasText: "train-miss" }).first().locator('[data-testid="positive-target-handoff"]');
    const esUrl = page.locator("#es-url");
    const originalEsUrl = await esUrl.inputValue();
    await esUrl.fill("http://cycle44-changed-origin.invalid:9200");
    require(await urlHandoff.isDisabled(), "handoff remained enabled after Elasticsearch URL input/change");
    await esUrl.fill(originalEsUrl);
    require(await urlHandoff.isDisabled(), "restoring the Elasticsearch URL re-enabled the old report handoff");
    await page.evaluate(() => {
      state.connectedIndex = "cycle44-index";
      state.connectedIndexExists = true;
      setConnected(true);
    });
    require(await urlHandoff.isDisabled(), "reconnecting re-enabled a handoff from the prior connection generation");

    // A new report is valid, but applying different tune settings invalidates it immediately.
    const settingsRegion = await runTune(normalResponse());
    const settingsHandoff = settingsRegion.locator('[data-testid="positive-target-miss"]').filter({ hasText: "train-miss" }).first().locator('[data-testid="positive-target-handoff"]');
    require(!(await settingsHandoff.isDisabled()), "fresh report handoff was not enabled before applying settings");
    await page.evaluate(() => applyTunedSettings({ size: 3 }));
    require(await settingsHandoff.isDisabled(), "applyTunedSettings did not immediately disable the old report handoff");

    // A same-values connect/refresh attempt advances connection scope and invalidates the old report.
    const connectRegion = await runTune(normalResponse());
    const connectHandoff = connectRegion.locator('[data-testid="positive-target-miss"]').filter({ hasText: "train-miss" }).first().locator('[data-testid="positive-target-handoff"]');
    require(!(await connectHandoff.isDisabled()), "fresh report handoff was not enabled before connect/refresh");
    const unchangedUrl = await page.locator("#es-url").inputValue();
    const unchangedIndex = await page.locator("#index-name").inputValue();
    const connectionGeneration = await page.evaluate(() => state.connectionGeneration);
    holdConnectResponse = true;
    const connectRequest = page.waitForRequest(request => new URL(request.url()).pathname === "/api/connect");
    await page.locator("#connect-button").click();
    await connectRequest;
    await page.waitForFunction(generation => state.connectionGeneration > generation, connectionGeneration);
    require(await page.locator("#es-url").inputValue() === unchangedUrl && await page.locator("#index-name").inputValue() === unchangedIndex, "connect/refresh fixture unexpectedly changed URL or index form values");
    require(await connectHandoff.isDisabled(), "connect/refresh attempt with unchanged form values left the old handoff enabled");

    // Start a tune while refresh is still pending; its response arrives after the refresh completes.
    await setTune(normalResponse());
    holdTuneResponse = true;
    const tuneRequest = page.waitForRequest(request => new URL(request.url()).pathname === "/api/concepts/tune");
    await page.locator("#concept-tune").click();
    await tuneRequest;
    require(await page.locator(".tune-miss-handoff:not(:disabled)").count() === 0, "an enabled handoff remained mounted while a tune request overlapped connect/refresh");

    holdConnectResponse = false;
    if (releaseConnectResponse) releaseConnectResponse();
    await page.waitForFunction(() => state.connected && !document.querySelector("#connect-button")?.disabled);
    require(await page.locator(".tune-miss-handoff:not(:disabled)").count() === 0, "successful connect/refresh left an enabled handoff mounted before the late tune response");
    holdTuneResponse = false;
    if (releaseTuneResponse) releaseTuneResponse();
    await page.waitForFunction(() => !document.querySelector("#concept-tune")?.disabled);
    const lateTuneRegion = page.locator("#tune-positive-target-misses");
    const lateTuneHandoff = lateTuneRegion.locator('[data-testid="positive-target-miss"]').filter({ hasText: "train-miss" }).first().locator('[data-testid="positive-target-handoff"]');
    require(await lateTuneHandoff.isDisabled(), "tune response from before the completed connection refresh enabled a stale handoff");

    // Judgment rows without a positive grade are evidence of no positive targets, not a no-miss result.
    const noPositive = normalResponse();
    noPositive.input_snapshot.judgments = [
      { query_id: "val-q", document_index: "idx-V", document_id: "validation-zero", rating: 0, stale: false },
      { query_id: "val-q", document_index: "idx-V", document_id: "validation-null", rating: null, stale: false },
    ];
    const noPositiveRegion = await runTune(noPositive);
    const noPositiveValidation = await noPositiveRegion.locator(".tune-misses-lane").nth(1).innerText();
    require(/양수.*평가.*없|긍정.*평가.*없|no positive/i.test(noPositiveValidation), "validation judgments without positive grades did not explain that there are no positive ratings to compare");
    require(!/현재 스냅샷에서.*찾지 못|no misses|no missed targets/i.test(noPositiveValidation), "validation with no positive ratings was incorrectly presented as no misses");

    // A positive grade without a usable (index, document ID) identity is inconclusive, not empty.
    const invalidPositiveIdentities = [
      { query_id: "val-q", document_id: "missing-index", rating: 3, stale: false },
      { query_id: "val-q", document_index: "", document_id: "blank-index", rating: 2, stale: false },
      { query_id: "val-q", document_index: "idx-V", rating: 3, stale: false },
      { query_id: "val-q", document_index: "idx-V", document_id: "", rating: 1, stale: false },
    ];
    for (const judgment of invalidPositiveIdentities) {
      const invalidIdentity = normalResponse();
      invalidIdentity.input_snapshot.judgments = [judgment];
      const invalidIdentityRegion = await runTune(invalidIdentity);
      const validationStatus = await invalidIdentityRegion.locator(".tune-misses-lane").nth(1).innerText();
      require(/긍정 평가 대상의 인덱스 또는 문서 ID가 비어 있어 누락 여부를 판정하지 않았습니다/.test(validationStatus), `positive judgment with missing/blank identity was not marked inconclusive: ${validationStatus}`);
      require(!/긍정 평가가 없어|누락 대상을 찾지 못|no positive|no misses|no missed targets/i.test(validationStatus), `positive judgment with missing/blank identity was misreported as no positive ratings/no misses: ${validationStatus}`);
    }

    // An absent validation snapshot is explicitly unavailable, never an empty/no-misses claim.
    const noValidation = normalResponse();
    delete noValidation.output_snapshot.validation;
    const noValidationRegion = await runTune(noValidation);
    const noValidationText = await noValidationRegion.locator(".tune-misses-lane").nth(1).innerText();
    require(/검증용 스냅샷을 사용할 수 없|validation.*unavailable|validation.*snapshot/i.test(noValidationText), "missing validation snapshot did not show an unavailable state");
    require(!/누락 대상.*찾지 못|no misses|no missed targets/i.test(noValidationText), "missing validation snapshot was presented as having no misses");

    // Missing or malformed query maps inside a split are inconclusive too.
    for (const malformed of [
      { baseline: { "train-q": [] }, tuned: {} },
      { baseline: { "train-q": "bad rows" }, tuned: { "train-q": [] } },
    ]) {
      const incomplete = normalResponse();
      incomplete.output_snapshot.train = malformed;
      const incompleteRegion = await runTune(incomplete);
      const status = await incompleteRegion.locator(".tune-misses-lane").nth(0).innerText();
      require(/스냅샷|판정하지 않았습니다|snapshot|not determine/i.test(status), "missing or malformed in-split snapshot did not explain that misses are undetermined");
      require(!/누락 대상.*찾지 못|no misses|no missed targets/i.test(status), "malformed in-split snapshot was presented as no misses");
    }

    // A separate fixture proves the 20-row display cap and remainder count.
    const capped = normalResponse();
    const manyJudgments = [];
    const baseRows = [];
    for (let index = 0; index < 23; index += 1) {
      const id = `cap-${index}`;
      manyJudgments.push({ query_id: "train-q", document_index: "idx-cap", document_id: id, rating: 1 + (index % 3), stale: false });
      baseRows.push(row("idx-cap", id, index + 1));
    }
    capped.input_snapshot.judgments = manyJudgments;
    capped.output_snapshot.train.baseline = { "train-q": baseRows };
    capped.output_snapshot.train.tuned = { "train-q": [] };
    capped.output_snapshot.validation = { baseline: { "val-q": [] }, tuned: { "val-q": [] } };
    const cappedRegion = await runTune(capped);
    const cappedTrain = cappedRegion.locator(".tune-misses-lane").nth(0);
    require(await cappedTrain.locator('[data-testid="positive-target-miss"]').count() === 20, "expected display cap of exactly 20 train misses");
    require(/3개는 표시하지 않았습니다|3.*생략|3.*omitted/i.test(await cappedTrain.innerText()), "remainder count of 3 omitted misses is missing");

    require(consoleErrors.length === 0, `console errors: ${JSON.stringify(consoleErrors)}`);
    require(pageErrors.length === 0, `page errors: ${JSON.stringify(pageErrors)}`);
    require(requestFailures.length === 0, `browser request failures: ${JSON.stringify(requestFailures)}`);
    require(calls.every(call => call.path.startsWith("/api/")), "unexpected non-API request was recorded");
    console.log(JSON.stringify({
      result: "PASS",
      cases: ["train/validation isolation", "unjudged saved train query", "visible numeric grade", "rating and identity filtering", "tuned top-K boundary", "baseline rank", "validation unavailable", "incomplete snapshots", "20-row cap", "HTML escaping", "exact handoff and explicit diagnosis", "index-change and dirty-scope handoff disable", "URL/connection-generation invalidation", "applyTunedSettings invalidation", "same-values connect/refresh invalidation", "connect/tune response race", "judgments without positive ratings", "positive judgments with missing/blank identity"],
      apiCalls: calls.length,
      consoleErrors,
      pageErrors,
      requestFailures,
    }));
  } finally {
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
