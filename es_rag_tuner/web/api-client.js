"use strict";

// The request client receives its browser dependencies so callers can supply
// auth state and handle session expiry without coupling this module to the UI.
export function createApiClient({ fetchImpl, getCsrfToken, getIdentity, onUnauthorized }) {
  if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl is required");
  if (typeof getCsrfToken !== "function") throw new TypeError("getCsrfToken is required");
  if (typeof getIdentity !== "function") throw new TypeError("getIdentity is required");

  return async function api(path, body = {}) {
    const headers = { "Content-Type": "application/json" };
    const csrfToken = getCsrfToken();
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    const response = await fetchImpl(path, {
      method: "POST",
      headers,
      cache: "no-store",
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    let value;
    try { value = await response.json(); } catch { value = {}; }
    if (response.status === 401 && getIdentity() && path !== "/api/auth/login" && path !== "/api/auth/password/change") {
      onUnauthorized?.();
    }
    if (!response.ok) {
      const error = new Error(path === "/api/auth/login" && response.status === 401
        ? "사용자 이름 또는 비밀번호가 올바르지 않습니다."
        : (value.error || `요청 실패 (HTTP ${response.status})`));
      error.status = response.status;
      if (value.code) error.code = value.code;
      throw error;
    }
    return value;
  };
}
