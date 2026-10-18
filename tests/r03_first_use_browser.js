"use strict";

// Mock-only R03 frontend checks. No Elasticsearch endpoint is contacted.
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

async function main() {
  const root = path.resolve(__dirname, "..");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "r03-first-use-browser-"));
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const python = process.env.PYTHON || (fs.existsSync(path.join(root, ".venv", "bin", "python")) ? path.join(root, ".venv", "bin", "python") : "python3");
  const child = spawn(python, ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: path.join(tempDir, "test.sqlite3"), HOME: tempDir },
    stdio: "ignore",
  });
  let browser;
  try {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new Error(`workbench exited: ${child.exitCode}`);
      try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const apiCalls = [];
    let connectFixture = "ready";
    let sampleImportRequests = [];
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      let body = {};
      try { if (route.request().method() === "POST") body = route.request().postDataJSON(); } catch {}
      apiCalls.push({ path: url.pathname, body });
      const json = (value, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated: true, csrf_token: "fixture", user: { id: "fixture-user", username: "fixture", display_name: "Fixture", role: "user" } });
      if (url.pathname === "/api/health") return json({ version: "1.10.0" });
      if (url.pathname === "/api/codebase-status") return json({ indexed: false });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/connect") {
        if (connectFixture === "forbidden") return json({ error: "synthetic access denied" }, 403);
        if (connectFixture === "unreachable") return json({ error: "synthetic unavailable" }, 503);
        const missing = connectFixture === "missing";
        const sampleSized = ["unrelated-25", "imported-sample"].includes(connectFixture);
        const count = missing || connectFixture === "empty" ? 0 : sampleSized ? 25 : 3;
        return json({ cluster_name: "fixture", version: "8.19.0", selected_index: body.index, selected_index_exists: !missing, selected_index_count: count, sample_expected_count: 25, sample_data_metadata_count: 20, indices: missing ? [] : [{ index: body.index }], embedding: { mapping_available: false, mapping_dimensions: null, runtime_installed: true, model_cached: false, model_name: "fixture", vector_count: 0, document_count: count } });
      }
      if (url.pathname === "/api/sample-import") {
        sampleImportRequests.push(body);
        connectFixture = "imported-sample";
        return json({ created: true, partial: false, index: body.index, document_count: 25, message: "fixture sample imported" });
      }
      if (url.pathname === "/api/concepts/list") return json({ concepts: [] });
      if (url.pathname === "/api/concepts/runs") return json({ runs: [] });
      if (url.pathname === "/api/corpus/schema") return json({ index: body.index, fields: [{ name: "title", type: "text", searchable: true }, { name: "body", type: "text", searchable: true }] });
      if (url.pathname === "/api/concepts/quickstart") return json({ index: body.index, fields: [{ name: "title", type: "text", searchable: true }, { name: "body", type: "text", searchable: true }], suggested_title_field: "title", suggested_text_fields: ["body"], suggested_filter_fields: [], sample_documents: [{ _id: "DOC-1", _index: body.index, source: { title: "Timeout recovery", body: "Retries restore the connection after a timeout." } }] });
      if (url.pathname === "/api/concepts/save") return json({ concept: { id: "fixture-concept", name: body.concept.name, settings: {} } });
      if (url.pathname === "/api/concepts/ensure-query") return json({ query_id: "fixture-query" });
      if (url.pathname === "/api/concepts/preview") return json({ query: body.query, warning_codes: ["score_not_probability", "lexical_candidate_evidence"], baseline: { hits: [], total: 0 }, candidate: { hits: [{ _id: "DOC-1", _index: body.concept.corpus.index, rank: 1, source: { title: "Timeout recovery", body: "Retries restore the connection after a timeout." } }], total: 1 } });
      if (url.pathname === "/api/concepts/judge") return json({ saved: true });
      if (url.pathname === "/api/concepts/versions") return json({ versions: [] });
      return json({});
    });
    await page.goto(base);
    page.on("dialog", dialog => dialog.accept());
    await page.waitForFunction(() => !document.querySelector("#workbench-layout").classList.contains("hidden"));
    const require = (condition, message) => { if (!condition) throw new Error(message); };

    await page.locator("#connection-profile-name").fill("Local dev");
    await page.locator("#es-url").fill("http://127.0.0.1:19203");
    await page.locator("#index-name").fill("user-docs");
    await page.locator("#auth-type").selectOption("basic");
    await page.locator("#es-user").fill("user-secret-name");
    await page.locator("#es-password").fill("password-sentinel-r03");
    await page.locator("#save-connection-profile").click();
    let storage = await page.evaluate(() => JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) }));
    require(storage.includes("Local dev") && storage.includes("19203"), "named profile was not stored locally");
    require(!storage.includes("password-sentinel-r03") && !storage.includes("user-secret-name"), "profile or browser storage included credentials");
    const storedProfile = await page.evaluate(() => JSON.parse(localStorage.getItem("es-rag-connection-profiles"))[0]);
    require(JSON.stringify(Object.keys(storedProfile).sort()) === JSON.stringify(["auth_type", "id", "index", "name", "url"]) && storedProfile.name === "Local dev" && storedProfile.url === "http://127.0.0.1:19203" && storedProfile.index === "user-docs" && storedProfile.auth_type === "basic", `profile stored unexpected fields: ${JSON.stringify(storedProfile)}`);
    await page.locator("#auth-type").selectOption("api_key");
    await page.locator("#es-api-key").fill("api-key-sentinel-r03");
    await page.locator("#save-connection-profile").click();
    storage = await page.evaluate(() => JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) }));
    require(!storage.includes("api-key-sentinel-r03"), "profile or browser storage included the API key");
    await page.locator("#connection-profile-name").fill("Local dev");
    await page.locator("#index-name").fill("user-docs-edited");
    await page.locator("#save-connection-profile").click();
    require(await page.locator("#connection-profile-select option").count() === 2, "editing a named profile created a duplicate");
    await page.locator("#load-connection-profile").click();
    require(await page.locator("#index-name").inputValue() === "user-docs-edited", "saved profile could not be reloaded");

    const sentinel = "credential-sentinel-r03";
    await page.locator("#es-url").fill(`https://${sentinel}:hidden@elastic.example:9200`);
    await page.locator("#es-url").dispatchEvent("change");
    await page.locator("#connection-profile-name").fill("Unsafe URL");
    await page.locator("#save-connection-profile").click();
    storage = await page.evaluate(() => JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) }));
    require(!storage.includes(sentinel) && !storage.includes("hidden@elastic"), "credential-bearing URL was persisted in browser storage");
    await page.locator("#connect-button").click();
    require((await page.locator("#connection-guidance").innerText()).includes("user name") || (await page.locator("#connection-guidance").innerText()).includes("사용자 이름"), "endpoint credentials recovery guidance missing");
    require(!apiCalls.some(call => JSON.stringify(call.body).includes(sentinel)), "credential-bearing endpoint reached the API");
    const querySentinel = "token-query-sentinel-r03";
    await page.locator("#es-url").fill(`https://elastic.example:9200?api_key=${querySentinel}`);
    await page.locator("#es-url").dispatchEvent("change");
    await page.locator("#save-connection-profile").click();
    storage = await page.evaluate(() => JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) }));
    require(!storage.includes(querySentinel), "query-token endpoint was persisted in browser storage");
    await page.locator("#connect-button").click();
    require(!apiCalls.some(call => JSON.stringify(call.body).includes(querySentinel)), "query-token endpoint reached the API");

    await page.locator("#ui-language").selectOption("en");
    require(await page.locator("#connect-button").innerText().then(text => text.includes("Check connection")), "English connect label did not switch");
    require((await page.locator("#search-results").innerText()).includes("Start a search experiment"), "English empty search state did not switch");
    connectFixture = "unrelated-25";
    await page.locator("#es-url").fill("http://127.0.0.1:19203");
    await page.locator("#index-name").fill("unrelated-25-documents");
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-guidance").innerText.includes("unrelated-25-documents"), null, { timeout: 5000 }).catch(async () => { const current = await page.evaluate(() => ({ status: document.querySelector("#connection-status")?.innerText, guidance: document.querySelector("#connection-guidance")?.innerText })); throw new Error(`identity guidance did not update; ${JSON.stringify(current)}; api=${JSON.stringify(apiCalls.map(call => call.path))}`); });
    let identityText = await page.locator("#connection-guidance").innerText();
    require(identityText.includes("Selected existing index") && !identityText.includes("Supplied sample data"), `25-document existing index was misclassified: ${identityText}`);
    await page.waitForFunction(() => document.querySelector("#sample-status").textContent.includes("unrelated-25-documents"));
    require((await page.locator("#sample-status").evaluate(node => node.textContent)).includes("sample identity unverified"), `existing-index sample status did not remain unverified: ${await page.locator("#sample-status").evaluate(node => node.textContent)}`);
    require(await page.locator("#load-sample-button").isDisabled(), "sample import was enabled for an existing 25-document index");
    await page.locator("#ui-language").selectOption("ko");
    identityText = await page.locator("#connection-guidance").innerText();
    require(identityText.includes("샘플 정체 미확인") && !identityText.includes("명시적으로 가져온 제공 샘플"), `Korean existing-index identity was incorrect: ${identityText}`);
    require((await page.locator("#sample-status").evaluate(node => node.textContent)).includes("샘플 정체 미확인"), "Korean existing sample status did not switch");
    connectFixture = "missing";
    await page.locator("#index-name").fill("fixture-new");
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => !document.querySelector("#sample-onboarding").classList.contains("hidden"));
    require((await page.locator("#sample-onboarding-copy").innerText()).includes("선택 사항") || (await page.locator("#sample-onboarding-copy").innerText()).includes("선택"), "new-index sample import was not clearly optional");
    require(sampleImportRequests.length === 0, "sample import happened without an explicit click");
    await page.locator("#sample-onboarding-open").click();
    await page.locator("#load-sample-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-guidance").innerText.includes("명시적으로 가져온 제공 샘플"));
    require(sampleImportRequests.length === 1, "explicit sample import did not call the sample API exactly once");
    identityText = await page.locator("#connection-guidance").innerText();
    require(identityText.includes("명시적으로 가져온 제공 샘플"), `explicit import was not identified in Korean: ${identityText}`);
    require((await page.locator("#sample-status").evaluate(node => node.textContent)).includes("현재 세션에서 제공 샘플을 명시적으로 가져왔습니다"), "sample status did not confirm only the explicit import");
    await page.locator("#ui-language").selectOption("en");
    identityText = await page.locator("#connection-guidance").innerText();
    require(identityText.includes("Supplied sample data explicitly imported in this session"), `explicit import did not switch to English: ${identityText}`);
    require((await page.locator("#sample-status").evaluate(node => node.textContent)).includes("Supplied sample explicitly imported in this session"), "English imported sample status did not switch");
    connectFixture = "empty";
    await page.locator("#es-url").fill("http://127.0.0.1:19203");
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-status").innerText.includes("Connected"));
    require((await page.locator("#connection-guidance").innerText()).includes("empty"), "empty-index recovery guidance missing");
    connectFixture = "ready";
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-guidance").innerText.includes("Vector search is not ready"));
    require((await page.locator("#connection-guidance").innerText()).includes("Vector search is not ready"), `vector readiness explanation missing: ${await page.locator("#connection-guidance").innerText()}`);
    connectFixture = "forbidden";
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-guidance").innerText.includes("403"));
    require((await page.locator("#connection-guidance").innerText()).includes("403"), "permission recovery guidance missing");
    connectFixture = "unreachable";
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-guidance").innerText.includes("could not be reached"));
    require((await page.locator("#connection-guidance").innerText()).includes("could not be reached"), "unreachable recovery guidance missing");

    await page.locator("#connection-profile-select").selectOption({ index: 1 });
    await page.locator("#delete-connection-profile").click();
    require(await page.locator("#connection-profile-select option").count() === 1, "profile deletion failed");
    connectFixture = "ready";
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#connection-guidance").innerText.includes("Vector search is not ready"));
    await page.locator("#quickstart-fields").click();
    await page.locator("#apply-quickstart-fields").waitFor();
    require((await page.locator("#quickstart-preview").innerText()).includes("Suggested fields") && (await page.locator("#quickstart-preview").innerText()).includes("Example 1 / 1") && (await page.locator("#quickstart-preview").innerText()).includes("These are a few examples"), "English field inspection/sample guidance did not render");
    await page.locator("#ui-language").selectOption("ko");
    require((await page.locator("#quickstart-preview").innerText()).includes("추천 필드") && (await page.locator("#quickstart-preview").innerText()).includes("예시 1 / 1") && (await page.locator("#quickstart-preview").innerText()).includes("전체 인덱스"), "Korean field inspection/sample guidance did not switch");
    await page.locator("#ui-language").selectOption("en");
    require((await page.locator("#quickstart-preview").innerText()).includes("title (text)") && (await page.locator("#quickstart-preview").innerText()).includes("body (text)"), "English field inspection did not show mocked mapping fields");
    await page.locator("#apply-quickstart-fields").click();
    require((await page.locator("#quickstart-preview").innerText()).includes("Fields to apply"), "English applied field summary did not render");
    await page.locator("#ui-language").selectOption("ko");
    require((await page.locator("#quickstart-preview").innerText()).includes("적용할 필드"), "Korean applied field summary did not switch");
    await page.locator("#ui-language").selectOption("en");
    await page.locator("#guided-query-text").fill("How does retry recover after a timeout?");
    await page.locator("#guided-first-preview").click();
    await page.locator("#concept-preview-results .judge-controls").waitFor();
    require((await page.locator("#concept-preview-results").innerText()).includes("Baseline search") && (await page.locator("#concept-preview-results").innerText()).includes("Concept search · BM25"), "first-search result columns did not use English labels");
    require((await page.locator("#concept-preview-results").innerText()).includes("Save judgment"), "human judgment control did not use English labels");
    require((await page.locator("#concept-preview-results").innerText()).includes("matches") && (await page.locator("#concept-preview-results").innerText()).includes("No concept-match evidence"), "English first-search result labels did not switch as a unit");
    let warningsText = await page.locator("#concept-preview-results").innerText();
    require(warningsText.includes("Scores rank search results; they are not probabilities") && warningsText.includes("Missing evidence does not mean the document is irrelevant"), `English result warnings were not localized: ${warningsText}`);
    await page.locator("#ui-language").selectOption("ko");
    require((await page.locator("#concept-preview-results").innerText()).includes("기본 검색") && (await page.locator("#concept-preview-results").innerText()).includes("관련도"), "Korean first-search result labels did not switch as a unit");
    warningsText = await page.locator("#concept-preview-results").innerText();
    require(warningsText.includes("점수는 검색 순위를 매기는 값이며 확률을 뜻하지 않습니다") && warningsText.includes("표현 근거는 문서에 같은 글자가 나타났다는 뜻입니다"), `Korean result warnings did not rerender with the preview: ${warningsText}`);
    await page.locator("#ui-language").selectOption("en");
    warningsText = await page.locator("#concept-preview-results").innerText();
    require(warningsText.includes("Scores rank search results; they are not probabilities") && warningsText.includes("Missing evidence does not mean the document is irrelevant"), `English warnings did not rerender after switching back: ${warningsText}`);
    await page.locator("#concept-preview-results .judge-rating").selectOption("2");
    await page.locator("#concept-preview-results .save-judgment").click();
    await page.waitForFunction(() => document.querySelector("#concept-preview-status").innerText.includes("Search complete"));
    const judgmentCall = apiCalls.find(call => call.path === "/api/concepts/judge");
    require(judgmentCall?.body.rating === 2 && judgmentCall.body.document_id === "DOC-1" && judgmentCall.body.query_id === "fixture-query", "human judgment did not save the expected document/query identity and rating");
    const comparisonGuidance = await page.locator('[data-i18n="comparison"]').innerText();
    require(comparisonGuidance.includes("After saving judgments") && comparisonGuidance.includes("does not automatically determine quality"), "retrieval-mode comparison guidance did not explain the human-label boundary");
    await page.locator("#ui-language").selectOption("ko");
    require((await page.locator('[data-i18n="comparison"]').innerText()).includes("품질을 자동으로 판정하지는 않습니다") && (await page.locator("#concept-preview-status").innerText()).includes("비교 완료"), "Korean judgment/comparison guidance did not switch");
    await page.locator("#ui-language").selectOption("en");
    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, focus: getComputedStyle(document.querySelector("#connect-button"), ":focus-visible").outlineStyle }));
    require(mobile.scrollWidth <= mobile.width, `390px layout overflows: ${JSON.stringify(mobile)}`);
    await page.locator("#es-url").focus();
    await page.keyboard.press("Tab");
    require(await page.evaluate(() => document.activeElement === document.querySelector("#auth-type") && getComputedStyle(document.activeElement).outlineStyle !== "none"), "connection controls were not in logical keyboard order with visible focus");
    require(apiCalls.every(call => !JSON.stringify(call.body).includes(sentinel) && !JSON.stringify(call.body).includes(querySentinel)), "secret sentinel was observed in a request payload");
    console.log(JSON.stringify({ result: "PASS", evidence: "mock API fixtures only; no Elasticsearch traffic", checked: ["connect → inspect and apply fields → first search → save human judgment → comparison guidance", "existing 25-document index remains unverified; explicit sample import only", "Korean/English field inspection, sample identity, first-search results, judgment and comparison guidance", "profile save/edit/load/delete", "password/API key-free storage and request payload", "userinfo/query-token endpoint rejection", "empty/403/unreachable/vector recovery", "390px overflow", "keyboard order and visible focus"], mobile, apiCalls: apiCalls.map(call => call.path) }));
  } finally {
    await browser?.close();
    if (child.pid && child.exitCode === null && child.signalCode === null) {
      child.kill("SIGTERM");
      await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once("exit", resolve));
    }
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
