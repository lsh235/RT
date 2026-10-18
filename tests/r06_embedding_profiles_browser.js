"use strict";

// Mock-only R06 UI contract check. Fixtures verify profile selection and consent flows, not model or Elasticsearch behavior.
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
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "r06-profile-browser-"));
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
    let mappingDimensions = 1024;
    let savedPrivateProfile = "e5-multilingual-large";
    let tokenizersInstalled = true;
    const profiles = [
      { profile_id: "e5-multilingual-large", model_name: "intfloat/multilingual-e5-large", source_repo: "Qdrant/multilingual-e5-large-onnx", source_revision: "e5-revision-fixture", dimensions: 1024, query_prefix: "query: ", passage_prefix: "passage: ", max_tokens: 512, license: "mit", fastembed_version: "0.9.0", tokenizer_runtime_installed: true, tokenizer_runtime_version: "0.21.4", similarity: "cosine", normalized: true, recipe_fingerprint: "e5-recipe-fixture", runtime_installed: true, model_cached: true, setup_state: "cached", safe_message: "fixture ready" },
      { profile_id: "paraphrase-multilingual-minilm-l12", model_name: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", source_repo: "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q", source_revision: "minilm-revision-fixture", dimensions: 384, query_prefix: "", passage_prefix: "", max_tokens: 128, license: "apache-2.0", fastembed_version: "0.9.0", tokenizer_runtime_installed: true, tokenizer_runtime_version: "0.21.4", similarity: "cosine", normalized: true, recipe_fingerprint: "minilm-recipe-fixture", runtime_installed: true, model_cached: true, setup_state: "cached", safe_message: "fixture ready" },
    ];
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      let body = {};
      try { if (route.request().method() === "POST") body = route.request().postDataJSON(); } catch {}
      calls.push({ path: url.pathname, body });
      const json = value => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
      if (url.pathname === "/api/auth/session") return json({ configured: true, authenticated: true, csrf_token: "fixture-csrf", user: { id: "fixture-account", username: "fixture", display_name: "Fixture", role: "user" } });
      if (url.pathname === "/api/health") return json({ version: "1.12.0" });
      if (url.pathname === "/api/embedding/profiles") return json({ default_profile_id: "e5-multilingual-large", profiles });
      if (url.pathname === "/api/connect") return json({ cluster_name: "synthetic", version: "9.5.5", selected_index: body.index || "fixture-index", selected_index_exists: true, selected_index_count: 2, sample_expected_count: 0, sample_data_metadata_count: 0, indices: [{ index: body.index || "fixture-index" }], embedding: { profile_id: body.profile_id, model_name: profiles.find(p => p.profile_id === body.profile_id)?.model_name, profile_dimensions: profiles.find(p => p.profile_id === body.profile_id)?.dimensions, mapping_available: true, mapping_dimensions: mappingDimensions, mapping_compatible: mappingDimensions === profiles.find(p => p.profile_id === body.profile_id)?.dimensions, mapping_error: mappingDimensions === profiles.find(p => p.profile_id === body.profile_id)?.dimensions ? null : "Stored vector recipe does not match the selected profile.", runtime_installed: true, model_cached: true, vector_count: 1, document_count: 2 } });
      if (url.pathname === "/api/concepts/list") return json({ concepts: [] });
      if (url.pathname === "/api/concepts/runs") return json({ runs: [] });
      if (url.pathname === "/api/corpus/schema") return json({ index: body.index, fields: [{ name: "title", type: "text", searchable: true }, { name: "body", type: "text", searchable: true }] });
      if (url.pathname === "/api/concepts/quickstart") return json({ index: body.index, fields: [{ name: "title", type: "text", searchable: true }, { name: "body", type: "text", searchable: true }], suggested_title_field: "title", suggested_text_fields: ["body"], suggested_filter_fields: [], sample_documents: [] });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/knowledge/list") return json({ documents: [], usage: { documents: 0, bytes: 0 } });
      if (url.pathname === "/api/knowledge/chunks/policy/get") return json({ policy: { strategy: "character", size: 1800, overlap: 200 }, policy_sha256: "fixture" });
      if (url.pathname === "/api/knowledge/reindex/latest") return json({ job: null });
      if (url.pathname === "/api/knowledge/es-status") return json({ state: "in_sync", vector_state: "in_sync", vector_profile_id: savedPrivateProfile, vector_profile_recipe: { dimensions: savedPrivateProfile.includes("minilm") ? 384 : 1024 }, vector_profile_status: { runtime_installed: true, model_cached: true, status: "cached" }, local_documents: 1, local_chunks: 1, indexed_chunks: 1, vector_chunks: 1, tokenizer: { tokenizers_installed: tokenizersInstalled, tokenizers_version: tokenizersInstalled ? "0.21.4" : null, huggingface_hub_installed: true, cached: true } });
      if (url.pathname === "/api/token-preview/status") return json({ available: true, tokenizers_installed: true, huggingface_hub_installed: true, cached: true });
      if (url.pathname === "/api/vectorize") return json({ message: "synthetic vectorization accepted" });
      if (url.pathname === "/api/search") return json({ mode: body.mode, total: 1, took_ms: 1, query: { rank_constant: 60 }, hits: [], private_knowledge: { state: "in_sync", mode: "bm25", results: [] } });
      if (url.pathname === "/api/knowledge/es-vector-sync") { savedPrivateProfile = body.profile_id; return json({ vector_chunks: 1, profile_id: body.profile_id, recipe: { dimensions: body.profile_id.includes("minilm") ? 384 : 1024, similarity: "cosine" } }); }
      return json({});
    });
    let dialogCount = 0;
    page.on("dialog", dialog => { dialogCount += 1; dialog.accept(); });
    await page.goto(base);
    await page.waitForFunction(() => !document.querySelector("#workbench-layout").classList.contains("hidden"));
    await page.waitForFunction(() => document.querySelectorAll("#embedding-profile-select option").length === 2);
    const require = (condition, message) => { if (!condition) throw new Error(message); };

    await page.locator("#es-url").fill("http://127.0.0.1:19203");
    await page.locator("#index-name").fill("profile-fixture");
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => document.querySelector("#embedding-profile-select option")?.textContent.includes("캐시됨"));
    require(calls.some(call => call.path === "/api/embedding/profiles"), "protected profile list was not requested");
    require(calls.some(call => call.path === "/api/connect" && call.body.profile_id === "e5-multilingual-large"), "default profile_id was not included in connect");
    await page.waitForFunction(() => document.querySelector("#embedding-profile-help").textContent.includes("e5-revision-fixture"));
    await page.locator(".sample-maintenance > summary").click();
    const initialDetails = await page.locator("#embedding-profile-help").innerText();
    require(initialDetails.includes("query: ") && initialDetails.includes("passage: ") && initialDetails.includes("512") && initialDetails.includes("mit") && initialDetails.includes("e5-revision-fixture") && initialDetails.includes("Qdrant/multilingual-e5-large-onnx") && initialDetails.includes("0.9.0") && initialDetails.includes("e5-recipe-fixture") && initialDetails.includes("모델 캐시됨") && initialDetails.includes("tokenizer 런타임 설치됨 0.21.4"), `shared profile details are incomplete: ${initialDetails}`);
    await page.locator("#ui-language").selectOption("en");
    const englishDetails = await page.locator("#knowledge-vector-profile-help").innerText();
    require(englishDetails.includes("next explicitly approved") && englishDetails.includes("Context:") && englishDetails.includes("License:") && englishDetails.includes("tokenizer runtime installed 0.21.4"), `English private profile guidance/details missing: ${englishDetails}`);
    await page.locator("#ui-language").selectOption("ko");
    require((await page.locator("#embedding-profile-help").innerText()).includes("질의 접두사"), "Korean profile guidance/details did not render");

    await page.locator("#embedding-profile-select").selectOption("paraphrase-multilingual-minilm-l12");
    const miniDetails = await page.locator("#embedding-profile-help").innerText();
    const miniOption = await page.locator("#embedding-profile-select option:checked").textContent();
    require(miniOption.includes("384차원") && miniDetails.includes("없음") && miniDetails.includes("128") && miniDetails.includes("apache-2.0") && miniDetails.includes("minilm-revision-fixture") && miniDetails.includes("minilm-recipe-fixture"), `MiniLM profile details are incomplete: ${miniOption} · ${miniDetails}`);
    await page.waitForFunction(() => document.querySelector("#embedding-status").textContent.includes("384차원"));
    require(calls.some(call => call.path === "/api/connect" && call.body.profile_id === "paraphrase-multilingual-minilm-l12"), "selected MiniLM profile was not sent to connect");
    const mismatchText = await page.locator("#embedding-status").innerText();
    require(mismatchText.includes("different embedding spaces") || mismatchText.includes("recipe"), `mapping recipe mismatch was not surfaced: ${mismatchText}`);
    require(await page.locator("#vectorize-button").isDisabled(), "vectorize remained available with an incompatible mapping");

    mappingDimensions = 384;
    await page.locator("#connect-button").click();
    await page.waitForFunction(() => !document.querySelector("#vectorize-button").disabled);
    await page.locator("#vectorize-button").click();
    require(calls.some(call => call.path === "/api/vectorize" && call.body.profile_id === "paraphrase-multilingual-minilm-l12"), "selected profile was not sent to vectorize");

    await page.getByRole("tab", { name: /검색 실험/ }).click();
    await page.locator("#search-mode").selectOption("vector");
    await page.locator("#search-query").fill("synthetic query");
    await page.locator("#search-button").click();
    await page.waitForFunction(() => document.querySelector("#search-summary").textContent.includes("documents matched") || document.querySelector("#search-summary").textContent.includes("개 문서 일치"));
    require(calls.some(call => call.path === "/api/search" && call.body.profile_id === "paraphrase-multilingual-minilm-l12"), "selected profile was not sent to vector search");

    await page.getByRole("tab", { name: /내 지식/ }).click();
    await page.waitForFunction(() => document.querySelector("#knowledge-es-status").textContent.includes("intfloat/multilingual-e5-large"));
    await page.locator("#knowledge-vector-profile-select").selectOption("paraphrase-multilingual-minilm-l12");
    require((await page.locator("#knowledge-es-status").innerText()).includes("기존 generation은 그대로 유지됩니다"), "private selection falsely implied the saved/current generation changed");
    tokenizersInstalled = false;
    await page.evaluate(async () => loadKnowledgeEsStatus());
    require((await page.locator("#knowledge-es-status").innerText()).includes("선택 tokenizers 런타임 없음"), "private status did not show missing tokenizer runtime");
    const beforeMissingRuntimeClick = dialogCount;
    await page.locator("#knowledge-es-vector-sync").click();
    require(dialogCount === beforeMissingRuntimeClick, "private sync asked for consent despite missing tokenizers runtime");
    require((await page.locator("#knowledge-es-status").innerText()).includes("private-vector extra"), "Korean missing-tokenizer install guidance was not shown");
    await page.locator("#ui-language").selectOption("en");
    await page.locator("#knowledge-es-vector-sync").click();
    require(dialogCount === beforeMissingRuntimeClick, "English private sync asked for consent despite missing tokenizers runtime");
    require((await page.locator("#knowledge-es-status").innerText()).includes("needs the optional tokenizers runtime"), "English missing-tokenizer install guidance was not shown");
    tokenizersInstalled = true;
    await page.evaluate(async () => loadKnowledgeEsStatus());
    await page.locator("#knowledge-es-vector-sync").click();
    const sync = calls.find(call => call.path === "/api/knowledge/es-vector-sync");
    require(sync?.body.profile_id === "paraphrase-multilingual-minilm-l12" && sync.body.allow_model_download === true, `private sync did not use selected profile plus explicit consent: ${JSON.stringify(sync)}`);
    require(!calls.some(call => call.path === "/api/token-preview/status"), "MiniLM private sync incorrectly required the E5 tokenizer preview route");
    await page.waitForFunction(() => document.querySelector("#knowledge-es-status").textContent.includes("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"));
    require(!calls.some(call => /127\.0\.0\.1:9200|:8765/.test(JSON.stringify(call))), "protected shared service endpoint was referenced");
    console.log("R06 mock-only embedding profile browser flow passed; fixtures only, no model or Elasticsearch proof.");
  } finally {
    if (browser) await browser.close();
    child.kill("SIGTERM");
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
