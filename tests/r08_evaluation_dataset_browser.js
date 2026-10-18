"use strict";

// Mock-only R08 browser fixture. API responses and evaluation rankings are synthetic; no retrieval-quality claim is made.
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
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "r08-mock-browser-"));
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const python = process.env.PYTHON || (fs.existsSync(path.join(root, ".venv", "bin", "python")) ? path.join(root, ".venv", "bin", "python") : "python3");
  const child = spawn(python, ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root, env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(tempDir, "mock.sqlite3"), HOME: tempDir }, stdio: "ignore",
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
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    page.on("pageerror", error => console.error("pageerror:", error.message));
    const calls = [];
    let datasetId = "ds-mock";
    let versionId = "v1-mock";
    let runCounter = 1;
    let failEvaluation = false;
    let datasets = [{ dataset_id: datasetId, name: "Synthetic fixture", versions: [
      { version_id: versionId, version_number: 2, fingerprint: "fp-v1", provenance: { judgment_source: "synthetic" }, query_count: 1, qrel_count: 2, unjudged_policy: "judged_only" },
      { version_id: "v0-mock", version_number: 1, fingerprint: "fp-v0", provenance: { judgment_source: "synthetic" }, query_count: 1, qrel_count: 2, unjudged_policy: "judged_only" },
    ] }];
    const detail = {
      dataset: { dataset_id: datasetId, name: "Synthetic fixture" },
      version: { version_id: versionId, version_number: 1, fingerprint: "fp-v1", unjudged_policy: "judged_only", qrels_complete: false },
      provenance: { source_name: "Synthetic only", source_license: "fixture-only", permission_status: "mock", judgment_source: "synthetic", extraction_rules: "mock subset", omitted_known_relevant_items: "none asserted" },
      queries: [{ query_id: "q1", query: "synthetic query", split: "validation", information_need: "need-a", related_query_group: "group-a" }],
      qrels: [
        { query_id: "q1", document_index: "fixture-index", document_id: "known-relevant", grade: 2, document_family_id: "family-a" },
        { query_id: "q1", document_index: "fixture-index", document_id: "explicit-null", grade: null },
      ],
    };
    const runs = [];
    await page.route("**/api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch {}
      calls.push({ path: url.pathname, method: request.method(), body });
      const json = (value, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated: true, csrf_token: "mock-csrf", user: { id: "mock-user", username: "mock", role: "user" } });
      if (url.pathname === "/api/health") return json({ version: "1.13.0" });
      if (url.pathname === "/api/codebase-status") return json({ indexed: false });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/embedding-profiles") return json({ profiles: [] });
      if (url.pathname === "/api/reranker/status") return json({ ready: false, runtime: { installed: false }, cache: { ready: false } });
      if (url.pathname === "/api/evaluation/datasets/list") return json({ datasets });
      if (url.pathname === "/api/evaluation/datasets/detail") return json(detail);
      if (url.pathname === "/api/evaluation/datasets/versions/create") {
        require(body.base_version_id === versionId, "version edit omitted latest base_version_id");
        require(body.queries?.[0]?.query === "synthetic query edited", `query edit was not submitted: ${JSON.stringify(body.queries)}`);
        require(body.qrels?.some(row => row.grade === null) && body.qrels?.some(row => row.grade === 2), "explicit-null/numeric qrels were not preserved");
        require(body.qrels?.every(row => row.document_index && row.document_id), "qrels were missing concrete index/document identity");
        require(body.provenance.source_license === "fixture-only" && body.provenance.extraction_rules === "mock subset" && body.provenance.omitted_known_relevant_items === "none asserted", "backend provenance fields were not preserved");
        versionId = "v2-mock";
        datasets = [{ dataset_id: datasetId, name: "Synthetic fixture", versions: [{ version_id: versionId, version_number: 2, fingerprint: "fp-v2", unjudged_policy: body.unjudged_policy }] }];
        detail.version = { ...detail.version, version_id: versionId, version_number: 2, fingerprint: "fp-v2", unjudged_policy: body.unjudged_policy };
        detail.queries = body.queries;
        detail.qrels = body.qrels;
        return json({ dataset_id: datasetId, version: detail.version });
      }
      if (url.pathname === "/api/evaluation/datasets/create") {
        require(body.name === "New synthetic set", "new dataset name was not submitted");
        datasetId = "ds-created"; versionId = "v1-created";
        datasets = [{ dataset_id: datasetId, name: body.name, versions: [{ version_id: versionId, version_number: 1, fingerprint: "fp-created" }] }];
        return json({ dataset_id: datasetId, version: { version_id: versionId, version_number: 1, fingerprint: "fp-created" } });
      }
      if (url.pathname === "/api/evaluation/datasets/export") return json({ format: body.format, filename: "mock-dataset.jsonl", content: "{\"record_type\":\"dataset\"}\n" });
      if (url.pathname === "/api/evaluation/datasets/import") return json({ dataset: { dataset_id: datasetId, name: "Synthetic fixture" }, version: { version_id: versionId, fingerprint: "fp-v2" }, fingerprint: "fp-v2" });
      if (url.pathname === "/api/evaluation/runs/list") return json({ runs });
      if (url.pathname === "/api/evaluation/datasets/evaluate") {
        if (failEvaluation) {
          require(body.split === "test" && body.configuration_frozen === true, "test evaluation did not use the frozen-configuration contract");
          return json({ run_id: null, persisted: false, failures: [{ query_id: "q1", failure_category: "search_failure" }] });
        }
        require(body.dataset_id && body.version_id && body.split === "validation", `evaluation scope was wrong: ${JSON.stringify(body)}`);
        require(body.settings?.candidate_pool && body.settings?.size && body.settings.size >= body.cutoff, "candidate pool or top-K settings missing/invalid");
        const run = { run_id: `run-${runCounter++}`, dataset_id: body.dataset_id, dataset_version_id: body.version_id, dataset_version_number: 2, dataset_provenance: { judgment_source: "synthetic" }, dataset_fingerprint: "fp-v2", split: body.split, mode: body.mode, cutoff: body.cutoff, unjudged_policy: "judged_only", aggregate: { precision_at_k: { mean: 0.5, query_count: 1 }, judged_coverage_at_k: { mean: 0.5, query_count: 1 } }, queries: [{ query_id: "q1", query: "synthetic query edited", split: "validation", metrics: { precision_at_k: 0.5, recall_at_k: 1, mrr_at_k: 1, ndcg_at_k: 1, judged_coverage_at_k: 0.5 }, counts: { numeric_judged_retrieved: 1, explicit_null_retrieved: 1, absent_qrel_retrieved: 0 }, missed_known_relevant: [], ranked_hits: [{ original_rank: 1, judged_rank: 1, document_index: "fixture-index", document_id: "known-relevant", qrel_state: "numeric" }, { original_rank: 2, judged_rank: null, document_index: "fixture-index", document_id: "unknown-doc", qrel_state: "absent" }] }] };
        runs.push(run);
        return json(run);
      }
      if (url.pathname === "/api/evaluation/runs/compare") return json({ dataset_id: datasetId, dataset_version_id: versionId, cutoff: 10, queries: [{ query_id: "q1", query: "synthetic query edited", regressions: ["ndcg_at_k"], metric_deltas: { ndcg_at_k: -0.5 }, missed_relevant_added: [{ document_index: "fixture-index", document_id: "known-relevant", grade: 2 }], left_missed_known_relevant: [], right_missed_known_relevant: [{ document_index: "fixture-index", document_id: "known-relevant", grade: 2 }], left_retrieved_unjudged_count: 0, right_retrieved_unjudged_count: 1, left_coverage: 0.5, right_coverage: 0.25 }] });
      return json({});
    });
    await page.goto(base);
    await page.waitForFunction(() => !document.querySelector("#workbench-layout").classList.contains("hidden"));
    await page.locator('[data-tab="evaluation-panel"]').click();
    const require = (condition, message) => { if (!condition) throw new Error(message); };
    try { await page.waitForFunction(() => document.querySelector("#evaluation-dataset-version")?.value === "v1-mock", { timeout: 8000 }); }
    catch (error) { const debug = await page.evaluate(() => ({ datasets: state.evaluationDatasets, status: document.querySelector("#evaluation-dataset-import-status").textContent, identity: state.identity })); throw new Error(`initial dataset did not load; ${JSON.stringify(debug)} calls=${JSON.stringify(calls)} select=${await page.locator("#evaluation-dataset-select").inputValue()} version=${await page.locator("#evaluation-dataset-version").inputValue()}`); }
    require(calls.some(call => call.path.endsWith("/datasets/list") && call.method === "POST"), "dataset list did not use the authenticated POST contract");
    const provenanceText = await page.locator("#evaluation-dataset-provenance").innerText();
    require(provenanceText.includes("합성") || provenanceText.includes("synthetic"), `provenance label was not visible: ${provenanceText}`);
    require(await page.locator("#evaluation-dataset-version").inputValue() === "v1-mock", "version list did not default to its first (latest) entry");
    await page.locator("#evaluation-dataset-version").selectOption("v0-mock");
    await page.waitForFunction(() => document.querySelector("#evaluation-dataset-save-version").disabled);
    require((await page.locator(".dataset-editor-toolbar").innerText()).includes("최신"), "editor did not explain that new versions branch from latest");
    await page.locator("#evaluation-dataset-version").selectOption("v1-mock");
    await page.waitForFunction(() => !document.querySelector("#evaluation-dataset-save-version").disabled);
    await page.locator('#evaluation-dataset-editor textarea[data-field="query"]').fill("synthetic query edited");
    await page.locator("#evaluation-dataset-save-version").click();
    await page.waitForFunction(() => document.querySelector("#evaluation-dataset-version")?.value === "v2-mock");
    const versionCreate = calls.find(call => call.path.endsWith("/datasets/versions/create"));
    require(versionCreate?.method === "POST" && versionCreate.body.provenance.judgment_source === "synthetic", "version/provenance edit did not use the API contract");
    await page.locator("#evaluation-split").selectOption("validation");
    await page.locator("#evaluation-dataset-run").evaluate(button => { button.disabled = false; });
    await page.locator("#evaluation-dataset-run").click();
    await page.locator(".dataset-run-query").waitFor();
    const runText = await page.locator("#evaluation-dataset-run-results").innerText();
    for (const marker of ["run-1", "Judged coverage", "known-relevant", "unknown-doc", "qrel 행 없음"]) require(runText.includes(marker), `evaluation evidence missing ${marker}: ${runText}`);
    require(!(await page.locator("#evaluation-dataset-run-status").innerText()).includes("quality"), "UI made an unsupported retrieval-quality claim");
    // Add a second mock run through a second evaluation request.
    await page.locator("#evaluation-dataset-run").click();
    await page.waitForFunction(() => document.querySelectorAll("#evaluation-run-left option").length >= 3);
    await page.locator("#evaluation-run-left").selectOption("run-1");
    await page.locator("#evaluation-run-right").selectOption("run-2");
    await page.locator("#evaluation-run-compare").click();
    await page.locator(".dataset-compare-query").waitFor();
    const compareText = await page.locator("#evaluation-run-compare-results").innerText();
    require(compareText.includes("회귀") && compareText.includes("known-relevant") && compareText.includes("결과 내 미평가"), `comparison evidence missing: ${compareText}`);
    await page.locator("#evaluation-split").selectOption("test");
    await page.locator("#evaluation-config-frozen").check();
    failEvaluation = true;
    await page.locator("#evaluation-dataset-run").click();
    await page.waitForFunction(() => document.querySelector("#evaluation-dataset-run-status").textContent.includes("저장하지 않았습니다"));
    require((await page.locator("#evaluation-dataset-run-results").innerText()).includes("search_failure"), "non-persisted test failure did not show the safe failure category");
    const failedTestRequest = calls.filter(call => call.path.endsWith("/datasets/evaluate")).at(-1);
    require(failedTestRequest.body.split === "test" && failedTestRequest.body.configuration_frozen === true, "test evaluation did not use the frozen-configuration contract");
    failEvaluation = false;
    await page.locator("#ui-language").selectOption("en");
    require((await page.locator("#evaluation-datasets-title").innerText()).includes("Account-scoped"), "R08 title did not localize to English");
    await page.locator("#evaluation-dataset-create").click();
    await page.locator("#evaluation-dataset-name").fill("New synthetic set");
    await page.locator("#evaluation-dataset-save-version").click();
    await page.waitForFunction(() => document.querySelector("#evaluation-dataset-version")?.value === "v1-created");
    const create = calls.find(call => call.path.endsWith("/datasets/create"));
    require(create?.body.queries?.length === 1 && create.body.provenance.judgment_source === "human", "new dataset creation did not submit initial query/provenance");
    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    require(mobile.scroll <= mobile.width, `mobile dataset layout overflows: ${JSON.stringify(mobile)}`);
    console.log(JSON.stringify({ ok: true, mockOnly: true, requests: calls.filter(call => call.path.includes("/evaluation/")).map(call => call.path), mobile }));
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
