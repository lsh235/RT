"use strict";

// Cycle 38 knowledge-library UI smoke. All /api/** calls are deterministic mocks;
// only the static UI is served by the isolated loopback workbench process.
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
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle38-knowledge-browser-"));
  const dbPath = path.join(tempDir, "synthetic.sqlite3");
  const port = await allocatePort();
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.env.PYTHON || "python3", ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: dbPath, ES_RAG_ACCEPTANCE_ES_URL: "http://127.0.0.1:1" },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer(`${base}/`, child);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CYCLE38_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE38_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE38_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const calls = [];
    const pageErrors = [];
    const loginPassword = "Cycle38-browser-login-secret-001!";
    const csrfToken = "cycle38-browser-csrf-secret";
    const documentText = "# cycle38needle private procedure\n</pre><img id=cycle38-injected src=x onerror=alert(1)>\nKeep this local text.";
    const editedText = "Pasted cycle38updated notes, kept only in the account library.";
    const docs = new Map();
    let loggedIn = false;
    let nextId = 1;
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.addInitScript(() => { window.confirm = () => true; });
    await page.goto("about:blank");
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const request = route.request();
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch { /* keep a safe empty body */ }
      calls.push({ path: url.pathname, method: request.method(), body, headers: request.headers() });
      const json = (payload, status = 200, headers = {}) => route.fulfill({
        status, contentType: "application/json", headers, body: JSON.stringify(payload),
      });
      if (url.pathname === "/api/auth/session") {
        if (loggedIn) return json({ configured: true, authenticated: true, user: { id: "mock-admin", username: "cycle38-admin", display_name: "Cycle 38 Admin", role: "admin" }, csrf_token: csrfToken });
        return json({ configured: true, authenticated: false, csrf_token: "cycle38-login-csrf" }, 200, {
          "set-cookie": "es_rag_login_nonce=cycle38-nonce; Path=/; HttpOnly; SameSite=Strict",
        });
      }
      if (url.pathname === "/api/auth/login") {
        if (body.username !== "cycle38-admin" || body.password !== loginPassword) return json({ error: "Invalid username or password" }, 401);
        loggedIn = true;
        return json({ configured: true, authenticated: true, user: { id: "mock-admin", username: "cycle38-admin", display_name: "Cycle 38 Admin", role: "admin" }, csrf_token: csrfToken }, 200, {
          "set-cookie": "es_rag_session=mock-opaque-session; Path=/; HttpOnly; SameSite=Strict",
        });
      }
      if (url.pathname === "/api/auth/logout") {
        loggedIn = false;
        return json({ authenticated: false }, 200, { "set-cookie": "es_rag_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" });
      }
      if (url.pathname === "/api/health") return json({ ok: true, version: "cycle38-browser-fixture" });
      if (url.pathname === "/api/admin/accounts/list") return json({ accounts: [{ id: "mock-admin", username: "cycle38-admin", display_name: "Cycle 38 Admin", role: "admin", enabled: true }] });
      if (url.pathname === "/api/knowledge/list") return json({ documents: [...docs.values()].map(({ content, ...metadata }) => metadata) });
      if (url.pathname === "/api/knowledge/preview") return json({
        title: body.title, source_label: body.source_label || "", content_bytes: Buffer.byteLength(body.content || "", "utf8"),
        chunks: [{ ordinal: 0, start: 0, end: (body.content || "").length, content: body.content || "" }],
      });
      if (url.pathname === "/api/knowledge/save") {
        const id = body.document_id || `cycle38-doc-${nextId++}`;
        const prior = docs.get(id);
        const doc = { document_id: id, title: body.title, source_label: body.source_label || "", content: body.content,
          content_bytes: Buffer.byteLength(body.content || "", "utf8"), created_at: prior?.created_at || "2026-10-18T00:00:00+00:00", updated_at: "2026-10-18T00:00:01+00:00" };
        docs.set(id, doc);
        return json({ document: { ...doc, content: undefined }, chunks: [{ id: `${id}-chunk`, ordinal: 0, start: 0, end: doc.content.length, content: doc.content }] });
      }
      if (url.pathname === "/api/knowledge/get") {
        const doc = docs.get(body.document_id);
        return doc ? json({ ...doc, chunks: [{ id: `${doc.document_id}-chunk`, ordinal: 0, start: 0, end: doc.content.length, content: doc.content }] }) : json({ error: "Knowledge document not found" }, 404);
      }
      if (url.pathname === "/api/knowledge/search") {
        const needle = String(body.query || "").toLocaleLowerCase();
        const results = [...docs.values()].filter(doc => `${doc.title}\n${doc.content}`.toLocaleLowerCase().includes(needle)).map(doc => ({
          document_id: doc.document_id, title: doc.title, source_label: doc.source_label, chunk_id: `${doc.document_id}-chunk`,
          chunk: doc.content, excerpt: doc.content.slice(0, 280), score: -0.5,
        }));
        return json({ query: body.query, results });
      }
      if (url.pathname === "/api/knowledge/delete") return json({ deleted: docs.delete(body.document_id), document_id: body.document_id });
      return json({});
    });

    await page.goto(`${base}/`);
    await page.locator("#login-form").waitFor({ state: "visible" });
    await page.locator("#login-username").fill("cycle38-admin");
    await page.locator("#login-password").fill(loginPassword);
    await page.getByRole("button", { name: "로그인" }).click();
    await page.locator("#workbench-layout").waitFor({ state: "visible" });
    await page.getByRole("tab", { name: /내 지식/ }).click();

    await page.locator("#knowledge-file").setInputFiles({
      name: "cycle38-import.md", mimeType: "text/markdown", buffer: Buffer.from(documentText, "utf8"),
    });
    await page.locator("#knowledge-content").waitFor({ state: "visible" });
    await page.waitForFunction(expected => document.querySelector("#knowledge-content").value === expected, documentText);
    if (await page.locator("#knowledge-title").inputValue() !== "cycle38-import") throw new Error(".md import did not set its filename title");
    await page.locator("#knowledge-preview-button").click();
    await page.getByText("서버가 나눈 청크를 확인했습니다. 저장할 수 있습니다.").waitFor();
    const previewText = await page.locator("#knowledge-chunk-preview").innerText();
    if (!previewText.includes(documentText)) throw new Error("preview did not render the imported body as text");
    if (await page.locator("#knowledge-chunk-preview img, #knowledge-chunk-preview script").count()) throw new Error("HTML-looking document text created executable markup");
    await page.locator("#knowledge-save-button").click();
    await page.getByText("문서를 저장했습니다. 아래 청크는 서버가 저장한 결과입니다.").waitFor();
    await page.locator(".knowledge-row").filter({ hasText: "cycle38-import" }).waitFor();
    const documentId = [...docs.keys()][0];

    await page.locator(".knowledge-row").filter({ hasText: "cycle38-import" }).getByRole("button", { name: "열기" }).click();
    await page.waitForFunction(expected => document.querySelector("#knowledge-content").value === expected, documentText);
    await page.locator("#knowledge-query").fill("cycle38needle");
    await page.locator("#knowledge-search-form button[type=submit]").click();
    await page.locator(".knowledge-result").filter({ hasText: "cycle38-import" }).waitFor();
    await page.locator(".knowledge-result").getByRole("button", { name: "문서 열기" }).click();
    await page.waitForFunction(expected => document.querySelector("#knowledge-content").value === expected, documentText);

    await page.locator(".knowledge-row").filter({ hasText: "cycle38-import" }).getByRole("button", { name: "수정" }).click();
    await page.locator("#knowledge-content").fill(editedText);
    await page.locator("#knowledge-preview-button").click();
    await page.getByText("서버가 나눈 청크를 확인했습니다. 저장할 수 있습니다.").waitFor();
    await page.locator("#knowledge-save-button").click();
    await page.getByText("문서를 저장했습니다. 아래 청크는 서버가 저장한 결과입니다.").waitFor();
    if (docs.get(documentId)?.content !== editedText) throw new Error("paste/edit did not save the updated text");
    await page.locator("#knowledge-query").fill("cycle38updated");
    await page.locator("#knowledge-search-form button[type=submit]").click();
    await page.locator(".knowledge-result").filter({ hasText: "cycle38-import" }).waitFor();

    const storage = await page.evaluate(() => Object.fromEntries(Array.from({ length: localStorage.length }, (_, index) => {
      const key = localStorage.key(index); return [key, localStorage.getItem(key)];
    })));
    const storageText = JSON.stringify(storage);
    for (const secret of [documentText, editedText, "cycle38-import.md", loginPassword, csrfToken, "mock-opaque-session"]) {
      if (storageText.includes(secret)) throw new Error("document text, file name, or authentication data appeared in localStorage");
    }

    await page.locator(".knowledge-row").filter({ hasText: "cycle38-import" }).getByRole("button", { name: "삭제" }).click();
    await page.locator(".knowledge-row").waitFor({ state: "detached" });
    if (docs.size !== 0) throw new Error("delete did not remove the fixture document");
    await page.locator("#logout-button").click();
    await page.locator("#login-form").waitFor({ state: "visible" });
    if (loggedIn) throw new Error("logout did not clear the mocked authenticated session");
    if (pageErrors.length) throw new Error(`browser page errors: ${pageErrors.join(" | ")}`);

    const required = ["/api/auth/session", "/api/auth/login", "/api/knowledge/preview", "/api/knowledge/save", "/api/knowledge/list", "/api/knowledge/get", "/api/knowledge/search", "/api/knowledge/delete", "/api/auth/logout"];
    for (const route of required) if (!calls.some(call => call.path === route)) throw new Error(`missing API call: ${route}`);
    const knowledgeCalls = calls.filter(call => call.path.startsWith("/api/knowledge/"));
    if (knowledgeCalls.some(call => call.method === "POST" && call.headers["x-csrf-token"] !== csrfToken)) throw new Error("knowledge request omitted the authenticated CSRF header");
    console.log(JSON.stringify({ result: "PASS", evidence: "mocked API UI flow; static UI served by isolated loopback server", chromium: process.env.CYCLE38_CHROMIUM_EXECUTABLE || "Playwright default", apiCalls: calls.length, knowledgeCalls: knowledgeCalls.length, localStorage: "no document/file/auth markers", htmlTextRendering: "PASS", workflow: ["login", ".md import", "preview", "save", "list", "open", "search", "paste/edit", "search updated", "delete", "logout"] }));
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
