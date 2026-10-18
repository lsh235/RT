"use strict";

// Run with: node tests/cycle37_auth_browser.js
// A fresh loopback port and temporary SQLite path are used for every run.
// Every browser request under /api/ is intercepted with synthetic responses.
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
    if (child.exitCode !== null) throw new Error("workbench exited during startup");
    try { if ((await fetch(url)).ok) return; } catch { /* wait for listener */ }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("workbench did not become ready");
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cycle37-auth-browser-"));
  const dbPath = path.join(tempDir, "synthetic.sqlite3");
  const port = await allocatePort();
  const base = "http://127.0.0.1:" + port;
  const child = spawn(process.env.PYTHON || "python3", ["-m", "es_rag_tuner", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root,
    env: { ...process.env, ES_RAG_CONCEPT_DB: dbPath, ES_RAG_ACCEPTANCE_ES_URL: "http://127.0.0.1:1" },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer(base + "/", child);
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CYCLE37_CHROMIUM_EXECUTABLE ? { executablePath: process.env.CYCLE37_CHROMIUM_EXECUTABLE } : {}),
      args: process.env.CYCLE37_CHROMIUM_EXECUTABLE ? ["--no-sandbox"] : [],
    });
    const page = await browser.newPage();
    const calls = [];
    const loginPassword = "Cycle37-browser-password-001!";
    let loggedIn = false;
    let force401 = false;
    const accounts = [{ id: "fixture-admin-id", username: "fixture-admin", display_name: "Fixture Admin", role: "admin", enabled: true }];
    await page.goto("about:blank");
    await page.addInitScript(() => { window.confirm = () => true; });
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const request = route.request();
      let body = {};
      try { if (request.method() === "POST") body = request.postDataJSON(); } catch { /* handled by default response */ }
      calls.push({ path: url.pathname, method: request.method(), body, headers: request.headers() });
      const json = (payload, status = 200, headers = {}) => route.fulfill({
        status, contentType: "application/json", headers, body: JSON.stringify(payload),
      });
      if (url.pathname === "/api/auth/session") {
        if (loggedIn) return json({ configured: true, authenticated: true, user: accounts[0], csrf_token: "fixture-session-csrf" });
        return json({ configured: true, authenticated: false, csrf_token: "fixture-login-csrf" }, 200, {
          "set-cookie": "es_rag_login_nonce=fixture-nonce; Path=/; HttpOnly; SameSite=Strict",
        });
      }
      if (url.pathname === "/api/auth/login") {
        if (body.password !== loginPassword || body.username !== "fixture-admin") return json({ error: "Invalid username or password" }, 401);
        loggedIn = true;
        return json({ configured: true, authenticated: true, user: accounts[0], csrf_token: "fixture-session-csrf" }, 200, {
          "set-cookie": "es_rag_session=opaque-fixture-session; Path=/; HttpOnly; SameSite=Strict",
        });
      }
      if (url.pathname === "/api/auth/logout") {
        loggedIn = false;
        return json({ authenticated: false }, 200, { "set-cookie": "es_rag_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" });
      }
      if (url.pathname === "/api/admin/accounts/list") return json({ accounts });
      if (url.pathname === "/api/admin/accounts/create") {
        accounts.push({ id: "fixture-user-id", username: body.username, display_name: body.display_name, role: "user", enabled: true });
        return json({ account: accounts.at(-1) }, 201);
      }
      if (url.pathname === "/api/admin/accounts/update") {
        const account = accounts.find(item => item.id === body.user_id);
        if (account) account.display_name = body.display_name;
        return json({ account });
      }
      if (url.pathname === "/api/admin/accounts/disable") return json({ disabled: true });
      if (url.pathname === "/api/admin/accounts/password/reset") return json({ reset: true });
      if (force401 && url.pathname === "/api/concepts/list") {
        force401 = false;
        loggedIn = false;
        return json({ error: "Authentication required" }, 401);
      }
      if (url.pathname === "/api/health") return json({ ok: true, version: "cycle37-test" });
      if (url.pathname === "/api/ai/status") return json({ providers: [] });
      if (url.pathname === "/api/codebase-status") return json({ indexed: false });
      if (url.pathname === "/api/concepts/list") return json({ concepts: [] });
      if (url.pathname === "/api/concepts/runs") return json({ runs: [] });
      return json({});
    });

    const require = (condition, message) => { if (!condition) throw new Error(message); };
    await page.goto(base + "/");
    await page.locator("#login-form").waitFor({ state: "visible" });
    await page.locator("#login-username").fill("fixture-admin");
    await page.locator("#login-password").fill(loginPassword);
    await page.locator("#login-form button[type=submit]").click();
    await page.locator("#workbench-layout").waitFor({ state: "visible" });
    require((await page.locator("#identity-indicator").innerText()).includes("Fixture Admin"), "authenticated identity is not visible");
    await page.locator("#admin-account-tools").waitFor({ state: "visible" });

    await page.locator("#new-username").fill("fixture-user");
    await page.locator("#new-display-name").fill("Fixture User");
    await page.locator("#new-account-password").fill("Cycle37-created-user-password-001!");
    await page.locator("#create-account-form button[type=submit]").click();
    await page.locator("#account-list").getByText("fixture-user").waitFor({ state: "visible" });
    require(calls.some(call => call.path === "/api/admin/accounts/create" && call.body.password === "Cycle37-created-user-password-001!"), "account creation did not submit its password");
    const userRow = page.locator("#account-list .account-row").filter({ hasText: "fixture-user" });
    await userRow.locator("input:not([type=password])").fill("Updated Fixture User");
    const accountRefresh = page.waitForRequest(request => new URL(request.url()).pathname === "/api/admin/accounts/list");
    await userRow.getByRole("button", { name: "이름 저장" }).click();
    await accountRefresh;
    await page.waitForFunction(() => Array.from(document.querySelectorAll("#account-list .account-row input:not([type=password])")).some(input => input.value === "Updated Fixture User"));
    require(calls.some(call => call.path === "/api/admin/accounts/update" && call.body.display_name === "Updated Fixture User"), "admin account update control did not call its API");
    page.on("dialog", dialog => dialog.accept());
    const resetPassword = "Cycle37-reset-user-password-001!";
    await page.evaluate(() => { window.confirm = () => true; });
    await userRow.locator("input[type=password]").fill(resetPassword);
    require(await userRow.locator("input[type=password]").evaluate(input => input.checkValidity()), "reset password input was invalid");
    const resetRequest = page.waitForRequest(request => new URL(request.url()).pathname === "/api/admin/accounts/password/reset", { timeout: 5000 });
    await userRow.getByRole("button", { name: "비밀번호 재설정" }).click();
    await resetRequest;
    await page.waitForFunction(() => document.querySelector("#admin-status")?.textContent.includes("비밀번호를 재설정"));
    require(calls.some(call => call.path === "/api/admin/accounts/password/reset" && call.body.user_id === "fixture-user-id" && call.body.new_password === resetPassword), "admin password-reset control did not call its API");
    require(await userRow.locator("input[type=password]").inputValue() === "", "password reset left the new password in the form");
    await userRow.getByRole("button", { name: "비활성화" }).click();
    require(calls.some(call => call.path === "/api/admin/accounts/disable" && call.body.user_id === "fixture-user-id"), "admin account disable control did not call its API");

    const browserStorage = await page.evaluate(() => ({
      entries: Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)])),
      visibleCookie: document.cookie,
    }));
    const serializedStorage = JSON.stringify(browserStorage.entries);
    require(!/(password|csrf|session|token|credential|secret|hash)/i.test(serializedStorage), "credential-like material was stored in localStorage");
    require(!serializedStorage.includes(loginPassword) && !serializedStorage.includes("fixture-session-csrf"), "password or CSRF token appeared in localStorage values");
    require(!browserStorage.visibleCookie.includes("opaque-fixture-session"), "HttpOnly session cookie is visible to page JavaScript");
    require(!browserStorage.visibleCookie.includes("fixture-session-csrf"), "CSRF token is visible in document.cookie");
    const loginCall = calls.find(call => call.path === "/api/auth/login");
    require(loginCall && loginCall.headers["x-csrf-token"] === "fixture-login-csrf", "login omitted pre-auth CSRF token");
    require(!loginCall.headers.cookie || !loginCall.headers.cookie.includes(loginPassword), "password leaked into cookies");

    // A protected API 401 must clear private UI state and return to login.
    force401 = true;
    await page.evaluate(async () => { try { await api("/api/concepts/list", {}); } catch { /* expected revoked session */ } });
    await page.locator("#login-form").waitFor({ state: "visible" });
    require(await page.locator("#workbench-layout").isHidden(), "401 left authenticated workbench content visible");

    await page.locator("#login-username").fill("fixture-admin");
    await page.locator("#login-password").fill(loginPassword);
    await page.locator("#login-form button[type=submit]").click();
    await page.locator("#workbench-layout").waitFor({ state: "visible" });
    await page.locator("#logout-button").click();
    await page.locator("#login-form").waitFor({ state: "visible" });
    const logoutCall = calls.findLast(call => call.path === "/api/auth/logout");
    require(logoutCall && logoutCall.headers["x-csrf-token"] === "fixture-session-csrf", "logout omitted session CSRF token");
    require(calls.filter(call => call.method === "POST").every(call => call.headers.origin === base), "POST API request did not retain same-origin header");
    require(calls.every(call => call.path.startsWith("/api/")), "fixture observed an unmocked API call");
    console.log(JSON.stringify({ result: "PASS", port, db: "temporary synthetic path", apiCalls: calls.length, adminCreate: true, loginLogout: true, storageCheck: true, revoked401Gate: true }));
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
