"use strict";

// Mock-only R09 browser fixture. Tuning responses and judgments are synthetic; no Elasticsearch service is contacted.
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

function requireThat(condition, message) { if (!condition) throw new Error(message); }

async function main() {
  const root = path.resolve(__dirname, "..");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "r09-mock-browser-"));
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
    const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
    page.on("pageerror", error => console.error("pageerror:", error.message));
    const calls = [];
    let scenario = "complete";
    const diagnostics = [{
      query_id: "q-val-1", query: "synthetic validation query", status: "incomplete",
      metric_deltas: { ndcg_at_k: 0.2, judged_coverage_at_k: 0.1, recall_of_judged_relevant_at_k: 0.25 },
      baseline_missed_known_relevant: [{ document_index: "fixture-index", document_id: "target-old", rating: 2 }],
      selected_missed_known_relevant: [{ document_index: "fixture-index", document_id: "target-new", rating: 3 }],
      missed_relevant_added: [{ document_index: "fixture-index", document_id: "target-new", rating: 3 }],
      missed_relevant_fixed: [{ document_index: "fixture-index", document_id: "target-old", rating: 2 }],
      baseline_retrieved_unjudged_count: 2, selected_retrieved_unjudged_count: 1, stale_judgment_count: 1,
      incomplete_categories: ["qrels_not_exhaustive"], error_categories: [],
    }];
    const baseCandidate = { candidate_id: "baseline", settings: { concept_weight: 1, size: 10 }, train_metrics: { ndcg_at_k: 0.4, judged_coverage_at_k: 0.6 }, validation_metrics: { ndcg_at_k: 0.5, judged_coverage_at_k: 0.7 }, evaluation_status: "validation_unavailable" };
    const tunedCandidate = { candidate_id: "candidate-001", settings: { concept_weight: 1.4, size: 10 }, train_metrics: { ndcg_at_k: 0.8, judged_coverage_at_k: 0.9 }, validation_metrics: { ndcg_at_k: 0.7, judged_coverage_at_k: 0.8 }, evaluation_status: "complete" };
    const responseFor = () => {
      if (scenario === "baseline") return {
        settings: baseCandidate.settings,
        tuning_budget: { max_candidates: 4, time_budget_seconds: 60, candidates_evaluated: 1, elapsed_ms: 18, stop_reason: "completed" },
        candidate_trace: [baseCandidate], selection: { selected_candidate_id: "baseline", reason: "validation_unavailable" },
        validation_diagnostics: [], validation_qrels_complete: false,
      };
      const limited = scenario === "time-limited" || scenario === "candidate-limited";
      return {
        settings: tunedCandidate.settings,
        baseline: { ndcg_at_k: 0.4, judged_coverage_at_k: 0.6 }, tuned: { ndcg_at_k: 0.8, judged_coverage_at_k: 0.9 },
        validation: { baseline: baseCandidate.validation_metrics, tuned: tunedCandidate.validation_metrics, qrels_complete: false },
        tuning_budget: { max_candidates: 3, time_budget_seconds: 20, candidates_evaluated: 2, elapsed_ms: scenario === "time-limited" ? 20000 : 231, stop_reason: scenario === "time-limited" ? "time_budget" : scenario === "candidate-limited" ? "candidate_budget" : "completed" },
        candidate_trace: [baseCandidate, tunedCandidate], selection: { selected_candidate_id: "candidate-001", reason: "candidate_selected" },
        validation_diagnostics: diagnostics, validation_qrels_complete: false,
      };
    };
    await page.route("**/api/**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch {}
      calls.push({ path: url.pathname, method: request.method(), body });
      const json = (value, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated: true, csrf_token: "mock-csrf", user: { id: "mock-user", username: "mock", role: "user" } });
      if (url.pathname === "/api/health") return json({ version: "1.14.0" });
      if (url.pathname === "/api/codebase-status") return json({ indexed: false });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/embedding-profiles") return json({ profiles: [] });
      if (url.pathname === "/api/reranker/status") return json({ ready: false, runtime: { installed: false }, cache: { ready: false } });
      if (url.pathname === "/api/concepts/tune") return json(responseFor());
      if (url.pathname === "/api/concepts/runs") return json({ runs: [] });
      if (url.pathname === "/api/concepts/save") return json({ concept: { id: "concept-mock", settings: body.concept.settings } });
      if (url.pathname === "/api/concepts/list") return json({ concepts: [] });
      if (url.pathname === "/api/concepts/versions") return json({ versions: [] });
      return json({});
    });
    await page.goto(base);
    await page.waitForFunction(() => !document.querySelector("#workbench-layout").classList.contains("hidden"));
    await page.evaluate(() => {
      state.connected = true;
      state.conceptId = "concept-mock";
      state.connectedIndex = "fixture-index";
      state.connectedIndexExists = true;
      document.querySelector("#concept-name").value = "Synthetic concept";
      document.querySelector("#index-name").value = "fixture-index";
      document.querySelector("#concept-title-field").innerHTML = '<option value="title" selected>title</option>';
      document.querySelector("#concept-title-field").value = "title";
      document.querySelector("#concept-text-fields").innerHTML = '<label><input type="checkbox" value="body" checked>body</label>';
      document.querySelector("#concept-tune").disabled = false;
    });
    requireThat(await page.locator("#concept-tune-max-candidates").inputValue() === "30", "default max candidate count was not 30");
    requireThat(await page.locator("#concept-tune-time-budget").inputValue() === "600", "default time budget was not 600 seconds");
    requireThat(await page.locator("#concept-tune-max-candidates").getAttribute("max") === "30" && await page.locator("#concept-tune-time-budget").getAttribute("max") === "600", "numeric limits are missing from accessible controls");
    await page.locator("#ui-language").selectOption("en");
    requireThat((await page.locator('label[for="concept-tune-max-candidates"]').innerText()).includes("Maximum candidates"), "maximum-candidate label did not localize to English");
    await page.locator("#ui-language").selectOption("ko");
    const run = async (name) => {
      scenario = name;
      await page.locator("#concept-tune").click();
      await page.waitForFunction(() => !document.querySelector("#concept-tune").disabled && document.querySelector("#concept-tune-results .r09-budget") && document.querySelector("#concept-tune-results .r09-selection"), null, { timeout: 8000 });
      const call = calls.filter(item => item.path === "/api/concepts/tune").at(-1);
      requireThat(call?.body.max_candidates === 30 && call?.body.time_budget_seconds === 600, `tuning request omitted exact bound keys/defaults: ${JSON.stringify(call?.body)}`);
      requireThat(!Object.hasOwn(call.body, "passes"), "legacy passes parameter was sent");
      return await page.locator("#concept-tune-results").innerText();
    };

    const completeText = await run("complete");
    for (const marker of ["candidate-001", "후보를 검증 기준으로 선택", "target-new", "target-old", "검증 자료 없음", "학습 판단으로 후보 설정을 평가", "판단 자료가 불완전", "누락이 없다는 사실은 모든 관련 대상을 찾았다는 뜻이 아닙니다"]) requireThat(completeText.includes(marker), `complete diagnostics missing ${marker}: ${completeText}`);
    await page.locator("#ui-language").selectOption("en");
    const englishDiagnostics = await page.locator("#concept-tune-results").innerText();
    requireThat(englishDiagnostics.includes("Newly missed known-relevant judged targets") && englishDiagnostics.includes("No reported misses does not prove") && englishDiagnostics.includes("Validation unavailable") && englishDiagnostics.includes("Train judgments evaluate candidate settings"), "validation diagnostics/status/boundary did not switch to English");
    await page.locator("#ui-language").selectOption("ko");
    requireThat(calls.filter(call => call.path === "/api/concepts/save").length === 0, "settings were saved without an explicit apply action");
    requireThat(await page.locator("#concept-weight").inputValue() === "1", "candidate settings were silently applied to the concept editor");
    await page.locator("#concept-tune-results .apply-tuned-settings").click();
    await page.waitForFunction(() => document.querySelector("#concept-weight").value === "1.4");
    requireThat(calls.filter(call => call.path === "/api/concepts/save").length === 1, "explicit apply did not use the existing save workflow");

    const baselineText = await run("baseline");
    for (const marker of ["baseline", "사용 가능한 검증 양성 판단이 없어 기준선을 유지", "검증 질의별 진단이 없습니다"]) requireThat(baselineText.includes(marker), `baseline-retention response missing ${marker}: ${baselineText}`);

    const timeText = await run("time-limited");
    requireThat(timeText.includes("시간 한도 도달 · 결과가 일부 탐색일 수 있음"), `time-limited stop state is missing: ${timeText}`);
    const candidateText = await run("candidate-limited");
    requireThat(candidateText.includes("후보 한도 도달 · 결과가 일부 탐색일 수 있음"), `candidate-limited stop state is missing: ${candidateText}`);

    // Invalid bounds are rejected in the browser before a tuning API call.
    const beforeInvalid = calls.filter(call => call.path === "/api/concepts/tune").length;
    await page.locator("#concept-tune-max-candidates").fill("31");
    await page.locator("#concept-tune").click();
    requireThat(calls.filter(call => call.path === "/api/concepts/tune").length === beforeInvalid, "over-limit candidate request reached the API");

    console.log(JSON.stringify({ mockOnly: true, scenarios: ["complete", "baseline-retained", "time-limited", "candidate-limited", "validation-diagnostics"], apiCalls: calls.filter(call => call.path === "/api/concepts/tune").length, result: "PASS" }));
  } finally {
    if (browser) await browser.close();
    child.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
