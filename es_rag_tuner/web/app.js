"use strict";

const DEFAULT_PROFILE = {
  error_signature: 4,
  summary: 3,
  "summary.code": 3.5,
  root_cause: 2.5,
  "root_cause.code": 2.5,
  workaround_or_fix: 2,
  description: 1,
  "description.code": 1,
  steps_to_reproduce: 1,
  rag_chunk_text: 1.5,
  "rag_chunk_text.code": 1.5,
  "comments.body": 1.5,
  "comments.body.code": 2,
};
const FIELD_LABELS = {
  error_signature: "error_signature",
  summary: "summary",
  "summary.code": "summary.code",
  root_cause: "root_cause",
  "root_cause.code": "root_cause.code",
  workaround_or_fix: "workaround_or_fix",
  description: "description",
  "description.code": "description.code",
  steps_to_reproduce: "steps_to_reproduce",
  rag_chunk_text: "rag_chunk_text",
  "rag_chunk_text.code": "rag_chunk_text.code",
  "comments.body": "comments.body",
  "comments.body.code": "comments.body.code",
};
const CHUNK_FIELDS = [
  ["summary", "요약"],
  ["error_signature", "에러 시그니처"],
  ["description", "설명"],
  ["steps_to_reproduce", "재현 단계"],
  ["root_cause", "근본 원인"],
  ["workaround_or_fix", "해결책"],
  ["comments", "댓글"],
  ["rag_chunk_text", "통합 rag_chunk_text"],
];
const state = {
  csrfToken: null,
  identity: null,
  connected: false,
  connectedIndex: "",
  connectedIndexExists: false,
  indices: [],
  filters: [],
  lastSearch: null,
  currentDocument: null,
  currentEmbeddingInput: null,
  tokenPreviewRequest: 0,
  lastEvaluation: null,
  bestProfile: null,
  embedding: null,
  embeddingIndex: "",
  embeddingProfiles: [],
  sharedProfileId: "e5-multilingual-large",
  privateProfileId: "e5-multilingual-large",
  privateSavedProfileId: "e5-multilingual-large",
  privateTokenizerStatus: null,
  privateProfileTouched: false,
  sampleExpectedCount: 0,
  codebaseStatus: null,
  conceptId: null,
  tuneReadinessTimer: null,
  tuneReadinessRequestId: 0,
  concepts: [],
  schema: [],
  schemaIndex: "",
  preview: null,
  vectorCandidateGeneration: 0,
  modeComparisonGeneration: 0,
  modeComparisonGroupGeneration: 0,
  modeComparisonGroupRunning: false,
  knowledgeDocumentId: null,
  knowledgePreviewKey: null,
  knowledgeEditing: true,
  knowledgeEval: null,
  knowledgeEvalRequest: 0,
  knowledgeEvalInFlight: false,
  knowledgeControlsBound: false,
  knowledgeReindexJobId: null,
  knowledgeReindexTimer: null,
  knowledgeImport: null,
  knowledgeRestore: null,
  conceptFilters: [],
  conceptSettings: { concept_weight: 1, related_weight: 1, size: 10, candidate_size: 50, mode: "bm25", rank_constant: 60, field_boosts: {} },
  aiProviders: [], aiSession: null, aiJobId: null, aiJobTimer: null, aiLastDraft: null, aiLastMessage: "",
  stagedAiResultContext: null, aiLastContext: null,
  profileVersions: [], quickstart: null, quickstartSampleIndex: 0,
  manualDocumentIndex: null,
  manualDocumentFromLocator: false,
  tuneMisses: null,
  connectionGeneration: 0,
  connectionAttemptInProgress: false,
  locatorRequestId: 0,
  informationNeedPreviewGeneration: 0,
  locale: "ko",
  connectionGuidance: { keys: ["connectHint"], index: "" },
  sampleImportedTarget: "",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function renderLocatorHighlight(value) {
  return escapeHtml(value)
    .replaceAll("&lt;em&gt;", "<mark>")
    .replaceAll("&lt;/em&gt;", "</mark>");
}

const RESULT_HIGHLIGHT_FIELDS = [
  ["summary", "요약"],
  ["error_signature", "에러 시그니처"],
  ["root_cause", "근본 원인"],
  ["workaround_or_fix", "해결책"],
  ["description", "설명"],
  ["rag_chunk_text", "RAG 청크"],
];

function renderResultHighlights(highlights, mode, retrievalScores) {
  const snippets = [];
  for (const [field, label] of RESULT_HIGHLIGHT_FIELDS) {
    const fragments = highlights?.[field];
    const fragment = Array.isArray(fragments) ? fragments[0] : fragments;
    if (typeof fragment !== "string" || !fragment) continue;
    const safeFragment = escapeHtml(fragment.slice(0, 240))
      .replaceAll("&lt;mark&gt;", "<mark>")
      .replaceAll("&lt;/mark&gt;", "</mark>");
    snippets.push(`<div class="result-highlight-fragment"><strong>${label}</strong><span>${safeFragment}</span></div>`);
    if (snippets.length === 2) break;
  }
  const vectorOnlyContext = mode === "vector" || (mode === "hybrid" && retrievalScores?.bm25 == null && retrievalScores?.vector != null);
  const unavailableCopy = vectorOnlyContext
    ? "벡터 검색에서 어휘 강조 발췌는 제공되지 않습니다. 발췌가 없다는 것만으로 문서가 무관하다고 볼 수 없습니다."
    : "반환된 강조 발췌가 없습니다. 발췌가 없다는 것만으로 문서가 무관하다고 볼 수 없습니다.";
  return `<div class="hit-section result-highlights"><strong>강조된 어휘/텍스트 문맥</strong>${snippets.length ? `<div class="result-highlight-list">${snippets.join("")}</div>` : `<p class="result-highlight-empty">${unavailableCopy}</p>`}<small>강조 표시는 검색 문맥이며 문서 관련성이나 답변 품질의 증명은 아닙니다.</small></div>`;
}

function showToast(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 3600);
}

function setBusy(button, busy, label) {
  if (!button.dataset.originalLabel) button.dataset.originalLabel = button.innerHTML;
  button.disabled = busy || !state.connected;
  button.innerHTML = busy ? `<span class="spinner"></span>${escapeHtml(label || "처리 중")}` : button.dataset.originalLabel;
}

function getConnection() {
  const authType = $("#auth-type").value;
  const auth = { type: authType };
  if (authType === "basic") {
    auth.username = $("#es-user").value;
    auth.password = $("#es-password").value;
  } else if (authType === "api_key") {
    auth.api_key = $("#es-api-key").value;
  }
  const url = safeEndpoint($("#es-url").value.trim());
  if (!url) throw new Error("endpoint-userinfo");
  return {
    url,
    auth,
  };
}

function safeEndpoint(value) {
  try {
    const parsed = new URL(value);
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password || parsed.search || parsed.hash) return "";
    return parsed.toString().replace(/\/$/, "");
  } catch { return ""; }
}

const UI_COPY = {
  ko: {
    endpointLabel: "Endpoint", authLabel: "인증 방식", authNone: "인증 없음", authBasic: "Basic Auth", authApiKey: "API Key", indexLabel: "검색 인덱스", searchTitle: "검색 실험", searchIntro: "BM25, dense vector, RRF를 비교하거나 코드 색인과 Jira 이슈를 함께 검색합니다.", searchQuery: "검색 질의", searchButton: "검색", searchEmptyTitle: "검색 실험을 시작하세요", searchEmptyCopy: "Elasticsearch에 연결한 다음 질문을 입력하면 실제 인덱스의 문서와 점수를 보여줍니다.",
    connectTitle: "Elasticsearch 연결", connectIntro: "연결 프로필에는 endpoint, 인덱스, 인증 방식만 저장합니다. 사용자 이름, 비밀번호, API 키는 저장하지 않습니다.", profilesTitle: "저장한 연결 프로필", noProfiles: "프로필 없음", profileLoad: "불러오기", profileSave: "현재 설정 저장", profileDelete: "선택 프로필 삭제", profileNote: "이 브라우저에 endpoint, 인덱스, 인증 방식만 저장합니다. 사용자 이름, 비밀번호, API 키는 저장하지 않습니다.", notConnected: "연결 전", connectHint: "먼저 연결하세요. 연결이 끝나면 인덱스 필드를 확인하고 첫 검색을 시작할 수 있습니다.", firstUsePath: "처음이라면 순서대로 진행하세요: 연결 → 필드 확인 및 적용 → 첫 검색 → 문서 관련도 저장 → 검색 모드 비교.", queryLabel: "어떤 내용을 찾고 싶나요?", firstSearchButton: "이 내용으로 결과 보기", queryHelp: "첫 질문은 설정 조정에 사용합니다. 다른 질문은 조정에 쓰지 않고 결과가 유지되는지 따로 확인할 수 있습니다.", modeHelp: "개념 검색은 선택한 필드에서 표현을 찾습니다. 벡터·혼합 검색은 ‘검색 실험’ 탭에서 계속 사용할 수 있습니다.",
    connectLabel: "연결 확인", connecting: "연결 중", checking: "Elasticsearch 확인 중", connected: "연결됨", failed: "연결 실패", invalid: "Endpoint 주소를 확인하세요. 사용자 이름, 비밀번호, query string, fragment를 URL에 넣지 말고 인증 칸을 사용하세요.", unreachable: "Elasticsearch에 연결할 수 없습니다. 주소와 서비스 상태를 확인한 뒤 다시 시도하세요.", forbidden: "접근 권한이 없습니다 (403). 계정에 클러스터/인덱스 읽기 권한이 있는지 관리자에게 확인하세요.", emptyIndex: "인덱스가 비어 있습니다. 필드와 문서가 있는 인덱스를 선택하거나, 새 인덱스에서만 선택 사항인 샘플 가져오기를 사용할 수 있습니다.", ready: "연결했습니다. 1단계에서 필드를 확인하고, 첫 검색 후 문서 관련도를 직접 저장하세요.", vectorUnavailable: "벡터 검색은 아직 준비되지 않았습니다. 일반 검색은 사용할 수 있습니다. 호환 벡터 매핑, 로컬 런타임, 문서 임베딩이 필요합니다.", sample: "현재 세션에서 명시적으로 가져온 제공 샘플", realIndex: "선택한 기존 인덱스 · 샘플 정체 미확인", newIndex: "선택한 새 인덱스 대상", sampleOptional: "새 인덱스에서 제공된 샘플을 가져올 수 있습니다. 가져오기는 선택 사항이며 기존 인덱스에는 적재하지 않습니다.", fieldLoading: "{index} 필드와 예시 문서를 불러오는 중…", fieldLoadFailed: "필드와 예시 문서를 불러오지 못했습니다. 연결 권한과 인덱스를 확인한 뒤 다시 시도하세요.", fieldSummary: "추천 필드 · 확인 후 적용", titleField: "제목", textField: "본문", filterField: "필터", applyFields: "추천 필드 적용", inspectCriteria: "추천 기준", fieldList: "필드 목록 보기 · {count}개", noTitleCandidate: "직접 선택 필요", noFields: "없음", samplePicker: "예시 문서 선택", sampleDoc: "예시 {n} / {total}", sampleTitle: "제목", missingSampleTitle: "추천 제목 필드에 값이 없습니다. 문서 ID {id}를 표시합니다.", noSampleBody: "추천 본문 필드에서 표시할 값이 없습니다.", sampleCaveat: "아래 문서는 몇 개의 예시일 뿐입니다. 전체 인덱스의 필드 포함 여부, 검색 가능성 또는 관련성을 나타내지 않습니다.", transferQuery: "검색 시작 문구로 옮기기", editableQueryNote: "예시에서 만든 편집 가능한 시작 문구입니다. 내용을 다듬은 뒤 직접 ‘이 내용으로 결과 보기’를 선택하세요.", noSampleDocs: "예시 문서가 없습니다. 연결과 인덱스를 확인하세요.", fieldsLoaded: "{count}개 필드를 확인했습니다. 추천을 적용하거나 고급 설정에서 직접 고를 수 있습니다.", fieldsApplied: "추천 필드를 적용했습니다. 제목과 본문 필드를 확인한 뒤 검색하세요.", fieldsAppliedToast: "추천 필드를 입력란에 적용했습니다. 저장 전에 목록을 확인하세요.", fieldApplySummary: "적용할 필드: 제목 {title} · 본문 {text} · 조건 필드 {filters}", sampleMissing: "{index} 인덱스가 아직 없습니다. 제공된 샘플 {count}건을 이 새 인덱스에 적재할 수 있습니다. 가져오기는 선택 사항이며 기존 인덱스는 덮어쓰지 않습니다.", sampleExisting: "기존 인덱스 · 문서 {count}건 · 샘플 정체 미확인 · 기존 인덱스에는 샘플을 적재하지 않습니다.", sampleImportedStatus: "현재 세션에서 제공 샘플을 명시적으로 가져왔습니다 · 문서 {count}건.", sampleMeta: "첨부 메타데이터 {metadata}건 · NDJSON 샘플 {count}건", judgment: "문서별 관련도를 직접 판단해 저장하세요. 이 기록은 자동 채점이 아닙니다.", comparison: "평가 기록이 생기면 검색 실험 또는 평가 및 튜닝에서 같은 질의로 BM25, 벡터, 혼합 모드를 비교할 수 있습니다. 비교 결과가 품질을 자동으로 판정하지는 않습니다."
  },
  en: {
    endpointLabel: "Endpoint URL", authLabel: "Authentication", authNone: "None", authBasic: "Basic Auth", authApiKey: "API Key", indexLabel: "Search index", searchTitle: "Search experiments", searchIntro: "Compare BM25, dense vector, and RRF, or search the code index with Jira issues.", searchQuery: "Search query", searchButton: "Search", searchEmptyTitle: "Start a search experiment", searchEmptyCopy: "Connect to Elasticsearch and enter a question to view documents and scores from the selected index.",
    connectTitle: "Connect Elasticsearch", connectIntro: "Profiles save only the endpoint, index, and authentication type. Usernames, passwords, and API keys are not saved.", profilesTitle: "Saved connection profiles", noProfiles: "No profiles", profileLoad: "Load", profileSave: "Save current settings", profileDelete: "Delete selected profile", profileNote: "Only the endpoint, index, and auth type are saved in this browser. Username, password, and API key are never saved.", notConnected: "Not connected", connectHint: "Connect first. Then inspect index fields and start your first search.", firstUsePath: "New here? Follow these steps: connect → inspect and apply fields → first search → save document relevance → compare search modes.", queryLabel: "What do you want to find?", firstSearchButton: "Show results for this query", queryHelp: "Your first query is used to tune settings. Try other queries separately to check whether results hold up.", modeHelp: "Concept search looks for terms in selected fields. Vector and hybrid search are available in the Search experiments tab.",
    connectLabel: "Check connection", connecting: "Connecting", checking: "Checking Elasticsearch", connected: "Connected", failed: "Connection failed", invalid: "Check the endpoint URL. Do not put usernames, passwords, query strings, or fragments in the URL; use the authentication fields.", unreachable: "Elasticsearch could not be reached. Check the endpoint and service, then try again.", forbidden: "Access denied (403). Ask an administrator to check cluster and index read permissions.", emptyIndex: "This index is empty. Select an index with fields and documents, or use the optional sample import only for a new index.", ready: "Connected. Inspect fields in step 1, search, then save your own relevance judgment.", vectorUnavailable: "Vector search is not ready. Standard search remains available. A compatible vector mapping, local runtime, and document embeddings are required.", sample: "Supplied sample data explicitly imported in this session", realIndex: "Selected existing index · sample identity unverified", newIndex: "Selected new index target", sampleOptional: "You can import the supplied sample into a new index. Import is optional and never writes into an existing index.", fieldLoading: "Loading fields and example documents for {index}…", fieldLoadFailed: "Could not load fields and example documents. Check index access and try again.", fieldSummary: "Suggested fields · review before applying", titleField: "Title", textField: "Text", filterField: "Filter", applyFields: "Apply suggested fields", inspectCriteria: "How suggestions are chosen", fieldList: "View all {count} fields", noTitleCandidate: "Choose manually", noFields: "None", samplePicker: "Choose an example document", sampleDoc: "Example {n} / {total}", sampleTitle: "Title", missingSampleTitle: "The suggested title field has no value. Showing document ID {id}.", noSampleBody: "No values to show from the suggested text fields.", sampleCaveat: "These are a few examples. They do not represent field coverage, searchability, or relevance for the full index.", transferQuery: "Use as a starting query", editableQueryNote: "This editable query was assembled from the example. Revise it, then choose “Show results for this query”.", noSampleDocs: "No example documents are available. Check the connection and index.", fieldsLoaded: "Reviewed {count} fields. Apply the suggestions or choose fields in advanced settings.", fieldsApplied: "Suggested fields are applied. Review the title and text fields, then search.", fieldsAppliedToast: "Suggested fields are in the form. Review them before saving.", fieldApplySummary: "Fields to apply: title {title} · text {text} · filter {filters}", sampleMissing: "Index {index} does not exist yet. You may import {count} supplied sample documents into this new index. Import is optional; existing indexes are not overwritten.", sampleExisting: "Selected existing index · {count} documents · sample identity unverified · sample import is unavailable for existing indexes.", sampleImportedStatus: "Supplied sample explicitly imported in this session · {count} documents.", sampleMeta: "Attached metadata: {metadata} · sample NDJSON: {count}", judgment: "Judge each document's relevance and save it yourself. This is not automatic grading.", comparison: "After saving judgments, compare BM25, vector, and hybrid modes for the same query in Search experiments or Evaluation. The comparison does not automatically determine quality."
  }
};

function copy(key) { return UI_COPY[state.locale]?.[key] || UI_COPY.ko[key] || key; }

function sampleTargetKey(endpoint, index) {
  return JSON.stringify([safeEndpoint(endpoint), String(index || "").trim()]);
}

function applyLocale(locale) {
  state.locale = locale === "en" ? "en" : "ko";
  document.documentElement.lang = state.locale;
  $("#ui-language").value = state.locale;
  $$('[data-i18n]').forEach(node => { const value = copy(node.dataset.i18n); if (value) node.textContent = value; });
  $("#es-url").setAttribute("aria-label", state.locale === "en" ? "Elasticsearch endpoint URL" : "Elasticsearch endpoint 주소");
  $("#index-name").setAttribute("aria-label", state.locale === "en" ? "Elasticsearch index name" : "Elasticsearch 인덱스 이름");
  const sharedProfileLabel = document.querySelector('label[for="embedding-profile-select"]');
  if (sharedProfileLabel) sharedProfileLabel.textContent = state.locale === "en" ? "Shared index embedding profile" : "공유 인덱스 임베딩 프로필";
  const privateProfileLabel = document.querySelector('label[for="knowledge-vector-profile-select"]');
  if (privateProfileLabel) privateProfileLabel.textContent = state.locale === "en" ? "Private vector profile" : "비공개 벡터 프로필";
  const sharedProfileHelp = $("#embedding-profile-help");
  if (sharedProfileHelp) sharedProfileHelp.textContent = state.locale === "en"
    ? "The selected profile recipe must match the indexed vectors before retrieval."
    : "선택한 프로필과 색인 벡터의 recipe 지문이 일치해야 검색할 수 있습니다.";
  $("#connection-profile-name").placeholder = state.locale === "en" ? "Profile name" : "프로필 이름";
  $("#connect-button").lastChild.textContent = ` ${copy("connectLabel")}`;
  const { keys, index, identity } = state.connectionGuidance;
  $("#connection-guidance").textContent = [...keys.map(copy), ...(index ? [`${copy(identity || "newIndex")}: ${index}.`] : [])].join(" ");
  $("#load-sample-button").textContent = state.locale === "en" ? "Import supplied sample into this new index" : "제공 샘플을 새 인덱스에 가져오기";
  if (state.sampleStatusInfo) renderSampleStatus(state.sampleStatusInfo);
  if (state.quickstart) renderQuickstartResult(state.quickstart);
  if (state.quickstartAppliedFields) renderAppliedQuickstartFields();
  renderConnectionProfiles?.();
  renderEmbeddingProfileDetails();
  if (state.embedding) renderEmbeddingStatus(state.embedding);
  if (state.lastSearch?.result && state.lastSearch.mode !== "code_rag") renderSearch(state.lastSearch.result, state.lastSearch.query);
  if (state.preview && state.preview.queryId) renderConceptPreview(state.preview, state.preview.queryId);
  if (state.preview?.queryId) $("#concept-preview-status").textContent = `${state.locale === "en" ? "Search complete" : "비교 완료"} · ${state.preview.query || (state.locale === "en" ? "Saved query" : "저장된 질의")}`;
}

function setConnectionGuidance(keys, index = "", identity = "newIndex") {
  state.connectionGuidance = { keys, index, identity };
  $("#connection-guidance").textContent = [...keys.map(copy), ...(index ? [`${copy(identity)}: ${index}.`] : [])].join(" ");
}

const PROFILE_STORAGE_KEY = "es-rag-connection-profiles";
function readConnectionProfiles() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROFILE_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter(profile => profile && typeof profile.name === "string" && safeEndpoint(profile.url) && typeof profile.index === "string" && ["none", "basic", "api_key"].includes(profile.auth_type)) : [];
  } catch { return []; }
}

function renderConnectionProfiles(selectedId = $("#connection-profile-select").value) {
  const select = $("#connection-profile-select");
  const profiles = readConnectionProfiles();
  select.replaceChildren(new Option(copy("noProfiles"), ""));
  for (const profile of profiles) select.add(new Option(profile.name, profile.id));
  if (profiles.some(profile => profile.id === selectedId)) select.value = selectedId;
  $("#delete-connection-profile").disabled = !select.value;
}

function saveConnectionProfile() {
  const name = $("#connection-profile-name").value.trim();
  const url = safeEndpoint($("#es-url").value.trim());
  if (!url) { $("#profile-status").textContent = copy("invalid"); return; }
  if (!name) { $("#profile-status").textContent = state.locale === "en" ? "Enter a profile name." : "프로필 이름을 입력하세요."; $("#connection-profile-name").focus(); return; }
  const profiles = readConnectionProfiles();
  const existing = profiles.find(profile => profile.name.toLocaleLowerCase() === name.toLocaleLowerCase());
  const profile = { id: existing?.id || crypto.randomUUID(), name, url, index: $("#index-name").value.trim(), auth_type: $("#auth-type").value };
  const updated = [...profiles.filter(item => item.id !== profile.id), profile];
  try {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(updated));
    renderConnectionProfiles(profile.id);
    $("#profile-status").textContent = state.locale === "en" ? "Saved in this browser. Credentials were not saved." : "이 브라우저에 저장했습니다. 인증정보는 저장하지 않았습니다.";
  } catch { $("#profile-status").textContent = state.locale === "en" ? "Browser storage is unavailable." : "브라우저 저장소를 사용할 수 없습니다."; }
}

function loadConnectionProfile() {
  const profile = readConnectionProfiles().find(item => item.id === $("#connection-profile-select").value);
  if (!profile) return;
  $("#es-url").value = safeEndpoint(profile.url);
  $("#index-name").value = profile.index;
  $("#auth-type").value = profile.auth_type;
  $("#basic-fields").classList.toggle("hidden", profile.auth_type !== "basic");
  $("#api-key-fields").classList.toggle("hidden", profile.auth_type !== "api_key");
  $("#profile-status").textContent = state.locale === "en" ? "Settings loaded. Enter credentials again if required." : "설정을 불러왔습니다. 필요한 인증정보는 다시 입력하세요.";
  saveNonSecretPreferences();
  setConnected(false);
  setConnectionStatus("idle", copy("notConnected"));
}

function deleteConnectionProfile() {
  const id = $("#connection-profile-select").value;
  if (!id) return;
  localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(readConnectionProfiles().filter(profile => profile.id !== id)));
  renderConnectionProfiles("");
  $("#profile-status").textContent = state.locale === "en" ? "Profile deleted." : "프로필을 삭제했습니다.";
}

function requestPayload(extra = {}) {
  return {
    connection: getConnection(),
    index: $("#index-name").value.trim(),
    ...extra,
  };
}

async function api(path, body = {}) {
  if (!apiRequest) throw new Error("브라우저 API 모듈을 불러오지 못했습니다.");
  return apiRequest(path, body);
}

function showAuth(message, mode = "login") {
  $("#workbench-layout").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  $("#auth-message").textContent = message;
  $("#login-form").classList.toggle("hidden", mode !== "login");
  $("#bootstrap-guidance").classList.toggle("hidden", mode !== "setup");
  $("#identity-indicator").classList.add("hidden");
  $("#logout-button").classList.add("hidden");
}

function enterWorkbench(session) {
  state.csrfToken = session.csrf_token || session.csrf || null;
  state.identity = session.user || null;
  $("#auth-screen").classList.add("hidden");
  $("#workbench-layout").classList.remove("hidden");
  const identity = state.identity;
  const label = identity?.display_name || identity?.username || "로그인 사용자";
  const indicator = $("#identity-indicator");
  indicator.textContent = `${label}${identity?.role === "admin" ? " · 관리자" : ""}`;
  indicator.classList.remove("hidden");
  $("#logout-button").classList.remove("hidden");
  $("#account-tools").classList.remove("hidden");
  $("#current-identity-copy").textContent = `현재 로그인: ${label} (${identity?.username || "계정"})`;
  $("#admin-account-tools").classList.toggle("hidden", identity?.role !== "admin");
  if (identity?.role === "admin") refreshAccounts();
}

async function refreshAuthSession(retryAfterUnauthorized = true) {
  try {
    const response = await fetch("/api/auth/session", { cache: "no-store", credentials: "same-origin" });
    if (response.status === 401 && retryAfterUnauthorized) { state.csrfToken = null; return refreshAuthSession(false); }
    const session = await response.json();
    if (!response.ok) throw new Error(session.error || `HTTP ${response.status}`);
    if (!session.configured) { state.csrfToken = null; showAuth("관리자 계정을 먼저 설정해야 합니다.", "setup"); return; }
    if (session.authenticated) { enterWorkbench(session); init(); return; }
    state.csrfToken = session.csrf_token || session.csrf || null;
    showAuth("사용자 이름과 비밀번호로 로그인하세요.");
  } catch (error) {
    showAuth(`로그인 상태를 확인하지 못했습니다: ${error.message}`);
  }
}

async function refreshAccounts() {
  const list = $("#account-list");
  list.replaceChildren();
  try {
    const result = await api("/api/admin/accounts/list", {});
    (result.accounts || []).forEach((account) => {
      const row = document.createElement("div"); row.className = "account-row";
      const detail = document.createElement("span"); detail.textContent = `${account.username} · ${account.role}${account.enabled === false ? " · 비활성" : ""}`;
      const name = document.createElement("input"); name.className = "text-input"; name.value = account.display_name || ""; name.setAttribute("aria-label", `${account.username} 표시 이름`);
      const save = document.createElement("button"); save.type = "button"; save.className = "button button-secondary button-small"; save.textContent = "이름 저장";
      save.addEventListener("click", async () => { try { await api("/api/admin/accounts/update", { user_id: account.id, display_name: name.value }); showToast("표시 이름을 저장했습니다."); await refreshAccounts(); } catch (error) { showToast(error.message, true); } });
      const disable = document.createElement("button"); disable.type = "button"; disable.className = "button button-secondary button-small"; disable.textContent = "비활성화"; disable.disabled = account.enabled === false || account.id === state.identity?.id;
      disable.addEventListener("click", async () => { if (!window.confirm(`${account.username} 계정을 비활성화할까요?`)) return; try { await api("/api/admin/accounts/disable", { user_id: account.id }); await refreshAccounts(); } catch (error) { showToast(error.message, true); } });
      row.append(detail, name, save, disable);
      if (account.id !== state.identity?.id) {
        const resetPassword = document.createElement("input"); resetPassword.type = "password"; resetPassword.className = "text-input"; resetPassword.autocomplete = "new-password"; resetPassword.minLength = 15; resetPassword.required = true; resetPassword.setAttribute("aria-label", `${account.username} 새 비밀번호 (최소 15자)`); resetPassword.placeholder = "새 비밀번호 · 최소 15자";
        const resetButton = document.createElement("button"); resetButton.type = "button"; resetButton.className = "button button-secondary button-small"; resetButton.textContent = "비밀번호 재설정";
        resetButton.addEventListener("click", async () => {
          if (!resetPassword.reportValidity()) return;
          if (!window.confirm(`${account.username} 계정의 비밀번호를 재설정할까요? 대상 계정의 기존 세션은 종료됩니다.`)) return;
          try { await api("/api/admin/accounts/password/reset", { user_id: account.id, new_password: resetPassword.value }); resetPassword.value = ""; $("#admin-status").textContent = `비밀번호를 재설정했습니다. 새 비밀번호를 ${account.username} 사용자에게 안전한 별도 경로로 전달하세요.`; }
          catch { resetPassword.value = ""; $("#admin-status").textContent = "비밀번호를 재설정하지 못했습니다. 입력값과 관리자 권한을 확인한 뒤 다시 시도하세요."; }
        });
        row.append(resetPassword, resetButton);
      }
      list.append(row);
    });
  } catch (error) { $("#admin-status").textContent = `계정 목록을 불러오지 못했습니다: ${error.message}`; }
}

function bindAuthControls() {
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const button = $("#login-form button[type=submit]"); button.disabled = true;
    try { const result = await api("/api/auth/login", { username: $("#login-username").value.trim(), password: $("#login-password").value }); $("#login-password").value = ""; enterWorkbench(result); init(); }
    catch (error) { $("#auth-message").textContent = error.message; $("#login-password").value = ""; if ([401, 403].includes(error.status) || /CSRF/i.test(error.message)) await refreshAuthSession(); }
    finally { button.disabled = false; }
  });
  $("#logout-button").addEventListener("click", async () => { try { await api("/api/auth/logout", {}); state.csrfToken = null; location.reload(); } catch (error) { showToast(error.message, true); } });
  $("#toggle-password-form").addEventListener("click", () => $("#password-form").classList.toggle("hidden"));
  $("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/auth/password/change", { current_password: $("#current-password").value, new_password: $("#new-password").value });
      state.csrfToken = null; state.identity = null; $("#password-form").reset();
      showAuth("비밀번호를 변경했습니다. 새 비밀번호로 다시 로그인하세요."); refreshAuthSession();
    } catch (error) {
      $("#password-form").reset();
      if (error.status === 401 && error.message !== "Current password is incorrect") {
        state.csrfToken = null; state.identity = null;
        showAuth("로그인 세션이 만료되었습니다. 다시 로그인하세요."); refreshAuthSession();
      } else if (error.status === 403 || /CSRF/i.test(error.message)) {
        state.csrfToken = null; state.identity = null;
        showAuth("로그인 세션이 만료되었습니다. 다시 로그인하세요."); refreshAuthSession();
      } else {
        $("#password-status").textContent = "비밀번호를 변경하지 못했습니다. 현재 비밀번호와 새 비밀번호 정책을 확인하세요.";
      }
    }
  });
  $("#create-account-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/admin/accounts/create", { username: $("#new-username").value.trim(), display_name: $("#new-display-name").value.trim(), password: $("#new-account-password").value }); $("#create-account-form").reset(); $("#admin-status").textContent = "계정을 만들었습니다."; await refreshAccounts(); } catch { $("#create-account-form").reset(); $("#admin-status").textContent = "계정을 만들지 못했습니다. 사용자 이름, 표시 이름, 비밀번호 정책을 확인하세요."; } });
}

function setConnectionStatus(mode, message) {
  const status = $("#connection-status");
  status.className = `connection-status ${mode}`;
  status.lastElementChild.textContent = message;
}

async function refreshCodebaseStatus() {
  const badge = $("#codebase-index-status");
  try {
    const response = await fetch("/api/codebase-status", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    state.codebaseStatus = result;
    if (result.indexed) {
      const nodes = Number(result.nodes || 0).toLocaleString();
      badge.textContent = `gRPC 코드 색인 · ${nodes} nodes`;
      badge.title = `${result.repo_path}\n${result.branch || "branch 미상"} @ ${result.commit || "commit 미상"}\n미파싱 일부 파일: ${result.partial_parse_files || 0}`;
      badge.classList.remove("codebase-unavailable");
    } else {
      badge.textContent = "gRPC 코드 색인 사용 불가";
      badge.title = result.repo_path || result.error || "색인 상태를 확인할 수 없습니다.";
      badge.classList.add("codebase-unavailable");
    }
  } catch (error) {
    state.codebaseStatus = null;
    badge.textContent = "gRPC 코드 색인 확인 실패";
    badge.title = error.message;
    badge.classList.add("codebase-unavailable");
  }
}

function saveNonSecretPreferences() {
  try {
    const url = safeEndpoint($("#es-url").value.trim());
    if (url) localStorage.setItem("es-rag-url", url);
    else localStorage.removeItem("es-rag-url");
    localStorage.setItem("es-rag-index", $("#index-name").value.trim());
    localStorage.setItem("es-rag-auth-type", $("#auth-type").value);
  } catch { /* Private browsing can disable localStorage. */ }
}

function setConnected(enabled) {
  if (state.connected !== enabled) state.informationNeedPreviewGeneration += 1;
  state.connected = enabled;
  if (!enabled) clearVectorCandidatePool("Elasticsearch 연결이 끊겨 후보 목록을 지웠습니다. 다시 연결하고 BM25 비교부터 실행하세요.");
  $("#search-button").disabled = !enabled;
  $("#evaluate-button").disabled = !enabled;
  $("#tune-button").disabled = !enabled;
  $("#load-sample-button").disabled = !enabled || !state.canImportSample;
  const selectedDimensions = Number(selectedEmbeddingProfile()?.dimensions || 1024);
  $("#vectorize-button").disabled = !enabled || !state.embedding?.mapping_available || Number(state.embedding.mapping_dimensions) !== selectedDimensions || state.embedding.mapping_compatible === false || !state.embedding.runtime_installed || state.embedding.vector_count >= state.embedding.document_count;
  $("#concept-preview").disabled = !enabled;
  $("#concept-tune").disabled = !enabled;
  $("#refresh-schema").disabled = !enabled;
  updateManualDocumentActions();
  updateInformationNeedPreviewAction();
  renderSampleOnboarding();
  $("#quickstart-fields").disabled = !enabled;
  $("#guided-first-preview").disabled = !enabled;
  $("#ai-send").disabled = !enabled;
  $("#refresh-profile-versions").disabled = !state.conceptId;
  $("#export-concept-profile").disabled = !state.conceptId;
  renderSearchReadiness();
}

function updateManualDocumentActions() {
  const ready = state.connected && Boolean(state.conceptId) && Boolean($("#manual-document-id").value.trim()) && Boolean($("#manual-query-id").value);
  $("#fetch-manual-document").disabled = !ready;
  $("#diagnose-manual-document").disabled = !ready;
  $("#locate-document-button").disabled = !state.connected || !state.conceptId || !$("#locate-document-text").value.trim();
}

function tuneMissConceptScope(concept) { return cycle44Feature?.tuneMissConceptScope(concept) || ""; }
function tuneMissScopeCurrent() { return cycle44Feature?.tuneMissScopeCurrent() || false; }
function refreshTuneMissHandoffs() { cycle44Feature?.refreshTuneMissHandoffs(); }
function advanceConnectionGeneration() { cycle44Feature?.advanceConnectionGeneration(); }
function renderTuneMisses(result, sentConcept, connectionGeneration) { return cycle44Feature?.renderTuneMisses(result, sentConcept, connectionGeneration) || ""; }
function handoffTuneMiss(button) { return cycle44Feature?.handoffTuneMiss(button); }

function clearDocumentLocatorState() {
  state.locatorRequestId += 1;
  state.manualDocumentIndex = null;
  if (state.manualDocumentFromLocator) $("#manual-document-id").value = "";
  state.manualDocumentFromLocator = false;
  $("#locate-document-results").replaceChildren();
  $("#manual-document-result").replaceChildren();
  $("#manual-document-diagnosis").replaceChildren();
  updateManualDocumentActions();
}

function renderDocumentLocatorResults(result) {
  const host = $("#locate-document-results");
  const candidates = Array.isArray(result.candidates) ? result.candidates.slice(0, 10) : [];
  if (!candidates.length) {
    host.innerHTML = '<div class="notice notice-muted">이번 찾기에서는 선택된 개념의 제목·본문 필드에서 일치 후보를 찾지 못했습니다. 다른 단어를 입력하거나 문서 ID를 알고 있다면 직접 입력하세요. 이것만으로 문서가 인덱스에 없다고 판단할 수는 없습니다.</div>';
    return;
  }
  host.innerHTML = `<div class="locator-candidates"><p class="helper-text">후보를 찾았습니다. 후보를 고르면 문서 ID가 입력됩니다. 아래 필드와 발췌는 Elasticsearch가 반환한 어휘 일치 문맥이며 관련성이나 답변 품질의 증명은 아닙니다. 저장 질의 선택과 평가는 직접 진행하세요.</p>${candidates.map((candidate) => `<article class="locator-candidate"><div><strong>${escapeHtml(candidate.title || candidate.document_id)}</strong><code>${escapeHtml(candidate.document_index)} / ${escapeHtml(candidate.document_id)}</code>${candidate.excerpt ? `<p>${renderLocatorHighlight(candidate.excerpt)} <small>· Elasticsearch 일치 문맥 · ${escapeHtml(candidate.excerpt_field || "")}</small></p>` : candidate.excerpt_is_nested ? '<p class="muted">중첩 필드에서 후보가 나왔습니다. 이 미리보기에는 중첩 내용을 표시하지 않습니다.</p>' : '<p class="muted">표시할 어휘 일치 미리보기가 없습니다. 그래도 검색 후보로 반환된 문서입니다.</p>'}</div><button class="button button-secondary locator-select" data-document-index="${escapeHtml(candidate.document_index)}" data-document-id="${escapeHtml(candidate.document_id)}">이 문서를 평가 대상으로 선택</button></article>`).join("")}</div>`;
}

async function locateManualDocument() {
  const text = $("#locate-document-text").value.trim();
  if (!text || !state.conceptId) return;
  const button = $("#locate-document-button");
  const requestId = ++state.locatorRequestId;
  button.disabled = true;
  $("#locate-document-results").innerHTML = '<span class="loading-inline"><i class="spinner"></i> 저장된 개념의 설정 필드에서 후보를 찾고 있습니다.</span>';
  try {
    const result = await api("/api/concepts/locate-document", { connection: getConnection(), concept_id: state.conceptId, text });
    if (requestId !== state.locatorRequestId) return;
    renderDocumentLocatorResults(result);
  } catch (error) {
    if (requestId !== state.locatorRequestId) return;
    $("#locate-document-results").innerHTML = `<div class="notice notice-error">문서 찾기를 완료하지 못했습니다. 연결을 확인한 뒤 다시 시도하세요. ${escapeHtml(error.message)}</div>`;
  } finally { if (requestId === state.locatorRequestId) updateManualDocumentActions(); }
}

function selectLocatedDocument(index, id) {
  state.manualDocumentIndex = index;
  state.manualDocumentFromLocator = true;
  $("#manual-document-id").value = id;
  updateManualDocumentActions();
  showToast("문서 ID를 입력했습니다. 저장 질의를 고른 뒤 직접 불러오거나 원인을 확인하세요.");
}

function populateIndexSuggestions(indices) {
  let list = $("#index-options");
  if (!list) {
    list = document.createElement("datalist");
    list.id = "index-options";
    $("#index-name").after(list);
    $("#index-name").setAttribute("list", "index-options");
  }
  list.replaceChildren(...indices.map((item) => {
    const option = document.createElement("option");
    option.value = item.index;
    return option;
  }));
}

async function connect() {
  if (state.connectionAttemptInProgress) return;
  state.connectionAttemptInProgress = true;
  const button = $("#connect-button");
  const refreshButton = $("#refresh-indices");
  state.sharedProfileId = $("#embedding-profile-select")?.value || state.sharedProfileId || "e5-multilingual-large";
  button.disabled = true;
  refreshButton.disabled = true;
  advanceConnectionGeneration();
  clearDocumentLocatorState();
  state.canImportSample = false;
  renderSampleOnboarding();
  state.embedding = null;
  state.embeddingIndex = "";
  state.connectedIndex = "";
  state.connectedIndexExists = false;
  renderSearchReadiness();
  updateModeComparisonGroupAction();
  button.innerHTML = `<span class="spinner"></span> ${copy("connecting")}`;
  setConnectionStatus("idle", copy("checking"));
  setConnectionGuidance(["checking"]);
  $("#cluster-summary").classList.add("hidden");
  try {
    const result = await api("/api/connect", requestPayload({ profile_id: state.sharedProfileId }));
    await loadEmbeddingProfiles();
    state.indices = result.indices || [];
    state.embedding = result.embedding || null;
    state.embeddingIndex = result.selected_index || $("#index-name").value.trim();
    state.connectedIndex = result.selected_index || $("#index-name").value.trim();
    state.connectedIndexExists = Boolean(result.selected_index_exists);
    populateIndexSuggestions(state.indices);
    setConnected(true);
    setConnectionStatus("connected", copy("connected"));
    const selected = escapeHtml(result.selected_index);
    const indexLine = result.selected_index_exists
      ? `${Number(result.selected_index_count).toLocaleString()}개 문서`
      : "인덱스 없음";
    $("#cluster-summary").innerHTML = `<strong>${escapeHtml(result.cluster_name || "Elasticsearch")}</strong><br>버전 ${escapeHtml(result.version)} · ${selected}<br>${indexLine}`;
    $("#cluster-summary").classList.remove("hidden");
    $("#search-index-badge").textContent = result.selected_index;
    const sample = {
      index: result.selected_index,
      exists: result.selected_index_exists,
      document_count: result.selected_index_count,
      sample_expected_count: result.sample_expected_count,
      metadata_count: result.sample_data_metadata_count,
      can_import: !result.selected_index_exists,
    };
    renderSampleStatus(sample);
    renderEmbeddingStatus(state.embedding);
    const empty = !result.selected_index_exists || Number(result.selected_index_count) === 0;
    const selectedDimensions = Number(selectedEmbeddingProfile()?.dimensions || 1024);
    const vectorNotReady = !state.embedding?.mapping_available || Number(state.embedding.mapping_dimensions) !== selectedDimensions || state.embedding.mapping_compatible === false || !state.embedding?.runtime_installed || (Number(state.embedding?.document_count) > 0 && Number(state.embedding?.vector_count) === 0);
    const guidanceKeys = [empty ? "emptyIndex" : "ready", ...(vectorNotReady ? ["vectorUnavailable"] : []), ...(!result.selected_index_exists ? ["sampleOptional"] : [])];
    const identity = state.sampleImportedTarget === sampleTargetKey($("#es-url").value, result.selected_index) ? "sample" : result.selected_index_exists ? "realIndex" : "newIndex";
    setConnectionGuidance(guidanceKeys, result.selected_index, identity);
    $("#concept-index-badge").textContent = result.selected_index;
    await loadConcepts();
    await loadCorpusSchema();
    await loadConceptRuns();
    await loadAiStatus();
    if (!state.conceptId) await runQuickstart();
    saveNonSecretPreferences();
    resetAiIfScopeChanged();
    showToast(`Elasticsearch ${result.version} 연결 완료`);
  } catch (error) {
    state.connectedIndex = "";
    state.connectedIndexExists = false;
    setConnected(false);
    state.canImportSample = false;
    renderSampleOnboarding();
    renderSearchReadiness();
    setConnectionStatus("error", copy("failed"));
    const recovery = error.message === "endpoint-userinfo" ? copy("invalid")
      : error.status === 403 ? copy("forbidden")
        : /invalid|url|scheme|endpoint/i.test(error.message) ? copy("invalid") : copy("unreachable");
    setConnectionGuidance([error.message === "endpoint-userinfo" ? "invalid" : error.status === 403 ? "forbidden" : /invalid|url|scheme|endpoint/i.test(error.message) ? "invalid" : "unreachable"]);
    $("#sample-status").textContent = "Elasticsearch에 연결한 뒤 샘플 상태를 확인하세요.";
    $("#sample-status").className = "sample-status";
    showToast(recovery, true);
  } finally {
    state.connectionAttemptInProgress = false;
    advanceConnectionGeneration();
    updateModeComparisonGroupAction();
    button.disabled = false;
    refreshButton.disabled = false;
    button.innerHTML = `<span class="button-icon">↗</span> ${copy("connectLabel")}`;
  }
}

function renderEmbeddingStatus(info) {
  const status = $("#embedding-status");
  if (!info) { renderSearchReadiness(); return; }
  const english = state.locale === "en";
  const profile = selectedEmbeddingProfile();
  const dimensions = Number(profile?.dimensions || info.profile_dimensions || 1024);
  const profileName = profile?.model_name || info.model_name || state.sharedProfileId;
  $("#sample-document-count").textContent = Number(info.document_count || 0).toLocaleString();
  $("#embedding-count").textContent = Number(info.vector_count || 0).toLocaleString();
  if (!info.mapping_available) {
    status.className = "notice notice-muted";
    status.textContent = english
      ? `The selected index has no ${dimensions}-dimension rag_embedding mapping. Use the supplied sample index or prepare a mapping for this profile.`
      : `선택한 인덱스에 ${dimensions}차원 rag_embedding 매핑이 없습니다. 제공 샘플 인덱스를 사용하거나 선택한 프로필의 매핑을 준비하세요.`;
  } else if (info.mapping_compatible === false) {
    status.className = "notice notice-error";
    status.textContent = `${english
      ? `Stored vector recipe does not match ${profileName} (${dimensions}d); index mapping is ${info.mapping_dimensions}d. Different embedding spaces are incompatible.`
      : `기존 벡터의 recipe가 ${profileName} (${dimensions}차원) 프로필과 다릅니다. 현재 매핑은 ${info.mapping_dimensions}차원이며 다른 임베딩 공간은 호환되지 않습니다.`}${info.mapping_error ? ` · ${info.mapping_error}` : ""}`;
    status.title = info.mapping_error || "";
  } else if (Number(info.mapping_dimensions) !== dimensions) {
    status.className = "notice notice-muted";
    status.textContent = english
      ? `rag_embedding is ${info.mapping_dimensions}d, but ${profileName} requires ${dimensions}d. Vector work is unavailable.`
      : `rag_embedding 매핑은 ${info.mapping_dimensions}차원입니다. ${profileName} 프로필은 ${dimensions}차원이므로 벡터 작업을 할 수 없습니다.`;
  } else if (!info.runtime_installed) {
    status.className = "notice notice-muted";
    status.innerHTML = `${english ? "dense_vector" : "dense_vector"} ${escapeHtml(info.mapping_dimensions)}${english ? "d ready · install FastEmbed runtime" : "차원 준비됨 · FastEmbed 런타임 설치 필요"}<br><code>${escapeHtml(info.install_command)}</code>`;
  } else if (!info.model_cached) {
    status.className = "notice notice-muted";
    status.textContent = english
      ? `Mapping ready · ${profileName} can be downloaded into the local cache after explicit consent for vectorization or the first query.`
      : `매핑 준비됨 · ${profileName} 모델은 동의한 벡터 생성 또는 첫 질의에서 로컬 캐시에 내려받을 수 있습니다.`;
  } else if (info.vector_count >= info.document_count && info.document_count > 0) {
    status.className = "notice notice-success";
    status.textContent = english
      ? `${info.vector_count} documents have vectors · ${profileName} · ${dimensions}d`
      : `${info.vector_count}개 문서 임베딩 완료 · ${profileName} · ${dimensions}차원`;
  } else {
    status.className = "notice notice-muted";
    status.textContent = english
      ? `${info.vector_count}/${info.document_count} documents have vectors · ${profileName} · ${dimensions}d`
      : `${info.vector_count}/${info.document_count}개 문서에 임베딩이 있습니다 · ${profileName} · ${dimensions}차원`;
  }
  $("#vectorize-button").disabled = !state.connected || !info.mapping_available || Number(info.mapping_dimensions) !== dimensions || info.mapping_compatible === false || !info.runtime_installed || info.vector_count >= info.document_count;
  $("#vectorize-button").textContent = info.model_cached
    ? (english ? "Create missing vectors" : "누락 임베딩 생성")
    : (english ? "Consent and download model" : "동의 후 모델 다운로드 및 생성");
  renderSearchReadiness();
}

function selectedEmbeddingProfile(profileId = state.sharedProfileId) {
  return state.embeddingProfiles.find((profile) => profile.profile_id === profileId)
    || ({
      "e5-multilingual-large": { profile_id: "e5-multilingual-large", model_name: "intfloat/multilingual-e5-large", dimensions: 1024, max_tokens: 512, license: "mit" },
      "paraphrase-multilingual-minilm-l12": { profile_id: "paraphrase-multilingual-minilm-l12", model_name: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", dimensions: 384, max_tokens: 128, license: "apache-2.0" },
    })[profileId] || null;
}

async function loadEmbeddingProfiles() {
  try {
    const response = await fetch("/api/embedding/profiles", { cache: "no-store" });
    const value = await response.json();
    if (!response.ok || !Array.isArray(value.profiles)) return;
    state.embeddingProfiles = value.profiles;
    if (!$("#embedding-profile-select").dataset.touched) state.sharedProfileId = value.default_profile_id || state.sharedProfileId;
    const renderOptions = (select, selectedId) => {
      if (!select) return;
      const prior = select.value || selectedId;
      select.replaceChildren(...value.profiles.map((profile) => {
        const option = document.createElement("option");
        option.value = profile.profile_id;
        const statusLabels = state.locale === "en"
          ? { cached: "cached", model_not_cached: "model not cached", dependency_missing: "runtime missing", loading_failure: "load failed" }
          : { cached: "캐시됨", model_not_cached: "모델 캐시 없음", dependency_missing: "런타임 설치 필요", loading_failure: "불러오기 실패" };
        const dimensions = state.locale === "en" ? `${profile.dimensions}d` : `${profile.dimensions}차원`;
        option.textContent = `${profile.model_name} · ${dimensions} · ${statusLabels[profile.setup_state] || profile.setup_state || (state.locale === "en" ? "status unknown" : "상태 확인 불가")}`;
        return option;
      }));
      select.value = value.profiles.some((profile) => profile.profile_id === prior) ? prior : (value.default_profile_id || value.profiles[0]?.profile_id || "");
    };
    renderOptions($("#embedding-profile-select"), state.sharedProfileId);
    renderOptions($("#knowledge-vector-profile-select"), state.privateProfileId);
    state.sharedProfileId = $("#embedding-profile-select").value || state.sharedProfileId;
    if (!state.privateProfileTouched) state.privateProfileId = $("#knowledge-vector-profile-select").value || state.privateProfileId;
    renderEmbeddingProfileDetails();
    if (state.embedding) renderEmbeddingStatus(state.embedding);
  } catch { /* Profile discovery is supplemental; legacy E5 controls remain usable. */ }
}

function renderEmbeddingProfileDetails() {
  const format = (profileId) => {
    const profile = selectedEmbeddingProfile(profileId);
    if (!profile) return state.locale === "en" ? "Profile details are unavailable." : "프로필 정보를 확인할 수 없습니다.";
    const english = state.locale === "en";
    const query = profile.query_prefix || (english ? "none" : "없음");
    const passage = profile.passage_prefix || (english ? "none" : "없음");
    const context = profile.max_tokens || profile.context_tokens || "?";
    const revision = profile.source_revision || (english ? "resolved when cached" : "캐시 준비 시 확인");
    const source = profile.source_repo || profile.recipe?.source_repo || (english ? "source unavailable" : "출처 확인 불가");
    const fastembed = profile.fastembed_version || profile.recipe?.fastembed_version || "?";
    const similarity = profile.similarity || profile.recipe?.similarity || "cosine";
    const normalized = profile.normalized ?? profile.recipe?.normalized;
    const fingerprint = profile.recipe_fingerprint || profile.recipe?.recipe_fingerprint || "";
    const setup = profile.setup_state || profile.status || "unavailable";
    const runtime = profile.runtime_installed ? (english ? "runtime installed" : "런타임 설치됨") : (english ? "runtime missing" : "런타임 없음");
    const tokenizerRuntime = profile.tokenizer_runtime_installed == null
      ? (english ? "tokenizer runtime status unavailable" : "tokenizer 런타임 상태 확인 불가")
      : profile.tokenizer_runtime_installed
        ? `${english ? "tokenizer runtime installed" : "tokenizer 런타임 설치됨"}${profile.tokenizer_runtime_version ? ` ${profile.tokenizer_runtime_version}` : ""}`
        : (english ? "tokenizer runtime missing" : "tokenizer 런타임 없음");
    const cached = profile.model_cached ? (english ? "model cached" : "모델 캐시됨") : (english ? "model not cached" : "모델 캐시 없음");
    const stateMessages = english
      ? { cached: "Model is ready locally.", model_not_cached: "Model is not cached; explicit consent is required before download.", dependency_missing: "Install the optional FastEmbed runtime.", loading_failure: "Model could not be loaded; check the local install and cache." }
      : { cached: "로컬 모델이 준비되었습니다.", model_not_cached: "모델이 캐시에 없습니다. 다운로드 전에 명시적 동의가 필요합니다.", dependency_missing: "선택 FastEmbed 런타임을 설치하세요.", loading_failure: "모델을 불러오지 못했습니다. 설치와 캐시를 확인하세요." };
    const safeMessage = stateMessages[setup] ? ` · ${stateMessages[setup]}` : "";
    return state.locale === "en"
      ? `Query prefix: ${query} · Passage prefix: ${passage} · Context: ${context} tokens · License: ${profile.license || "see model source"} · Source: ${source} · Revision: ${revision} · FastEmbed: ${fastembed} · ${tokenizerRuntime} · Similarity: ${similarity} · Normalized: ${normalized == null ? "unknown" : normalized} · Recipe: ${fingerprint || "not resolved"} · ${runtime} · ${cached} · Setup: ${setup}${safeMessage}`
      : `질의 접두사: ${query} · 문서 접두사: ${passage} · 입력 한도: ${context}토큰 · 라이선스: ${profile.license || "모델 출처 확인"} · 출처: ${source} · revision: ${revision} · FastEmbed: ${fastembed} · ${tokenizerRuntime} · 유사도: ${similarity} · 정규화: ${normalized == null ? "확인 불가" : normalized ? "예" : "아니요"} · recipe 지문: ${fingerprint || "미확정"} · ${runtime} · ${cached} · 설정: ${setup}${safeMessage}`;
  };
  const shared = $("#embedding-profile-help");
  if (shared) {
    const guidance = state.locale === "en"
      ? "The selected profile recipe must match the indexed vectors before retrieval. "
      : "선택한 프로필과 색인 벡터의 recipe 지문이 일치해야 검색할 수 있습니다. ";
    shared.textContent = guidance + format(state.sharedProfileId);
  }
  const privateHelp = $("#knowledge-vector-profile-help");
  if (privateHelp) {
    const guidance = state.locale === "en"
      ? "This profile applies to the next explicitly approved private vector generation. "
      : "이 프로필은 다음에 명시적으로 동의한 개인 벡터 generation에 적용됩니다. ";
    privateHelp.textContent = guidance + format(state.privateProfileId);
  }
}

function isVectorDependentMode(mode) {
  return ["vector", "hybrid", "code_rag"].includes(mode);
}

function searchModeReadiness(mode = $("#search-mode").value) {
  if (!isVectorDependentMode(mode)) return { active: false, blocked: false, paragraphs: [], plain: "" };
  if (mode === "vector" || mode === "hybrid") {
    const info = state.embedding;
    const profile = selectedEmbeddingProfile();
    const dimensions = Number(profile?.dimensions || 1024);
    const sharedCanRun = !!(state.connected && info?.mapping_available && Number(info.mapping_dimensions) === dimensions && info.mapping_compatible !== false && info.runtime_installed && Number(info.vector_count) > 0);
    const paragraphs = [
      `${mode === "vector" ? "벡터" : "하이브리드"} 검색은 공유 인덱스에서 ${profile?.model_name || "선택한 임베딩 프로필"} (${dimensions}차원)를 사용하고, 내 비공개 지식은 저장된 개인 프로필을 사용합니다.`,
      "내 비공개 lane은 ‘내 지식’에서 명시적으로 벡터 동기화를 마친 경우에만 결과를 제공합니다. 모델 또는 매핑이 준비되지 않은 lane은 unavailable 상태로 표시됩니다.",
      "공유 결과와 비공개 결과는 합쳐지지 않습니다. 모델·revision·prefix 지문이 다른 벡터는 차원이 같아도 함께 검색하지 않습니다.",
    ];
    if (info?.mapping_compatible === false) paragraphs.push(state.locale === "en"
      ? (info.mapping_error || "The shared index vector recipe does not match the selected profile.")
      : "공유 인덱스의 벡터 recipe가 선택한 프로필과 다릅니다. 같은 차원이어도 다른 recipe는 함께 검색하지 않습니다.");
    return { active: true, blocked: false, requiresModelDownload: sharedCanRun && !info.model_cached, paragraphs, plain: paragraphs.join(" ") };
  }
  const selectedIndex = $("#index-name").value.trim();
  const info = state.embedding;
  const modeLabel = mode === "vector" ? "벡터 검색" : mode === "hybrid" ? "하이브리드 검색" : "코드 + Jira RAG";
  if (!state.connected || !info || !state.embeddingIndex) {
    const paragraphs = [
      `${modeLabel}: 최신 연결에서 벡터 준비 상태를 확인할 수 없습니다. 다시 연결해 상태를 갱신하세요.`,
      "벡터가 필요한 검색을 시작할 수 없습니다. BM25 검색은 계속 사용할 수 있습니다.",
      "저장된 벡터를 만든 모델의 출처는 확인할 수 없습니다.",
    ];
    return { active: true, blocked: true, paragraphs, plain: paragraphs.join(" ") };
  }
  if (state.embeddingIndex !== selectedIndex) {
    const paragraphs = [
      `현재 검색 인덱스 ${selectedIndex || "(미선택)"}와 마지막 연결에서 확인한 ${state.embeddingIndex}의 벡터 상태가 다릅니다. 다시 연결해 갱신하세요.`,
      "벡터가 필요한 검색은 연결 상태를 새로 확인한 뒤 사용할 수 있습니다. BM25 검색은 계속 사용할 수 있습니다.",
      "저장된 벡터를 만든 모델의 출처는 확인할 수 없습니다.",
    ];
    return { active: true, blocked: true, paragraphs, plain: paragraphs.join(" ") };
  }

  const paragraphs = [`${modeLabel} 준비 상태는 마지막 연결 시 ${state.embeddingIndex}에서 확인했습니다. 다시 연결하면 상태가 갱신됩니다.`];
  let blocked = false;
  if (!info.mapping_available) {
    paragraphs.push("rag_embedding 매핑이 없습니다. 벡터 검색은 사용할 수 없지만 BM25 검색은 계속 사용할 수 있습니다.");
    blocked = true;
  } else if (Number(info.mapping_dimensions) !== Number(selectedEmbeddingProfile()?.dimensions || 1024)) {
    paragraphs.push(`rag_embedding 매핑은 ${info.mapping_dimensions}차원이며 현재 프로필 ${selectedEmbeddingProfile()?.profile_id || "e5-multilingual-large"}은 ${selectedEmbeddingProfile()?.dimensions || 1024}차원을 요구합니다. 벡터가 필요한 검색은 사용할 수 없지만 BM25 검색은 계속 사용할 수 있습니다.`);
    blocked = true;
  } else if (info.mapping_compatible === false) {
    paragraphs.push(state.locale === "en"
      ? (info.mapping_error || "The stored vector recipe does not match the selected profile.")
      : "저장 벡터의 recipe fingerprint가 선택한 프로필과 다릅니다. 같은 차원이어도 다른 모델은 함께 검색할 수 없습니다.");
    blocked = true;
  } else {
    paragraphs.push(`rag_embedding 매핑은 현재 프로필 요청에 필요한 ${selectedEmbeddingProfile()?.dimensions || 1024}차원입니다.`);
  }

  if (!info.runtime_installed) {
    paragraphs.push("FastEmbed 런타임이 설치되지 않아 질의 벡터를 만들 수 없습니다.");
    blocked = true;
  } else {
    paragraphs.push("FastEmbed 런타임이 설치되어 있습니다.");
  }

  const vectorCount = Number(info.vector_count);
  const documentCount = Number(info.document_count);
  const validCounts = Number.isFinite(vectorCount) && vectorCount >= 0 && Number.isFinite(documentCount) && documentCount >= 0;
  if (!validCounts) {
    paragraphs.push("저장 벡터 개수를 확인할 수 없습니다. 다시 연결해 상태를 갱신하세요.");
    blocked = true;
  } else {
    paragraphs.push(`저장 벡터 ${vectorCount}/${documentCount}개.`);
    if (vectorCount === 0) {
      paragraphs.push("저장 벡터가 없어 벡터가 필요한 검색을 시작할 수 없습니다. BM25 검색은 계속 사용할 수 있습니다.");
      blocked = true;
    } else if (vectorCount < documentCount) {
      paragraphs.push(`벡터 후보는 벡터가 저장된 ${vectorCount}개 문서에만 제한됩니다 (${vectorCount}/${documentCount}).`);
    }
  }

  if (info.model_cached) {
    paragraphs.push(`질의용 로컬 ${info.model_name || "FastEmbed"} 모델은 캐시되어 있습니다.`);
  } else if (blocked) {
    paragraphs.push(`질의용 로컬 ${info.model_name || "FastEmbed"} 모델은 아직 캐시되지 않았습니다.`);
  } else {
    paragraphs.push(`질의용 로컬 ${info.model_name || selectedEmbeddingProfile()?.model_name || "FastEmbed"} 모델은 아직 캐시되지 않았습니다. 다운로드는 명시적으로 동의한 경우에만 시작합니다.`);
  }
  if (mode === "vector") {
    paragraphs.push("이 방식은 저장 벡터가 있는 문서의 벡터 후보를 검색합니다.");
  } else if (mode === "hybrid") {
    paragraphs.push("벡터 요청이 성공하면 하이브리드 검색은 벡터 후보와 어휘 결과를 결합합니다.");
  } else {
    paragraphs.push("벡터 요청이 성공하면 코드 + Jira RAG는 Jira 벡터 후보와 어휘 후보를 결합하고, 코드 후보는 별도로 보여줍니다.");
  }
  paragraphs.push("선택한 profile_id의 호환성과 준비 상태를 확인합니다. 이 표시는 검색 품질의 검증 결과가 아닙니다.");
  return { active: true, blocked, requiresModelDownload: !blocked && !info.model_cached, paragraphs, plain: paragraphs.join(" ") };
}

function renderSearchReadiness() {
  const status = $("#search-mode-readiness");
  const detailButton = $("[data-open-embedding-setup]");
  if (!status || !detailButton) return;
  const readiness = searchModeReadiness();
  status.classList.toggle("hidden", !readiness.active);
  detailButton.classList.toggle("hidden", !readiness.active);
  status.innerHTML = readiness.paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("");
}

async function vectorizeIndex() {
  if (!state.connected || !state.embedding?.mapping_available) return;
  const button = $("#vectorize-button");
  const profile = selectedEmbeddingProfile();
  if (!window.confirm(`선택한 인덱스의 rag_chunk_text를 ${profile?.model_name || state.embedding.model_name} (${profile?.dimensions || state.embedding.mapping_dimensions}차원) 프로필로 임베딩할까요? 모델 파일은 아직 캐시되지 않았다면 이 동의 후 로컬 캐시에 내려받습니다. 기존 문서 필드는 변경하지 않습니다.`)) return;
  setBusy(button, true, "모델 다운로드 및 임베딩 중");
  $("#embedding-status").textContent = "로컬 모델을 준비하고 누락된 문서 벡터를 생성 중입니다. 첫 다운로드는 시간이 걸릴 수 있습니다…";
  try {
    const result = await api("/api/vectorize", requestPayload({ profile_id: state.sharedProfileId }));
    showToast(result.message);
    const updated = await api("/api/connect", requestPayload({ profile_id: state.sharedProfileId }));
    state.embedding = updated.embedding;
    state.embeddingIndex = updated.selected_index || $("#index-name").value.trim();
    renderEmbeddingStatus(state.embedding);
  } catch (error) {
    $("#embedding-status").className = "notice notice-error";
    $("#embedding-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.textContent = state.embedding?.model_cached ? "누락 임베딩 생성" : "임베딩 모델 다운로드 및 생성";
    const dimensions = Number(selectedEmbeddingProfile()?.dimensions || 1024);
    button.disabled = !state.connected || !state.embedding?.mapping_available || Number(state.embedding.mapping_dimensions) !== dimensions || state.embedding.mapping_compatible === false || !state.embedding.runtime_installed || state.embedding.vector_count >= state.embedding.document_count;
  }
}

function renderSampleStatus(info) {
  state.sampleStatusInfo = info;
  state.canImportSample = Boolean(info.can_import);
  state.sampleExpectedCount = Number(info.sample_expected_count) || 0;
  const status = $("#sample-status");
  if (!info.exists) {
    status.className = "sample-status";
    status.innerHTML = `<strong>${escapeHtml(info.index)}</strong> ${copy("sampleMissing").replace("{index}", escapeHtml(info.index)).replace("{count}", Number(info.sample_expected_count).toLocaleString())}`;
  } else {
    status.className = "sample-status";
    status.textContent = state.sampleImportedTarget === sampleTargetKey($("#es-url").value, info.index)
      ? `${info.index}: ${copy("sampleImportedStatus").replace("{count}", Number(info.document_count).toLocaleString())}`
      : `${info.index}: ${copy("sampleExisting").replace("{index}", escapeHtml(info.index)).replace("{count}", Number(info.document_count).toLocaleString())}`;
    if (Number(info.metadata_count) !== Number(info.sample_expected_count)) status.innerHTML += `<br><span class="metadata-warning">${copy("sampleMeta").replace("{metadata}", escapeHtml(info.metadata_count)).replace("{count}", escapeHtml(info.sample_expected_count))}</span>`;
  }
  $("#load-sample-button").disabled = !state.connected || !state.canImportSample;
  renderSampleOnboarding();
}

function renderSampleOnboarding() {
  const notice = $("#sample-onboarding");
  const index = $("#index-name").value.trim();
  const available = Boolean(state.connected && state.canImportSample && state.embeddingIndex && index === state.embeddingIndex);
  notice.classList.toggle("hidden", !available);
  if (!available) return;
  const count = Number.isFinite(state.sampleExpectedCount) ? state.sampleExpectedCount : 0;
  $("#sample-onboarding-copy").textContent = copy("sampleMissing").replace("{index}", index).replace("{count}", count.toLocaleString());
}

async function loadSample() {
  const button = $("#load-sample-button");
  if (!state.connected || !state.canImportSample) return;
  if (!window.confirm(state.locale === "en" ? `Create new index ${$("#index-name").value.trim()} and import the supplied sample?\nExisting indexes are never overwritten.` : `새 인덱스 ${$("#index-name").value.trim()}를 만들고 제공 샘플을 적재할까요?\n기존 인덱스는 덮어쓰지 않습니다.`)) return;
  const requestedIndex = $("#index-name").value.trim();
  setBusy(button, true, "인덱스 생성 및 적재 중");
  $("#sample-status").textContent = "매핑 생성, Bulk 적재, refresh를 진행하고 있습니다…";
  try {
    const result = await api("/api/sample-import", requestPayload());
    if (result.created === true && !result.partial) state.sampleImportedTarget = sampleTargetKey($("#es-url").value, result.index || requestedIndex);
    if (result.partial) {
      $("#sample-status").className = "sample-status error";
      $("#sample-status").textContent = `${result.message} 부분 적재 ${result.document_count ?? "확인 불가"}건.`;
      showToast("일부 샘플 문서 적재에 실패했습니다.", true);
    } else {
      showToast(result.message);
    }
    await connect();
  } catch (error) {
    $("#sample-status").className = "sample-status error";
    $("#sample-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.innerHTML = '<span class="button-icon">＋</span> 샘플 인덱스 생성 및 적재';
    button.disabled = !state.connected || !state.canImportSample;
  }
}

function renderBoostInputs(profile = DEFAULT_PROFILE) {
  $("#boost-grid").innerHTML = Object.entries(FIELD_LABELS).map(([field, label]) => `
    <div class="boost-item"><label title="${escapeHtml(field)}" for="boost-${escapeHtml(field.replaceAll(".", "-"))}">${escapeHtml(label)}</label>
      <input id="boost-${escapeHtml(field.replaceAll(".", "-"))}" data-field="${escapeHtml(field)}" type="number" min="0" max="100" step="0.25" value="${escapeHtml(profile[field] ?? 0)}"></div>
  `).join("");
}

function readBoosts() {
  const result = {};
  $$("#boost-grid input[data-field]").forEach((input) => {
    const value = Number(input.value);
    result[input.dataset.field] = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  });
  return result;
}

function readFilters() { return state.filters.map((item) => ({ ...item })); }

function renderFilters() {
  $("#active-filters").innerHTML = state.filters.map((filter, index) => `
    <span class="filter-chip">${escapeHtml(filter.field)} = ${escapeHtml(filter.value)}<button data-remove-filter="${index}" aria-label="필터 제거">×</button></span>
  `).join("");
}

function activateTab(tabId) {
  $$(".tab").forEach((tab) => {
    const active = tab.dataset.tab === tabId;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $$(".tab-panel").forEach((panel) => {
    const active = panel.id === tabId;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

const KNOWLEDGE_MAX_BYTES = 1024 * 1024;
const KNOWLEDGE_ACCOUNT_MAX_BYTES = 20 * 1024 * 1024;
const KNOWLEDGE_RESTORE_MAX_BYTES = 128 * 1024 * 1024;

function knowledgeFields() {
  return {
    title: $("#knowledge-title").value.trim(),
    source_label: $("#knowledge-source").value.trim(),
    content: $("#knowledge-content").value,
  };
}

function knowledgePreviewKey(fields) {
  return JSON.stringify([state.knowledgeDocumentId, fields.title, fields.source_label, fields.content]);
}

function knowledgeSizeBytes(content = $("#knowledge-content").value) {
  return new TextEncoder().encode(content).byteLength;
}

function updateKnowledgeEditor() {
  const fields = knowledgeFields();
  const bytes = knowledgeSizeBytes(fields.content);
  const tooLarge = bytes > KNOWLEDGE_MAX_BYTES;
  $("#knowledge-size").textContent = `${bytes.toLocaleString()} B / 1 MiB${tooLarge ? " · 크기 초과" : ""}`;
  $("#knowledge-size").classList.toggle("knowledge-over-limit", tooLarge);
  ["#knowledge-title", "#knowledge-source", "#knowledge-content", "#knowledge-file"].forEach((selector) => { $(selector).disabled = !state.knowledgeEditing; });
  const canSave = state.knowledgeEditing && !tooLarge && Boolean(fields.title && fields.content.trim()) && state.knowledgePreviewKey === knowledgePreviewKey(fields);
  $("#knowledge-save-button").disabled = !canSave;
  $("#knowledge-preview-button").disabled = !state.knowledgeEditing;
  $("#knowledge-editor-mode").textContent = state.knowledgeDocumentId ? (state.knowledgeEditing ? "문서 수정" : "문서 보기") : "새 문서";
}

function renderKnowledgeChunks(chunks) {
  const root = $("#knowledge-chunk-preview");
  root.replaceChildren();
  if (!Array.isArray(chunks) || !chunks.length) {
    root.textContent = "미리볼 청크가 없습니다. 내용을 확인한 뒤 다시 시도하세요.";
    return;
  }
  chunks.forEach((chunk) => {
    const card = document.createElement("article"); card.className = "knowledge-chunk";
    const heading = document.createElement("div"); heading.className = "knowledge-chunk-heading";
    const label = document.createElement("strong"); label.textContent = `청크 ${Number(chunk.ordinal) + 1}${chunk.token_count == null ? "" : ` · ${chunk.token_count} tokens`}`;
    const offsets = document.createElement("span"); offsets.textContent = `${Number(chunk.start ?? chunk.start_offset) || 0}–${Number(chunk.end ?? chunk.end_offset) || 0}`;
    const text = document.createElement("pre"); text.textContent = String(chunk.content ?? chunk.text ?? "");
    heading.append(label, offsets); card.append(heading, text); root.append(card);
  });
}

function selectedKnowledgePolicy() {
  return { strategy: $("#knowledge-chunk-strategy").value, size: Number($("#knowledge-chunk-size").value), overlap: Number($("#knowledge-chunk-overlap").value) };
}

function renderKnowledgeJob(job) {
  const status = $("#knowledge-reindex-status");
  const failed = Array.isArray(job.failed_documents) ? job.failed_documents : [];
  status.textContent = `${job.state} · 문서 ${job.completed}/${job.total} 완료 · target ${job.generation || "미지정"}${job.safe_error ? ` · ${job.safe_error}` : ""}${failed.length ? ` · 실패 ${failed.length}건` : ""}`;
  $("#knowledge-reindex-cancel").disabled = !["queued", "running", "cancelling"].includes(job.state);
  $("#knowledge-reindex-retry").disabled = !["failed", "interrupted", "cancelled"].includes(job.state);
  if (["queued", "running", "cancelling"].includes(job.state)) {
    clearTimeout(state.knowledgeReindexTimer);
    state.knowledgeReindexTimer = setTimeout(pollKnowledgeJob, 900);
  }
}

async function pollKnowledgeJob() {
  if (!state.knowledgeReindexJobId) return;
  try {
    const job = await api("/api/knowledge/reindex/status", { job_id: state.knowledgeReindexJobId });
    renderKnowledgeJob(job);
    if (job.state === "complete") { setKnowledgeEsFreshness(false); await loadKnowledgeEsStatus(); }
    else if (["failed", "interrupted", "cancelled"].includes(job.state)) setKnowledgeEsFreshness(true, "재청킹 작업이 끝나지 않았습니다. 이전 비공개 별칭은 유지되며 상태를 확인한 뒤 재시도할 수 있습니다.");
  } catch (error) { $("#knowledge-reindex-status").textContent = `상태를 확인하지 못했습니다 · ${error.message || "다시 확인하세요."}`; }
}

async function startKnowledgeReindex(retry = false) {
  const policy = selectedKnowledgePolicy();
  const result = await api(retry ? "/api/knowledge/reindex/retry" : "/api/knowledge/reindex/start", {
    ...(retry ? { job_id: state.knowledgeReindexJobId } : { policy, connection: getConnection() }),
    ...(retry ? { connection: getConnection() } : {}),
  });
  state.knowledgeReindexJobId = result.job_id;
  renderKnowledgeJob({ ...result, completed: 0, failed_documents: [], safe_error: "" });
  await pollKnowledgeJob();
}

async function loadKnowledgePolicy() {
  try {
    const saved = await api("/api/knowledge/chunks/policy/get", {});
    const policy = saved.policy || {};
    $("#knowledge-chunk-strategy").value = policy.strategy || "character";
    $("#knowledge-chunk-size").value = policy.size || 1800;
    $("#knowledge-chunk-overlap").value = policy.overlap || 200;
  } catch { /* the migration or authenticated session may not be ready yet */ }
  try {
    const latest = await api("/api/knowledge/reindex/latest", {});
    if (latest.job) {
      state.knowledgeReindexJobId = latest.job.job_id;
      renderKnowledgeJob(latest.job);
    }
  } catch { /* job recovery status is supplemental to local document access */ }
}

async function loadKnowledgeEsStatus() {
  const node = $("#knowledge-es-status");
  if (!node) return;
  try {
    const response = await fetch("/api/knowledge/es-status", { cache: "no-store" });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || "상태를 확인하지 못했습니다.");
    if (!state.privateProfileTouched && typeof value.vector_profile_id === "string") {
      state.privateProfileId = value.vector_profile_id;
      if ($("#knowledge-vector-profile-select")) $("#knowledge-vector-profile-select").value = value.vector_profile_id;
    }
    if (typeof value.vector_profile_id === "string") state.privateSavedProfileId = value.vector_profile_id;
    const names = { in_sync: "BM25 동기화 완료", stale: "변경 사항 있음 · 동기화 필요", syncing: "동기화 중", error: "동기화 실패 · 재시도 필요", not_synced: "아직 비공개 문서가 없습니다" };
    const vectorNames = { in_sync: `벡터 준비 완료 (${value.vector_chunks} passages)`, not_indexed: "벡터 미색인 · BM25만 검색 가능", stale: "벡터 동기화 필요", mapping_unavailable: "벡터 매핑을 확인할 수 없음", unavailable: "벡터 런타임을 확인할 수 없음" };
    const tokenizer = value.tokenizer || {};
    state.privateTokenizerStatus = tokenizer;
    const profileRuntime = value.vector_profile_status || {};
    const privateProfileId = value.vector_profile_id || state.privateProfileId;
    const privateProfile = selectedEmbeddingProfile(privateProfileId);
    const vectorSetup = !tokenizer.tokenizers_installed
      ? (state.locale === "en" ? "optional tokenizers runtime missing" : "선택 tokenizers 런타임 없음")
      : privateProfileId === "e5-multilingual-large"
        ? (!tokenizer.cached ? "고정 tokenizer 캐시 준비 필요" : "고정 tokenizer 사용 가능")
        : (profileRuntime.status === "dependency_missing" ? "FastEmbed 런타임 설치 필요" : profileRuntime.status === "loading_failure" ? "모델/tokenizer 불러오기 실패" : profileRuntime.model_cached ? "선택 모델과 tokenizer 캐시 사용 가능" : "선택 모델과 tokenizer 캐시 준비 필요");
    const profileCopy = value.vector_profile_id ? ` · 벡터 프로필 ${privateProfile?.model_name || value.vector_profile_id} (${value.vector_profile_recipe?.dimensions || privateProfile?.dimensions || "?"}차원)` : "";
    node.textContent = `${names[value.state] || value.state} · ${vectorNames[value.vector_state] || value.vector_state}${profileCopy} · ${vectorSetup} · SQLite 문서 ${value.local_documents}개 / 청크 ${value.local_chunks}개 · ES 청크 ${value.indexed_chunks}개${value.last_synced_at ? ` · 마지막 동기화 ${formatKnowledgeDate(value.last_synced_at)}` : ""}${value.error ? ` · ${value.error}` : ""}`;
  } catch (error) { node.textContent = error.message || "동기화 상태를 확인하지 못했습니다."; }
}

async function syncKnowledgeEs() {
  const button = $("#knowledge-es-sync");
  if (!button) return;
  button.disabled = true; $("#knowledge-es-status").textContent = "내 문서를 새 비공개 인덱스에 색인하고 별칭을 전환하는 중입니다.";
  try {
    const status = await api("/api/knowledge/es-sync", { connection: getConnection() });
    const labels = { in_sync: "동기화 완료", stale: "변경 사항 있음 · 동기화 필요", error: "동기화 실패" };
    $("#knowledge-es-status").textContent = `${labels[status.state] || status.state} · 계정 비공개 BM25 · ${status.indexed_chunks}개 청크`;
    if (status.state === "in_sync") setKnowledgeEsFreshness(false);
    else setKnowledgeEsFreshness(true, "동기화가 완료되지 않았습니다. Elasticsearch 개인 별칭은 아직 최신 상태가 아닙니다.");
  } catch (error) {
    $("#knowledge-es-status").textContent = error.message || "동기화하지 못했습니다. Elasticsearch 연결을 확인한 뒤 재시도하세요.";
    setKnowledgeEsFreshness(true, "BM25 동기화에 성공하지 못했습니다. Elasticsearch 개인 별칭은 최신 상태로 확인되지 않았습니다.");
  }
  finally { button.disabled = false; await loadKnowledgeEsStatus(); }
}

async function syncKnowledgeEsVectors() {
  const button = $("#knowledge-es-vector-sync");
  if (!button) return;
  state.privateProfileId = $("#knowledge-vector-profile-select")?.value || state.privateProfileId;
  const profile = selectedEmbeddingProfile(state.privateProfileId);
  if (!profile?.runtime_installed) {
    $("#knowledge-es-status").textContent = state.locale === "en"
      ? "Vector sync needs the optional FastEmbed runtime. Install the private-vector extra, then retry. BM25 remains available."
      : "벡터 동기화에는 선택 FastEmbed 런타임이 필요합니다. private-vector extra 설치 후 다시 시도하세요. BM25는 계속 사용할 수 있습니다.";
    return;
  }
  if (state.privateProfileId === "e5-multilingual-large") {
    const tokenizer = await fetch("/api/token-preview/status", { cache: "no-store" }).then((r) => r.json()).catch(() => ({}));
    if (!tokenizer.tokenizers_installed || !tokenizer.huggingface_hub_installed) {
      $("#knowledge-es-status").textContent = state.locale === "en"
        ? "E5 private vector sync needs the optional tokenizer packages. Install the private-vector extra, then retry. BM25 remains available."
        : "E5 개인 벡터 동기화에는 선택 tokenizer 패키지가 필요합니다. private-vector extra 설치 후 다시 시도하세요. BM25는 계속 사용할 수 있습니다.";
      return;
    }
  } else if (state.privateTokenizerStatus?.tokenizers_installed === false) {
    $("#knowledge-es-status").textContent = state.locale === "en"
      ? "MiniLM private vector sync needs the optional tokenizers runtime. Install the private-vector extra, then reload status and retry. The current generation stays active; BM25 remains available."
      : "MiniLM 개인 벡터 동기화에는 선택 tokenizers 런타임이 필요합니다. private-vector extra를 설치한 뒤 상태를 새로고침하고 다시 시도하세요. 현재 generation은 유지되며 BM25는 계속 사용할 수 있습니다.";
    return;
  }
  const consentMessage = state.locale === "en"
    ? `Create a new account-private vector generation from your documents using ${profile?.model_name || state.privateProfileId} (${profile?.dimensions || "?"}d)? If needed, tokenizer/model files will be downloaded into the local cache after this consent. The current generation stays active until the new generation is published.`
    : `내 문서로 ${profile?.model_name || state.privateProfileId} (${profile?.dimensions || "?"}차원) 프로필의 새 계정 비공개 벡터 generation을 만들까요? 필요한 tokenizer/model 파일은 이 동의 후 로컬 캐시에 내려받습니다. 새 generation 게시 전까지 현재 generation을 유지합니다.`;
  if (!window.confirm(consentMessage)) return;
  button.disabled = true;
  $("#knowledge-es-status").textContent = "고정 tokenizer를 확인하고, 동의된 경우 모델을 로컬 캐시에 준비한 뒤 새 벡터 generation을 만듭니다…";
  try {
    const status = await api("/api/knowledge/es-vector-sync", { connection: getConnection(), allow_model_download: true, profile_id: state.privateProfileId });
    $("#knowledge-es-status").textContent = state.locale === "en"
      ? `Vector sync complete · ${status.vector_chunks} passages · ${status.recipe?.dimensions || profile?.dimensions || "?"}d ${status.recipe?.similarity || "cosine"} · ${status.profile_id || state.privateProfileId} · account-private alias`
      : `벡터 동기화 완료 · ${status.vector_chunks} passages · ${status.recipe?.dimensions || profile?.dimensions || "?"}차원 ${status.recipe?.similarity || "cosine"} · ${status.profile_id || state.privateProfileId} · 계정 비공개 별칭`;
  } catch (error) {
    $("#knowledge-es-status").textContent = error.message || "벡터 동기화에 실패했습니다. 이전 별칭은 유지됩니다. 런타임, tokenizer, 모델 캐시와 Elasticsearch 매핑을 확인하세요.";
  } finally { button.disabled = false; await loadKnowledgeEsStatus(); }
}

async function loadKnowledgeList() {
  const status = $("#knowledge-list-status");
  status.textContent = "문서 목록을 불러오는 중입니다.";
  $("#knowledge-list").replaceChildren();
  try {
    const result = await api("/api/knowledge/list", {});
    const documents = Array.isArray(result.documents) ? result.documents : [];
    if (result.usage || result.limits) renderKnowledgeUsage(result.usage, result.limits);
    if (!documents.length) { status.textContent = "저장한 문서가 없습니다. 위에서 첫 문서를 추가해 보세요."; return; }
    status.textContent = `${documents.length}개 문서를 불러왔습니다.`;
    documents.forEach((documentInfo) => {
      const row = document.createElement("article"); row.className = "knowledge-row";
      const summary = document.createElement("div"); summary.className = "knowledge-row-summary";
      const title = document.createElement("strong"); title.textContent = String(documentInfo.title || "제목 없는 문서");
      const meta = document.createElement("small"); meta.textContent = `${documentInfo.source_label || "출처 표시 없음"} · ${formatKnowledgeBytes(documentInfo.content_bytes)} · ${formatKnowledgeDate(documentInfo.updated_at || documentInfo.created_at)}`;
      summary.append(title, meta);
      const actions = document.createElement("div"); actions.className = "knowledge-row-actions";
      actions.append(knowledgeAction("열기", "open", documentInfo.document_id), knowledgeAction("수정", "edit", documentInfo.document_id), knowledgeAction("삭제", "delete", documentInfo.document_id, true));
      row.append(summary, actions); $("#knowledge-list").append(row);
    });
  } catch {
    status.textContent = "문서 목록을 불러오지 못했습니다. 로그인 상태를 확인한 뒤 다시 시도하세요.";
  }
}

function formatKnowledgeDate(value) {
  if (!value) return "날짜 정보 없음";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "날짜 정보 없음" : date.toLocaleDateString("ko-KR");
}

function formatKnowledgeBytes(value) {
  const bytes = Number(value);
  return Number.isFinite(bytes) ? `${bytes.toLocaleString()} B` : "크기 정보 없음";
}

function strictUtf8(bytes) {
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function bytesToBase64(bytes) {
  let binary = "";
  const step = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += step) binary += String.fromCharCode(...bytes.subarray(offset, offset + step));
  return btoa(binary);
}

function formatKnowledgeUsage(usage = {}, limits = {}) {
  const documents = usage.documents ?? usage.document_count ?? usage.documents_used ?? usage.local_documents ?? 0;
  const bytes = usage.bytes ?? usage.content_bytes ?? usage.bytes_used ?? usage.stored_bytes ?? 0;
  const documentLimit = limits.documents ?? limits.document_count ?? limits.max_documents ?? 100;
  const byteLimit = limits.bytes ?? limits.content_bytes ?? limits.max_content_bytes ?? KNOWLEDGE_ACCOUNT_MAX_BYTES;
  return `사용량 · 문서 ${Number(documents).toLocaleString()} / ${Number(documentLimit).toLocaleString()}개 · 내용 ${formatKnowledgeBytes(bytes)} / ${formatKnowledgeBytes(byteLimit)}`;
}

function renderKnowledgeUsage(usage, limits) {
  if (!usage && !limits) return;
  $("#knowledge-usage").textContent = formatKnowledgeUsage(usage || {}, limits || {});
}

async function refreshKnowledgeAfterMutation(message = "로컬 문서가 바뀌었습니다. Elasticsearch 개인 별칭은 성공적인 명시적 동기화 전까지 최신 상태가 아닙니다.") {
  $("#knowledge-search-results")?.replaceChildren();
  $("#knowledge-results").replaceChildren();
  $("#knowledge-search-status").textContent = `${message} Elasticsearch 개인 별칭은 성공적인 명시적 동기화 전까지 최신 상태가 아닙니다.`;
  setKnowledgeEsFreshness(true, "로컬 문서가 변경되었습니다. Elasticsearch 개인 별칭은 BM25 동기화가 성공할 때까지 최신 상태가 아닙니다.");
  await Promise.all([loadKnowledgeList(), loadKnowledgeEsStatus()]);
}

function setKnowledgeEsFreshness(stale, message) {
  const node = $("#knowledge-es-freshness");
  if (!node) return;
  node.classList.toggle("notice-error", stale);
  node.classList.toggle("notice-muted", !stale);
  node.textContent = message || (stale
    ? "로컬 문서가 변경되었습니다. Elasticsearch 개인 별칭은 BM25 동기화가 성공할 때까지 최신 상태가 아닙니다."
    : "BM25 동기화가 성공했습니다. Elasticsearch 개인 별칭에 현재 로컬 문서 변경 사항이 반영되었습니다.");
}

function importMappingFromControls() {
  const importState = state.knowledgeImport;
  if (!importState) return null;
  if (importState.format === "txt" || importState.format === "md") return null;
  return {
    title: $("#knowledge-import-title-field").value,
    content: $("#knowledge-import-content-field").value,
    source: $("#knowledge-import-source-field").value,
  };
}

function availableFieldNames(value) {
  const fields = Array.isArray(value) ? value : [];
  return fields.map((field) => typeof field === "string" ? field : String(field?.name || field?.field || "")).filter(Boolean);
}

function setImportFieldOptions(selector, fields, selected, optional = false) {
  const select = $(selector);
  select.replaceChildren();
  if (optional) {
    const empty = document.createElement("option"); empty.value = ""; empty.textContent = "선택 안 함"; select.append(empty);
  }
  fields.forEach((field) => { const option = document.createElement("option"); option.value = field; option.textContent = field; select.append(option); });
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  else if (!optional && fields.length) select.value = fields[0];
}

function renderKnowledgeImportPreview(result) {
  const root = $("#knowledge-import-preview");
  root.replaceChildren();
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const records = Array.isArray(result.valid_records) ? result.valid_records : [];
  if (Array.isArray(result.fields_available)) {
    const fields = availableFieldNames(result.fields_available);
    const mapping = $("#knowledge-import-mapping");
    mapping.classList.toggle("hidden", !["csv", "jsonl"].includes(state.knowledgeImport?.format));
    if (fields.length) {
      const prior = importMappingFromControls() || {};
      const choose = (names, preferences) => names.find((name) => preferences.includes(name.toLowerCase())) || names[0] || "";
      setImportFieldOptions("#knowledge-import-title-field", fields, prior.title || choose(fields, ["title", "name", "subject", "headline"]));
      setImportFieldOptions("#knowledge-import-content-field", fields, prior.content || choose(fields, ["content", "text", "body", "description"]));
      setImportFieldOptions("#knowledge-import-source-field", fields, prior.source || choose(fields, ["source", "url", "source_label"]), true);
    }
  }
  renderKnowledgeUsage(result.usage, result.limits);
  if (result.format || result.file_sha256) {
    const identity = document.createElement("p");
    identity.className = "helper-text";
    identity.textContent = `형식 ${String(result.format || state.knowledgeImport?.format || "확인 중")} · 파일 SHA256 ${String(result.file_sha256 || "미제공")}`;
    root.append(identity);
  }
  errors.forEach((error) => {
    const row = document.createElement("p"); row.className = "notice notice-error knowledge-row-error";
    const rowNumber = error.row_number == null ? "파일" : `행 ${error.row_number}`;
    row.textContent = `${rowNumber} · ${String(error.code || "invalid_row")} · ${String(error.message || "이 행을 읽지 못했습니다.")}`;
    root.append(row);
  });
  records.forEach((record) => {
    const card = document.createElement("article"); card.className = "knowledge-import-record";
    const heading = document.createElement("strong"); heading.textContent = `행 ${Number(record.row_number)} · ${String(record.title || "제목 없음")}`;
    const source = document.createElement("small"); source.textContent = `${String(record.source_label || state.knowledgeImport?.filename || "출처 없음")} · SHA256 ${String(record.content_sha256 || "미제공")}`;
    const content = document.createElement("pre"); content.textContent = String(record.content || "");
    card.append(heading, source, content);
    if (record.duplicate) {
      const duplicate = document.createElement("p"); duplicate.className = "notice notice-muted";
      duplicate.textContent = `기존 문서 중복 · ID ${String(record.duplicate.document_id || "알 수 없음")} · revision ${String(record.duplicate.revision ?? "알 수 없음")}`;
      const label = document.createElement("label"); label.className = "field-label"; label.textContent = "중복 처리 선택";
      const select = document.createElement("select"); select.className = "text-input knowledge-duplicate-action"; select.dataset.rowNumber = String(record.row_number);
      const placeholder = document.createElement("option"); placeholder.value = ""; placeholder.textContent = "건너뛰기 또는 교체 선택"; select.append(placeholder);
      for (const [value, text] of [["skip", "기존 문서 유지 · 건너뛰기"], ["replace", "내용 교체"]]) { const option = document.createElement("option"); option.value = value; option.textContent = text; select.append(option); }
      label.append(select); card.append(duplicate, label);
    }
    root.append(card);
  });
  if (result.needs_field_mapping) {
    const mappingNotice = document.createElement("p"); mappingNotice.className = "notice notice-muted";
    mappingNotice.textContent = "제목과 내용 열을 선택한 뒤 행 미리보기를 다시 실행하세요. 이 단계에서는 행을 검증하거나 저장하지 않았습니다.";
    root.append(mappingNotice);
  } else if (!records.length && !errors.length) root.textContent = "미리보기 결과가 비어 있습니다.";
  state.knowledgeImport.preview = result;
  updateKnowledgeImportCommitButton();
}

function updateKnowledgeImportCommitButton() {
  const preview = state.knowledgeImport?.preview;
  const duplicates = (preview?.valid_records || []).filter((record) => record.duplicate);
  const actionsChosen = duplicates.every((record) => $(".knowledge-duplicate-action[data-row-number='" + String(Number(record.row_number)) + "']")?.value);
  $("#knowledge-import-commit-button").disabled = !preview || preview.needs_field_mapping || !(preview.valid_records || []).length || !actionsChosen;
}

async function previewKnowledgeImport() {
  const item = state.knowledgeImport;
  if (!item) return;
  const fields = importMappingFromControls();
  if (!fields && !["txt", "md"].includes(item.format)) return;
  $("#knowledge-import-preview-button").disabled = true;
  $("#knowledge-import-commit-button").disabled = true;
  $("#knowledge-import-status").textContent = "파일을 안전하게 파싱하고 행을 미리보는 중입니다. 아직 저장하지 않습니다.";
  try {
    const result = await api("/api/knowledge/import/preview", { filename: item.filename, content_base64: item.contentBase64, ...(fields ? { fields } : {}) });
    item.fields = fields;
    renderKnowledgeImportPreview(result);
    $("#knowledge-import-status").textContent = result.needs_field_mapping
      ? `열 ${availableFieldNames(result.fields_available).join(", ") || "없음"}을 찾았습니다. 제목과 내용 열을 고른 뒤 미리보기를 다시 실행하세요.`
      : `${(result.valid_records || []).length}개 유효 행 · ${(result.errors || []).length}개 오류. 아직 저장하지 않았습니다. 중복은 각각 처리 방법을 선택하세요.`;
  } catch (error) {
    item.preview = null;
    $("#knowledge-import-status").textContent = `미리보기 실패 · ${error.message || "파일, UTF-8 인코딩 또는 필드 선택을 확인하세요."}`;
  } finally { $("#knowledge-import-preview-button").disabled = false; updateKnowledgeImportCommitButton(); }
}

function renderKnowledgeImportOutcomes(result) {
  const root = $("#knowledge-import-preview");
  const heading = document.createElement("h4"); heading.textContent = `저장 결과 · ${Array.isArray(result.outcomes) ? result.outcomes.length : 0}개 행`;
  root.prepend(heading);
  (result.outcomes || []).forEach((outcome) => {
    const row = document.createElement("p"); row.className = `knowledge-import-outcome outcome-${String(outcome.outcome || "failed")}`;
    row.textContent = `행 ${outcome.row_number ?? "?"} · ${String(outcome.outcome || "failed")} · ${String(outcome.message || outcome.document_id || "결과 정보 없음")}`;
    root.append(row);
  });
  (result.errors || []).forEach((error) => {
    const row = document.createElement("p"); row.className = "notice notice-error knowledge-row-error";
    row.textContent = `${error.row_number == null ? "파일" : `행 ${error.row_number}`} · ${String(error.code || "import_error")} · ${String(error.message || "이 행을 저장하지 못했습니다.")}`;
    root.append(row);
  });
  if (result.usage || result.limits) renderKnowledgeUsage(result.usage, result.limits);
}

async function commitKnowledgeImport() {
  const item = state.knowledgeImport;
  if (!item?.preview) return;
  const duplicateActions = [...$$(".knowledge-duplicate-action")].map((select) => ({ row_number: Number(select.dataset.rowNumber), action: select.value }));
  if (duplicateActions.some((action) => !["skip", "replace"].includes(action.action))) return;
  const button = $("#knowledge-import-commit-button"); button.disabled = true;
  $("#knowledge-import-status").textContent = "선택한 행을 계정의 개인 지식 보관함에 저장하고 있습니다.";
  try {
    const result = await api("/api/knowledge/import/commit", { filename: item.filename, content_base64: item.contentBase64, ...(item.fields ? { fields: item.fields } : {}), duplicate_actions: duplicateActions });
    renderKnowledgeImportOutcomes(result);
    const outcomes = result.outcomes || [];
    const failed = outcomes.filter((entry) => entry.outcome === "failed").length + (result.errors || []).length;
    $("#knowledge-import-status").textContent = result.partial || failed ? `부분 완료 · 실패 ${failed}개. 성공한 행은 보관되었으므로 아래 결과를 확인하세요.` : `가져오기 완료 · ${outcomes.length}개 행 처리됨.`;
    await refreshKnowledgeAfterMutation();
  } catch (error) {
    $("#knowledge-import-status").textContent = `가져오기 실패 · ${error.message || "기존 문서는 변경되지 않았습니다."}`;
  } finally { updateKnowledgeImportCommitButton(); }
}

function conflictList(result) {
  const entries = result?.conflicts || result?.duplicates || [];
  return Array.isArray(entries) ? entries : [];
}

function renderKnowledgeRestorePreview(result) {
  const root = $("#knowledge-restore-preview"); root.replaceChildren();
  const conflicts = conflictList(result);
  const errors = result.errors || [];
  renderKnowledgeUsage(result.usage || result.quota_impact, result.limits);
  const summary = document.createElement("p"); summary.className = "helper-text";
  summary.textContent = `Archive SHA256 ${String(result.archive_sha256 || "미제공")} · 충돌 ${conflicts.length}개 · 오류 ${errors.length}개 · quota ${JSON.stringify(result.quota_impact || {})}`;
  root.append(summary);
  errors.forEach((error) => { const row = document.createElement("p"); row.className = "notice notice-error"; row.textContent = `${error.row_number == null ? "백업" : `행 ${error.row_number}`} · ${String(error.code || "invalid_archive")} · ${String(error.message || "항목을 복원할 수 없습니다.")}`; root.append(row); });
  conflicts.forEach((conflict) => {
    const item = document.createElement("article"); item.className = "knowledge-import-record";
    const title = document.createElement("strong"); title.textContent = `${String(conflict.title || "기존 문서 충돌")} · ID ${String(conflict.document_id || conflict.archive_document_id || "알 수 없음")}`;
    const select = document.createElement("select"); select.className = "text-input knowledge-restore-action"; select.dataset.documentId = String(conflict.document_id || conflict.archive_document_id || "");
    const placeholder = document.createElement("option"); placeholder.value = ""; placeholder.textContent = "복원 방식 선택"; select.append(placeholder);
    for (const [value, text] of [["skip", "현재 문서 유지 · 건너뛰기"], ["replace", "백업 내용으로 교체"]]) { const option = document.createElement("option"); option.value = value; option.textContent = text; select.append(option); }
    item.append(title, select); root.append(item);
  });
  state.knowledgeRestore.preview = result;
  updateKnowledgeRestoreCommitButton();
}

function updateKnowledgeRestoreCommitButton() {
  const restore = state.knowledgeRestore;
  const conflicts = conflictList(restore?.preview);
  const choices = $$(".knowledge-restore-action");
  const chosen = conflicts.every((conflict) => choices.find((select) => select.dataset.documentId === String(conflict.document_id || conflict.archive_document_id || ""))?.value);
  $("#knowledge-restore-commit-button").disabled = !restore?.preview?.archive_sha256 || Boolean(restore.preview.errors?.length) || !chosen;
}

async function previewKnowledgeRestore() {
  const item = state.knowledgeRestore;
  if (!item) return;
  $("#knowledge-restore-preview-button").disabled = true;
  $("#knowledge-restore-status").textContent = "백업 형식, 해시, 참조와 충돌을 확인하는 중입니다. 아직 복원하지 않습니다.";
  try {
    const result = await api("/api/knowledge/restore/preview", { archive: item.archive });
    renderKnowledgeRestorePreview(result);
    $("#knowledge-restore-status").textContent = "복원 미리보기를 확인하세요. 충돌이 있으면 각 항목의 방식을 선택해야 합니다.";
  } catch (error) {
    item.preview = null; $("#knowledge-restore-preview").replaceChildren();
    $("#knowledge-restore-status").textContent = `복원 미리보기 실패 · ${error.message || "파일이 유효한 UTF-8 JSON 백업인지 확인하세요."}`;
  } finally { $("#knowledge-restore-preview-button").disabled = false; updateKnowledgeRestoreCommitButton(); }
}

async function commitKnowledgeRestore() {
  const item = state.knowledgeRestore;
  if (!item?.preview?.archive_sha256) return;
  const actions = [...$$(".knowledge-restore-action")].map((select) => ({ document_id: select.dataset.documentId, action: select.value }));
  if (actions.some((choice) => !["skip", "replace"].includes(choice.action))) return;
  const button = $("#knowledge-restore-commit-button"); button.disabled = true;
  try {
    const result = await api("/api/knowledge/restore/commit", { archive: item.archive, expected_sha256: item.preview.archive_sha256, actions });
    $("#knowledge-restore-status").textContent = `복원 완료 · 문서 ${JSON.stringify(result.document_outcomes || result.documents || [])} · 평가 ${JSON.stringify(result.judgment_outcomes || result.judgments || [])}`;
    renderKnowledgeUsage(result.usage, result.limits);
    await refreshKnowledgeAfterMutation("백업을 복원했습니다. 검색 결과를 다시 불러오고 비공개 Elasticsearch 상태를 확인하세요.");
  } catch (error) { $("#knowledge-restore-status").textContent = `복원 실패 · ${error.message || "미리보기를 다시 실행하고 충돌 선택을 확인하세요."}`; }
  finally { updateKnowledgeRestoreCommitButton(); }
}

async function exportKnowledgeArchive() {
  const button = $("#knowledge-export-button"); button.disabled = true;
  try {
    const archive = await api("/api/knowledge/export", {});
    const blob = new Blob([JSON.stringify(archive, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = `private-knowledge-${new Date().toISOString().slice(0, 10)}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    $("#knowledge-import-status").textContent = `계정 전용 백업을 다운로드했습니다 · 문서 ${archive.documents?.length || 0}개 · 평가 ${archive.judgments?.length || 0}개.`;
  } catch (error) { $("#knowledge-import-status").textContent = `내보내기 실패 · ${error.message || "로그인 상태를 확인하세요."}`; }
  finally { button.disabled = false; }
}

function knowledgeAction(label, action, id, danger = false) {
  const button = document.createElement("button");
  button.type = "button"; button.className = `button button-secondary button-small${danger ? " knowledge-delete" : ""}`;
  button.textContent = label; button.dataset.knowledgeAction = action; button.dataset.documentId = String(id);
  return button;
}

function resetKnowledgeEditor() {
  state.knowledgeDocumentId = null; state.knowledgePreviewKey = null; state.knowledgeEditing = true;
  $("#knowledge-title").value = ""; $("#knowledge-source").value = ""; $("#knowledge-content").value = ""; $("#knowledge-file").value = "";
  $("#knowledge-editor-status").textContent = "제목과 내용을 입력한 뒤 청크 미리보기를 확인하세요.";
  renderKnowledgeChunks([]); updateKnowledgeEditor();
}

async function openKnowledgeDocument(documentId, editing = false) {
  $("#knowledge-editor-status").textContent = "문서를 불러오는 중입니다.";
  try {
    const result = await api("/api/knowledge/get", { document_id: documentId });
    const item = result || {};
    state.knowledgeDocumentId = item.document_id; state.knowledgeEditing = editing; state.knowledgePreviewKey = null;
    $("#knowledge-title").value = String(item.title || ""); $("#knowledge-source").value = String(item.source_label || ""); $("#knowledge-content").value = String(item.content || "");
    $("#knowledge-editor-status").textContent = editing ? "문서를 불러왔습니다. 수정한 뒤 저장하려면 새 청크 미리보기를 확인하세요." : "저장된 문서와 서버가 저장한 청크를 표시합니다. 수정하려면 ‘수정’을 선택하세요.";
    renderKnowledgeChunks(result.chunks || []); updateKnowledgeEditor();
    $("#knowledge-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    if (editing) $("#knowledge-title").focus();
  } catch {
    $("#knowledge-editor-status").textContent = "문서를 열지 못했습니다. 목록을 새로고침한 뒤 다시 시도하세요.";
  }
}

function renderKnowledgeEvalConcepts() {
  const select = $("#knowledge-eval-concept");
  if (!select) return;
  const selectedId = select.value || state.knowledgeEval?.concept_id || "";
  select.replaceChildren();
  const placeholder = document.createElement("option"); placeholder.value = "";
  placeholder.textContent = state.concepts.length ? "개념 선택" : "저장한 개념 없음";
  select.append(placeholder);
  state.concepts.forEach((concept) => {
    const option = document.createElement("option"); option.value = String(concept.id || "");
    option.textContent = String(concept.name || "이름 없는 개념"); select.append(option);
  });
  select.value = state.concepts.some((concept) => String(concept.id) === String(selectedId)) ? String(selectedId) : "";
  refreshKnowledgeEvalQueries();
  if (!state.concepts.length) $("#knowledge-eval-status").textContent = "비교할 저장 개념이 없습니다. 개념을 먼저 저장하세요.";
  else if (!select.value && !state.knowledgeEval) $("#knowledge-eval-status").textContent = "저장한 개념과 질의를 선택하세요.";
}

function refreshKnowledgeEvalQueries() {
  const conceptSelect = $("#knowledge-eval-concept");
  const querySelect = $("#knowledge-eval-query");
  if (!conceptSelect || !querySelect) return;
  const concept = state.concepts.find((item) => String(item.id) === conceptSelect.value);
  const previous = querySelect.value || state.knowledgeEval?.query_id || "";
  querySelect.replaceChildren();
  const queries = Array.isArray(concept?.queries) ? concept.queries : [];
  const placeholder = document.createElement("option"); placeholder.value = "";
  placeholder.textContent = concept ? (queries.length ? "질의 선택" : "저장한 질의 없음") : "먼저 개념을 선택하세요";
  querySelect.append(placeholder);
  queries.forEach((query) => {
    const option = document.createElement("option"); option.value = String(query.id || "");
    option.textContent = String(query.query || "내용 없는 질의"); querySelect.append(option);
  });
  querySelect.disabled = !queries.length;
  querySelect.value = queries.some((query) => String(query.id) === String(previous)) ? String(previous) : "";
  $("#knowledge-eval-run").disabled = !(concept && queries.length && querySelect.value);
  if (concept && !queries.length && !state.knowledgeEval) $("#knowledge-eval-status").textContent = "이 개념에는 저장된 질의가 없습니다. 개념 편집 화면에서 질의를 저장하세요.";
}

function clearKnowledgeEval(message = "") {
  state.knowledgeEval = null;
  state.knowledgeEvalRequest += 1;
  $("#knowledge-eval-result")?.replaceChildren();
  if (message) $("#knowledge-eval-status").textContent = message;
}

function appendKnowledgeEvalJson(root, title, value) {
  const section = document.createElement("section"); section.className = "knowledge-eval-data";
  const heading = document.createElement("h4"); heading.textContent = title;
  const pre = document.createElement("pre");
  try { pre.textContent = JSON.stringify(value ?? {}, null, 2); }
  catch { pre.textContent = String(value ?? ""); }
  section.append(heading, pre); root.append(section);
}

function appendKnowledgeEvalMetrics(root, title, metrics = {}) {
  const section = document.createElement("section"); section.className = "knowledge-eval-data knowledge-eval-metrics";
  const heading = document.createElement("h4"); heading.textContent = title; section.append(heading);
  const rows = [
    [`nDCG@${metrics.k ?? "K"}`, metrics.ndcg_at_k, "상위 순서와 저장된 관련성 등급을 함께 요약합니다. 이 결과와 현재 평가 기록에 한정된 값입니다."],
    ["평가된 결과 비율", metrics.judged_coverage, "이번 결과 중 평가 기록이 있는 문서의 비율입니다."],
    ["알려진 관련 문서 재현율", metrics.known_positive_recall, "관련하다고 이미 평가한 문서 중 이번 결과에 나타난 비율입니다. 미평가 문서의 관련성은 알 수 없습니다."],
  ];
  const list = document.createElement("dl"); list.className = "knowledge-eval-metric-list";
  rows.forEach(([labelText, value, explanation], index) => {
    const label = document.createElement("dt"); label.textContent = labelText;
    const detail = document.createElement("dd");
    const number = Number(value);
    const displayed = value == null || !Number.isFinite(number)
      ? "정보 없음"
      : index === 0 ? String(value) : `${(number * 100).toFixed(1)}% (${String(value)})`;
    const strong = document.createElement("strong"); strong.textContent = displayed;
    const note = document.createElement("small"); note.textContent = explanation;
    detail.append(strong, note); list.append(label, detail);
  });
  const countsHeading = document.createElement("h5"); countsHeading.textContent = "평가 문서 수";
  const counts = document.createElement("p"); counts.className = "knowledge-eval-counts";
  counts.textContent = `상위 K ${metrics.k ?? "정보 없음"} · 평가 완료 ${metrics.judged_count ?? "정보 없음"} · 관련 평가(1–3) ${metrics.positive_count ?? "정보 없음"} · 미평가 ${metrics.unjudged_count ?? "정보 없음"} · 오래된 평가 ${metrics.stale_count ?? "정보 없음"}`;
  section.append(list, countsHeading, counts);
  if (metrics.source_counts && typeof metrics.source_counts === "object") {
    const sourceHeading = document.createElement("h5"); sourceHeading.textContent = "출처별 평가 수"; section.append(sourceHeading);
    const sourceList = document.createElement("ul"); sourceList.className = "knowledge-eval-source-counts";
    Object.entries(metrics.source_counts).forEach(([source, countsBySource]) => {
      const item = document.createElement("li");
      item.textContent = `${source}: 평가 ${countsBySource?.judged ?? 0} · 관련 ${countsBySource?.positive ?? 0} · 미평가 ${countsBySource?.unjudged ?? 0} · 오래됨 ${countsBySource?.stale ?? 0}`;
      sourceList.append(item);
    });
    section.append(sourceList);
  }
  root.append(section);
}

function renderKnowledgeEvalResult(result) {
  const root = $("#knowledge-eval-result"); root.replaceChildren();
  const intro = document.createElement("div"); intro.className = "knowledge-eval-query";
  const query = document.createElement("strong"); query.textContent = String(result.query || "");
  const split = document.createElement("small");
  split.textContent = `저장 질의 구분(참고 정보): ${String(result.split || "정보 없음")} · 이 로컬 비교에서는 질의 구분을 문맥으로만 표시합니다.`;
  intro.append(query, split); root.append(intro);

  const scoreNote = document.createElement("p"); scoreNote.className = "knowledge-eval-score-note";
  scoreNote.textContent = "FTS5 BM25 점수는 작을수록 앞에 표시되며, 확률이 아니고 Elasticsearch 점수와 비교할 수 없습니다.";
  root.append(scoreNote);
  const cueNote = document.createElement("p"); cueNote.className = "knowledge-eval-score-note";
  cueNote.textContent = "일치 표현 표시는 각 결과의 대표 청크에서 확인한 어휘 일치 단서입니다. 본문·제목·출처 표시에 있을 수 있으며 순위 점수의 원인을 설명하지 않고 의미상 관련성의 증거도 아닙니다.";
  root.append(cueNote);

  const behavior = result.weight_behavior;
  if (behavior && typeof behavior === "object") {
    const weightNote = document.createElement("section"); weightNote.className = "knowledge-eval-score-note";
    weightNote.setAttribute("aria-label", "로컬 가중치 적용 안내");
    const title = document.createElement("h3"); title.textContent = "저장된 가중치와 로컬 검색";
    const detail = document.createElement("p");
    const conceptWeight = Number(behavior.concept_weight ?? 0);
    const relatedWeight = Number(behavior.related_weight ?? 0);
    const expressions = Number(behavior.concept_expression_count ?? 0);
    const relatedTotal = Number(behavior.related_terms_total ?? 0);
    const relatedIncluded = Number(behavior.related_terms_included ?? 0);
    detail.textContent = `서버가 불러온 저장값: 개념 ${conceptWeight} (${behavior.concept_expressions_included ? `표현 ${expressions}개 포함` : `표현 ${expressions}개 미포함`}), 관련 표현 ${relatedWeight} (저장 ${relatedTotal}개 중 ${relatedIncluded}개 포함). 로컬 FTS5에서는 양수 여부가 표현 묶음의 포함 여부를 정하고, 숫자의 크기는 점수나 순위를 바꾸지 않습니다.`;
    const boundary = document.createElement("p");
    boundary.textContent = "이 비교는 계정의 로컬 비공개 SQLite 문서 모음을 사용합니다. Elasticsearch의 문서 모음과 다를 수 있습니다. 숫자형 부스트는 별도의 Elasticsearch 기반 검색 흐름에서 의미가 있지만, 그 결과가 이 SQLite 문서 모음의 검색 결과를 나타내지는 않습니다.";
    weightNote.append(title, detail, boundary); root.append(weightNote);
  }

  const metricGrid = document.createElement("div"); metricGrid.className = "knowledge-eval-data-grid";
  appendKnowledgeEvalMetrics(metricGrid, "기준 질의", result.metrics?.baseline);
  appendKnowledgeEvalMetrics(metricGrid, "질의 + 저장 개념 표현", result.metrics?.expanded);
  root.append(metricGrid);

  const limits = document.createElement("div"); limits.className = "knowledge-eval-limits";
  appendKnowledgeEvalJson(limits, "이 비교의 한계", result.limits);
  root.append(limits);

  const baselineHits = Array.isArray(result.baseline?.hits) ? result.baseline.hits : [];
  const expandedHits = Array.isArray(result.expanded?.hits) ? result.expanded.hits : [];
  const docs = new Map();
  for (const [kind, hits] of [["baseline", baselineHits], ["expanded", expandedHits]]) {
    hits.forEach((hit) => {
      const id = String(hit.document_id ?? "");
      if (!id) return;
      const doc = docs.get(id) || { id, baseline: null, expanded: null, preferred: hit };
      doc[kind] = hit;
      if (!doc.preferred || kind === "baseline") doc.preferred = hit;
      docs.set(id, doc);
    });
  }
  const heading = document.createElement("h4"); heading.className = "knowledge-eval-hits-title";
  heading.textContent = `문서 비교 · 기준 질의 ${Number(result.baseline?.total ?? baselineHits.length)}개 / 확장 질의 ${Number(result.expanded?.total ?? expandedHits.length)}개`;
  root.append(heading);
  const list = document.createElement("div"); list.className = "knowledge-eval-hits";
  if (!docs.size) {
    const empty = document.createElement("p"); empty.className = "knowledge-status"; empty.textContent = "기준 검색과 확장 검색 모두에서 일치한 문서가 없습니다."; list.append(empty);
  }
  for (const doc of docs.values()) {
    const hit = doc.preferred || {};
    const card = document.createElement("article"); card.className = "knowledge-eval-hit";
    const header = document.createElement("div"); header.className = "knowledge-eval-hit-header";
    const title = document.createElement("strong"); title.textContent = String(hit.title || "제목 없는 문서");
    const source = document.createElement("small"); source.textContent = String(hit.source_label || "출처 표시 없음");
    header.append(title, source); card.append(header);
    const ranks = document.createElement("div"); ranks.className = "knowledge-eval-ranks";
    const groupLabels = new Map([
      ["saved_query", "저장 질의 표현"],
      ["concept_expressions", "저장 개념 표현"],
      ["related_terms", "저장 관련 표현"],
    ]);
    for (const [key, label] of [["baseline", "기준 질의"], ["expanded", "확장 질의"]]) {
      const found = doc[key]; const rank = document.createElement("span");
      rank.textContent = found ? `${label} · ${Number(found.rank) || "순위 없음"}위 · 점수 ${Number(found.score).toFixed(3)}` : `${label} · 결과에 없음`;
      rank.classList.toggle("missing", !found); ranks.append(rank);
      if (found) {
        const cues = document.createElement("span"); cues.className = "knowledge-eval-match-groups";
        const groups = Array.isArray(found.matched_groups) ? found.matched_groups : [];
        groups.forEach((groupId) => {
          if (!groupLabels.has(groupId)) return;
          const badge = document.createElement("span"); badge.textContent = groupLabels.get(groupId); cues.append(badge);
        });
        ranks.append(cues);
      }
    }
    card.append(ranks);
    const chunk = document.createElement("small"); chunk.className = "knowledge-eval-chunk";
    chunk.textContent = `대표 청크: ${String(hit.chunk_id || "정보 없음")}`; card.append(chunk);
    const excerpt = document.createElement("p"); excerpt.textContent = String(hit.excerpt || "발췌 없음"); card.append(excerpt);

    const judgment = doc.baseline?.judgment || doc.expanded?.judgment || null;
    const controls = document.createElement("div"); controls.className = "knowledge-eval-judgment";
    const label = document.createElement("label"); label.textContent = "문서 관련성 평가";
    const select = document.createElement("select"); select.className = "text-input knowledge-eval-rating"; select.dataset.documentId = doc.id;
    [["", "미평가"], ["0", "0 · 관계없음"], ["1", "1 · 조금 관련"], ["2", "2 · 관련"], ["3", "3 · 매우 관련"]].forEach(([value, text]) => {
      const option = document.createElement("option"); option.value = value; option.textContent = text; select.append(option);
    });
    select.value = judgment?.rating == null ? "" : String(judgment.rating);
    const stale = document.createElement("small"); stale.className = `knowledge-eval-stale${judgment?.stale ? " is-stale" : ""}`;
    stale.textContent = judgment?.stale ? "이전 질의/개념 기준 평가 · 다시 확인 권장" : judgment ? "현재 기준 평가" : "평가 기록 없음";
    const feedback = document.createElement("small"); feedback.className = "knowledge-eval-save-status"; feedback.setAttribute("aria-live", "polite");
    label.append(select); controls.append(label, stale, feedback); card.append(controls); list.append(card);
  }
  root.append(list);
}

async function runKnowledgeEval() {
  if (state.knowledgeEvalInFlight) return false;
  const conceptId = $("#knowledge-eval-concept").value;
  const queryId = $("#knowledge-eval-query").value;
  const concept = state.concepts.find((item) => String(item.id) === conceptId);
  if (!concept) { clearKnowledgeEval("선택한 저장 개념이 없습니다. 개념 목록을 새로고침하세요."); return false; }
  if (!(concept.queries || []).some((query) => String(query.id) === queryId)) { clearKnowledgeEval("선택한 질의를 찾을 수 없습니다. 개념의 저장 질의를 확인하세요."); return false; }
  state.knowledgeEvalInFlight = true;
  const requestId = ++state.knowledgeEvalRequest;
  state.knowledgeEval = null; $("#knowledge-eval-result").replaceChildren();
  $("#knowledge-eval-run").disabled = true; $("#knowledge-eval-status").textContent = "내 지식 보관함에서 기준 검색과 확장 검색 결과를 비교하는 중입니다.";
  try {
    const result = await api("/api/knowledge/concept-preview", { concept_id: conceptId, query_id: queryId });
    if (requestId !== state.knowledgeEvalRequest) return false;
    state.knowledgeEval = result; renderKnowledgeEvalResult(result);
    $("#knowledge-eval-status").textContent = "비교가 끝났습니다. 순위와 발췌를 살펴보고 문서별 관련성을 평가할 수 있습니다.";
    return true;
  } catch (error) {
    if (requestId !== state.knowledgeEvalRequest) return false;
    const message = error.status === 404
      ? "저장 개념, 질의 또는 비교할 문서를 찾지 못했습니다. 저장 목록을 새로고침하세요."
      : `비교를 실행하지 못했습니다: ${error.message || "로그인 상태와 저장한 개념을 확인하세요."}`;
    $("#knowledge-eval-status").textContent = message;
    return false;
  } finally {
    state.knowledgeEvalInFlight = false;
    if (requestId === state.knowledgeEvalRequest) $("#knowledge-eval-run").disabled = false;
  }
}

async function saveKnowledgeEvalJudgment(select) {
  const result = state.knowledgeEval;
  if (!result) return;
  const docCard = select.closest(".knowledge-eval-hit");
  const status = docCard?.querySelector(".knowledge-eval-save-status");
  const rating = select.value === "" ? null : Number(select.value);
  select.disabled = true;
  if (status) status.textContent = "평가 저장 중…";
  try {
    await api("/api/knowledge/judge", {
      concept_id: result.concept_id,
      query_id: result.query_id,
      document_id: select.dataset.documentId,
      rating,
    });
    const refreshedResult = await runKnowledgeEval();
    if (!refreshedResult) {
      $("#knowledge-eval-status").textContent = "평가는 저장했지만 비교 결과 갱신에 실패했습니다. 다시 비교를 실행하세요.";
      return;
    }
    const refreshed = [...$("#knowledge-eval-result").querySelectorAll(".knowledge-eval-rating")]
      .find((item) => item.dataset.documentId === select.dataset.documentId);
    const feedback = refreshed?.closest(".knowledge-eval-hit")?.querySelector(".knowledge-eval-save-status");
    if (feedback) feedback.textContent = "평가를 저장하고 비교 지표를 갱신했습니다.";
    $("#knowledge-eval-status").textContent = "평가를 저장하고 비교 결과와 지표를 갱신했습니다.";
  } catch (error) {
    if (status) status.textContent = `평가를 저장하지 못했습니다: ${error.message}`;
    select.disabled = false;
  }
}

function invalidateKnowledgeEvalWhileEditing() {
  if (!state.knowledgeEval || String(state.knowledgeEval.concept_id) !== String(state.conceptId || "")) return;
  clearKnowledgeEval("개념 또는 저장 질의가 편집되어 이전 비교를 지웠습니다. 저장 후 다시 실행하세요.");
}

function bindKnowledgeControls() {
  if (state.knowledgeControlsBound) return;
  state.knowledgeControlsBound = true;
  $("#knowledge-eval-concept").addEventListener("change", () => {
    clearKnowledgeEval("개념 선택이 바뀌었습니다. 저장 질의를 고른 뒤 비교를 실행하세요.");
    refreshKnowledgeEvalQueries();
  });
  $("#knowledge-eval-query").addEventListener("change", () => {
    clearKnowledgeEval("질의 선택이 바뀌었습니다. 비교를 실행해 최신 결과를 확인하세요.");
    refreshKnowledgeEvalQueries();
  });
  $("#knowledge-eval-run").addEventListener("click", runKnowledgeEval);
  $("#knowledge-eval-result").addEventListener("change", (event) => {
    const select = event.target.closest(".knowledge-eval-rating");
    if (select) saveKnowledgeEvalJudgment(select);
  });
  $("#concept-editor")?.addEventListener("input", invalidateKnowledgeEvalWhileEditing);
  $("#concept-editor")?.addEventListener("change", invalidateKnowledgeEvalWhileEditing);
  $("#knowledge-eval-status").textContent = "저장한 개념을 불러오는 중입니다.";
  loadConcepts().catch((error) => {
    $("#knowledge-eval-status").textContent = `저장한 개념을 불러오지 못했습니다: ${error.message || "로그인 상태를 확인하세요."}`;
  });
  $("#knowledge-import-file").addEventListener("change", async () => {
    const file = $("#knowledge-import-file").files?.[0];
    state.knowledgeImport = null;
    $("#knowledge-import-preview").replaceChildren();
    $("#knowledge-import-mapping").classList.add("hidden");
    ["#knowledge-import-title-field", "#knowledge-import-content-field", "#knowledge-import-source-field"].forEach((selector) => $(selector).replaceChildren());
    $("#knowledge-import-commit-button").disabled = true;
    $("#knowledge-import-preview-button").disabled = true;
    if (!file) return;
    const format = /\.([^.]+)$/.exec(file.name)?.[1]?.toLowerCase() || "";
    if (!["txt", "md", "csv", "jsonl"].includes(format)) {
      $("#knowledge-import-status").textContent = "지원하지 않는 형식입니다. .txt, .md, .csv 또는 .jsonl 파일을 선택하세요.";
      $("#knowledge-import-file").value = ""; return;
    }
    if (file.size > KNOWLEDGE_MAX_BYTES) {
      $("#knowledge-import-status").textContent = "파일이 1 MiB를 넘습니다. 더 작은 UTF-8 파일을 선택하세요.";
      $("#knowledge-import-file").value = ""; return;
    }
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      strictUtf8(bytes);
      const filename = file.name;
      state.knowledgeImport = { filename, format, contentBase64: bytesToBase64(bytes), fields: null, preview: null };
      $("#knowledge-import-mapping").classList.toggle("hidden", !["csv", "jsonl"].includes(format));
      $("#knowledge-import-preview-button").disabled = false;
      $("#knowledge-import-status").textContent = `${filename} · ${formatKnowledgeBytes(bytes.byteLength)} · UTF-8 확인 완료. 행 미리보기는 아직 저장하지 않습니다.`;
      await previewKnowledgeImport();
    } catch (error) {
      state.knowledgeImport = null;
      $("#knowledge-import-status").textContent = error instanceof TypeError ? "파일이 유효한 UTF-8이 아닙니다. UTF-8로 저장한 뒤 다시 선택하세요." : `파일을 읽지 못했습니다 · ${error.message || "다시 선택하세요."}`;
      $("#knowledge-import-file").value = "";
    }
  });
  $("#knowledge-import-preview-button").addEventListener("click", previewKnowledgeImport);
  $("#knowledge-import-commit-button").addEventListener("click", commitKnowledgeImport);
  $("#knowledge-import-preview").addEventListener("change", (event) => {
    if (!event.target.matches(".knowledge-duplicate-action")) return;
    updateKnowledgeImportCommitButton();
  });
  ["#knowledge-import-title-field", "#knowledge-import-content-field", "#knowledge-import-source-field"].forEach((selector) => $(selector).addEventListener("change", () => {
    if (!state.knowledgeImport) return;
    state.knowledgeImport.preview = null;
    $("#knowledge-import-commit-button").disabled = true;
    $("#knowledge-import-status").textContent = "필드 선택이 바뀌었습니다. 행 미리보기를 다시 실행하세요.";
  }));
  $("#knowledge-export-button").addEventListener("click", exportKnowledgeArchive);
  $("#knowledge-restore-file").addEventListener("change", async () => {
    const file = $("#knowledge-restore-file").files?.[0];
    state.knowledgeRestore = null;
    $("#knowledge-restore-preview").replaceChildren();
    $("#knowledge-restore-preview-button").disabled = true;
    $("#knowledge-restore-commit-button").disabled = true;
    if (!file) return;
    if (!/\.json$/i.test(file.name)) {
      $("#knowledge-restore-status").textContent = "JSON 백업 파일(.json)을 선택하세요."; $("#knowledge-restore-file").value = ""; return;
    }
    if (file.size > KNOWLEDGE_RESTORE_MAX_BYTES) {
      $("#knowledge-restore-status").textContent = "백업 파일이 128 MiB를 넘습니다. 서버의 안전한 복원 크기 제한을 초과합니다."; $("#knowledge-restore-file").value = ""; return;
    }
    try {
      const text = strictUtf8(new Uint8Array(await file.arrayBuffer()));
      const archive = JSON.parse(text);
      if (!archive || typeof archive !== "object" || Array.isArray(archive)) throw new Error("백업은 JSON 객체여야 합니다.");
      state.knowledgeRestore = { filename: file.name, archive, preview: null };
      $("#knowledge-restore-preview-button").disabled = false;
      $("#knowledge-restore-status").textContent = `${file.name} · ${formatKnowledgeBytes(file.size)} · UTF-8 JSON 확인 완료. 복원 전 미리보기를 실행하세요.`;
    } catch (error) {
      $("#knowledge-restore-status").textContent = `백업을 읽지 못했습니다 · ${error.message || "유효한 UTF-8 JSON 파일을 선택하세요."}`;
      $("#knowledge-restore-file").value = "";
    }
  });
  $("#knowledge-restore-preview-button").addEventListener("click", previewKnowledgeRestore);
  $("#knowledge-restore-commit-button").addEventListener("click", commitKnowledgeRestore);
  $("#knowledge-restore-preview").addEventListener("change", (event) => {
    if (event.target.matches(".knowledge-restore-action")) updateKnowledgeRestoreCommitButton();
  });
  $("#knowledge-content").addEventListener("input", updateKnowledgeEditor);
  ["#knowledge-title", "#knowledge-source"].forEach((selector) => $(selector).addEventListener("input", updateKnowledgeEditor));
  $("#knowledge-file").addEventListener("change", async () => {
    const file = $("#knowledge-file").files?.[0]; if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name)) { $("#knowledge-editor-status").textContent = ".txt 또는 .md 파일을 선택하세요."; $("#knowledge-file").value = ""; return; }
    if (file.size > KNOWLEDGE_MAX_BYTES) { $("#knowledge-editor-status").textContent = "파일이 1 MiB를 넘습니다. 더 작은 파일을 선택하세요."; $("#knowledge-file").value = ""; return; }
    try {
      $("#knowledge-content").value = strictUtf8(new Uint8Array(await file.arrayBuffer()));
      if (!$("#knowledge-title").value.trim()) $("#knowledge-title").value = file.name.replace(/\.(txt|md)$/i, "");
      updateKnowledgeEditor(); $("#knowledge-editor-status").textContent = "파일 내용을 가져왔습니다. 제목과 내용을 확인한 뒤 미리보기를 선택하세요.";
    } catch { $("#knowledge-editor-status").textContent = "파일을 읽지 못했습니다. 텍스트 파일을 다시 선택하세요."; }
  });
  $("#knowledge-preview-button").addEventListener("click", async () => {
    const fields = knowledgeFields();
    if (!fields.title || !fields.content.trim()) { $("#knowledge-editor-status").textContent = "제목과 문서 내용을 입력하세요."; return; }
    if (knowledgeSizeBytes(fields.content) > KNOWLEDGE_MAX_BYTES) { $("#knowledge-editor-status").textContent = "문서가 1 MiB를 넘습니다. 내용을 줄인 뒤 다시 미리보세요."; updateKnowledgeEditor(); return; }
    $("#knowledge-preview-button").disabled = true; $("#knowledge-editor-status").textContent = "서버에서 청크를 미리 보는 중입니다.";
    try {
      const result = await api("/api/knowledge/chunks/preview", { content: fields.content, ...selectedKnowledgePolicy() });
      state.knowledgePreviewKey = knowledgePreviewKey(fields); renderKnowledgeChunks(result.chunks || []);
      $("#knowledge-editor-status").textContent = `${result.policy?.strategy || "청크"} 정책 · 실제 source offset과 제공된 token count를 확인했습니다. 저장할 수 있습니다.`; updateKnowledgeEditor();
    } catch { state.knowledgePreviewKey = null; $("#knowledge-editor-status").textContent = "청크 미리보기에 실패했습니다. 제목과 내용을 확인한 뒤 다시 시도하세요."; updateKnowledgeEditor(); }
    finally { $("#knowledge-preview-button").disabled = false; }
  });
  $("#knowledge-save-button").addEventListener("click", async () => {
    const fields = knowledgeFields();
    if (knowledgeSizeBytes(fields.content) > KNOWLEDGE_MAX_BYTES || state.knowledgePreviewKey !== knowledgePreviewKey(fields)) return;
    const payload = state.knowledgeDocumentId ? { document_id: state.knowledgeDocumentId, ...fields } : fields;
    $("#knowledge-save-button").disabled = true; $("#knowledge-editor-status").textContent = "문서를 저장하는 중입니다.";
    try {
      const result = await api("/api/knowledge/save", payload);
      state.knowledgeDocumentId = result.document?.document_id || state.knowledgeDocumentId; state.knowledgePreviewKey = knowledgePreviewKey(fields);
      renderKnowledgeChunks(result.chunks || []); $("#knowledge-editor-status").textContent = "문서를 저장했습니다. 아래 청크는 서버가 저장한 결과입니다.";
      updateKnowledgeEditor(); await refreshKnowledgeAfterMutation("문서를 저장했습니다. 저장된 문서는 아래 목록에서 확인할 수 있습니다.");
    } catch { state.knowledgePreviewKey = null; $("#knowledge-editor-status").textContent = "문서를 저장하지 못했습니다. 내용을 확인한 뒤 다시 미리보고 저장하세요."; updateKnowledgeEditor(); }
  });
  $("#knowledge-new-button").addEventListener("click", resetKnowledgeEditor);
  $("#knowledge-refresh-button").addEventListener("click", loadKnowledgeList);
  $("#knowledge-es-sync").addEventListener("click", syncKnowledgeEs);
  $("#knowledge-es-vector-sync").addEventListener("click", syncKnowledgeEsVectors);
  $("#knowledge-reindex-start").addEventListener("click", async () => {
    const button = $("#knowledge-reindex-start"); button.disabled = true;
    try { await api("/api/knowledge/chunks/policy", { policy: selectedKnowledgePolicy() }); await startKnowledgeReindex(false); }
    catch (error) { $("#knowledge-reindex-status").textContent = error.message || "재청킹 작업을 시작하지 못했습니다."; }
    finally { button.disabled = false; }
  });
  $("#knowledge-policy-save").addEventListener("click", async () => {
    try { const result = await api("/api/knowledge/chunks/policy", { policy: selectedKnowledgePolicy() }); $("#knowledge-reindex-status").textContent = `정책 저장 · ${result.policy.strategy} · ${result.policy_sha256}`; }
    catch (error) { $("#knowledge-reindex-status").textContent = error.message || "정책을 저장하지 못했습니다."; }
  });
  $("#knowledge-reindex-cancel").addEventListener("click", async () => {
    try { renderKnowledgeJob(await api("/api/knowledge/reindex/cancel", { job_id: state.knowledgeReindexJobId })); }
    catch (error) { $("#knowledge-reindex-status").textContent = error.message || "취소 요청을 처리하지 못했습니다."; }
  });
  $("#knowledge-reindex-retry").addEventListener("click", async () => {
    try { await startKnowledgeReindex(true); }
    catch (error) { $("#knowledge-reindex-status").textContent = error.message || "재시도하지 못했습니다."; }
  });
  loadKnowledgePolicy();
  $("#knowledge-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-knowledge-action]"); if (!button) return;
    const id = button.dataset.documentId;
    if (button.dataset.knowledgeAction === "open") await openKnowledgeDocument(id, false);
    else if (button.dataset.knowledgeAction === "edit") await openKnowledgeDocument(id, true);
    else if (button.dataset.knowledgeAction === "delete") {
      if (!window.confirm("이 문서를 삭제할까요?")) return;
      button.disabled = true;
      try { await api("/api/knowledge/delete", { document_id: id }); if (String(state.knowledgeDocumentId) === id) resetKnowledgeEditor(); await refreshKnowledgeAfterMutation("문서를 삭제했습니다. 남은 문서는 목록에서 확인할 수 있습니다."); }
      catch { button.disabled = false; $("#knowledge-list-status").textContent = "문서를 삭제하지 못했습니다. 다시 시도하세요."; }
    }
  });
  $("#knowledge-search-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const query = $("#knowledge-query").value.trim();
    $("#knowledge-results").replaceChildren();
    if (!query) { $("#knowledge-search-status").textContent = "검색어를 입력하세요."; return; }
    $("#knowledge-search-status").textContent = "내 문서에서 검색하는 중입니다.";
    try {
      const result = await api("/api/knowledge/search", { query, limit: 20 });
      const results = Array.isArray(result.results) ? result.results : [];
      $("#knowledge-search-status").textContent = results.length ? `${results.length}개 결과 · SQLite FTS5 BM25 (작은 점수가 앞)` : "일치하는 문서가 없습니다. 다른 단어로 검색해 보세요.";
      results.forEach((hit) => {
        const row = document.createElement("article"); row.className = "knowledge-result";
        const title = document.createElement("strong"); title.textContent = String(hit.title || "제목 없는 문서");
        const meta = document.createElement("small"); meta.textContent = `${hit.source_label || "출처 표시 없음"} · BM25 ${Number(hit.score).toFixed(3)}`;
        const excerpt = document.createElement("p"); excerpt.textContent = String(hit.excerpt || hit.chunk || "");
        const open = knowledgeAction("문서 열기", "open", hit.document_id); row.append(title, meta, excerpt, open); $("#knowledge-results").append(row);
      });
    } catch { $("#knowledge-search-status").textContent = "검색하지 못했습니다. 검색어를 바꾸거나 다시 시도하세요."; }
  });
  $("#knowledge-results").addEventListener("click", (event) => {
    const button = event.target.closest("[data-knowledge-action='open']");
    if (button) openKnowledgeDocument(button.dataset.documentId, false);
  });
  updateKnowledgeEditor(); loadKnowledgeList(); loadKnowledgeEsStatus();
}

function formatNumber(value, digits = 3) {
  return Number(value || 0).toFixed(digits);
}

function localizeConceptWarning(value) {
  const englishWarningCodes = {
    score_not_probability: "Scores rank search results; they are not probabilities.",
    lexical_candidate_evidence: "Expression evidence means the same text appears in a document. Missing evidence does not mean the document is irrelevant.",
  };
  if (state.locale === "en" && englishWarningCodes[value]) return englishWarningCodes[value];
  const warningCodes = {
    score_not_probability: "점수는 검색 순위를 매기는 값이며 확률을 뜻하지 않습니다.",
    lexical_candidate_evidence: "표현 근거는 문서에 같은 글자가 나타났다는 뜻입니다. 근거가 없더라도 문서가 무관하다는 뜻은 아닙니다.",
    stale_judgments: "질의 문구가 바뀌거나 삭제되어 일부 평가를 연결하지 않았습니다. 문서를 다시 평가하세요.",
    pinned_document_missing: "고정한 문서를 현재 인덱스에서 찾지 못했습니다. 문서 ID를 확인하세요.",
    index_identity_unavailable: "인덱스 식별 정보를 확인하지 못했습니다. 실험 기록에서 인덱스 교체 여부를 구분할 수 없습니다.",
    judged_only_ndcg: "순위 점수는 평가한 문서만으로 계산합니다. 미평가 문서는 무관한 문서로 보지 않으며, 결과 내 미평가와 명시적 미평가를 따로 표시합니다. 고정 위치는 검색 순위에 더하지 않습니다.",
    validation_unavailable: "검증용으로 평가한 문서가 없어 일반화 여부를 확인할 수 없습니다. 현재 결과는 학습용 평가에만 해당합니다.",
    mapping_conflict: "같은 필드 경로에 서로 다른 형식이 있어 필드 선택이 제한될 수 있습니다.",
    specialized_field_unsupported: "일부 특수 형식 필드는 검색에 사용할 수 없어 제외했습니다.",
    sample_not_query_ranked: "예시 문서는 인덱스 확인용입니다. 검색 정답이나 관련 문서로 평가하지 않습니다.",
    mapping_unavailable: "인덱스 필드 정보를 확인하지 못했습니다. 연결과 인덱스를 확인하세요.",
    diagnostic_cause_uncertain: "현재 확인한 검색 조건만으로는 빠진 이유를 단정할 수 없습니다.",
    diagnostic_document_missing: "선택한 인덱스에서 문서를 읽을 수 없습니다. 인덱스와 문서 ID를 확인하세요.",
  };
  if (warningCodes[value]) return warningCodes[value];
  const message = typeof value === "string" ? value : JSON.stringify(value);
  const lower = message.toLowerCase();
  if (lower.includes("scores are ranking scores, not probabilities")) return state.locale === "en" ? "Scores rank search results; they are not probabilities." : "점수는 검색 순위를 매기는 값이며 확률을 뜻하지 않습니다.";
  if (lower.includes("lexical evidence is a surface-text match")) return state.locale === "en" ? "Expression evidence means the same text appears in a document. Missing evidence does not mean the document is irrelevant." : "표현 근거는 문서에 같은 글자가 나타났다는 뜻입니다. 근거가 없더라도 문서가 무관하다는 뜻은 아닙니다.";
  if (lower.includes("older query version")) return "저장된 질의 문구가 이전 버전이라 해당 평가는 이번 비교에 연결하지 않았습니다. 문서를 다시 평가하세요.";
  if (lower.includes("pinned document") && lower.includes("could not be found")) return `고정한 문서를 현재 인덱스에서 찾지 못했습니다. ${message.match(/Pinned document (.+?) could not be found/i)?.[1] || "문서 ID를 확인하세요."}`;
  if (lower.includes("validation judgments are unavailable")) return "검증용으로 평가한 문서가 없어 일반화 여부를 확인할 수 없습니다. 현재 결과는 학습용 평가에만 해당합니다.";
  if (lower.includes("ndcg uses a condensed judged-only")) return "순위 점수는 평가한 문서만으로 계산합니다. 미평가 문서는 무관한 문서로 보지 않으며, 평가 문서 포함률을 따로 표시합니다. 고정 위치는 검색 순위에 더하지 않습니다.";
  if (lower.includes("judgments were excluded because their saved query text has changed")) {
    const count = message.match(/^(\d+)/)?.[1] || "일부";
    return `질의 문구가 바뀌거나 삭제되어 평가 ${count}건을 제외했습니다. 문서를 다시 평가하세요.`;
  }
  if (lower.includes("elasticsearch index uuid was unavailable") || lower.includes("elasticsearch index uuid was not returned")) return "인덱스 식별 정보를 확인하지 못했습니다. 실험 기록에서 인덱스 교체 여부를 구분할 수 없습니다.";
  if (lower.includes("explain probes test this exact document")) return "검색 엔진 점검은 이 문서와 질의 조건의 일치 여부를 확인합니다. 문서의 의미 관련성이나 RAG 답변 품질을 판정하지 않습니다.";
  if (lower.includes("no probe established a single cause")) return "한 가지 원인을 확인하지 못했습니다. 매핑과 색인된 문구를 살펴본 뒤 설정 변경을 검토하세요.";
  if (lower.includes("specialized fields are shown as non-searchable")) return message.replace(/Specialized fields are shown as non-searchable in this BM25 concept workflow:/i, "이 검색 방식에서 사용할 수 없는 특수 필드:");
  if (lower.includes("no first-search query was provided")) return "첫 검색어를 입력하면 예시 문서와 함께 살펴볼 수 있습니다. 예시 문서는 정답으로 표시되지 않습니다.";
  return message;
}

function localizedConceptWarnings(result) {
  const items = result?.warning_codes?.length ? result.warning_codes : (result?.warnings || []);
  return items.map(localizeConceptWarning);
}

async function runSearch() {
  if (!state.connected) return showToast("먼저 Elasticsearch에 연결하세요.", true);
  const query = $("#search-query").value.trim();
  if (!query) return showToast("검색 질의를 입력하세요.", true);
  const button = $("#search-button");
  const mode = $("#search-mode").value;
  if (isVectorDependentMode(mode)) {
    const readiness = searchModeReadiness(mode);
    if (readiness.blocked) return showToast(readiness.plain, true);
    if (readiness.requiresModelDownload && !window.confirm(`첫 질의 임베딩을 위해 ${selectedEmbeddingProfile()?.model_name || state.embedding.model_name || "FastEmbed 모델"} 파일을 로컬 캐시에 내려받을 수 있습니다. 계속 검색할까요?`)) return;
  }
  setBusy(button, true, state.locale === "en" ? "Searching" : "검색 중");
  $("#search-results").innerHTML = `<div class="empty-state"><span class="loading-inline"><i class="spinner"></i> ${state.locale === "en" ? (mode === "code_rag" ? "Searching Jira and the gRPC code index" : "Searching Elasticsearch") : (mode === "code_rag" ? "Jira와 gRPC 코드 색인 검색 중" : "Elasticsearch 검색 중")}</span></div>`;
  $("#search-summary").classList.add("hidden");
  try {
    const payload = requestPayload({ query, size: Number($("#search-size").value), boosts: readBoosts(), filters: readFilters(), mode, rank_constant: Number($("#rank-constant").value), ...(mode === "vector" || mode === "hybrid" || mode === "code_rag" ? { profile_id: state.sharedProfileId } : {}) });
    if (mode === "code_rag") {
      const result = await api("/api/code-rag", payload);
      state.lastSearch = { ...payload, result: { ...result.issues, mode: "hybrid" } };
      renderCodeRag(result, query);
    } else {
      const result = await api("/api/search", payload);
      state.lastSearch = { ...payload, result };
      renderSearch(result, query);
    }
  } catch (error) {
    const message = state.locale === "en" ? "Search failed. Check the connection, index, and permissions, then retry." : error.message;
    $("#search-results").innerHTML = `<div class="notice notice-error" role="status" aria-live="polite">${escapeHtml(message)}</div>`;
    showToast(message, true);
  } finally {
    button.innerHTML = `<span>${state.locale === "en" ? "Search" : "검색"}</span><kbd>↵</kbd>`;
    button.disabled = !state.connected;
  }
}

function renderCodeRag(result, query) {
  const issues = result.issues || { hits: [], total: 0 };
  const code = result.code || { code_hits: [], semantic_hits: [] };
  const issueHits = issues.hits || [];
  const codeHits = code.code_hits || [];
  const semanticHits = code.semantic_hits || [];
  const summary = $("#search-summary");
  summary.innerHTML = `<strong>${issueHits.length}</strong> Jira 근거 <span>·</span><strong>${codeHits.length}</strong> 코드 발췌 <span>·</span><strong>${semanticHits.length}</strong> 의미 검색 후보 <span>·</span><span>project ${escapeHtml(code.project || "grpc")}</span>${scoreGuidance("hybrid")}`;
  summary.classList.remove("hidden");

  const answer = result.answer || {};
  const issueSection = issueHits.length
    ? issueHits.map((hit, index) => renderHit(hit, index, query, false)).join("")
    : '<div class="empty-state compact-empty"><p>현재 Elasticsearch 인덱스에서 관련 Jira 문서를 찾지 못했습니다.</p></div>';
  const codeSection = codeHits.length
    ? codeHits.map((hit, index) => `<article class="code-hit-card"><div class="code-hit-heading"><div><span class="code-hit-number">CODE #${index + 1}</span><h4>${escapeHtml(hit.label || hit.qualified_name || "코드 발췌")}</h4></div><code>${escapeHtml(hit.file || "")}${hit.lines ? `:${escapeHtml(hit.lines)}` : ""}</code></div>${hit.qualified_name ? `<div class="code-qualified-name">${escapeHtml(hit.qualified_name)}</div>` : ""}${hit.matched_terms?.length ? `<div class="code-match-terms">검색 일치: ${hit.matched_terms.map(escapeHtml).join(" · ")}</div>` : ""}<pre class="code-snippet">${escapeHtml(hit.snippet || "원문 발췌 없음")}</pre></article>`).join("")
    : '<div class="empty-state compact-empty"><p>문자열/식별자 기준 코드 발췌가 없습니다. 의미 검색 후보를 아래에서 확인하세요.</p></div>';
  const semanticSection = semanticHits.length
    ? `<details class="semantic-candidates"><summary>codebase-memory 의미 검색 후보 ${semanticHits.length}개 <span>후보이므로 원문 코드를 열어 확인하세요.</span></summary><ol>${semanticHits.map((hit) => `<li><strong>${escapeHtml(hit.label || hit.qualified_name || "코드 심볼")}</strong><code>${escapeHtml(hit.file || "")}</code>${hit.qualified_name ? `<small>${escapeHtml(hit.qualified_name)}</small>` : ""}</li>`).join("")}</ol></details>`
    : "";
  const terms = code.expanded_terms || [];
  $("#search-results").innerHTML = `<article class="evidence-answer"><div class="evidence-answer-title"><span>근거 기반 답변 초안</span><span class="extractive-tag">EXTRACTIVE</span></div><p>${escapeHtml(answer.text || "검색된 근거가 없습니다.")}</p><div class="notice notice-muted">${escapeHtml(answer.notice || "아래 Jira 문서와 코드 원문을 함께 확인하세요.")}</div></article>
    <section class="evidence-section"><div class="evidence-section-heading"><h3>Jira RAG 근거</h3><span>${Number(issues.total || issueHits.length).toLocaleString()}개 문서 매치</span></div>${issueSection}</section>
    <section class="evidence-section"><div class="evidence-section-heading"><h3>gRPC 코드 원문 발췌</h3><span>${Number(code.total_code_matches || 0).toLocaleString()}개 코드 후보 · ${escapeHtml(code.repo_path || "")}</span></div>${codeSection}${semanticSection}${terms.length ? `<details class="semantic-candidates"><summary>코드 검색에 사용한 확장 용어 ${terms.length}개</summary><p class="expanded-terms">${terms.map(escapeHtml).join(" · ")}</p></details>` : ""}</section>`;
}

function renderSearch(result, query) {
  const english = state.locale === "en";
  const summary = $("#search-summary");
  const method = { bm25: "BM25", vector: "dense vector", hybrid: `RRF hybrid · k=${result.query.rank_constant}` }[result.mode] || "검색";
  summary.innerHTML = `<strong>${Number(result.total).toLocaleString()}</strong>${english ? " documents matched" : "개 문서 일치"} <span>·</span><span>${method}</span><span>·</span><span>${english ? "Elapsed" : "실행 시간"} ${escapeHtml(result.took_ms ?? "—")} ms</span><span class="spacer"></span><span>${english ? "Query details" : "질의 분석"}</span><details><summary>DSL</summary><pre class="explain-box">${escapeHtml(JSON.stringify(result.query, null, 2))}</pre></details>${scoreGuidance(result.mode)}`;
  summary.classList.remove("hidden");
  const sharedUnavailable = result.shared_search?.state === "unavailable";
  const sharedHtml = sharedUnavailable
    ? `<div class="notice notice-muted">${escapeHtml(english ? "Shared-index search is unavailable. Check search permissions and readiness." : result.shared_search.message || "공유 인덱스 검색을 사용할 수 없습니다.")}</div>`
    : result.hits.length ? result.hits.map((hit, index) => renderHit(hit, index, query, true)).join("") : `<div class="empty-state compact-empty"><p>${english ? "No results in the selected Elasticsearch index." : "선택한 공유 Elasticsearch 인덱스에서 결과가 없습니다."}</p></div>`;
  const privateLane = result.private_knowledge || {};
  const privateHits = privateLane.results || [];
  const privateHtml = privateHits.length ? privateHits.map((hit, index) => {
    const source = hit._source || {};
    return `<article class="hit-card"><div class="hit-heading"><span class="hit-rank">PRIVATE #${index + 1}</span><h3>${escapeHtml(source.title || "내 문서")}</h3><code>${escapeHtml(source.source_label || "내 문서")} · 청크 ${escapeHtml(source.ordinal ?? "")}</code></div><p>${escapeHtml((source.rag_chunk_text || "").slice(0, 700))}</p><small>내 비공개 지식 · 순위와 점수는 공유 인덱스 결과와 직접 비교할 수 없습니다.</small></article>`;
  }).join("") : (privateLane.state === "in_sync")
    ? '<div class="empty-state compact-empty"><p>내 비공개 Elasticsearch 지식에서 결과가 없습니다.</p></div>'
    : (privateLane.state === "empty" || privateLane.state === "not_synced" && !privateLane.local_chunks)
      ? '<div class="empty-state compact-empty"><p>아직 비공개 문서가 없습니다. 내 지식 화면에서 문서를 추가하세요.</p></div>'
      : `<div class="notice notice-muted">${privateLane.state === "unsupported_mode" ? `내 비공개 지식은 ${escapeHtml(privateLane.supported_mode || "BM25")} 검색만 지원합니다. 현재 ${escapeHtml(privateLane.mode || result.mode)} 결과에는 포함되지 않았습니다.` : "비공개 문서가 아직 동기화되지 않았거나 동기화가 실패했습니다. 결과를 숨겼습니다. ‘내 지식’ 화면에서 동기화/재시도를 선택하세요."}</div>`;
  const privateMode = privateLane.mode || "bm25";
  const savedPrivateProfile = state.embeddingProfiles.find((profile) => profile.profile_id === state.privateSavedProfileId);
  const privateMethod = { bm25: "BM25", vector: english ? `vector · ${savedPrivateProfile?.model_name || state.privateSavedProfileId || "saved profile"}` : `벡터 · ${savedPrivateProfile?.model_name || state.privateSavedProfileId || "저장 프로필"}`, hybrid: "RRF hybrid" }[privateMode] || (english ? "private search" : "비공개 검색");
  const privateNote = english ? (privateLane.state === "in_sync" ? `${privateMethod} results use the saved account profile and remain a separate lane. They are not merged with shared results. Scores are not probabilities or quality proof.` : "Private search is unavailable. Check model, mapping, and sync status under Private knowledge.") : privateLane.state === "in_sync" ? `${privateMethod} 결과는 저장된 개인 프로필을 사용하며 별도 계정 비공개 lane입니다. 공유 결과와 합치지 않습니다. ${privateMode === "hybrid" ? "RRF는 순위를 결합하며 원점수를 더하지 않습니다." : "점수는 확률이나 품질 검증 결과가 아닙니다."}` : privateLane.message || "비공개 검색 상태를 확인할 수 없습니다. 내 지식 화면에서 모델, 매핑, 동기화 상태를 확인하세요.";
  const sharedLabel = sharedUnavailable ? (english ? "Unavailable" : "검색을 사용할 수 없음") : `${Number(result.total).toLocaleString()}${english ? " matches" : "개"} · ${method}`;
  $("#search-results").innerHTML = `<section class="evidence-section"><div class="evidence-section-heading"><h3>${english ? "Selected shared index" : "선택한 공유 인덱스"}</h3><span>${sharedLabel}</span></div>${sharedHtml}</section><section class="evidence-section"><div class="evidence-section-heading"><h3>${english ? `Private knowledge · ${privateMethod}` : `내 비공개 지식 · ${privateMethod}`}</h3><span>${privateHits.length}${english ? " · separate ranking" : "개 · 별도 순위"}</span></div>${privateHtml}<p class="helper-text">${escapeHtml(privateNote)}</p></section>`;
}

function scoreGuidance(mode) {
  if (state.locale === "en") {
    const guidance = {
      bm25: "BM25 is this search's text-match score, not a probability or a human relevance judgment. Do not compare it directly with scores from other search modes.",
      vector: "Vector score reflects the selected embedding and similarity settings. It is not a probability or a human relevance judgment, and it is not directly comparable with BM25 or another model.",
      hybrid: "RRF combines result ranks; it does not add raw BM25 and vector scores. RRF is not a probability or a human relevance judgment."
    };
    return `<span class="score-guidance">${guidance[mode] || guidance.bm25}</span>`;
  }
  const guidance = {
    bm25: "BM25 점수는 이 검색의 텍스트 일치 점수입니다. 확률이나 사용자 관련도 등급이 아니며, 다른 검색 방식의 점수와 직접 비교할 수 없습니다.",
    vector: "벡터 점수는 선택한 임베딩·유사도 설정의 유사도 점수입니다. 확률이나 사용자 관련도 등급이 아니며, BM25나 다른 모델 설정의 점수와 직접 비교할 수 없습니다.",
    hybrid: "RRF 점수는 BM25·벡터 결과 목록의 순위를 결합하며, 표시된 원점수의 합이 아닙니다. BM25와 벡터 원점수는 척도가 달라 직접 비교할 수 없고, RRF 점수도 확률이 아닙니다.",
  };
  return `<span class="score-guidance">${guidance[mode] || guidance.bm25}</span>`;
}

function displayTitleScalar(value) {
  if (typeof value === "string") return value.trim() || "";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function capResultTitle(value) {
  return value.length > 240 ? `${value.slice(0, 239).trimEnd()}…` : value;
}

function renderHit(hit, index, query, allowMappedTitle = false) {
  const english = state.locale === "en";
  const source = hit._source || {};
  const selectedIndex = $("#index-name").value.trim();
  const requestedIndex = state.lastSearch?.index || selectedIndex;
  const documentIndex = hit._index || requestedIndex;
  let displayTitle = "";
  const titleField = $("#concept-title-field").value;
  if (allowMappedTitle && requestedIndex === selectedIndex && state.schemaIndex === requestedIndex && titleField) {
    const mappedTitle = state.schema.find((field) => field.name === titleField);
    if (mappedTitle?.searchable && mappedTitle.nested !== true && !mappedTitle.nested_path) {
      displayTitle = displayTitleScalar(sourceField(source, mappedTitle.source_field || titleField));
    }
  }
  if (!displayTitle) displayTitle = displayTitleScalar(source.summary);
  if (!displayTitle) displayTitle = english ? "Untitled document" : "제목 없음";
  displayTitle = capResultTitle(displayTitle);
  const issueKey = source.issue_key || hit._id;
  const components = Array.isArray(source.components) ? source.components : source.components ? [source.components] : [];
  const comments = hit.inner_hits?.comments?.hits?.hits || [];
  const commentHtml = comments.slice(0, 2).map((comment) => `<div class="hit-section"><strong>${english ? "Matching comment" : "댓글 매치"}</strong>${escapeHtml(comment._source?.body || "")}</div>`).join("");
  const scoreLabel = state.lastSearch?.result?.mode === "hybrid" ? "RRF SCORE" : state.lastSearch?.result?.mode === "vector" ? "VECTOR SCORE" : "BM25 SCORE";
  const componentScores = hit.retrieval_scores ? `<div class="hit-section"><strong>${english ? "Raw scores" : "원점수"}</strong>BM25 ${hit.retrieval_scores.bm25 == null ? "—" : formatNumber(hit.retrieval_scores.bm25, 4)} · Vector ${hit.retrieval_scores.vector == null ? "—" : formatNumber(hit.retrieval_scores.vector, 4)}</div>` : "";
  const highlightHtml = renderResultHighlights(hit.highlight, state.lastSearch?.result?.mode, hit.retrieval_scores);
  return `<article class="hit-card" data-hit-id="${escapeHtml(hit._id)}" data-hit-index="${escapeHtml(documentIndex)}">
    <div class="hit-head"><div class="hit-title-wrap"><span class="issue-key">${escapeHtml(issueKey)}</span><h3 class="hit-title">${escapeHtml(displayTitle)}</h3></div><div class="score-box"><div class="score-label">${scoreLabel} · #${index + 1}</div><div class="score-value">${formatNumber(hit._score, 4)}</div></div></div>
    <div class="hit-meta">${documentIndex !== selectedIndex ? `<span class="meta-chip">${escapeHtml(documentIndex)}</span>` : ""}${source.status ? `<span class="meta-chip">${escapeHtml(source.status)}</span>` : ""}${source.priority ? `<span class="meta-chip">${escapeHtml(source.priority)}</span>` : ""}${components.map((item) => `<span class="meta-chip">${escapeHtml(item)}</span>`).join("")}</div>
    ${source.error_signature ? `<div class="hit-section"><strong>Error</strong>${escapeHtml(source.error_signature)}</div>` : ""}
    ${source.root_cause ? `<div class="hit-section"><strong>Root cause</strong>${escapeHtml(source.root_cause)}</div>` : ""}
    ${componentScores}
    ${highlightHtml}
    ${commentHtml}
    <div class="hit-actions"><button data-stage-ai-result="" data-index="${escapeHtml(documentIndex)}">${english ? "Ask AI about this result" : "AI 도우미에게 이 결과 묻기"}</button><button data-open-document="${escapeHtml(hit._id)}" data-index="${escapeHtml(documentIndex)}">${english ? "Document and chunk lab" : "문서 · 청크 랩"}</button>${state.lastSearch?.result?.mode !== "vector" ? `<button data-explain="${escapeHtml(hit._id)}" data-index="${escapeHtml(documentIndex)}">${english ? (state.lastSearch?.result?.mode === "hybrid" ? "Explain BM25 score" : "Explain score") : state.lastSearch?.result?.mode === "hybrid" ? "BM25 점수 설명" : "점수 설명"}</button>` : ""}${source.source_url ? `<a href="${escapeHtml(source.source_url)}" target="_blank" rel="noreferrer">${english ? "Source ↗" : "원본 ↗"}</a>` : ""}</div>
  </article>`;
}

function renderAiContextReadouts() {
  const stagedHost = $("#ai-staged-context");
  const staged = state.stagedAiResultContext;
  if (staged) {
    stagedHost.innerHTML = `<div class="ai-context-card"><div><strong>보낼 예정인 검색 결과</strong><p>아래 내용은 요청 보내기를 누를 때 포함됩니다. 이 선택만으로 대화나 제공자 요청은 만들지 않습니다.</p><p>AI의 답은 참고용 가설인 모델 해석이며, 관련성이나 답변 품질을 증명하지 않습니다.</p></div><dl><dt>제목/요약 (화면에만 표시)</dt><dd>${escapeHtml(staged.title)}</dd><dt>검색어</dt><dd>${escapeHtml(staged.query)}</dd><dt>문서 인덱스</dt><dd>${escapeHtml(staged.document.index)}</dd><dt>문서 ID</dt><dd>${escapeHtml(staged.document.id)}</dd></dl><button data-clear-ai-staged-context type="button" class="button button-secondary button-small">선택 지우기</button></div>`;
  } else stagedHost.replaceChildren();

  const retryHost = $("#ai-retry-context");
  const retry = state.aiLastContext;
  if (retry && state.aiLastMessage) {
    retryHost.innerHTML = `<div class="ai-context-card retry-context-card"><div><strong>다시 시도할 요청의 고정 문맥</strong><p>다시 시도는 아래 문맥을 그대로 사용합니다.</p></div>${retry.query ? `<dl><dt>검색어</dt><dd>${escapeHtml(retry.query)}</dd></dl>` : ""}${retry.document ? `<dl><dt>문서 인덱스</dt><dd>${escapeHtml(retry.document.index)}</dd><dt>문서 ID</dt><dd>${escapeHtml(retry.document.id)}</dd></dl>` : '<p class="helper-text">검색 결과 문맥 없이 다시 시도합니다.</p>'}<button data-clear-ai-retry-context type="button" class="button button-secondary button-small">다시 시도 문맥 지우기</button></div>`;
  } else retryHost.replaceChildren();
}

function stageAiResultContext(button) {
  const card = button.closest(".hit-card");
  const search = state.lastSearch;
  if (!card || !search?.query) return;
  const title = card.querySelector(".hit-title")?.textContent?.trim() || "제목 없음";
  const displayTitle = title.length > 240 ? `${title.slice(0, 239).trimEnd()}…` : title;
  state.stagedAiResultContext = {
    query: search.query,
    title: displayTitle,
    document: { index: card.dataset.hitIndex || search.index || "", id: card.dataset.hitId || "" },
  };
  renderAiContextReadouts();
  const draft = $("#ai-message");
  if (!draft.value.trim()) draft.value = "이 결과를 검색어와 비교해 해석해 주세요. 관련성 판단은 제가 직접 검토하겠습니다.";
  activateTab("concept-panel");
  $("#ai-result-stage-status").textContent = `검색 결과 ${displayTitle}를 선택했습니다. 제목은 화면에만 표시되며 AI 요청에는 포함되지 않습니다.`;
  $("#ai-coach").scrollIntoView({ behavior: "smooth", block: "center" });
  draft.focus({ preventScroll: true });
}

function explainTree(node, depth = 0) {
  if (!node || depth > 7) return "";
  const prefix = "  ".repeat(depth);
  let output = `${prefix}${formatNumber(node.value, 4)} — ${node.description || "score"}\n`;
  for (const child of (node.details || []).slice(0, 20)) output += explainTree(child, depth + 1);
  return output;
}

async function explainHit(button) {
  const card = button?.closest(".hit-card");
  if (!card || !state.lastSearch) return;
  const id = button.dataset.explain;
  const index = button.dataset.index || state.lastSearch.index || $("#index-name").value.trim();
  const existing = card.querySelector(".explain-box.explanation-result");
  if (existing) { existing.remove(); return; }
  button.disabled = true;
  button.textContent = "설명 조회 중…";
  try {
    const search = state.lastSearch;
    const result = await api("/api/explain", requestPayload({
      id, index, query: search.query, boosts: readBoosts(), filters: readFilters(),
    }));
    const pre = document.createElement("pre");
    pre.className = "explain-box explanation-result";
    pre.textContent = result.matched ? explainTree(result.explanation) : "현재 쿼리에서 이 문서가 매치되지 않습니다.";
    card.append(pre);
    button.textContent = "점수 설명 닫기";
  } catch (error) {
    showToast(error.message, true);
    button.textContent = "점수 설명";
  } finally { button.disabled = false; }
}

async function openDocument(button) {
  if (!state.lastSearch) return;
  const id = button.dataset.openDocument;
  const index = button.dataset.index || state.lastSearch.index || $("#index-name").value.trim();
  const cachedHit = state.lastSearch.result.hits.find((hit) => String(hit._id) === id && String(hit._index || state.lastSearch.index || $("#index-name").value.trim()) === index);
  const cached = cachedHit?._source;
  try {
    const result = await api("/api/document", requestPayload({ id, index }));
    state.currentDocument = result._source || cached || {};
    state.currentEmbeddingInput = result.embedding_input || null;
    renderDocument(state.currentDocument, result._id || id);
    activateTab("document-panel");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    if (cached) {
      state.currentDocument = cached;
      state.currentEmbeddingInput = null;
      renderDocument(cached, id);
      activateTab("document-panel");
    } else showToast(error.message, true);
  }
}

function renderDocument(source, id) {
  $("#document-empty").classList.add("hidden");
  $("#document-content").classList.remove("hidden");
  const key = source.issue_key || id;
  $("#document-key").textContent = key;
  $("#document-title").textContent = source.summary || "제목 없음";
  const meta = [source.issue_type, source.status, source.priority, source.language].filter(Boolean);
  $("#document-meta").innerHTML = meta.map((value) => `<span class="meta-chip">${escapeHtml(value)}</span>`).join("");
  const sourceLink = $("#document-source");
  if (source.source_url) {
    sourceLink.href = source.source_url;
    sourceLink.classList.remove("hidden");
  } else sourceLink.classList.add("hidden");
  const input = state.currentEmbeddingInput;
  const inputSourceLabels = { rag_chunk_text: "기존 rag_chunk_text", structured_fields: "구조화 필드 조합", empty: "임베딩 대상 텍스트 없음" };
  $("#document-embedding-origin").textContent = input && inputSourceLabels[input.source]
    ? inputSourceLabels[input.source]
    : "원문 입력을 확인할 수 없습니다";
  $("#document-embedding-input").textContent = input && typeof input.text === "string"
    ? (input.text || "임베딩 대상 텍스트가 비어 있어 벡터 생성 시 건너뜁니다.")
    : "서버에서 원문을 가져오지 못해 실제 임베딩 입력을 확인할 수 없습니다.";
  refreshTokenPreview(input && typeof input.text === "string" ? input.text : null);
  const fields = [
    ["error_signature", "오류 시그니처"], ["description", "설명"],
    ["steps_to_reproduce", "재현 단계"], ["root_cause", "근본 원인"],
    ["workaround_or_fix", "해결 방법"], ["rag_chunk_text", "기존 rag_chunk_text"],
  ];
  $("#document-fields").innerHTML = fields.filter(([field]) => source[field]).map(([field, label]) => `
    <article class="doc-field"><h3>${escapeHtml(label)} · ${escapeHtml(field)}</h3><p>${escapeHtml(source[field])}</p></article>
  `).join("");
  if (Array.isArray(source.comments) && source.comments.length) {
    $("#document-fields").innerHTML += `<article class="doc-field"><h3>댓글 · ${source.comments.length}개</h3>${source.comments.map((comment) => `<div class="doc-comment"><div class="doc-comment-meta">${escapeHtml(comment.author || "unknown")} · ${escapeHtml(comment.role || "")} · ${escapeHtml(comment.created_at || "")}</div><p>${escapeHtml(comment.body || "")}</p></div>`).join("")}</article>`;
  }
  if (!$("#chunk-field-selectors").dataset.ready) {
    $("#chunk-field-selectors").innerHTML = CHUNK_FIELDS.map(([field, label]) => `<label><input type="checkbox" data-chunk-field="${escapeHtml(field)}" ${["summary", "error_signature", "root_cause", "workaround_or_fix", "comments"].includes(field) ? "checked" : ""}>${escapeHtml(label)}</label>`).join("");
    $("#chunk-field-selectors").dataset.ready = "true";
  }
  renderChunkPreview();
}

async function refreshTokenPreview(inputText) {
  const requestId = ++state.tokenPreviewRequest;
  const status = $("#token-preview-status");
  const resultBox = $("#token-preview-result");
  const prepareButton = $("#token-preview-prepare");
  resultBox.classList.add("hidden");
  prepareButton.classList.add("hidden");
  if (inputText === null) {
    status.textContent = "실제 임베딩 입력을 확인할 수 없어 토큰 수를 계산하지 않았습니다.";
    return;
  }
  if (!inputText) {
    status.textContent = "임베딩 대상 텍스트가 비어 있습니다.";
    return;
  }
  status.textContent = "로컬 토크나이저 캐시를 확인하는 중…";
  try {
    const response = await fetch("/api/token-preview/status", { cache: "no-store" });
    const cacheStatus = await response.json();
    if (requestId !== state.tokenPreviewRequest) return;
    if (!cacheStatus.available) {
      status.textContent = cacheStatus.reason || "로컬 토크나이저를 사용할 수 없습니다.";
      if (cacheStatus.tokenizers_installed && cacheStatus.huggingface_hub_installed) prepareButton.classList.remove("hidden");
      return;
    }
    status.textContent = "입력은 이 로컬 앱에서만 토큰화합니다. Elasticsearch 요청은 보내지 않습니다.";
    const preview = await api("/api/token-preview", { input_text: inputText });
    if (requestId !== state.tokenPreviewRequest) return;
    if (!preview.available) {
      status.textContent = preview.reason || "토큰 미리보기를 사용할 수 없습니다.";
      return;
    }
    $("#token-full-count").textContent = Number(preview.full_token_count).toLocaleString();
    $("#token-retained-count").textContent = Number(preview.retained_token_count).toLocaleString();
    $("#token-retained-text").textContent = preview.retained_text;
    $("#token-removed-text").textContent = preview.removed_text || "없음";
    resultBox.classList.remove("hidden");
    status.textContent = preview.truncated
      ? `512 토큰 오른쪽 자르기 · 원문 문자 위치 ${preview.cut_char_offset}부터 제거`
      : "512 토큰 안에 모두 유지됩니다.";
  } catch (error) {
    if (requestId === state.tokenPreviewRequest) status.textContent = `토큰 미리보기 실패: ${error.message}`;
  }
}

async function prepareTokenPreview() {
  const button = $("#token-preview-prepare");
  if (!window.confirm("토큰 미리보기를 위해 공개된 토크나이저와 설정 파일 약 17 MB를 한 번 내려받을까요? 모델 가중치는 받지 않으며 문서 내용은 전송하지 않습니다.")) return;
  button.disabled = true;
  button.textContent = "토크나이저 준비 중…";
  $("#token-preview-status").textContent = "고정 버전의 토크나이저 파일만 다운로드하고 SHA-256을 확인합니다…";
  try {
    const prepared = await api("/api/token-preview/prepare", {});
    if (!prepared.available) throw new Error(prepared.reason || "토크나이저를 준비하지 못했습니다.");
    $("#token-preview-status").textContent = "준비 완료. 현재 입력을 로컬에서 토큰화합니다.";
    await refreshTokenPreview(state.currentEmbeddingInput?.text ?? null);
  } catch (error) {
    $("#token-preview-status").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "토크나이저만 준비 (약 17 MB, 최초 1회)";
  }
}

function renderChunkPreview() {
  const source = state.currentDocument;
  if (!source) return;
  const selected = $$("[data-chunk-field]:checked").map((input) => input.dataset.chunkField);
  const parts = [];
  for (const field of selected) {
    const label = CHUNK_FIELDS.find(([name]) => name === field)?.[1] || field;
    let value = source[field];
    if (field === "comments" && Array.isArray(value)) value = value.map((comment) => `${comment.author || "comment"}: ${comment.body || ""}`).join("\n");
    if (Array.isArray(value)) value = value.join(", ");
    if (value) parts.push(`${label}: ${value}`);
  }
  const words = parts.join("\n\n").trim().split(/\s+/u).filter(Boolean);
  const size = Math.max(20, Math.min(1000, Number($("#chunk-size").value) || 160));
  const overlap = Math.max(0, Math.min(size - 1, Number($("#chunk-overlap").value) || 0));
  const stride = Math.max(1, size - overlap);
  const chunks = [];
  for (let start = 0; start < words.length; start += stride) {
    const end = Math.min(words.length, start + size);
    chunks.push({ start, end, text: words.slice(start, end).join(" ") });
    if (end === words.length) break;
  }
  $("#chunk-summary").textContent = words.length
    ? `${words.length.toLocaleString()} 공백 단위 · ${chunks.length}개 청크 · 겹침 ${overlap}단위`
    : "필드를 선택하면 청크 미리보기가 표시됩니다.";
  $("#chunk-results").innerHTML = chunks.map((chunk, index) => `
    <article class="chunk-card"><div class="chunk-card-head"><span>CHUNK ${String(index + 1).padStart(2, "0")}</span><span>${chunk.end - chunk.start} words · ${chunk.start + 1}–${chunk.end}</span></div><div class="chunk-card-content">${escapeHtml(chunk.text)}</div></article>
  `).join("");
}

function splitTerms(value) { return value.split(",").map((term) => term.trim()).filter(Boolean); }
function sourceField(source, path) {
  const read = (value, parts) => {
    if (!parts.length) return value;
    if (Array.isArray(value)) return value.map((item) => read(item, parts)).filter((item) => item != null);
    if (!value || typeof value !== "object") return undefined;
    return read(value[parts[0]], parts.slice(1));
  };
  return read(source, String(path || "").split("."));
}
function makeId() { return crypto.randomUUID ? crypto.randomUUID() : `q-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

function addRelatedTerm(term = "", relation = "관련 표현", weight = 1) {
  const row = document.createElement("div");
  row.className = "related-row";
  row.innerHTML = `<label class="related-term-label">함께 볼 표현<input class="text-input related-term" maxlength="160" placeholder="예: 지수형 재시도" value="${escapeHtml(term)}"></label><label class="related-relation-label">관계 이름<input class="text-input related-relation" maxlength="80" value="${escapeHtml(relation)}" placeholder="예: 원인"></label><label class="related-weight-label">반영 정도<input class="text-input related-weight" type="number" min="0.01" max="10" step="0.1" value="${escapeHtml(weight)}"></label><button type="button" class="text-button related-remove" aria-label="표현 제거">제거</button>`;
  $("#related-terms").append(row);
}

function addConceptQuery(query = "", split = "train", id = "", informationNeed = "") {
  const row = document.createElement("div");
  row.className = "concept-query-row";
  row.dataset.queryId = id || makeId();
  const informationNeedListId = `information-need-options-${makeId()}`;
  row.innerHTML = `<label class="field-label query-text-label">평가 질의<input class="text-input saved-query-text" maxlength="500" value="${escapeHtml(query)}" placeholder="예: 재시도 대기 시간이 길어지는 문제"></label><label class="field-label information-need-label">정보 요구 묶음 <span>(선택)</span><input class="text-input saved-query-information-need" maxlength="120" value="${escapeHtml(informationNeed)}" placeholder="예: 재시도 안내 찾기"></label><label class="field-label">사용 방식<select class="text-input saved-query-split"><option value="train" ${split === "train" ? "selected" : ""}>설정 조정에 사용</option><option value="validation" ${split === "validation" ? "selected" : ""}>별도 확인용</option></select></label><button type="button" class="text-button query-remove" aria-label="질의 제거">삭제</button>`;
  const informationNeedInput = row.querySelector(".saved-query-information-need");
  const informationNeedList = document.createElement("datalist");
  informationNeedList.id = informationNeedListId;
  informationNeedInput.setAttribute("list", informationNeedListId);
  row.append(informationNeedList);
  $("#concept-queries").append(row);
  refreshQueryChoices();
  refreshInformationNeedSuggestions();
  updateManualDocumentActions();
}

function normalizeInformationNeedSuggestionWhitespace(value) {
  return value.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/gu, " ").replace(/^ | $/g, "");
}

function informationNeedSuggestionKey(value) {
  // Conservative subset of casefold: equal keys cannot merge distinct backend groups.
  return normalizeInformationNeedSuggestionWhitespace(value).replace(/[A-Z]/g, (character) => character.toLowerCase());
}

function refreshInformationNeedSuggestions() {
  const rows = [...$("#concept-queries").querySelectorAll(".concept-query-row")];
  for (const row of rows) {
    const input = row.querySelector(".saved-query-information-need");
    const list = row.querySelector("datalist");
    if (!input || !list) continue;
    const split = row.querySelector(".saved-query-split").value;
    const seen = new Set();
    const options = [];
    for (const candidate of rows) {
      if (candidate === row || candidate.querySelector(".saved-query-split").value !== split) continue;
      const label = normalizeInformationNeedSuggestionWhitespace(candidate.querySelector(".saved-query-information-need").value);
      if (!label) continue;
      const identity = informationNeedSuggestionKey(label);
      if (seen.has(identity)) continue;
      seen.add(identity);
      const option = document.createElement("option");
      option.value = label;
      options.push(option);
    }
    list.replaceChildren(...options);
  }
}

function refreshQueryChoices(selected = $("#concept-query-select").value) {
  const select = $("#concept-query-select");
  const options = [...$("#concept-queries").querySelectorAll(".concept-query-row")].filter((row) => row.querySelector(".saved-query-text").value.trim()).map((row) => ({ id: row.dataset.queryId, text: row.querySelector(".saved-query-text").value.trim() }));
  select.innerHTML = `<option value="">직접 입력</option>${options.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.text)}</option>`).join("")}`;
  if (options.some((item) => item.id === selected)) select.value = selected;
  const manual = $("#manual-query-id");
  if (manual) {
    const manualSelected = manual.value;
    manual.innerHTML = `<option value="">질의를 선택하세요</option>${options.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.text)}</option>`).join("")}`;
    if (options.some((item) => item.id === manualSelected)) manual.value = manualSelected;
  }
  updateManualDocumentActions();
  updateInformationNeedPreviewAction();
  updateModeComparisonAction();
  updateModeComparisonGroupAction();
}

function updateModeComparisonAction() {
  const button = $("#concept-mode-comparison");
  if (button) button.disabled = !vectorCandidateContextValid();
}

function updateModeComparisonGroupAction() {
  const button = $("#concept-mode-comparison-group");
  if (!button) return;
  const readiness = $("#concept-mode-comparison-group-readiness");
  const selectedId = $("#concept-query-select").value;
  const selectedRow = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((row) => row.dataset.queryId === selectedId);
  const selectedQuery = selectedRow?.querySelector(".saved-query-text")?.value.trim() || "";
  const label = selectedRow?.querySelector(".saved-query-information-need")?.value || "";
  const normalizeNeed = (value) => value.trim().replace(/\s+/gu, " ").toLocaleLowerCase("und")
    .replace(/ß/g, "ss").replace(/ς/g, "σ").replace(/[ﬀ-ﬆ]/g, (ligature) => ({ "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st" })[ligature]);
  const identity = normalizeNeed(label);
  const members = identity ? [...$("#concept-queries").querySelectorAll(".concept-query-row")]
    .filter((row) => normalizeNeed(row.querySelector(".saved-query-information-need").value) === identity) : [];
  const split = selectedRow?.querySelector(".saved-query-split")?.value;
  const oneSplit = members.every((row) => row.querySelector(".saved-query-split").value === split);
  const currentIndex = $("#index-name").value.trim();
  let message;
  let status = "blocked";
  if (state.modeComparisonGroupRunning) {
    message = "묶음 비교를 진행 중입니다. 검색이 끝날 때까지 기다려 주세요.";
    status = "running";
  } else if (!state.connected) {
    message = "먼저 Elasticsearch에 연결하세요. ‘연결 확인’을 눌러 현재 인덱스 상태를 확인합니다.";
  } else if (!currentIndex) {
    message = "검색할 인덱스를 입력한 뒤 ‘연결 확인’을 눌러 주세요.";
  } else if (state.connectedIndex !== currentIndex) {
    message = "현재 인덱스는 아직 확인되지 않았습니다. 인덱스 이름을 확인하고 ‘연결 확인’을 눌러 주세요.";
  } else if (!state.connectedIndexExists) {
    message = "현재 연결에서 선택한 인덱스를 찾지 못했습니다. 기존 인덱스를 선택하거나 인덱스를 만든 뒤 다시 연결하세요.";
  } else if (!selectedId || !selectedRow || !selectedQuery) {
    message = "비교 기준으로 삼을 저장 질의를 선택하세요. 필요하면 질의 목록에 먼저 저장해 주세요.";
  } else if (!state.conceptId) {
    message = "비교할 개념을 먼저 저장하세요.";
  } else if (state.savedConceptSnapshot !== JSON.stringify(collectConcept())) {
    message = "개념에 바뀐 내용이 있습니다. 저장한 뒤 비교할 수 있습니다.";
  } else if (!identity) {
    message = "선택한 질의의 ‘정보 요구 묶음’에 이름을 입력하세요.";
  } else if (members.length < 2) {
    message = "같은 정보 요구 이름을 가진 저장 질의를 하나 더 추가해 주세요. 최소 2개가 필요합니다.";
  } else if (members.length > 10) {
    message = "이 묶음에는 질의가 너무 많습니다. 한 번에 비교할 질의를 10개 이하로 줄여 주세요.";
  } else if (!oneSplit) {
    message = "묶음 안의 질의가 서로 다른 사용 방식으로 나뉘어 있습니다. 모두 ‘설정 조정에 사용’ 또는 모두 ‘별도 확인용’으로 맞춰 주세요.";
  } else {
    status = "ready";
    message = `${members.length}개 질의가 준비됐습니다. 각 저장 질의에 BM25와 선택한 벡터 프로필 검색을 실행합니다(최대 ${members.length * 2}번의 검색).`;
  }
  const eligible = status === "ready";
  button.disabled = !eligible;
  button.title = message;
  if (readiness) {
    readiness.textContent = message;
    readiness.dataset.state = status;
  }
}

function updateInformationNeedPreviewAction() {
  const button = $("#information-need-preview");
  if (!button) return;
  const selectedId = $("#concept-query-select").value;
  const selectedRow = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((row) => row.dataset.queryId === selectedId);
  const label = selectedRow?.querySelector(".saved-query-information-need")?.value || "";
  const normalizeNeed = (value) => value.trim().replace(/\s+/gu, " ").toLocaleLowerCase("und")
    .replace(/ß/g, "ss").replace(/ς/g, "σ").replace(/[ﬀ-ﬆ]/g, (ligature) => ({ "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st" })[ligature]);
  const identity = normalizeNeed(label);
  const count = identity ? [...$("#concept-queries").querySelectorAll(".concept-query-row")]
    .filter((row) => normalizeNeed(row.querySelector(".saved-query-information-need").value) === identity).length : 0;
  const savedAndReady = Boolean(state.connected && state.conceptId && selectedId && state.savedConceptSnapshot === JSON.stringify(collectConcept()));
  button.disabled = !(savedAndReady && count >= 2 && count <= 10);
  button.title = count < 2 ? "같은 정보 요구 묶음에 저장 질의가 두 개 이상 필요합니다."
    : count > 10 ? "한 번에 미리볼 수 있는 정보 요구 묶음은 최대 10개 질의입니다."
      : "선택한 저장 질의와 같은 정보 요구 묶음의 질의를 각각 미리 봅니다.";
}

function collectConcept() {
  const related = [...$("#related-terms").querySelectorAll(".related-row")].map((row) => ({
    term: row.querySelector(".related-term").value.trim(), relation: row.querySelector(".related-relation").value.trim() || "관련 표현",
    weight: Math.max(0.01, Math.min(10, Number(row.querySelector(".related-weight").value) || 1)),
  })).filter((item) => item.term);
  const textFields = [...$("#concept-text-fields").querySelectorAll("input:checked")].map((input) => input.value);
  const filterFields = [...$("#concept-filter-fields").querySelectorAll("input:checked")].map((input) => input.value);
  const queries = [...$("#concept-queries").querySelectorAll(".concept-query-row")].map((row) => {
    const query = { id: row.dataset.queryId, query: row.querySelector(".saved-query-text").value.trim(), split: row.querySelector(".saved-query-split").value };
    const informationNeed = row.querySelector(".saved-query-information-need").value.trim().replace(/\s+/g, " ");
    if (informationNeed) query.information_need = informationNeed;
    return query;
  }).filter((item) => item.query);
  const boosts = {};
  textFields.forEach((field) => { boosts[field] = clampNumber($("#concept-field-boosts").querySelector(`[data-boost-field="${CSS.escape(field)}"]`)?.value ?? state.conceptSettings.field_boosts?.[field] ?? 1, 0.1, 10, 1); });
  state.conceptSettings = {
    ...state.conceptSettings,
    concept_weight: clampNumber($("#concept-weight").value, 0.1, 10, 1),
    related_weight: clampNumber($("#related-weight").value, 0.1, 10, 1),
    size: Math.round(clampNumber($("#concept-size").value, 1, 50, 10)),
    candidate_size: Math.max(Math.round(clampNumber($("#concept-size").value, 1, 50, 10)), Math.round(clampNumber($("#concept-candidate-size").value, 10, 100, 50))),
    field_boosts: boosts,
  };
  $("#concept-candidate-size").value = state.conceptSettings.candidate_size;
  return {
    ...(state.conceptId ? { id: state.conceptId } : {}),
    name: $("#concept-name").value.trim(), description: $("#concept-description").value.trim(),
    aliases: splitTerms($("#concept-aliases").value), related,
    excluded_terms: splitTerms($("#concept-exclusions").value),
    corpus: { index: $("#index-name").value.trim(), title_field: $("#concept-title-field").value, text_fields: textFields, filter_fields: filterFields },
    filters: readConceptFilters(),
    settings: { ...state.conceptSettings, field_boosts: boosts, mode: "bm25", rank_constant: 60 },
    queries,
  };
}

function populateConcept(concept) {
  clearDocumentLocatorState();
  clearVectorCandidatePool("");
  state.conceptId = concept.id || null;
  state.tunedSettings = null;
  $("#concept-field-boosts").replaceChildren();
  state.conceptSettings = { mode: "bm25", concept_weight: 1, related_weight: 1, size: 10, candidate_size: 50, rank_constant: 60, field_boosts: {}, ...(concept.settings || {}) };
  $("#concept-weight").value = state.conceptSettings.concept_weight;
  $("#related-weight").value = state.conceptSettings.related_weight;
  $("#concept-size").value = state.conceptSettings.size;
  $("#concept-candidate-size").value = Math.min(100, state.conceptSettings.candidate_size || 50);
  $("#concept-name").value = concept.name || "";
  $("#concept-description").value = concept.description || "";
  $("#concept-aliases").value = (concept.aliases || []).join(", ");
  $("#concept-exclusions").value = (concept.excluded_terms || []).join(", ");
  $("#related-terms").replaceChildren();
  (concept.related || []).forEach((item) => addRelatedTerm(item.term, item.relation, item.weight));
  if (!concept.related?.length) addRelatedTerm();
  $("#concept-queries").replaceChildren();
  (concept.queries || []).forEach((item) => { addConceptQuery(item.query, item.split, item.id, item.information_need || ""); const row = $("#concept-queries").lastElementChild; row.dataset.queryEnsured = "false"; });
  refreshInformationNeedSuggestions();
  const corpus = concept.corpus || {};
  renderSchemaChoices(corpus);
  state.conceptFilters = (concept.filters || []).map((filter) => ({ field: filter.field, value: filter.value }));
  renderConceptFilterRows();
  refreshQueryChoices();
  $("#concept-query").value = "";
  $("#concept-query-select").value = "";
  state.preview = null;
  $("#concept-vector-candidates").disabled = true;
  $("#concept-vector-status").textContent = "";
  $("#concept-vector-results").replaceChildren();
  $("#concept-preview-status").textContent = "";
  $("#concept-preview-results").replaceChildren();
  $("#concept-tune-results").replaceChildren();
  $("#manual-document-result").replaceChildren();
  $("#manual-document-diagnosis").replaceChildren();
  $("#guided-query-text").value = "";
  state.savedConceptSnapshot = JSON.stringify(collectConcept());
  updateTuneReadiness();
  updateManualDocumentActions();
}

async function loadConcepts() {
  try {
    const result = await api("/api/concepts/list", {});
    state.concepts = result.concepts || [];
    const select = $("#saved-concepts");
    select.innerHTML = `<option value="">개념 선택</option>${state.concepts.map((concept) => `<option value="${escapeHtml(concept.id)}">${escapeHtml(concept.name)}</option>`).join("")}`;
    if (state.conceptId) select.value = state.conceptId;
    renderKnowledgeEvalConcepts();
  } catch (error) {
    $("#schema-status").textContent = `저장한 개념을 불러오지 못했습니다: ${error.message}`;
    if ($("#knowledge-eval-status")) $("#knowledge-eval-status").textContent = `저장한 개념을 불러오지 못했습니다: ${error.message}`;
  }
}

function renderSchemaChoices(corpus = {}) {
  const fields = state.schema.filter((field) => field.searchable);
  const title = $("#concept-title-field");
  title.innerHTML = `<option value="">제목 필드 선택</option>${fields.map((field) => `<option value="${escapeHtml(field.name)}">${escapeHtml(field.name)} · ${escapeHtml(field.type)}</option>`).join("")}`;
  title.disabled = !fields.length;
  title.value = corpus.title_field || fields.find((field) => ["title", "name", "summary"].includes(field.name.toLowerCase()))?.name || fields[0]?.name || "";
  const selectedText = new Set(corpus.text_fields || fields.filter((field) => ["text", "match_only_text"].includes(field.type)).map((field) => field.name));
  const selectedFilters = new Set(corpus.filter_fields || []);
  $("#concept-text-fields").innerHTML = fields.map((field) => `<label class="field-check"><input type="checkbox" value="${escapeHtml(field.name)}" ${selectedText.has(field.name) ? "checked" : ""}><span>${escapeHtml(field.name)}${field.nested_path ? ` · ${escapeHtml(field.nested_path)}` : ""}</span><small>${escapeHtml(field.type)}</small></label>`).join("") || '<span class="muted">검색할 수 있는 필드가 없습니다.</span>';
  const filterTypes = new Set(["keyword", "constant_keyword", "integer", "long", "short", "byte", "boolean", "date", "ip"]);
  $("#concept-filter-fields").innerHTML = state.schema.filter((field) => filterTypes.has(field.type)).map((field) => `<label class="field-check"><input type="checkbox" value="${escapeHtml(field.name)}" ${selectedFilters.has(field.name) ? "checked" : ""}><span>${escapeHtml(field.name)}${field.nested_path ? ` · ${escapeHtml(field.nested_path)}` : ""}</span><small>${escapeHtml(field.type)}</small></label>`).join("") || '<span class="muted">필터로 사용할 수 있는 필드가 없습니다.</span>';
  renderConceptFieldBoosts();
}

function renderConceptFieldBoosts() {
  const fields = [...$("#concept-text-fields").querySelectorAll("input:checked")].map((input) => input.value);
  const current = { ...(state.conceptSettings.field_boosts || {}) };
  $("#concept-field-boosts").querySelectorAll("[data-boost-field]").forEach((input) => { current[input.dataset.boostField] = clampNumber(input.value, 0.1, 10, 1); });
  state.conceptSettings.field_boosts = current;
  $("#concept-field-boosts").innerHTML = fields.length ? `<p>본문 필드 반영 정도</p><div class="concept-boost-list">${fields.map((field) => `<label>${escapeHtml(field)}<input class="text-input" data-boost-field="${escapeHtml(field)}" type="number" min="0.1" max="10" step="0.1" value="${escapeHtml(current[field] ?? 1)}"></label>`).join("")}</div>` : '<p class="muted">본문 필드를 선택하면 필드별 반영 정도를 조정할 수 있습니다.</p>';
}

function clampNumber(value, min, max, fallback) { const number = Number(value); return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback; }

function renderConceptFilterRows() {
  const checked = [...$("#concept-filter-fields").querySelectorAll("input:checked")].map((input) => input.value);
  state.conceptFilters = state.conceptFilters.filter((filter) => checked.includes(filter.field));
  $("#concept-filter-rows").innerHTML = state.conceptFilters.map((filter, index) => `<div class="concept-filter-row"><label>필드<select class="text-input concept-filter-field" data-filter-index="${index}">${checked.map((field) => `<option value="${escapeHtml(field)}" ${field === filter.field ? "selected" : ""}>${escapeHtml(field)}</option>`).join("")}</select></label><label>일치 값<input class="text-input concept-filter-value" data-filter-index="${index}" value="${escapeHtml(filter.value)}" placeholder="예: Open"></label><button type="button" class="text-button remove-concept-filter" data-filter-index="${index}" aria-label="조건 제거">제거</button></div>`).join("");
}

function readConceptFilters() {
  return [...$("#concept-filter-rows").querySelectorAll(".concept-filter-row")].map((row) => ({ field: row.querySelector(".concept-filter-field").value, value: row.querySelector(".concept-filter-value").value.trim() })).filter((filter) => filter.field && filter.value);
}

async function loadCorpusSchema() {
  const index = $("#index-name").value.trim();
  if (!state.connected || !index) return;
  const priorCorpus = state.conceptId || state.schemaIndex === index ? collectConcept().corpus : {};
  if (state.schemaIndex !== index) { state.schema = []; state.schemaIndex = ""; renderSchemaChoices(); }
  $("#schema-status").textContent = `${index} 필드를 불러오는 중…`;
  try {
    const result = await api("/api/corpus/schema", { connection: getConnection(), index });
    state.schema = result.fields || [];
    state.schemaIndex = result.index || index;
    renderSchemaChoices(priorCorpus);
    renderConceptFilterRows();
    $("#schema-status").textContent = `${state.schema.length}개 필드를 확인했습니다. 검색 가능한 필드를 선택하세요.${localizedConceptWarnings(result).length ? ` ${localizedConceptWarnings(result).join(" · ")}` : ""}`;
  } catch (error) { $("#schema-status").textContent = `필드 목록을 불러오지 못했습니다: ${error.message}`; }
}

async function runQuickstart() {
  if (!state.connected) return showToast(state.locale === "en" ? "Check the Elasticsearch connection first." : "먼저 Elasticsearch 연결을 확인하세요.", true);
  const button = $("#quickstart-fields");
  button.disabled = true;
  $("#quickstart-preview").innerHTML = `<span class="loading-inline"><i class="spinner"></i> ${copy("fieldLoading").replace("{index}", escapeHtml(state.connectedIndex || $("#index-name").value.trim()))}</span>`;
  try {
    const result = await api("/api/concepts/quickstart", requestPayload());
    state.quickstart = result;
    state.quickstartSampleIndex = 0;
    state.quickstartAppliedFields = false;
    state.schema = result.fields || [];
    state.schemaIndex = result.index || $("#index-name").value.trim();
    renderQuickstartResult(result);
    renderSchemaChoices({ index: result.index, title_field: $("#concept-title-field").value, text_fields: [...$("#concept-text-fields").querySelectorAll("input:checked")].map((input) => input.value), filter_fields: [...$("#concept-filter-fields").querySelectorAll("input:checked")].map((input) => input.value) });
    renderConceptFilterRows();
    if (!state.conceptId) $("#schema-status").textContent = copy("fieldsLoaded").replace("{count}", state.schema.length);
    await loadAiStatus();
  } catch (error) {
    $("#quickstart-preview").innerHTML = `<p class="notice notice-error">${copy("fieldLoadFailed")}</p>`;
  } finally { button.disabled = !state.connected; }
}

function renderQuickstartResult(result) {
  if (!result) return;
  const suggestedTexts = result.suggested_text_fields || [];
  const suggestedTitle = result.suggested_title_field || "";
  const filterTypes = new Set(["keyword", "constant_keyword", "integer", "long", "short", "byte", "boolean", "date", "ip"]);
  const suggestedFilters = result.suggested_filter_fields || state.schema.filter((field) => filterTypes.has(field.type)).map((field) => field.name);
  const describeFields = (names) => names.map((name) => {
    const field = state.schema.find((candidate) => candidate.name === name);
    return field ? `${name} (${field.type})` : name;
  }).join(", ");
  const fieldsLine = `${copy("titleField")}: ${describeFields(suggestedTitle ? [suggestedTitle] : []) || copy("noTitleCandidate")} · ${copy("textField")}: ${describeFields(suggestedTexts) || copy("noFields")} · ${copy("filterField")}: ${describeFields(suggestedFilters) || copy("noFields")}`;
  const samples = (result.sample_documents || []).slice(0, 3);
  const mappingNames = state.schema.map((field) => `${field.name} (${field.type})`);
  const rules = state.locale === "en"
    ? `<p>Suggestions follow this app's mapping-name and type rules; they do not determine semantic fit. Nested fields are excluded from title validation.</p><ul><li>Title: searchable, non-nested fields named title, summary, subject, headline, or name are preferred.</li><li>Text: text, match_only_text, and search_as_you_type are preferred. Fallbacks may include keyword fields and are not equivalent to full-text fields.</li><li>Filters: keyword, numeric, boolean, date, and IP mapping types may be suggested.</li></ul><p>Example _source values do not prove mapping searchability or suitability.</p>`
    : `<p>이 앱의 매핑 이름·타입 규칙에 따른 후보이며, 의미에 맞는 필드인지 판단하지 않습니다. 중첩 필드는 제목 검증에서 제외됩니다.</p><ul><li>제목: 검색 가능한 비중첩 필드 중 title, summary, subject, headline, name 이름을 우선합니다.</li><li>본문: text, match_only_text, search_as_you_type를 우선합니다. 대체 후보에는 keyword가 포함될 수 있으며 전문 검색 필드와 같지 않습니다.</li><li>필터: keyword, 숫자, boolean, date, ip 타입을 후보로 표시합니다.</li></ul><p>예시 _source 값은 매핑의 검색 가능성이나 적합성을 증명하지 않습니다.</p>`;
  const preview = $("#quickstart-preview");
  preview.innerHTML = `<div class="quickstart-preview-grid"><div class="quickstart-fields-summary"><strong>${copy("fieldSummary")}</strong><span>${escapeHtml(fieldsLine)}</span><button type="button" id="apply-quickstart-fields" class="button button-secondary button-small quickstart-confirm">${copy("applyFields")}</button><details class="quickstart-mapping-details quickstart-guidance"><summary>${copy("inspectCriteria")}</summary>${rules}</details><details class="quickstart-mapping-details"><summary>${copy("fieldList").replace("{count}", mappingNames.length)}</summary><p>${copy("titleField")}: ${escapeHtml(describeFields(suggestedTitle ? [suggestedTitle] : []) || copy("noFields"))}</p><p>${copy("textField")}: ${escapeHtml(describeFields(suggestedTexts) || copy("noFields"))}</p><p>${copy("filterField")}: ${escapeHtml(describeFields(suggestedFilters) || copy("noFields"))}</p><ul>${mappingNames.map((name) => `<li>${escapeHtml(name)}</li>`).join("")}</ul></details></div><div class="quickstart-sample-column">${samples.length > 1 ? `<label class="quickstart-sample-picker" for="quickstart-sample-select">${copy("samplePicker")}<select id="quickstart-sample-select" class="text-input" aria-controls="quickstart-sample-panel">${samples.map((sample, index) => `<option value="${index}">${copy("sampleDoc").replace("{n}", index + 1).replace("{total}", samples.length)} · ${escapeHtml(sample._id || "ID")}</option>`).join("")}</select></label>` : ""}<div id="quickstart-sample-panel">${renderQuickstartSample(samples, state.quickstartSampleIndex, suggestedTitle, suggestedTexts, result.index)}</div><p class="quickstart-sample-caveat">${copy("sampleCaveat")}</p></div></div>`;
  preview.dataset.suggestions = JSON.stringify({ title_field: suggestedTitle, text_fields: suggestedTexts, filter_fields: suggestedFilters, index: result.index || $("#index-name").value.trim() });
  if (state.quickstartAppliedFields) renderAppliedQuickstartFields();
}

function renderAppliedQuickstartFields() {
  if (!state.quickstartAppliedFields) return;
  const summary = $("#quickstart-preview .quickstart-fields-summary");
  if (!summary) return;
  summary.querySelector(".selected-field-confirmation")?.remove();
  const currentTitle = $("#concept-title-field").value;
  const currentText = [...$("#concept-text-fields").querySelectorAll("input:checked")].map((input) => input.value);
  const currentFilters = [...$("#concept-filter-fields").querySelectorAll("input:checked")].map((input) => input.value);
  const summaryLine = copy("fieldApplySummary")
    .replace("{title}", escapeHtml(currentTitle || copy("noFields")))
    .replace("{text}", escapeHtml(currentText.join(", ") || copy("noFields")))
    .replace("{filters}", escapeHtml(currentFilters.join(", ") || copy("noFields")));
  summary.insertAdjacentHTML("beforeend", `<span class="selected-field-confirmation">${summaryLine}</span>`);
}

function renderQuickstartSample(samples, sampleIndex, suggestedTitle, suggestedTexts, indexName) {
  const samplesToShow = (samples || []).slice(0, 3);
  const sample = samplesToShow[sampleIndex];
  if (!sample) return `<div class="quickstart-sample"><p>${copy("noSampleDocs")}</p></div>`;
  const titleSource = state.schema.find((field) => field.name === suggestedTitle)?.source_field || suggestedTitle || "";
  const titleValues = sourcePathValues(sample.source || {}, titleSource);
  const bodyValues = suggestedTexts.flatMap((fieldName) => {
    const sourceField = state.schema.find((field) => field.name === fieldName)?.source_field || fieldName;
    return sourcePathValues(sample.source || {}, sourceField).slice(0, 1).map((value) => [fieldName, value]);
  }).slice(0, 2);
  const starterPhrase = quickstartStarterPhrase(titleValues, bodyValues);
  const docId = sample._id == null ? "ID" : String(sample._id);
  const docIndex = sample._index || indexName || "";
  return `<div class="quickstart-sample" aria-live="polite"><h4>${copy("sampleDoc").replace("{n}", sampleIndex + 1).replace("{total}", samplesToShow.length)} · ${escapeHtml(docIndex)} / ${escapeHtml(docId)}</h4>${titleValues.length ? `<p class="sample-title-excerpt"><strong>${escapeHtml(suggestedTitle || copy("sampleTitle"))}:</strong> ${escapeHtml(String(titleValues[0]).slice(0, 220))}</p>` : `<p class="sample-title-excerpt">${copy("missingSampleTitle").replace("{id}", escapeHtml(docId))}</p>`}${bodyValues.map(([field, value]) => `<p><strong>${escapeHtml(field)}:</strong> ${escapeHtml(String(value).slice(0, 420))}</p>`).join("") || `<p>${copy("noSampleBody")}</p>`}${starterPhrase ? `<button type="button" class="button button-secondary button-small quickstart-query-handoff" data-starter-phrase="${escapeHtml(starterPhrase)}">${copy("transferQuery")}</button><p class="quickstart-handoff-help">${copy("editableQueryNote")}</p>` : ""}</div>`;
}

function quickstartStarterPhrase(titleValues, bodyValues) {
  const usableText = (value) => (typeof value === "string" || typeof value === "number")
    ? String(value).replace(/\s+/g, " ").trim()
    : "";
  const title = (titleValues || []).map(usableText).find(Boolean) || "";
  const body = (bodyValues || []).map(([, value]) => usableText(value)).find(Boolean) || "";
  const parts = [];
  if (title) parts.push(title.slice(0, 180));
  if (body && (!title || body !== title)) parts.push(body.slice(0, title ? 300 : 480));
  return parts.join(" ").slice(0, 500).trim();
}

function selectQuickstartSample(index) {
  const samples = (state.quickstart?.sample_documents || []).slice(0, 3);
  const selected = Number(index);
  if (!Number.isInteger(selected) || selected < 0 || selected >= samples.length) return;
  state.quickstartSampleIndex = selected;
  const panel = $("#quickstart-sample-panel");
  if (!panel) return;
  const suggestions = JSON.parse($("#quickstart-preview").dataset.suggestions || "{}");
  panel.innerHTML = renderQuickstartSample(samples, selected, suggestions.title_field, suggestions.text_fields || [], suggestions.index);
}

function sourcePathValues(source, fieldPath) {
  if (!fieldPath) return [];
  const path = String(fieldPath).split(".").filter(Boolean);
  const visit = (value, depth) => {
    if (Array.isArray(value)) return value.flatMap((item) => visit(item, depth));
    if (depth >= path.length) {
      return value == null || typeof value === "object" ? [] : [value];
    }
    if (!value || typeof value !== "object" || !(path[depth] in value)) return [];
    return visit(value[path[depth]], depth + 1);
  };
  const values = visit(source, 0);
  if (values.length) return values;
  const direct = source && Object.hasOwn(source, fieldPath) ? source[fieldPath] : null;
  if (Array.isArray(direct)) return direct.filter((value) => value != null && typeof value !== "object");
  return direct == null || typeof direct === "object" ? [] : [direct];
}

function applyQuickstartFields() {
  let suggestions;
  try { suggestions = JSON.parse($("#quickstart-preview").dataset.suggestions || "{}"); } catch { suggestions = {}; }
  if (!state.quickstart) return;
  if (state.conceptId) return showToast(state.locale === "en" ? "Review saved concept fields in advanced settings." : "저장된 개념의 필드는 고급 설정에서 직접 확인해 바꾸세요.", true);
  renderSchemaChoices({ title_field: suggestions.title_field, text_fields: suggestions.text_fields || [], filter_fields: suggestions.filter_fields || [] });
  renderConceptFilterRows();
  state.quickstartAppliedFields = true;
  renderAppliedQuickstartFields();
  $("#schema-status").textContent = copy("fieldsApplied");
  showToast(copy("fieldsAppliedToast"));
}

async function ensureFeedbackQuery(query, split = "train") {
  const text = String(query || "").trim();
  if (!text) throw new Error("먼저 찾고 싶은 내용을 입력하세요.");
  let row = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((item) => item.querySelector(".saved-query-text").value.trim() === text);
  if (!row) { addConceptQuery(text, split); row = [...$("#concept-queries").querySelectorAll(".concept-query-row")].at(-1); }
  const oldId = row.dataset.queryId;
  const oldName = $("#concept-name").value.trim();
  if (!oldName) $("#concept-name").value = text.slice(0, 120);
  if (!$("#concept-description").value.trim()) $("#concept-description").value = text;
  if (!state.conceptId || JSON.stringify(collectConcept()) !== state.savedConceptSnapshot) {
    if (!await saveConcept({ silent: true })) throw new Error("개념을 저장하지 못해 질의를 준비하지 못했습니다.");
  }
  let ensured = { query_id: row.dataset.queryId };
  if (row.dataset.queryEnsured !== "true") {
    ensured = await api("/api/concepts/ensure-query", { concept_id: state.conceptId, query: text, split: row.querySelector(".saved-query-split").value || split });
    row.dataset.queryId = ensured.query_id;
    row.dataset.queryEnsured = "true";
  }
  if (oldId !== ensured.query_id || oldName !== $("#concept-name").value.trim()) {
    if (!await saveConcept({ silent: true })) throw new Error("질의 ID를 개념에 저장하지 못했습니다.");
  }
  refreshQueryChoices(ensured.query_id);
  $("#concept-query-select").value = ensured.query_id;
  $("#concept-query").value = text;
  return ensured.query_id;
}

async function runGuidedFirstPreview() {
  const text = $("#guided-query-text").value.trim();
  if (!text) return showToast("찾고 싶은 내용을 한 문장으로 입력하세요.", true);
  if (!state.schema.length || ![...$("#concept-text-fields").querySelectorAll("input:checked")].length) {
    $("#schema-status").textContent = "먼저 필드와 예시 문서를 확인하고 본문 필드를 하나 이상 선택하세요.";
    $("#quickstart-fields").focus();
    return;
  }
  try {
    $("#guided-first-preview").disabled = true;
    const queryId = await ensureFeedbackQuery(text, "train");
    await runConceptPreview(queryId);
    $("#concept-preview-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showToast(error.message, true); }
  finally { $("#guided-first-preview").disabled = !state.connected; }
}

async function saveConcept(options = {}) {
  const concept = collectConcept();
  if (!concept.name) { showToast("개념 이름을 입력하세요.", true); return false; }
  if (!concept.corpus.index || !concept.corpus.text_fields.length) { showToast("검색할 본문 필드를 하나 이상 선택하세요.", true); return false; }
  try {
    const result = await api("/api/concepts/save", { concept });
    state.conceptId = result.concept.id || state.conceptId;
    state.conceptSettings = { ...state.conceptSettings, ...(result.concept.settings || {}) };
    concept.id = state.conceptId;
    state.savedConceptSnapshot = JSON.stringify(concept);
    await loadConcepts();
    $("#saved-concepts").value = state.conceptId;
    updateManualDocumentActions();
    updateInformationNeedPreviewAction();
    $("#refresh-profile-versions").disabled = false;
    $("#export-concept-profile").disabled = false;
    if (!options.silent) await loadProfileVersions();
    updateTuneReadiness();
    if (!options.silent) showToast("개념을 저장했습니다.");
    return true;
  } catch (error) { showToast(error.message, true); return false; }
}

function applyTunedSettings(settings = {}) {
  clearVectorCandidatePool("설정이 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요.");
  state.conceptSettings = { ...state.conceptSettings, ...settings, field_boosts: { ...(settings.field_boosts || {}) } };
  $("#concept-weight").value = state.conceptSettings.concept_weight ?? 1;
  $("#related-weight").value = state.conceptSettings.related_weight ?? 1;
  $("#concept-size").value = state.conceptSettings.size ?? 10;
  $("#concept-candidate-size").value = Math.min(100, state.conceptSettings.candidate_size ?? 50);
  $("#concept-field-boosts").replaceChildren();
  renderConceptFieldBoosts();
  showToast("조정한 설정을 입력란에 반영했습니다.");
  refreshTuneMissHandoffs();
}

function chooseQuery() {
  const id = $("#concept-query-select").value;
  const row = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((item) => item.dataset.queryId === id);
  if (row) $("#concept-query").value = row.querySelector(".saved-query-text").value;
}

async function runConceptPreview(forcedQueryId = "") {
  if (!state.connected) return;
  let concept = collectConcept();
  let query = $("#concept-query").value.trim();
  let queryId = forcedQueryId || $("#concept-query-select").value;
  if (!concept.name || !concept.corpus.text_fields.length) return showToast("개념 이름과 검색 본문 필드를 설정하세요.", true);
  if (!query && !queryId) return showToast("검색어를 입력하거나 저장된 질의를 선택하세요.", true);
  const actionGeneration = ++state.informationNeedPreviewGeneration;
  updateInformationNeedPreviewAction();
  $("#concept-preview").disabled = true;
  $("#concept-preview-status").innerHTML = '<span class="loading-inline"><i class="spinner"></i> 개념 적용 전후를 비교하고 있습니다.</span>';
  $("#concept-preview-results").innerHTML = "";
  clearVectorCandidatePool("BM25 비교를 새로 실행했습니다. 벡터 후보를 함께 보려면 다시 불러오세요.");
  try {
    if (query) {
      queryId = await ensureFeedbackQuery(query, "train");
      concept = collectConcept();
    }
    if (actionGeneration !== state.informationNeedPreviewGeneration || !state.connected) return;
    const context = { conceptId: state.conceptId, queryId, querySelection: $("#concept-query-select").value, conceptSelection: $("#saved-concepts").value, snapshot: JSON.stringify(collectConcept()) };
    const current = () => actionGeneration === state.informationNeedPreviewGeneration && state.connected && state.conceptId === context.conceptId && $("#concept-query-select").value === context.querySelection && $("#saved-concepts").value === context.conceptSelection && JSON.stringify(collectConcept()) === context.snapshot;
    const result = await api("/api/concepts/preview", { connection: getConnection(), concept, ...(query ? { query } : {}), ...(queryId ? { query_id: queryId } : {}), filters: concept.filters });
    if (!current()) return;
    state.preview = { ...result, queryId, conceptId: state.conceptId };
    $("#concept-vector-candidates").disabled = !queryId || !state.conceptId || state.savedConceptSnapshot !== JSON.stringify(collectConcept());
    renderConceptPreview(result, queryId);
    $("#concept-preview-status").textContent = `${state.locale === "en" ? "Search complete" : "비교 완료"} · ${result.query || query || (state.locale === "en" ? "Saved query" : "저장된 질의")}`;
    updateTuneReadiness();
    await loadConceptRuns();
  } catch (error) {
    if (actionGeneration === state.informationNeedPreviewGeneration) { $("#concept-preview-status").textContent = error.message; showToast(error.message, true); }
  }
  finally {
    if (actionGeneration === state.informationNeedPreviewGeneration) {
      $("#concept-preview").disabled = !state.connected;
      updateInformationNeedPreviewAction();
    }
  }
}

function renderResultSet(result, label, kind, queryId) {
  const hits = result?.hits || [];
  const selectedConcept = collectConcept();
  const sourceFields = [...new Set([selectedConcept.corpus.title_field, ...selectedConcept.corpus.text_fields].filter(Boolean))];
  const english = state.locale === "en";
  const resultCountLabel = kind === "pool" ? (english ? `${hits.length} · candidates per mode` : `${hits.length}개 · 검색별 후보`) : (english ? `${Number(result?.total || 0).toLocaleString()} matches · top ${hits.length}` : `${Number(result?.total || 0).toLocaleString()}개 · 상위 ${hits.length}개`);
  return `<section class="concept-result-column"><div class="concept-result-heading"><h3>${label}</h3><span>${resultCountLabel}</span></div>${hits.map((hit) => {
    const id = hit._id || "";
    const documentIndex = String(hit._index || selectedConcept.corpus.index || "");
    const source = hit.source || {};
    const titleField = selectedConcept.corpus.title_field;
    const titleSourceField = state.schema.find((field) => field.name === titleField)?.source_field || titleField;
    const titleValue = sourceField(source, titleSourceField);
    const title = source.title || titleValue || source.summary || id;
    const evidence = hit.evidence || [];
    const kindLabels = english ? { concept: "concept", definition: "definition", alias: "alias", related: "related expression" } : { concept: "개념", definition: "설명", alias: "다른 표현", related: "함께 볼 표현" };
    const basisLabels = english ? { lexical: "text match" } : { lexical: "문자 일치" };
    const statusLabels = english ? { candidate: "search candidate" } : { candidate: "검색 후보" };
    const matchedTerms = [...new Set(evidence.map((item) => item.term || item.concept_term).filter(Boolean))];
    const evidenceSummary = matchedTerms.length ? `${english ? "Matched terms" : "일치 표현"}: ${matchedTerms.slice(0, 4).map(escapeHtml).join(", ")}${matchedTerms.length > 4 ? (english ? ` and ${matchedTerms.length - 4} more` : ` 외 ${matchedTerms.length - 4}개`) : ""}` : (english ? "No concept-match evidence is available." : "표시할 개념 일치 근거가 없습니다.");
    const evidenceItems = `${evidence.slice(0, 6).map((item) => `<span class="evidence-chip">${escapeHtml(item.field || (english ? "field" : "필드"))}: ${escapeHtml(item.term || item.concept_term || (english ? "matched term" : "일치 표현"))} · ${escapeHtml(kindLabels[item.kind] || item.kind || (english ? "expression" : "표현"))} · ${escapeHtml(basisLabels[item.basis] || item.basis || (english ? "text match" : "문자 일치"))} · ${escapeHtml(statusLabels[item.status] || item.status || (english ? "candidate" : "후보"))}</span>`).join("")}${evidence.length > 6 ? `<span class="evidence-chip muted">${english ? `${evidence.length - 6} more` : `외 ${evidence.length - 6}건`}</span>` : ""}`;
    const evidenceHtml = evidence.length ? `<div class="evidence-summary">${evidenceSummary}</div><details class="concept-evidence-details"><summary>${english ? `View matched expressions · ${evidence.length}` : `연결된 표현 보기 · ${evidence.length}건`}</summary><div class="concept-evidence-items">${evidenceItems}</div></details>` : (kind === "candidate" ? `<span class="muted">${english ? "No concept-match evidence is available." : "표시할 개념 일치 근거가 없습니다."}</span>` : "");
    let previewText = hit.snippet || evidence.map((item) => item.snippet || "").filter(Boolean).join(" … ");
    const titleText = titleValue == null ? "" : String(Array.isArray(titleValue) ? titleValue.flat(Infinity).join(" ") : titleValue).trim();
    if (kind === "candidate" && (!previewText || (titleText && previewText.trim() === titleText))) {
      for (const field of selectedConcept.corpus.text_fields || []) {
        if (field === titleField) continue;
        const sourceName = state.schema.find((item) => item.name === field)?.source_field || field;
        const value = sourceField(source, sourceName);
        const text = value == null ? "" : String(Array.isArray(value) ? value.flat(Infinity).join(" ") : typeof value === "object" ? JSON.stringify(value) : value).trim();
        if (text && text !== titleText) { previewText = text; break; }
      }
    }
    const originalFields = sourceFields.map((field) => {
      const sourceName = state.schema.find((item) => item.name === field)?.source_field || field;
      const value = sourceField(source, sourceName);
      if (value == null) return "";
      return `<section><strong>${escapeHtml(field)}</strong><pre>${escapeHtml(typeof value === "string" ? value : JSON.stringify(value, null, 2))}</pre></section>`;
    }).filter(Boolean).join("");
    const judgment = hit.judgment || {};
    const pinned = Boolean(hit.pinned ?? judgment.pinned);
    const organicRank = kind === "pool" ? (hit.laneRanks?.bm25 ?? null) : hit.organic_rank ?? (pinned ? null : hit.rank);
    const rankLabel = english ? (kind === "pool"
      ? `BM25 ${hit.laneRanks?.bm25 ? `#${hit.laneRanks.bm25}` : "not found"} · Vector ${hit.laneRanks?.vector ? `#${hit.laneRanks.vector}` : "not found"}`
      : kind === "vector" ? `Vector rank ${Number(hit.rank || 0)}` : pinned && organicRank == null ? "Pinned · outside search rank" : Number(organicRank || hit.rank || 0) ? `Search rank ${Number(organicRank || hit.rank)}` : "Search rank —") : kind === "pool"
      ? `BM25 ${hit.laneRanks?.bm25 ? `#${hit.laneRanks.bm25}` : "미포함"} · 벡터 ${hit.laneRanks?.vector ? `#${hit.laneRanks.vector}` : "미포함"}`
      : kind === "vector" ? `벡터 순위 ${Number(hit.rank || 0)}` : pinned && organicRank == null ? "고정 배치 · 검색 순위 밖" : Number(organicRank || hit.rank || 0) ? `검색 순위 ${Number(organicRank || hit.rank)}` : "검색 순위 —";
    const rankBadge = pinned ? `<span class="pin-badge">${english ? "Pinned separately" : "따로 고정"}</span>` : "";
    const canJudge = ["candidate", "vector", "pool"].includes(kind) && queryId;
    const ratingOption = judgment.rating == null ? "null" : String(judgment.rating);
    const judgmentUi = english ? `<label>Relevance <select class="judge-rating" aria-label="${escapeHtml(id)} relevance judgment"><option value="null" ${ratingOption === "null" ? "selected" : ""}>Not rated</option><option value="0" ${ratingOption === "0" ? "selected" : ""}>0 · Not relevant</option><option value="1" ${ratingOption === "1" ? "selected" : ""}>1 · Slightly relevant</option><option value="2" ${ratingOption === "2" ? "selected" : ""}>2 · Relevant</option><option value="3" ${ratingOption === "3" ? "selected" : ""}>3 · Highly relevant</option></select></label><label class="pin-label"><input type="checkbox" class="judge-pin" ${pinned ? "checked" : ""}> Pin separately</label><button class="button button-small button-secondary save-judgment">Save judgment</button>` : `<label>관련도 <select class="judge-rating" aria-label="${escapeHtml(id)} 관련도 평가"><option value="null" ${ratingOption === "null" ? "selected" : ""}>미평가</option><option value="0" ${ratingOption === "0" ? "selected" : ""}>0 · 무관</option><option value="1" ${ratingOption === "1" ? "selected" : ""}>1 · 조금 관련</option><option value="2" ${ratingOption === "2" ? "selected" : ""}>2 · 관련 있음</option><option value="3" ${ratingOption === "3" ? "selected" : ""}>3 · 매우 관련</option></select></label><label class="pin-label"><input type="checkbox" class="judge-pin" ${pinned ? "checked" : ""}> 따로 고정</label><button class="button button-small button-secondary save-judgment">평가 저장</button>`;
    return `<article class="concept-hit"><div class="concept-hit-top"><span class="issue-key">${escapeHtml(id)}</span><span class="concept-rank">${escapeHtml(rankLabel)} ${rankBadge}</span></div>${hit._index ? `<small class="muted concept-hit-index">${escapeHtml(documentIndex)}</small>` : ""}<h4>${escapeHtml(title)}</h4><p class="concept-hit-snippet">${escapeHtml(previewText || (english ? "No source excerpt is available." : "원문 발췌가 없습니다."))}</p>${originalFields ? `<details class="original-fields"><summary>${english ? "Show selected source fields" : "선택한 원문 필드 보기"}</summary>${originalFields}</details>` : ""}<div class="concept-evidence">${evidenceHtml || (["candidate", "pool"].includes(kind) ? `<span class="muted">${english ? "No concept-match evidence is available." : "표시할 개념 일치 근거가 없습니다."}</span>` : "")}</div>${canJudge ? `<div class="judge-controls" data-mode="${escapeHtml(kind)}" data-index="${escapeHtml(documentIndex)}" data-id="${escapeHtml(id)}" data-query-id="${escapeHtml(queryId)}" data-organic-rank="${escapeHtml(organicRank ?? "")}" data-vector-rank="${escapeHtml(hit.laneRanks?.vector ?? (kind === "vector" ? hit.rank : "") ?? "")}" data-bm25-rank="${escapeHtml(hit.laneRanks?.bm25 ?? "")}">${judgmentUi}</div>` : ""}</article>`;
  }).join("") || (kind === "candidate"
    ? `<div class="compact-empty concept-candidate-empty"><p>${english ? "No candidates are shown for this concept search. Try a word you remember from the title or text." : "개념 적용 결과 목록에 표시할 후보가 없습니다. 제목이나 본문에서 기억나는 단어로 찾아볼 수 있습니다."}</p><button type="button" class="button button-secondary button-small locate-document-cta">${english ? "Find a document" : "원하는 문서 찾아보기"}</button></div>`
    : `<div class="compact-empty"><p>${english ? "No matching documents." : "일치하는 문서가 없습니다."}</p></div>`)}</section>`;
}

async function loadVectorCandidates() {
  const queryId = $("#concept-query-select").value;
  if (!vectorCandidateContextValid(queryId)) {
    clearVectorCandidatePool("개념과 질의를 저장하고, 같은 질의로 ‘결과 비교’를 먼저 실행하세요.");
    return;
  }
  const requestedConceptId = state.conceptId;
  const requestedSnapshot = state.savedConceptSnapshot;
  const requestGeneration = ++state.vectorCandidateGeneration;
  const button = $("#concept-vector-candidates");
  button.disabled = true;
  $("#concept-vector-results").replaceChildren();
  $("#concept-vector-status").innerHTML = '<span class="loading-inline"><i class="spinner"></i> 벡터 후보를 확인하고 있습니다.</span>';
  try {
    const result = await api("/api/concepts/vector-candidates", { connection: getConnection(), concept_id: state.conceptId, query_id: queryId, profile_id: state.sharedProfileId });
    if (requestGeneration !== state.vectorCandidateGeneration) return;
    if (state.conceptId !== requestedConceptId || state.savedConceptSnapshot !== requestedSnapshot || $("#concept-query-select").value !== queryId || !vectorCandidateContextValid(queryId)) {
      clearVectorCandidatePool("선택한 개념이나 질의가 바뀌어 이전 응답을 표시하지 않았습니다.");
      labelBm25Only("요청 중 개념 또는 질의가 바뀌어 벡터 응답을 표시하지 않았습니다. 아래 BM25 비교에는 벡터 후보가 포함되지 않습니다.");
      return;
    }
    const size = Number(collectConcept().settings.size || 10);
    if (!validVectorCandidateResponse(result, requestedConceptId, queryId, size)) {
      throw new Error("벡터 후보 응답 형식이 올바르지 않아 후보 목록을 표시하지 않았습니다.");
    }
    const pool = buildUnifiedCandidatePool(result.candidates, size);
    $("#concept-vector-status").textContent = `BM25 후보를 먼저, 그 밖의 벡터 후보를 이어서 표시합니다. 각 검색 안의 순위만 표시하며 서로 비교할 수 없습니다. 근사 벡터 검색은 관련 문서를 놓칠 수 있습니다. · 최대 ${pool.hits.length}/${size * 2}개`;
    $("#concept-vector-results").innerHTML = renderResultSet(pool, "후보 목록 · BM25 + 벡터", "pool", queryId);
  } catch (error) {
    if (requestGeneration !== state.vectorCandidateGeneration) return;
    $("#concept-vector-results").replaceChildren();
    if (!vectorCandidateContextValid(queryId)) {
      $("#concept-vector-status").textContent = "선택한 개념이나 질의가 바뀌어 이전 응답을 표시하지 않았습니다.";
      labelBm25Only("요청 중 개념 또는 질의가 바뀌어 벡터 응답을 표시하지 않았습니다. 아래 BM25 비교에는 벡터 후보가 포함되지 않습니다.");
      return;
    }
    const message = `벡터 후보 목록을 만들지 못했습니다: ${error.message}`;
    $("#concept-vector-status").textContent = message;
    if (state.preview) renderConceptPreview(state.preview, queryId, { candidateLabel: "개념 적용 · BM25 결과만", extraNotice: message });
    showToast(error.message, true);
  } finally {
    if (requestGeneration === state.vectorCandidateGeneration) button.disabled = !vectorCandidateContextValid();
  }
}

function validVectorCandidateResponse(result, conceptId, queryId, size) {
  return Boolean(result && result.concept_id === conceptId && result.query_id === queryId
    && Array.isArray(result.candidates) && result.candidates.length <= size
    && Number.isInteger(result.total) && result.total >= result.candidates.length
    && result.candidates.every((hit) => hit && typeof hit._index === "string" && hit._index
      && hit._id != null && String(hit._id) && Number.isInteger(hit.rank) && hit.rank > 0 && hit.rank <= size
      && hit.source && typeof hit.source === "object" && !Array.isArray(hit.source)
      && typeof hit._score === "number" && Number.isFinite(hit._score)));
}

function buildUnifiedCandidatePool(vectorCandidates, size) {
  const concept = collectConcept();
  const combined = new Map();
  const identityKey = (index, id) => JSON.stringify([String(index || concept.corpus.index), String(id)]);
  const organicRank = (hit) => hit.organic_rank ?? (hit.pinned ? null : hit.rank);
  for (const hit of state.preview?.candidate?.hits || []) {
    const rank = organicRank(hit);
    if (rank == null || !Number.isInteger(Number(rank)) || Number(rank) < 1 || !String(hit._id || "")) continue;
    const index = String(hit._index || concept.corpus.index);
    const id = String(hit._id);
    const entry = { ...hit, _index: index, _id: id, laneRanks: { bm25: Number(rank) }, organic_rank: Number(rank), judgment: hit.judgment || { rating: null, pinned: false, reason: "" } };
    combined.set(identityKey(index, id), entry);
  }
  for (const hit of vectorCandidates) {
    const index = String(hit._index);
    const id = String(hit._id);
    const key = identityKey(index, id);
    const existing = combined.get(key);
    if (existing) {
      existing.laneRanks.vector = Number(hit.rank);
      if (hit.judgment) existing.judgment = hit.judgment;
    } else {
      combined.set(key, { ...hit, _index: index, _id: id, laneRanks: { vector: Number(hit.rank) }, organic_rank: null, judgment: hit.judgment || { rating: null, pinned: false, reason: "" } });
    }
  }
  return { hits: [...combined.values()].slice(0, 2 * size), total: combined.size };
}

function clearVectorCandidatePool(message = "") {
  state.vectorCandidateGeneration += 1;
  state.modeComparisonGeneration += 1;
  state.modeComparisonGroupGeneration += 1;
  $("#concept-vector-results").replaceChildren();
  $("#concept-vector-status").textContent = message;
  $("#concept-vector-candidates").disabled = true;
  $("#concept-mode-comparison-results").replaceChildren();
  $("#concept-mode-comparison-status").textContent = message ? "선택이 바뀌어 이전 비교를 지웠습니다." : "";
  $("#concept-mode-comparison").disabled = true;
  $("#concept-mode-comparison-group-results").replaceChildren();
  $("#concept-mode-comparison-group-status").textContent = message ? "선택이 바뀌어 이전 묶음 비교를 지웠습니다." : "";
  $("#concept-mode-comparison-group").disabled = true;
  updateModeComparisonGroupAction();
}

function labelBm25Only(message) {
  const results = $("#concept-preview-results");
  const heading = results.querySelector(".concept-results-grid .concept-result-column:nth-child(2) h3");
  if (heading) heading.textContent = "개념 적용 · BM25 결과만";
  if (message) {
    results.querySelectorAll(".vector-pool-warning").forEach((notice) => notice.remove());
    const notice = document.createElement("p");
    notice.className = "notice notice-muted vector-pool-warning";
    notice.textContent = message;
    results.prepend(notice);
  }
}

function vectorCandidateContextValid(queryId = $("#concept-query-select").value) {
  return Boolean(state.connected && state.conceptId && queryId && state.preview?.conceptId === state.conceptId && state.preview?.queryId === queryId && state.savedConceptSnapshot === JSON.stringify(collectConcept()));
}

function renderModeComparison(result) {
  const names = { concept_bm25: "개념 적용 BM25", e5_vector: `벡터 · ${selectedEmbeddingProfile()?.model_name || "선택 프로필"}` };
  const metricNames = [["ndcg_at_k", "nDCG"], ["judged_coverage_at_k", "평가 문서 포함률"], ["recall_of_judged_relevant_at_k", "평가한 관련 문서 회수율"]];
  const cards = Object.entries(result.metrics || {}).map(([key, metric]) => {
    const status = metric.status === "no_judgments" ? "저장된 유효 평가가 없습니다." : metric.status === "no_positive_judgments" ? "관련 있다고 평가한 문서가 없어 순위 점수를 계산할 수 없습니다." : "평가가 있는 문서만으로 계산했습니다.";
    return `<section class="mode-metric-card"><h5>${escapeHtml(names[key] || key)} · 최대 ${Number(metric.k) || 0}개</h5><p class="mode-metric-status">${escapeHtml(status)}</p><dl>${metricNames.map(([field, label]) => `<div><dt>${escapeHtml(label)}</dt><dd>${metric[field] == null ? "—" : formatNumber(metric[field])}</dd></div>`).join("")}<div><dt>평가 문서</dt><dd>${Number(metric.judged_count) || 0} (관련 ${Number(metric.positive_judged_count) || 0})</dd></div><div><dt>결과에 포함된 평가 문서</dt><dd>${Number(metric.retrieved_judged_count) || 0}</dd></div><div><dt>결과 내 미평가</dt><dd>${Number(metric.unjudged_retrieved_count) || 0}</dd></div><div><dt>명시적 미평가</dt><dd>${Number(metric.explicit_unjudged_count) || 0}</dd></div><div><dt>오래된 평가 제외</dt><dd>${Number(metric.stale_judgment_count) || 0}</dd></div></dl></section>`;
  }).join("");
  const filters = Array.isArray(result.effective_filters) ? result.effective_filters.map((item) => `${item.field} = ${String(item.value)}`).join(" · ") : "없음";
  const splitLabel = result.split === "train" ? "학습" : result.split === "validation" ? "검증" : "미지정";
  const caveats = Array.isArray(result.limits) ? result.limits : [];
  return `<section class="mode-comparison-result"><p><strong>질의</strong> · ${escapeHtml(result.query || "")} <span>· ${splitLabel} · 상위 ${Number(result.settings_size) || 0}개 기준</span></p><p><strong>현재 적용 필터</strong> · ${escapeHtml(filters || "없음")}<br><strong>필터 지문</strong> · <code>${escapeHtml(String(result.filters_fingerprint || "기록 없음"))}</code></p><div class="mode-metric-grid">${cards}</div><p class="mode-vector-note">벡터 후보 ${Number(result.vector?.candidate_count) || 0}/${Number(result.vector?.candidate_limit) || 0}개 · 근사 ${result.vector?.approximate === true ? "예" : "아니요"} · 전체 검색 아님</p><ul>${caveats.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
}

async function compareSavedQueryModes() {
  const queryId = $("#concept-query-select").value;
  if (!vectorCandidateContextValid(queryId)) return;
  const requestedConceptId = state.conceptId;
  const requestedSnapshot = state.savedConceptSnapshot;
  const generation = ++state.modeComparisonGeneration;
  const button = $("#concept-mode-comparison");
  button.disabled = true;
  $("#concept-mode-comparison-results").replaceChildren();
  $("#concept-mode-comparison-status").textContent = "같은 저장 질의와 평가로 두 검색을 실행하고 있습니다.";
  try {
    const result = await api("/api/concepts/mode-comparison", { connection: getConnection(), concept_id: requestedConceptId, query_id: queryId, profile_id: state.sharedProfileId });
    if (generation !== state.modeComparisonGeneration) return;
    if (state.conceptId !== requestedConceptId || state.savedConceptSnapshot !== requestedSnapshot || $("#concept-query-select").value !== queryId || !vectorCandidateContextValid(queryId)) {
      $("#concept-mode-comparison-status").textContent = "요청 중 개념 또는 질의가 바뀌어 이전 비교 결과를 표시하지 않았습니다.";
      return;
    }
    if (result.concept_id !== requestedConceptId || result.query_id !== queryId || !result.metrics?.concept_bm25 || !result.metrics?.e5_vector) throw new Error("비교 응답 형식이 올바르지 않습니다.");
    $("#concept-mode-comparison-results").innerHTML = renderModeComparison(result);
    $("#concept-mode-comparison-status").textContent = "비교 완료 · 검색·평가·실험 기록은 저장하지 않았습니다.";
  } catch (error) {
    if (generation === state.modeComparisonGeneration) {
      $("#concept-mode-comparison-results").replaceChildren();
      $("#concept-mode-comparison-status").textContent = `비교를 완료하지 못했습니다. 두 검색의 완전한 응답을 받지 못해 부분 점수는 표시하지 않았습니다: ${error.message}`;
    }
  } finally {
    if (generation === state.modeComparisonGeneration) updateModeComparisonAction();
  }
}

function renderModeComparisonGroup(result) {
  const names = { concept_bm25: "개념 적용 BM25", e5_vector: `벡터 · ${selectedEmbeddingProfile()?.model_name || "선택 프로필"}` };
  const metrics = [["ndcg_at_k", "nDCG"], ["judged_coverage_at_k", "평가 문서 포함률"], ["recall_of_judged_relevant_at_k", "평가한 관련 문서 회수율"]];
  const number = (value) => value == null ? "—" : formatNumber(value);
  const queryRows = (result.queries || []).map((query) => {
    const queryStatus = query.status === "complete" ? "완료" : String(query.status ?? "알 수 없음");
    const cards = Object.entries(query.metrics || {}).map(([mode, values]) => {
      const status = values.status === "no_judgments" ? "유효한 평가 없음" : values.status === "no_positive_judgments" ? "관련 평가 없음" : "완료";
      return `<section class="mode-metric-card"><h5>${escapeHtml(names[mode] || mode)} · ${status}</h5><dl>${metrics.map(([field, label]) => `<div><dt>${escapeHtml(label)}</dt><dd>${number(values[field])}</dd></div>`).join("")}<div><dt>평가 문서</dt><dd>${Number(values.judged_count) || 0} (관련 ${Number(values.positive_judged_count) || 0})</dd></div><div><dt>결과에 포함</dt><dd>${Number(values.retrieved_judged_count) || 0}</dd></div><div><dt>명시적 미평가</dt><dd>${Number(values.explicit_unjudged_count) || 0}</dd></div><div><dt>오래된 평가 제외</dt><dd>${Number(values.stale_judgment_count) || 0}</dd></div></dl></section>`;
    }).join("");
    return `<article class="mode-group-query"><h5>${escapeHtml(query.query_id)} · ${escapeHtml(query.query)}</h5><p>상태: ${escapeHtml(queryStatus)} · ${query.split === "train" ? "설정 조정에 사용" : "별도 확인용"} · 상위 ${Number(query.metrics?.concept_bm25?.k) || 0}개</p><div class="mode-metric-grid">${cards}</div></article>`;
  }).join("");
  const aggregate = result.aggregate ? `<section class="mode-group-aggregate"><h5>질의별 같은 비중 평균</h5><div class="mode-metric-grid">${metrics.map(([field, label]) => `<section class="mode-metric-card"><h5>${escapeHtml(label)}</h5><dl>${Object.entries(result.aggregate[field] || {}).map(([mode, value]) => `<div><dt>${escapeHtml(names[mode] || mode)} · ${value.query_count}/${Number(result.selected_count) || 0}개 질의</dt><dd>${number(value.mean)}</dd></div>`).join("")}</dl></section>`).join("")}</div></section>` : `<p class="notice notice-muted">하나 이상의 질의 쌍이 실패해 묶음 평균을 표시하지 않습니다.</p>`;
  const failures = (result.failures || []).map((failure) => `<li><strong>${escapeHtml(failure.query_id)} · ${escapeHtml(failure.query)}</strong>: ${escapeHtml(failure.error)}</li>`).join("");
  const limits = (result.limits || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `<section class="mode-group-result"><h4>정보 요구: ${escapeHtml(result.information_need)} · ${result.split === "train" ? "설정 조정에 사용" : "별도 확인용"}</h4><p>선택 ${Number(result.selected_count) || 0}개 · 완료 ${Number(result.completed_count) || 0}개 · 실패 ${Number(result.failed_count) || 0}개 · 결과 크기 ${Number(result.settings_size) || 0}</p><p>현재 적용 필터: ${escapeHtml((result.effective_filters || []).map((item) => `${item.field} = ${String(item.value)}`).join(" · ") || "없음")}</p>${aggregate}${queryRows ? `<h5>질의별 결과</h5>${queryRows}` : ""}${failures ? `<h5>실패한 질의</h5><ul>${failures}</ul>` : ""}<h5>해석할 때 알아둘 점</h5><ul>${limits}</ul></section>`;
}

async function compareSavedQueryGroupModes() {
  const queryId = $("#concept-query-select").value;
  if (!queryId || $("#concept-mode-comparison-group").disabled) return;
  const requestedConceptId = state.conceptId;
  const requestedSnapshot = state.savedConceptSnapshot;
  const generation = ++state.modeComparisonGroupGeneration;
  const button = $("#concept-mode-comparison-group");
  button.disabled = true;
  state.modeComparisonGroupRunning = true;
  updateModeComparisonGroupAction();
  $("#concept-mode-comparison-group-results").replaceChildren();
  $("#concept-mode-comparison-group-status").textContent = `저장된 묶음의 질의를 하나씩 비교하고 있습니다. 질의마다 BM25와 ${selectedEmbeddingProfile()?.model_name || "선택한 벡터 프로필"} 검색을 실행하므로 잠시 걸릴 수 있습니다.`;
  try {
    const result = await api("/api/concepts/mode-comparison-group", { connection: getConnection(), concept_id: requestedConceptId, query_id: queryId, profile_id: state.sharedProfileId });
    if (generation !== state.modeComparisonGroupGeneration) return;
    if (state.conceptId !== requestedConceptId || state.savedConceptSnapshot !== requestedSnapshot || $("#concept-query-select").value !== queryId || requestedSnapshot !== JSON.stringify(collectConcept())) {
      $("#concept-mode-comparison-group-status").textContent = "요청 중 개념 또는 질의가 바뀌어 이전 묶음 비교 결과를 표시하지 않았습니다.";
      return;
    }
    if (result.concept_id !== requestedConceptId || result.anchor_query_id !== queryId || !Array.isArray(result.queries) || !Array.isArray(result.failures)) throw new Error("묶음 비교 응답 형식이 올바르지 않습니다.");
    $("#concept-mode-comparison-group-results").innerHTML = renderModeComparisonGroup(result);
    $("#concept-mode-comparison-group-status").textContent = `묶음 비교 ${result.status === "complete" ? "완료" : "일부 실패"} · 검색·평가·실험 기록은 저장하지 않았습니다.`;
  } catch (error) {
    if (generation === state.modeComparisonGroupGeneration) {
      $("#concept-mode-comparison-group-results").replaceChildren();
      $("#concept-mode-comparison-group-status").textContent = `묶음 비교를 완료하지 못했습니다: ${error.message}`;
    }
  } finally {
    state.modeComparisonGroupRunning = false;
    updateModeComparisonGroupAction();
  }
}

function renderConceptPreview(result, queryId, options = {}) {
  const english = state.locale === "en";
  const comparison = result.comparison || [];
  const comparisonHtml = comparison.length ? `<details class="rank-comparison"><summary>${english ? `Per-document rank changes (${comparison.length})` : `문서별 순위 변화 (${comparison.length})`}</summary><div class="rank-comparison-list">${comparison.map((row) => `<div><code>${escapeHtml([row.document_index, row.document_id || row._id].filter(Boolean).join(" / ") || (english ? "Document" : "문서"))}</code><span>${english ? "Baseline" : "기본"} ${escapeHtml(row.baseline_rank ?? "—")} → ${english ? "Concept" : "개념 적용"} ${escapeHtml(row.candidate_rank ?? "—")}</span></div>`).join("")}</div></details>` : "";
  const warnings = [...localizedConceptWarnings(result), ...(options.extraNotice ? [options.extraNotice] : [])].map((warning) => `<p class="notice notice-muted">${escapeHtml(warning)}</p>`).join("");
  const markup = `${warnings}<div class="concept-results-grid">${renderResultSet(result.baseline, english ? "Baseline search" : "기본 검색", "baseline", queryId)}${renderResultSet(result.candidate, options.candidateLabel || (english ? "Concept search · BM25" : "개념 적용 · BM25"), "candidate", queryId)}</div>${comparisonHtml}`;
  const target = options.target || $("#concept-preview-results");
  target.innerHTML = markup;
  updateModeComparisonAction();
  return markup;
}

function renderInformationNeedVisibilitySummary(results, failures = [], cardIdsByQueryId = new Map()) {
  const summary = document.createElement("section");
  summary.id = "information-need-visibility-summary";
  summary.className = "information-need-visibility-summary card";
  const successfulCount = results.length;
  const heading = document.createElement("h3");
  heading.textContent = "질의 사이 문서가 보인 결과";
  summary.append(heading);
  const explanation = document.createElement("p");
  explanation.className = "information-need-visibility-explanation";
  explanation.textContent = `아래 내용은 성공한 ${successfulCount}개 질의의 표시 결과 창에서만 확인한 문서 노출입니다. 문서의 관련성이나 결과에 없는 문서의 부재를 증명하지 않으며, 순위를 합치거나 품질을 평가하지 않습니다.${failures.length ? ` 실패한 ${failures.length}개 질의는 관찰되지 않았고 집계에 포함하지 않았습니다.` : ""}`;
  summary.append(explanation);

  const lanes = [
    { key: "baseline", title: "기본 검색" },
    { key: "candidate", title: "개념 적용 검색" },
  ];
  const fallbackIndex = collectConcept().corpus.index || "";
  for (const lane of lanes) {
    const section = document.createElement("section");
    section.className = "information-need-visibility-lane";
    section.dataset.lane = lane.key;
    const laneHeading = document.createElement("h4");
    laneHeading.textContent = lane.title;
    section.append(laneHeading);

    const documents = new Map();
    const seenByQuery = new Map();
    for (const item of results) {
      const hits = item.preview?.[lane.key]?.hits || [];
      const queryId = String(item.query_id ?? "");
      if (!seenByQuery.has(queryId)) seenByQuery.set(queryId, new Set());
      const seenThisQuery = seenByQuery.get(queryId);
      for (const hit of hits) {
        const idValue = hit?._id;
        if (idValue == null || idValue === "") continue;
        const documentId = String(idValue);
        const documentIndex = String(hit?._index || fallbackIndex);
        if (!documentIndex) continue;
        const identity = JSON.stringify([documentIndex, documentId]);
        if (seenThisQuery.has(identity)) continue;

        let rank;
        if (lane.key === "baseline") {
          rank = hit.rank;
        } else {
          const pinned = Boolean(hit.pinned ?? hit.judgment?.pinned);
          if (Object.prototype.hasOwnProperty.call(hit, "organic_rank")) {
            if (hit.organic_rank == null) continue;
            rank = hit.organic_rank;
          } else {
            if (pinned) continue;
            rank = hit.rank;
          }
        }
        const numericRank = Number(rank);
        if (!Number.isInteger(numericRank) || numericRank <= 0) continue;
        seenThisQuery.add(identity);
        if (!documents.has(identity)) documents.set(identity, { index: documentIndex, id: documentId, occurrences: [] });
        documents.get(identity).occurrences.push({ queryId, query: String(item.query ?? ""), rank: String(numericRank) });
      }
    }

    const repeated = [...documents.values()].filter((document) => new Set(document.occurrences.map((occurrence) => occurrence.queryId)).size >= 2);
    if (!repeated.length) {
      const empty = document.createElement("p");
      empty.className = "information-need-visibility-empty";
      empty.textContent = successfulCount === 0
        ? "성공한 질의 결과가 없어 요약할 자료가 없습니다. 관련 문서가 있는지 판단할 수 없습니다."
        : "이 성공한 질의들의 표시 결과에서는 여러 질의에 반복된 문서가 없습니다. 관련 문서가 없다는 뜻은 아닙니다.";
      section.append(empty);
    } else {
      const list = document.createElement("div");
      list.className = "information-need-visibility-documents";
      for (const entry of repeated) {
        const row = document.createElement("article");
        row.className = "information-need-visibility-document";
        row.dataset.index = entry.index;
        row.dataset.id = entry.id;
        const identityLabel = document.createElement("strong");
        identityLabel.textContent = `${entry.index} / ${entry.id}`;
        row.append(identityLabel);
        const observedQueryCount = document.createElement("span");
        observedQueryCount.className = "information-need-visibility-query-count";
        observedQueryCount.textContent = `${new Set(entry.occurrences.map((occurrence) => occurrence.queryId)).size}개 질의에서 관찰`;
        row.append(observedQueryCount);
        const occurrences = document.createElement("ul");
        for (const occurrence of entry.occurrences) {
          const item = document.createElement("li");
          item.className = "information-need-visibility-occurrence";
          item.dataset.queryId = occurrence.queryId;
          item.dataset.rank = occurrence.rank;
          item.append(document.createTextNode(`${occurrence.query} · ${occurrence.queryId} · ${lane.key === "baseline" ? "기본 순위" : "검색 순위"} #${occurrence.rank} · `));
          const cardId = cardIdsByQueryId.get(occurrence.queryId);
          if (cardId) {
            const link = document.createElement("a");
            link.href = `#${cardId}`;
            link.className = "information-need-visibility-link";
            link.dataset.queryId = occurrence.queryId;
            link.setAttribute("aria-label", `질의 ${occurrence.queryId}의 전체 결과와 평가로 이동`);
            link.textContent = "전체 결과와 평가 보기";
            link.addEventListener("click", (event) => {
              const target = document.getElementById(cardId);
              if (!target) return;
              event.preventDefault();
              target.focus({ preventScroll: true });
              target.scrollIntoView({ behavior: "smooth", block: "start" });
            });
            item.append(link);
          }
          occurrences.append(item);
        }
        row.append(occurrences);
        list.append(row);
      }
      section.append(list);
    }
    summary.append(section);
  }
  return summary;
}

async function runInformationNeedPreview() {
  updateInformationNeedPreviewAction();
  if ($("#information-need-preview").disabled) return;
  const generation = ++state.informationNeedPreviewGeneration;
  const context = { conceptId: state.conceptId, conceptSelection: $("#saved-concepts").value, queryId: $("#concept-query-select").value, snapshot: JSON.stringify(collectConcept()) };
  const current = () => generation === state.informationNeedPreviewGeneration && state.connected && state.conceptId === context.conceptId && $("#saved-concepts").value === context.conceptSelection && $("#concept-query-select").value === context.queryId && JSON.stringify(collectConcept()) === context.snapshot && state.savedConceptSnapshot === context.snapshot;
  const status = $("#concept-preview-status");
  const output = $("#concept-preview-results");
  $("#information-need-preview").disabled = true;
  status.textContent = "정보 요구 묶음의 저장 질의를 각각 미리 보는 중입니다. 각 성공한 질의는 별도 미리보기 기록으로 저장됩니다.";
  output.replaceChildren();
  state.preview = null;
  $("#concept-vector-candidates").disabled = true;
  $("#concept-vector-results").replaceChildren();
  try {
    const result = await api("/api/concepts/information-need-preview", { connection: getConnection(), concept_id: context.conceptId, query_id: context.queryId });
    if (!current()) return;
    const heading = document.createElement("p");
    heading.className = "notice notice-muted";
    heading.textContent = `정보 요구: ${result.information_need} · ${result.split} · 저장 질의 ${result.count}개. 각 질의는 독립적으로 검색되며 성공한 질의마다 별도 미리보기 기록을 저장합니다.`;
    output.append(heading);
    const successfulResults = result.results || [];
    const failures = result.failures || [];
    const cardIdsByQueryId = new Map();
    successfulResults.forEach((item, index) => {
      const queryId = String(item.query_id ?? "");
      if (!cardIdsByQueryId.has(queryId)) cardIdsByQueryId.set(queryId, `information-need-query-card-${index + 1}`);
    });
    output.append(renderInformationNeedVisibilitySummary(successfulResults, failures, cardIdsByQueryId));
    for (const [index, item] of successfulResults.entries()) {
      if (!current()) return;
      const card = document.createElement("section");
      card.className = "information-need-query-card card";
      card.id = `information-need-query-card-${index + 1}`;
      card.dataset.queryId = String(item.query_id ?? "");
      card.tabIndex = -1;
      const title = document.createElement("h3");
      title.textContent = `${item.query} · ${item.query_id}`;
      const body = document.createElement("div");
      card.append(title, body);
      output.append(card);
      renderConceptPreview(item.preview, item.query_id, { target: body });
    }
    if (failures.length) {
      const failureSection = document.createElement("section");
      failureSection.className = "notice notice-error";
      failureSection.innerHTML = `<strong>일부 질의 미리보기에 실패했습니다.</strong>${failures.map((item) => `<p>${escapeHtml(item.query)} (${escapeHtml(item.query_id)}): ${escapeHtml(item.error)}</p>`).join("")}`;
      output.append(failureSection);
      status.textContent = `부분 완료 · ${successfulResults.length}개 성공, ${failures.length}개 실패. 실패한 질의는 0건 결과로 표시하지 않았습니다.`;
    } else status.textContent = `완료 · ${successfulResults.length}개 질의를 각각 비교했습니다.`;
    await loadConceptRuns();
  } catch (error) {
    if (current()) { status.textContent = error.message; showToast(error.message, true); }
  } finally {
    if (current()) updateInformationNeedPreviewAction();
  }
}

async function saveJudgment(button) {
  const controls = button.closest(".judge-controls");
  if (!state.conceptId) return showToast("문서 평가를 저장하기 전에 개념을 먼저 저장하세요.", true);
  const ratingValue = controls.querySelector(".judge-rating").value;
  const payload = { concept_id: state.conceptId, query_id: controls.dataset.queryId, document_index: controls.dataset.index, document_id: controls.dataset.id, rating: ratingValue === "null" ? null : Number(ratingValue), pinned: controls.querySelector(".judge-pin").checked };
  button.disabled = true;
  try {
    await api("/api/concepts/judge", payload);
    if (state.preview?.candidate?.hits) {
      const savedHit = state.preview.candidate.hits.find((hit) => String(hit._id) === payload.document_id && String(hit._index || selectedIndexFallback()) === payload.document_index);
      if (savedHit) { savedHit.judgment = { rating: payload.rating, pinned: payload.pinned, reason: null }; savedHit.pinned = payload.pinned; }
    }
    const card = controls.closest(".concept-hit");
    const rank = card.querySelector(".concept-rank");
    if (controls.dataset.mode === "pool") {
      const bm25 = controls.dataset.bm25Rank ? `#${controls.dataset.bm25Rank}` : "미포함";
      const vector = controls.dataset.vectorRank ? `#${controls.dataset.vectorRank}` : "미포함";
      rank.innerHTML = `BM25 ${bm25} · 벡터 ${vector}${payload.pinned ? ' <span class="pin-badge">따로 고정</span>' : ""}`;
    }
    else if (controls.dataset.mode === "vector") rank.textContent = `벡터 순위 ${controls.dataset.vectorRank || "—"}`;
    else if (payload.pinned && controls.dataset.organicRank) rank.innerHTML = `검색 순위 ${escapeHtml(controls.dataset.organicRank)} <span class="pin-badge">따로 고정</span>`;
    else if (payload.pinned) rank.innerHTML = `고정 배치 · 검색 순위 밖 <span class="pin-badge">따로 고정</span>`;
    else rank.textContent = controls.dataset.organicRank ? `검색 순위 ${controls.dataset.organicRank}` : "고정 해제 · 다시 비교하면 순위를 확인할 수 있습니다.";
    showToast(state.locale === "en" ? (payload.pinned ? "Saved pin and relevance judgment." : "Relevance judgment saved. Compare search modes using the same query when ready.") : (payload.pinned ? "고정 위치를 저장했습니다. 관련도 평가는 품질 점수에 반영되고 고정 위치는 검색 순위로 계산하지 않습니다." : "문서 평가를 저장했습니다."));
    updateTuneReadiness();
  }
  catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
}

function selectedIndexFallback() { return $("#index-name").value.trim(); }

function updateTuneReadiness() {
  const detail = $("#tune-readiness-detail");
  const status = $("#tune-readiness");
  const requestId = ++state.tuneReadinessRequestId;
  clearTimeout(state.tuneReadinessTimer);
  if (!state.conceptId) {
    status.textContent = "개념을 저장하면 평가 준비 상태를 확인할 수 있습니다.";
    detail.textContent = "저장된 개념이 없습니다.";
    $("#concept-tune").disabled = !state.connected || !state.conceptId;
    return;
  }
  const concept = collectConcept();
  const signature = JSON.stringify(concept);
  status.textContent = "저장된 평가를 확인하고 있습니다.";
  detail.textContent = "학습용·별도 확인용 평가 수와 해석 안내를 불러오는 중입니다.";
  state.tuneReadinessTimer = setTimeout(async () => {
    try {
      const result = await api("/api/concepts/tune/readiness", { concept });
      if (requestId !== state.tuneReadinessRequestId || signature !== JSON.stringify(collectConcept())) return;
      const counts = result?.counts || {};
      const count = (key) => Number.isInteger(counts[key]) && counts[key] >= 0 ? counts[key] : null;
      const trainingQueries = count("training_queries");
      const trainingGraded = count("training_graded");
      const trainingPositive = count("training_positive");
      const trainingGradedQueries = count("training_graded_queries");
      const trainingPositiveQueries = count("training_positive_queries");
      const validationQueries = count("validation_queries");
      const validationGraded = count("validation_graded");
      const validationPositive = count("validation_positive");
      const validationGradedQueries = count("validation_graded_queries");
      const validationPositiveQueries = count("validation_positive_queries");
      const trainingGroups = count("training_information_need_groups");
      const trainingGradedGroups = count("training_graded_information_need_groups");
      const trainingPositiveGroups = count("training_positive_information_need_groups");
      const validationGroups = count("validation_information_need_groups");
      const validationGradedGroups = count("validation_graded_information_need_groups");
      const validationPositiveGroups = count("validation_positive_information_need_groups");
      const stale = count("stale");
      if (typeof result?.eligible !== "boolean"
          || !["train_positive_available", "train_positive_required"].includes(result.reason_code)
          || result.scope !== "label_readiness_only"
          || [trainingQueries, trainingGraded, trainingPositive, trainingGradedQueries, trainingPositiveQueries,
            validationQueries, validationGraded, validationPositive, validationGradedQueries, validationPositiveQueries,
            trainingGroups, trainingGradedGroups, trainingPositiveGroups, validationGroups, validationGradedGroups,
            validationPositiveGroups, stale]
            .some((value) => value == null)
          || result.eligible !== (result.reason_code === "train_positive_available")
          || result.eligible !== (trainingPositive > 0)
          || result.eligible !== (trainingPositiveQueries > 0)
          || trainingPositive > trainingGraded || trainingGradedQueries > trainingQueries || trainingGradedQueries > trainingGraded
          || trainingPositiveQueries > trainingGradedQueries || trainingPositiveQueries > trainingPositive
          || trainingGradedGroups > trainingGroups || trainingPositiveGroups > trainingGradedGroups
          || validationPositive > validationGraded || validationGradedQueries > validationQueries || validationGradedQueries > validationGraded
          || validationPositiveQueries > validationGradedQueries || validationPositiveQueries > validationPositive
          || validationGradedGroups > validationGroups || validationPositiveGroups > validationGradedGroups) {
        throw new Error("저장된 평가 준비 상태 응답이 올바르지 않습니다.");
      }
      status.textContent = result.eligible
        ? "설정 비교를 시작할 수 있습니다."
        : "학습용 문서 평가가 필요합니다.";
      const nextStep = result.eligible
        ? "반복 횟수를 고른 뒤 설정 비교를 실행하세요."
        : "저장된 학습용 질의의 문서를 ‘조금 관련’ 이상으로 평가하세요. 별도 확인용 평가만으로는 준비되지 않습니다.";
      detail.innerHTML = `<p class="readiness-next-step">${nextStep}</p><details class="readiness-details"><summary>평가 범위와 해석 보기</summary><div class="readiness-details-body"><p><strong>학습용</strong> 문서: 평가 ${trainingGraded}개·양수 ${trainingPositive}개; 평가 질의 ${trainingGradedQueries}/${trainingQueries}개·양수 평가 ${trainingPositiveQueries}/${trainingQueries}개; 정보 요구 묶음 ${trainingGradedGroups}/${trainingGroups}개에 평가·${trainingPositiveGroups}개에 양수 평가.</p><p><strong>별도 확인용</strong> 문서: 평가 ${validationGraded}개·양수 ${validationPositive}개; 평가 질의 ${validationGradedQueries}/${validationQueries}개·양수 평가 ${validationPositiveQueries}/${validationQueries}개; 정보 요구 묶음 ${validationGradedGroups}/${validationGroups}개에 평가·${validationPositiveGroups}개에 양수 평가.</p><p>오래된 평가 제외 ${stale}개. 반복된 정보 요구 묶음 이름은 여러 표현을 묶으며, 빈 이름은 질의 하나씩 따로 셉니다. 현재 질의 목록에서 평가가 연결된 범위이며 실제 사용 대표성이나 검색 품질을 예측하지 않습니다. 최소 개수 기준은 없고 라벨 준비 상태만 보여줍니다. 준비 조건은 저장된 학습용 양수 평가의 존재뿐이며, 별도 확인용 평가는 설정 비교를 가능하게 하지 않습니다.</p></div></details>`;
    } catch {
      if (requestId !== state.tuneReadinessRequestId || signature !== JSON.stringify(collectConcept())) return;
      status.textContent = "평가 준비 상태를 확인하지 못했습니다.";
      detail.textContent = "설정 비교를 실행하면 서버가 준비 상태를 다시 확인합니다.";
    }
  }, 250);
  $("#concept-tune").disabled = !state.connected || !state.conceptId;
}

const AI_AUTH_LABELS = { ready: "로그인 상태 확인됨", sign_in_required: "로그인이 필요합니다", sdk_missing: "SDK 설치가 필요합니다", cli_missing: "CLI 설치가 필요합니다", unavailable: "현재 사용할 수 없습니다", unknown: "상태 확인 불가" };
const AI_TOOL_LABELS = { get_schema: "필드 확인", sample_documents: "예시 문서 확인", preview_search: "검색 결과 확인", get_document: "문서 읽기", diagnose_document: "문서 제외 이유 확인" };
const DIAGNOSIS_LABELS = { baseline_match: "기본 검색에서는 찾을 수 있습니다.", expansion_match: "표현을 확장한 검색에서는 찾을 수 있습니다.", filtered_out: "선택한 조건이 문서를 제외했을 수 있습니다.", excluded: "제외 표현에 걸렸을 수 있습니다.", matches_below_display_window: "검색 후보에는 있지만 표시 범위 아래에 있습니다.", matches_outside_candidate_pool: "후보 범위 밖에 있습니다.", no_selected_field_value: "선택한 본문 필드에 이 문서의 값이 없습니다.", no_selected_field_match: "선택한 본문 필드에서는 일치 항목을 찾지 못했습니다.", inconclusive: "현재 권한이나 정보만으로 원인을 구분하지 못했습니다.", document_not_found: "선택한 인덱스에서 문서를 찾지 못했습니다." };

async function loadAiStatus() {
  try {
    const result = await api("/api/ai/status", {});
    state.aiProviders = result.providers || [];
    renderAiProviderStatus();
  } catch (error) {
    $("#ai-provider-status").textContent = "AI 상태를 확인하지 못했습니다.";
    $("#ai-provider-status").className = "provider-status unavailable";
    $("#ai-setup-hint").textContent = `AI 연결 상태 조회 실패: ${error.message} 직접 검색과 평가는 계속 사용할 수 있습니다.`;
  }
}

function renderAiProviderStatus() {
  const setupText = (item) => ({
    sdk_missing: "이 서버에 선택한 AI SDK가 설치되지 않았습니다. 운영자가 선택 기능을 설치하면 사용할 수 있습니다.",
    cli_missing: "지원되는 로그인 프로그램을 찾지 못했습니다. 해당 구독에 로그인한 뒤 서버를 다시 시작하세요.",
    sign_in_required: "이 서버에서 선택한 구독으로 로그인한 뒤 상태를 새로고침하세요.",
    native_tools_not_isolated: "안전한 요청 범위를 확인할 수 없어 이 제공자를 사용할 수 없습니다. AI 없이 직접 검색과 평가를 계속할 수 있습니다.",
    unavailable: "현재 이 제공자를 사용할 수 없습니다. 상태를 새로고침하거나 직접 검색과 평가를 계속하세요.",
  }[item?.error_code || item?.auth_state] || "현재 이 제공자를 사용할 수 없습니다. AI 없이 직접 검색과 평가를 계속할 수 있습니다.");
  const provider = state.aiProviders.find((item) => item.id === $("#ai-provider").value);
  if (!provider) {
    $("#ai-provider-status").textContent = "이 제공자를 사용할 수 없습니다.";
    $("#ai-provider-status").className = "provider-status unavailable";
    $("#ai-setup-hint").textContent = "AI 연결 상태를 확인할 수 없습니다. AI 없이도 직접 검색과 평가를 계속할 수 있습니다.";
    $("#ai-send").disabled = true;
    return;
  }
  const ready = Boolean(provider.available);
  const node = $("#ai-provider-status");
  node.textContent = ready
    ? "SDK·로그인 상태 확인됨"
    : `사용 불가 · ${AI_AUTH_LABELS[provider.auth_state] || provider.auth_state || "상태 미상"}`;
  node.className = `provider-status ${ready ? "ready" : "unavailable"}`;
  const modelWrap = $("#ai-model-wrap"); const modelSelect = $("#ai-model");
  const models = provider.models || [];
  modelWrap.classList.toggle("hidden", !models.length);
  modelSelect.classList.toggle("hidden", !models.length);
  modelSelect.innerHTML = `<option value="">기본 모델 사용${provider.default_model ? ` · ${escapeHtml(provider.default_model)}` : ""}</option>${models.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("")}`;
  $("#ai-setup-hint").textContent = ready
    ? `이 상태는 호스트에서 ${$("#ai-provider").selectedOptions[0].textContent} SDK와 로그인 상태만 확인합니다. 실제 모델 응답은 제공자 접근 권한이나 사용 한도 때문에 실패할 수 있으며, 응답 여부는 요청 결과에서만 확인할 수 있습니다. 이 대화는 이 앱의 별도 세션이며 기존 Codex·Copilot 대화를 불러오지 않습니다.`
    : setupText(provider);
  $("#ai-send").disabled = !state.connected || !ready || Boolean(state.aiJobId);
  $("#ai-retry").disabled = !state.aiLastMessage || Boolean(state.aiJobId) || !ready;
  $("#ai-reset").disabled = !state.aiSession;
}

async function currentAiScope() {
  const concept = collectConcept();
  const connection = JSON.stringify(getConnection());
  let connectionFingerprint = "";
  if (window.crypto?.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(connection));
    connectionFingerprint = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  } else {
    connectionFingerprint = `${getConnection().url}|${getConnection().auth.type}|${getConnection().auth.username || ""}|${state.aiConnectionEpoch || 0}`;
  }
  return {
    provider: $("#ai-provider").value,
    model: $("#ai-model").classList.contains("hidden") ? "" : $("#ai-model").value,
    index: concept.corpus.index,
    text_fields: concept.corpus.text_fields,
    filter_fields: concept.corpus.filter_fields,
    concept_id: state.conceptId || "",
    concept_signature: JSON.stringify(concept),
    connection_fingerprint: connectionFingerprint,
  };
}

async function resetAiSession(silent = true) {
  clearTimeout(state.aiJobTimer);
  state.aiJobTimer = null;
  if (state.aiJobId) {
    try { await api("/api/ai/jobs/cancel", { job_id: state.aiJobId }); } catch { /* Drop the old job from this UI scope. */ }
  }
  if (state.aiSession?.session_id) {
    try { await api("/api/ai/sessions/reset", { session_id: state.aiSession.session_id }); } catch { /* Reset locally even if backend is unavailable. */ }
  }
  state.aiSession = null; state.aiJobId = null; state.aiLastDraft = null;
  state.aiLastMessage = "";
  state.aiLastContext = null;
  $("#ai-chat-history").innerHTML = '<p class="muted">새 앱 대화를 시작합니다. 예: “이 문서가 결과에서 빠진 이유를 살펴봐 주세요.”</p>';
  $("#ai-draft-review").replaceChildren();
  $("#ai-job-status").textContent = "";
  $("#ai-cancel").disabled = true;
  renderAiContextReadouts();
  renderAiProviderStatus();
  if (!silent) showToast("AI 대화 기록을 지웠습니다.");
}

async function resetAiIfScopeChanged() {
  if (!state.aiSession) return;
  try {
    const next = JSON.stringify(await currentAiScope());
    if (next !== state.aiSession.scopeSignature) await resetAiSession(true);
  } catch { await resetAiSession(true); }
}

async function ensureAiSession() {
  const scope = await currentAiScope();
  const signature = JSON.stringify(scope);
  if (state.aiSession && state.aiSession.scopeSignature !== signature) await resetAiSession(true);
  if (state.aiSession) return state.aiSession;
  const provider = state.aiProviders.find((item) => item.id === scope.provider);
  if (!provider?.available) throw new Error(provider?.setup_hint || "선택한 AI 제공자를 사용할 수 없습니다.");
  if (!scope.index || !scope.text_fields.length) throw new Error("AI에게 보여줄 인덱스와 본문 필드를 먼저 확인하세요.");
  const created = await api("/api/ai/sessions/create", {
    provider: scope.provider,
    ...(scope.model ? { model: scope.model } : {}),
    connection: getConnection(),
    corpus: { index: scope.index, text_fields: scope.text_fields, filter_fields: scope.filter_fields },
    ...(state.conceptId ? { concept_id: state.conceptId } : {}),
  });
  state.aiSession = { ...created, scopeSignature: signature };
  await loadAiHistory();
  $("#ai-reset").disabled = false;
  return state.aiSession;
}

async function loadAiHistory() {
  if (!state.aiSession?.session_id) return;
  try {
    const result = await api("/api/ai/sessions/history", { session_id: state.aiSession.session_id, limit: 20 });
    renderAiHistory(result.messages || []);
  } catch (error) { $("#ai-job-status").textContent = `대화 기록을 불러오지 못했습니다: ${error.message}`; }
}

function renderAiHistory(messages) {
  const host = $("#ai-chat-history");
  host.innerHTML = messages.length ? messages.map((message) => `<article class="ai-message ${message.role === "user" ? "user" : "assistant"}"><small>${message.role === "user" ? "나" : "AI 도우미"}</small>${escapeHtml(message.text || "")}${renderAiTrace(message.result)}</article>`).join("") : '<p class="muted">AI에게 질문하면 이 앱 세션의 대화가 표시됩니다.</p>';
  host.scrollTop = host.scrollHeight;
}

function renderAiTrace(result) {
  const trace = result?.tool_trace || result?.trace || [];
  if (!trace.length) return "";
  return `<details class="ai-trace"><summary>확인한 작업 ${trace.length}개</summary>${trace.map((item) => `<p>${escapeHtml(AI_TOOL_LABELS[item.tool] || "읽기 전용 확인")} · ${escapeHtml(item.summary || "완료")}${item.result_count != null ? ` · ${Number(item.result_count).toLocaleString()}개` : ""}</p>`).join("")}</details>`;
}

function aiContext() {
  const guided = $("#guided-query-text").value.trim();
  const query = guided || $("#concept-query").value.trim();
  const selectedId = $("#concept-query-select").value || "";
  const selectedText = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((row) => row.dataset.queryId === selectedId)?.querySelector(".saved-query-text").value.trim() || "";
  const queryId = selectedText && selectedText === query ? selectedId : "";
  const documentId = $("#manual-document-id").value.trim();
  const document = documentId ? { index: $("#index-name").value.trim(), id: documentId } : null;
  const concept = collectConcept();
  if (state.stagedAiResultContext) {
    return { query: state.stagedAiResultContext.query, concept, document: { ...state.stagedAiResultContext.document } };
  }
  return { ...(query ? { query } : {}), ...(queryId ? { query_id: queryId } : {}), concept, document };
}

function cloneAiContext(context) { return JSON.parse(JSON.stringify(context)); }

async function sendAiMessage(retry = false) {
  const message = retry ? state.aiLastMessage : $("#ai-message").value.trim();
  if (!message) return showToast("AI에게 부탁할 내용을 입력하세요.", true);
  const context = retry && state.aiLastContext ? cloneAiContext(state.aiLastContext) : aiContext();
  state.aiLastMessage = message;
  state.aiLastContext = cloneAiContext(context);
  renderAiContextReadouts();
  try {
    const session = await ensureAiSession();
    state.aiLastMessage = message;
    state.aiLastContext = cloneAiContext(context);
    renderAiContextReadouts();
    const result = await api("/api/ai/sessions/message", { session_id: session.session_id, connection: getConnection(), message, context });
    if (state.stagedAiResultContext && context.query === state.stagedAiResultContext.query && context.document?.index === state.stagedAiResultContext.document.index && context.document?.id === state.stagedAiResultContext.document.id) {
      state.stagedAiResultContext = null;
      $("#ai-result-stage-status").textContent = "";
      renderAiContextReadouts();
    }
    state.aiJobId = result.job_id;
    $("#ai-message").value = "";
    $("#ai-send").disabled = true;
    $("#ai-cancel").disabled = false;
    $("#ai-retry").disabled = true;
    $("#ai-job-status").textContent = "요청을 보냈습니다. 읽기 전용 확인을 진행 중입니다…";
    pollAiJob(result.job_id, session.session_id);
  } catch (error) {
    state.aiLastMessage = message;
    state.aiLastContext = cloneAiContext(context);
    renderAiContextReadouts();
    $("#ai-job-status").textContent = error.message;
    $("#ai-send").disabled = !state.connected || !state.aiProviders.find((item) => item.id === $("#ai-provider").value)?.available;
    $("#ai-retry").disabled = !state.aiLastMessage;
  }
}

async function pollAiJob(jobId = state.aiJobId, sessionId = state.aiSession?.session_id) {
  if (!jobId) return;
  try {
    const job = await api("/api/ai/jobs/get", { job_id: jobId });
    if (state.aiJobId !== jobId || state.aiSession?.session_id !== sessionId) return;
    if (job.status === "queued" || job.status === "running") {
      const stage = "확인 진행 중";
      const completed = Number(job.progress?.completed_steps || 0);
      const maximum = Number(job.progress?.max_steps || 6);
      const trace = (job.tool_trace || []).map((item) => AI_TOOL_LABELS[item.tool] || "읽기 전용 확인");
      $("#ai-job-status").textContent = `${stage} · ${completed}/${maximum}${trace.length ? ` · ${trace.join(", ")}` : ""}`;
      state.aiJobTimer = setTimeout(() => pollAiJob(jobId, sessionId), 700);
      return;
    }
    state.aiJobId = null;
    $("#ai-cancel").disabled = true;
    if (job.status === "succeeded") {
      $("#ai-job-status").textContent = "요청이 끝났습니다. 초안과 확인 내용을 검토하세요.";
      $("#ai-retry").disabled = true;
      renderAiJobResult(job.result || {}, job.tool_trace || []);
      await loadAiHistory();
    } else if (job.status === "cancelled") {
      $("#ai-job-status").textContent = "요청을 취소했습니다.";
      $("#ai-retry").disabled = false;
      await loadAiHistory();
    } else {
      $("#ai-job-status").textContent = `${friendlyAiError(job.error)} 다시 시도할 수 있습니다.`;
      $("#ai-retry").disabled = false;
      await loadAiHistory();
    }
  } catch (error) {
    state.aiJobId = null; $("#ai-cancel").disabled = true;
    $("#ai-retry").disabled = !state.aiLastMessage;
    $("#ai-job-status").textContent = `작업 상태를 확인하지 못했습니다: ${error.message} 요청을 다시 시도할 수 있습니다.`;
  } finally {
    if (!state.aiJobId) { $("#ai-send").disabled = !state.connected || !state.aiProviders.find((item) => item.id === $("#ai-provider").value)?.available; }
  }
}

function friendlyAiError(error) {
  const code = String(error?.code || "");
  const message = String(error?.message || "").toLowerCase();
  if (["sign_in_required", "auth_required", "not_authenticated"].includes(code) || message.includes("check provider sign-in")) return "선택한 구독에 로그인되어 있는지 확인한 뒤 다시 시도하세요.";
  if (["rate_limited", "quota_exceeded"].includes(code) || message.includes("rate limit")) return "제공자 사용 한도에 도달했습니다. 잠시 후 다시 시도하세요.";
  if (code || message.includes("selected ai provider")) return "선택한 구독에서 응답을 완료하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.";
  return "AI 요청을 완료하지 못했습니다. 잠시 후 다시 시도하세요.";
}

function renderAiJobResult(result, trace) {
  const draft = result.concept_draft;
  state.aiLastDraft = draft || null;
  const diagnosis = result.diagnosis;
  const summary = result.summary;
  const jobWarnings = (result.warnings || []).map((warning) => `<p class="notice notice-muted">${escapeHtml(localizeAiWarning(warning))}</p>`).join("");
  let html = "";
  if (result.text) html += `<div class="ai-message assistant"><small>AI 도우미</small>${escapeHtml(result.text)}${renderAiTrace({ tool_trace: trace })}</div>`;
  if (draft) {
    const corpus = draft.corpus || {};
    html += `<section class="ai-draft-review"><h4>검토할 개념 초안</h4><p><strong>${escapeHtml(draft.name || "현재 이름 유지")}</strong></p><p>${escapeHtml(draft.description || "현재 설명 유지")}</p><details class="draft-change-review" open><summary>현재 설정과 제안 비교</summary>${renderDraftChanges(collectConcept(), draft)}</details><p class="outcome-caveat">검토 후 입력란에 반영할 수 있습니다. 저장과 실제 검색은 따로 진행합니다.</p><button type="button" id="adopt-ai-draft" class="button button-primary button-small">검토한 초안을 입력란에 적용</button></section>`;
  }
  if (diagnosis?.kind === "model_hypothesis") {
    html += `<section class="ai-draft-review"><h4>AI가 제안한 가능성 · 확인이 필요합니다</h4>${renderAiInterpretation(diagnosis.text || "")}<p class="outcome-caveat">이는 모델의 해석이며 Elasticsearch가 확인한 원인 판정이 아닙니다.</p></section>`;
  } else if (diagnosis) {
    const label = DIAGNOSIS_LABELS[diagnosis.classification] || "원인을 확정하지 못했습니다.";
    const nextSteps = (diagnosis.next_steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("");
    html += `<section class="ai-draft-review"><h4>문서 확인 결과</h4><p>${escapeHtml(label)}</p>${nextSteps ? `<ul>${nextSteps}</ul>` : ""}<details><summary>확인 결과 자세히</summary>${(diagnosis.selected_field_presence || []).map((item) => `<p>${escapeHtml(item.field)} · ${item.has_value ? "값 있음" : "값 없음"}</p>`).join("")}${renderAiTrace({ tool_trace: trace })}</details></section>`;
  }
  if (summary?.kind === "model_summary") html += `<section class="ai-draft-review"><h4>AI 요약 · 참고용</h4>${renderAiInterpretation(summary.text || "")}<p class="outcome-caveat">평가된 문서와 검색 결과를 바탕으로 한 해석입니다. 품질 보증이나 사실 판정은 아닙니다.</p></section>`;
  else if (summary) html += `<section class="ai-draft-review"><h4>관찰 결과 요약</h4><p>${escapeHtml(summary.headline || "")}</p>${(summary.details || []).map((line) => `<p>${escapeHtml(line)}</p>`).join("")}</section>`;
  if (jobWarnings) html += jobWarnings;
  $("#ai-draft-review").innerHTML = html;
  if (!html) $("#ai-draft-review").innerHTML = renderAiTrace({ tool_trace: trace });
}

function renderDraftChanges(current, draft) {
  const rows = [];
  const has = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);
  const present = (value, format = (item) => String(item ?? "없음")) => format(value);
  const diff = (label, before, after, explicit, format) => {
    if (!explicit) { rows.push(`<li><strong>${escapeHtml(label)}:</strong> 현재 값 유지 (${escapeHtml(present(before, format))})</li>`); return; }
    if (JSON.stringify(before ?? null) === JSON.stringify(after ?? null)) { rows.push(`<li><strong>${escapeHtml(label)}:</strong> 변경 없음</li>`); return; }
    rows.push(`<li><strong>${escapeHtml(label)}:</strong> ${escapeHtml(present(before, format))} <span aria-hidden="true">→</span> ${escapeHtml(present(after, format))}</li>`);
  };
  const list = (items) => (items || []).join(", ") || "없음";
  const related = (items) => (items || []).map((item) => `${item.term || ""}${item.weight != null ? ` (${item.weight})` : ""}`).filter(Boolean).join(", ") || "없음";
  const filters = (items) => (items || []).map((item) => `${item.field}=${item.value}`).join(", ") || "없음";
  const queries = (items) => (items || []).map((item) => item.query || "").filter(Boolean).join(" · ") || "없음";
  diff("개념 이름", current.name, draft.name, has(draft, "name"));
  diff("설명", current.description, draft.description, has(draft, "description"));
  diff("다른 표현", current.aliases, draft.aliases, has(draft, "aliases"), list);
  diff("함께 볼 표현", current.related, draft.related, has(draft, "related"), related);
  diff("제외 표현", current.excluded_terms, draft.excluded_terms, has(draft, "excluded_terms"), list);
  const corpus = draft.corpus || {};
  if (has(draft, "corpus")) {
    if (corpus.index && corpus.index !== current.corpus.index) rows.push(`<li><strong>인덱스:</strong> 선택한 인덱스 ${escapeHtml(current.corpus.index)} 유지 (초안 제안 ${escapeHtml(corpus.index)}는 적용하지 않음)</li>`);
    diff("제목 필드", current.corpus.title_field, corpus.title_field, has(corpus, "title_field"));
    diff("본문 필드", current.corpus.text_fields, corpus.text_fields, has(corpus, "text_fields"), list);
    diff("조건 필드", current.corpus.filter_fields, corpus.filter_fields, has(corpus, "filter_fields"), list);
  } else rows.push("<li><strong>검색 필드:</strong> 현재 값 유지</li>");
  diff("조건 값", current.filters, draft.filters, has(draft, "filters"), filters);
  diff("저장 질의", current.queries, draft.queries, has(draft, "queries"), queries);
  const settingLabels = { size: "표시 결과 수", candidate_size: "검색 대상 수", concept_weight: "개념 반영 정도", related_weight: "함께 볼 표현 반영 정도", field_boosts: "필드별 반영 정도" };
  const settings = draft.settings || {};
  const currentSettings = current.settings || {};
  const proposed = Object.keys(settings).filter((key) => JSON.stringify(settings[key]) !== JSON.stringify(currentSettings[key]));
  if (!has(draft, "settings")) rows.push("<li><strong>검색 반영 설정:</strong> 현재 값 유지</li>");
  else if (!proposed.length) rows.push("<li><strong>검색 반영 설정:</strong> 변경 없음</li>");
  else rows.push(`<li><strong>검색 반영 설정:</strong> ${proposed.map((key) => escapeHtml(settingLabels[key] || key)).join(", ")} 변경 제안</li>`);
  return `<ul class="draft-change-list">${rows.join("")}</ul>`;
}

function renderAiInterpretation(value) {
  const labels = { proposed: "제안", unchanged: "그대로 둔 항목", unknowns: "확인하지 않은 점", rationale: "이유", observation: "관찰" };
  let parsed = null;
  try { parsed = typeof value === "string" ? JSON.parse(value) : value; } catch { /* Plain prose from the model remains plain text. */ }
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const lines = Object.entries(parsed).filter(([, text]) => typeof text === "string" || typeof text === "number").map(([key, text]) => `<p><strong>${escapeHtml(labels[key] || key)}:</strong> ${escapeHtml(String(text))}</p>`).join("");
    if (lines) return lines;
  }
  return `<p>${escapeHtml(typeof value === "string" ? value : JSON.stringify(value))}</p>`;
}

function localizeAiWarning(value) {
  const message = String(value || "");
  const lower = message.toLowerCase();
  if (lower.includes("ai summary is an interpretation of supplied observations")) return "AI 요약은 제공된 관찰을 풀어쓴 해석이며, 별도로 검증된 지표가 아닙니다.";
  if (lower.includes("model-generated") && lower.includes("hypothesis")) return "AI의 원인 설명은 가설입니다. 검색 엔진이 확인한 결과와 구분해 살펴보세요.";
  if (lower.includes("untrusted")) return "문서 내용은 확인 대상 자료이며 지시로 취급하지 않습니다.";
  return message;
}

function adoptAiDraft() {
  const draft = state.aiLastDraft;
  if (!draft) return;
  const currentGuidedQuery = $("#guided-query-text").value;
  const active = collectConcept();
  const corpus = { ...active.corpus, ...(draft.corpus || {}), index: active.corpus.index };
  const available = new Set(state.schema.map((field) => field.name));
  corpus.text_fields = (corpus.text_fields || active.corpus.text_fields).filter((field) => available.has(field));
  corpus.filter_fields = (corpus.filter_fields || active.corpus.filter_fields).filter((field) => available.has(field));
  const filters = (draft.filters || active.filters).filter((filter) => available.has(filter.field) && corpus.filter_fields.includes(filter.field));
  if (!String(draft.name || "").trim() || !corpus.text_fields.length) {
    $("#ai-job-status").textContent = "초안을 입력란에 적용하지 못했습니다. 개념 이름과 현재 인덱스의 본문 필드를 확인해 다시 요청하세요.";
    return;
  }
  const mergedDraft = {
    ...active,
    ...draft,
    id: state.conceptId || undefined,
    corpus,
    aliases: Object.hasOwn(draft, "aliases") ? draft.aliases : active.aliases,
    related: Object.hasOwn(draft, "related") ? draft.related : active.related,
    excluded_terms: Object.hasOwn(draft, "excluded_terms") ? draft.excluded_terms : active.excluded_terms,
    queries: Object.hasOwn(draft, "queries") ? draft.queries : active.queries,
    filters,
    settings: { ...active.settings, ...(draft.settings || {}), field_boosts: { ...(active.settings.field_boosts || {}), ...(draft.settings?.field_boosts || {}) } },
  };
  populateConcept(mergedDraft);
  // A concept draft without explicit query cases must not replace the user's
  // current search text. Query cases are merged above only when supplied.
  if (Object.hasOwn(draft, "queries") && draft.queries?.length) {
    $("#guided-query-text").value = draft.queries[0].query || "";
  } else $("#guided-query-text").value = currentGuidedQuery;
  $("#concept-name").scrollIntoView({ behavior: "smooth", block: "center" });
  showToast("초안을 입력란에 넣었습니다. 저장하고 실제 검색 결과를 확인하세요.");
}

async function cancelAiJob() {
  if (!state.aiJobId) return;
  try {
    const result = await api("/api/ai/jobs/cancel", { job_id: state.aiJobId });
    $("#ai-job-status").textContent = result.cancellation_requested ? "취소를 요청했습니다…" : "요청을 마무리하고 있습니다…";
  } catch (error) { $("#ai-job-status").textContent = `취소 요청을 보내지 못했습니다: ${error.message}`; }
}

function retryAiMessage() {
  if (!state.aiLastMessage) return;
  $("#ai-message").value = state.aiLastMessage;
  sendAiMessage(true);
}

async function fetchManualDocument() {
  const id = $("#manual-document-id").value.trim();
  const queryId = $("#manual-query-id").value;
  const scopeRequestId = state.locatorRequestId;
  if (!state.conceptId) return showToast("개념을 저장한 뒤 직접 문서를 평가하세요.", true);
  if (!id || !queryId) return showToast("문서 ID와 평가할 저장 질의를 선택하세요.", true);
  const button = $("#fetch-manual-document"); button.disabled = true;
  $("#manual-document-result").innerHTML = '<span class="loading-inline"><i class="spinner"></i> 인덱스에서 문서를 확인하고 있습니다.</span>';
  try {
    const result = await api("/api/concepts/document", { connection: getConnection(), index: state.manualDocumentIndex || $("#index-name").value.trim(), document_id: id });
    if (scopeRequestId !== state.locatorRequestId) return;
    const queryText = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((row) => row.dataset.queryId === queryId)?.querySelector(".saved-query-text").value || "";
    const titleField = $("#concept-title-field").value;
    const source = result.source || {};
    const title = sourceField(source, titleField) || source.title || source.summary || result.document_id;
    const snippet = Object.entries(source).filter(([, value]) => typeof value === "string" && value.trim()).slice(0, 3).map(([field, value]) => `${field}: ${value}`).join("\n");
    const hit = { _index: result.document_index || $("#index-name").value.trim(), _id: result.document_id || id, rank: null, source: { ...source, [titleField || "title"]: title }, snippet, evidence: [] };
    $("#manual-document-result").innerHTML = `<p class="manual-source-label">기본 검색 결과 밖에서 직접 불러온 문서 · 질의: ${escapeHtml(queryText)}</p>${renderResultSet({ hits: [hit], total: 1 }, "직접 불러온 문서", "candidate", queryId)}`;
  } catch (error) { $("#manual-document-result").innerHTML = `<div class="notice notice-error">${escapeHtml(error.message)}</div>`; }
  finally { button.disabled = !state.connected; }
}

async function diagnoseManualDocument() {
  const id = state.manualDocumentFromLocator ? $("#manual-document-id").value : $("#manual-document-id").value.trim();
  const queryId = $("#manual-query-id").value;
  const button = $("#diagnose-manual-document");
  if (!state.connected || !state.conceptId) return showToast("Elasticsearch에 연결하고 개념을 저장한 뒤 확인하세요.", true);
  const row = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((item) => item.dataset.queryId === queryId);
  const query = row?.querySelector(".saved-query-text").value.trim();
  const scopeRequestId = state.locatorRequestId;
  if (!id || !queryId || !query) return showToast("문서 ID와 확인할 저장 질의를 선택하세요.", true);
  if (JSON.stringify(collectConcept()) !== state.savedConceptSnapshot && !await saveConcept({ silent: true })) return;
  if (scopeRequestId !== state.locatorRequestId) return;
  button.disabled = true;
  $("#manual-document-diagnosis").innerHTML = '<span class="loading-inline"><i class="spinner"></i> 문서와 현재 검색 조건을 읽기 전용으로 확인하고 있습니다.</span>';
  try {
    const connection = getConnection();
    const selectedIndex = state.manualDocumentIndex || $("#index-name").value.trim();
    const fetched = await api("/api/concepts/document", { connection, index: selectedIndex, document_id: id });
    if (scopeRequestId !== state.locatorRequestId) return;
    const documentIndex = fetched.document_index || selectedIndex;
    const result = await api("/api/concepts/diagnose", {
      connection,
      concept: collectConcept(),
      query,
      query_id: queryId,
      document_index: documentIndex,
      document_id: fetched.document_id || id,
    });
    if (scopeRequestId !== state.locatorRequestId) return;
    const classification = DIAGNOSIS_LABELS[result.classification] || "원인을 구분하지 못했습니다.";
    const steps = (result.next_steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("");
    const present = (result.selected_field_presence || []).map((field) => `<li>${escapeHtml(field.field)} · ${field.has_value ? "값 있음" : "값 없음"}</li>`).join("");
    const probes = (result.probes || []).map((probe) => `<section><strong>${escapeHtml(({ baseline: "기본 검색", candidate_with_filters: "개념 적용과 조건", candidate_without_filters: "조건을 뺀 개념 검색", candidate_without_exclusions: "제외 표현을 뺀 개념 검색" })[probe.name] || probe.name || "검색 점검")}</strong><p>${probe.matched == null ? "확인할 수 없음" : probe.matched ? "이 문서와 일치" : "이 문서와 일치하지 않음"}${probe.score != null ? ` · 순위 점수 ${formatNumber(probe.score)}` : ""}</p>${probe.explanation ? `<details><summary>검색 엔진 설명 펼치기</summary><pre class="explain-box">${escapeHtml(JSON.stringify(probe.explanation, null, 2))}</pre></details>` : ""}</section>`).join("");
    const warningList = localizedConceptWarnings(result).map((warning) => `<p class="notice notice-muted">${escapeHtml(warning)}</p>`).join("");
    $("#manual-document-diagnosis").innerHTML = `<article class="diagnosis-result"><h4>${escapeHtml(result.document_index || documentIndex)} / ${escapeHtml(result.document_id || id)}</h4><p class="diagnosis-classification">${escapeHtml(classification)}</p><p class="helper-text">검색 조건과 필드의 일치 여부를 확인한 결과입니다. 문서가 찾으려는 내용과 관련 있는지는 직접 판단하세요.</p>${steps ? `<strong>다음에 확인할 점</strong><ul>${steps}</ul>` : ""}<details><summary>선택한 필드와 점검 결과 보기</summary>${present ? `<strong>문서에 값이 있는 본문 필드</strong><ul>${present}</ul>` : ""}${probes}</details>${warningList}</article>`;
  } catch (error) {
    const message = /404|not found|could not be found/i.test(error.message) ? "선택한 인덱스에서 문서를 찾지 못했습니다. 인덱스와 문서 ID를 확인하세요." : error.message;
    $("#manual-document-diagnosis").innerHTML = `<div class="notice notice-error">${escapeHtml(message)}</div>`;
  } finally { updateManualDocumentActions(); }
}

function metricSummary(metrics) {
  if (metrics == null) return "평가 자료 없음";
  const labels = { k: "평가 순위", query_count: "질의", judged_count: "평가 문서", retrieved_judged_count: "결과에 포함된 평가 문서", ndcg_at_k: "nDCG", judged_coverage_at_k: "평가 문서 포함률", recall_of_judged_relevant_at_k: "관련 문서 회수율", explicit_unjudged_count: "명시적 미평가", unjudged_retrieved_count: "결과 내 미평가" };
  return Object.entries(labels).filter(([key]) => metrics[key] != null).map(([key, label]) => `${label} ${typeof metrics[key] === "number" ? (Number.isInteger(metrics[key]) ? metrics[key].toLocaleString() : formatNumber(metrics[key])) : escapeHtml(metrics[key])}`).join(" · ") || "평가 결과를 받았습니다.";
}

function renderPerQueryMetrics(label, metrics) {
  const rows = metrics?.queries || [];
  if (!rows.length) return "";
  return `<section class="per-query-metrics"><h4>${escapeHtml(label)} · 질의별 결과</h4><div class="eval-table-wrap"><table class="eval-table"><thead><tr><th>질의</th><th>nDCG</th><th>평가 문서 포함률</th><th>관련 문서 회수율</th><th>명시적 미평가</th><th>결과 내 미평가</th></tr></thead><tbody>${rows.map((row) => `<tr><td class="query-cell"><span class="query-id">${escapeHtml(row.query_id || "질의")}</span><br>${escapeHtml(row.query || "")}</td><td>${formatNumber(row.ndcg_at_k)}</td><td>${formatNumber(row.judged_coverage_at_k)}</td><td>${formatNumber(row.recall_of_judged_relevant_at_k)}</td><td>${Number(row.explicit_unjudged_count || 0)}</td><td>${Number(row.unjudged_retrieved_count || 0)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

async function runConceptTune() {
  const concept = collectConcept();
  if (!state.connected) return;
  if (!state.conceptId) return showToast("튜닝하기 전에 개념을 저장하세요.", true);
  const requestConnectionGeneration = state.connectionGeneration;
  const button = $("#concept-tune"); button.disabled = true;
  $("#concept-tune-results").innerHTML = '<div class="loading-inline"><i class="spinner"></i> 평가 자료로 설정을 비교하고 있습니다.</div>';
  try {
    const result = await api("/api/concepts/tune", { connection: getConnection(), concept, passes: Number($("#concept-tune-passes").value) });
    state.tunedSettings = result.settings || null;
    const warningHtml = localizedConceptWarnings(result).map((item) => `<p class="notice notice-muted">${escapeHtml(item)}</p>`).join("");
    const validationHtml = result.validation
      ? `<div><span>검증용 · 조정 전</span><p>${metricSummary(result.validation.baseline)}</p></div><div><span>검증용 · 조정 후</span><p>${metricSummary(result.validation.tuned)}</p></div>`
      : `<div class="validation-empty"><span>검증용 평가</span><p>검증용 평가 자료가 없어 일반화 여부를 확인하지 못했습니다. 현재 결과는 학습용 자료 기준입니다.</p></div>`;
    const queryDetails = [renderPerQueryMetrics("학습용 · 조정 전", result.baseline), renderPerQueryMetrics("학습용 · 조정 후", result.tuned), renderPerQueryMetrics("검증용 · 조정 전", result.validation?.baseline), renderPerQueryMetrics("검증용 · 조정 후", result.validation?.tuned)].join("");
    const plain = result.plain_summary || {};
    const humanSummary = `<section class="plain-outcome"><h4>${escapeHtml(plain.headline || "평가한 문서를 기준으로 설정을 비교했습니다.")}</h4>${(plain.details || []).map((detail) => `<p>${escapeHtml(detail)}</p>`).join("")}${(plain.caveats || []).map((caveat) => `<p class="outcome-caveat">${escapeHtml(caveat)}</p>`).join("")}</section>`;
    const numericDetails = `<details class="numeric-outcomes"><summary>상세 수치와 질의별 비교 보기</summary><div class="tune-metric-grid"><div><span>학습용 · 조정 전</span><p>${metricSummary(result.baseline)}</p></div><div><span>학습용 · 조정 후</span><p>${metricSummary(result.tuned)}</p></div>${validationHtml}</div><p class="helper-text">평가 ${Number(result.judged_count || 0)}건 · 명시적 미평가 ${Number(result.explicit_unjudged_count || 0)}건 · 결과 내 미평가 ${Number(result.unjudged_retrieved_count || 0)}건 · 따로 고정 ${Number(result.pinned_count || 0)}건</p>${queryDetails}</details>`;
    const missedTargets = renderTuneMisses(result, concept, requestConnectionGeneration);
    $("#concept-tune-results").innerHTML = `<div class="concept-tune-result card"><div class="concept-section-heading"><div><h3>설정 비교 결과</h3><p>조정은 학습용 평가 자료만 사용했습니다. 다른 질의 평가는 별도로 확인합니다.</p></div><button type="button" class="button button-primary button-small apply-tuned-settings">워크벤치에 이 설정 적용</button></div>${humanSummary}${numericDetails}${missedTargets}<details><summary>적용 설정</summary><pre class="explain-box">${escapeHtml(JSON.stringify(result.settings || {}, null, 2))}</pre></details>${warningHtml}</div>`;
    await loadConceptRuns();
  } catch (error) {
    const detail = /positive|relevant|grade|label|judg/i.test(error.message) ? "설정 비교를 시작하려면 학습용 질의 결과에서 적어도 한 문서를 ‘조금 관련’ 이상으로 평가해 주세요. 0점은 무관, ‘미평가’는 아직 판단하지 않은 상태입니다." : error.message;
    $("#concept-tune-results").innerHTML = `<div class="notice notice-error">${escapeHtml(detail)}</div>`;
  }
  finally { button.disabled = !state.connected; }
}

async function loadConceptRuns() {
  try {
    const result = await api("/api/concepts/runs", { ...(state.conceptId ? { concept_id: state.conceptId } : {}), limit: 30 });
    const runs = result.runs || [];
    const runRows = runs.length ? runs.map((run) => {
      const runId = run.run_id == null ? "" : String(run.run_id);
      const conceptId = run.concept_id == null ? "" : String(run.concept_id);
      const savedSnapshot = run.snapshot || {};
      const previewOrganicCount = (savedSnapshot.candidate_ids || []).filter((item) => Array.isArray(item) ? item[2] != null : (item?.rank ?? item?.organic_rank) != null).length;
      const previewPinCount = Number(savedSnapshot.pinned_count ?? (savedSnapshot.candidate_ids || []).filter((item) => Array.isArray(item) ? item[2] == null : (item?.rank ?? item?.organic_rank) == null).length);
      const summary = run.kind === "preview"
        ? `기준선 ${Number(savedSnapshot.baseline_ids?.length || 0)}개 · 개념 적용 일반 결과 ${previewOrganicCount}개${previewPinCount ? ` · 고정 배치 힌트 ${previewPinCount}개` : ""}`
        : metricSummary(savedSnapshot.train?.tuned || run.metrics);
      const runKind = run.kind === "preview" || run.kind === "tune" ? run.kind : "";
      const runActions = runId && conceptId
        ? `<button type="button" class="button button-secondary button-small run-details-button" data-concept-id="${escapeHtml(conceptId)}" data-run-id="${escapeHtml(runId)}" data-run-kind="${escapeHtml(runKind)}" aria-label="저장된 실험 결과 자세히 보기 (${escapeHtml(runId)})" aria-expanded="false">저장된 결과 자세히 보기</button><button type="button" class="button button-secondary button-small run-export-button" data-concept-id="${escapeHtml(conceptId)}" data-run-id="${escapeHtml(runId)}" data-run-kind="${escapeHtml(runKind)}" aria-label="실험 결과 JSON 다운로드 (${escapeHtml(runId)})">JSON 다운로드</button><span class="run-export-status" aria-live="polite"></span>`
        : "";
      const compareChoice = run.kind === "preview" && runId && conceptId
        ? `<label class="preview-run-compare-choice"><input type="checkbox" class="preview-run-compare-select" data-concept-id="${escapeHtml(conceptId)}" data-run-id="${escapeHtml(runId)}" aria-label="비교할 저장 미리보기 선택 (${escapeHtml(runId)} · ${escapeHtml(run.created_at || run.timestamp || "시간 미상")})"><span>두 결과 비교에 포함</span></label>`
        : "";
      return `<article class="run-row"><div><strong>${escapeHtml(run.kind || "비교")}</strong><span>${escapeHtml(run.created_at || run.timestamp || "시간 미상")}</span><small>${escapeHtml(runId)}</small></div><div><span>${escapeHtml(conceptId || "개념")}</span><p>${escapeHtml(summary)}</p>${compareChoice}<details class="run-details"><summary>사용한 설정과 질의 보기</summary><pre class="explain-box">${escapeHtml(JSON.stringify({ settings: run.settings || {}, ...(run.reproducibility || {}), ...(run.query ? { query: run.query } : {}) }, null, 2))}</pre></details><div class="run-export-actions">${runActions}</div><div class="run-details-content" aria-live="polite" hidden></div></div></article>`;
    }).join("") : '<p class="muted">아직 실험 기록이 없습니다.</p>';
    const previewCount = runs.filter((run) => run.kind === "preview" && run.run_id && run.concept_id).length;
    const compareToolbar = previewCount ? '<section class="preview-run-compare-toolbar" aria-label="저장 미리보기 비교"><div><strong>저장 미리보기 두 개 비교</strong><p>같은 개념에서 저장한 미리보기 2개를 선택하세요.</p></div><div class="preview-run-compare-actions"><button id="compare-saved-previews" type="button" class="button button-primary button-small" disabled>선택한 결과 비교</button><button id="clear-saved-preview-selection" type="button" class="button button-secondary button-small" disabled>선택 지우기</button></div><p id="saved-preview-selection-status" class="helper-text" aria-live="polite">아직 선택하지 않았습니다.</p></section><div id="saved-preview-comparison" aria-live="polite"></div>' : "";
    $("#concept-runs-list").innerHTML = `${compareToolbar}${runRows}`;
    updateSavedPreviewSelection();
  } catch (error) { $("#concept-runs-list").textContent = `실험 기록을 불러오지 못했습니다: ${error.message}`; }
}

function runMetricCards(label, metrics) {
  if (!metrics) return `<p class="run-detail-empty">${escapeHtml(label)} 평가 자료가 없습니다.</p>`;
  const values = [
    ["질의", metrics.query_count],
    ["nDCG", metrics.ndcg_at_k],
    ["평가 문서 포함률", metrics.judged_coverage_at_k],
    ["관련 문서 회수율", metrics.recall_of_judged_relevant_at_k],
  ].filter(([, value]) => value != null);
  return `<section class="run-detail-metric"><h5>${escapeHtml(label)}</h5><div>${values.map(([name, value]) => `<span><small>${escapeHtml(name)}</small><strong>${typeof value === "number" && !Number.isInteger(value) ? formatNumber(value) : escapeHtml(value)}</strong></span>`).join("")}</div></section>`;
}

function runRankedRows(label, rows, maxRows = 10) {
  if (!Array.isArray(rows) || !rows.length) return `<section class="run-detail-ranks"><h5>${escapeHtml(label)}</h5><p class="run-detail-empty">저장된 결과 ID가 없습니다.</p></section>`;
  const ranked = rows.filter((item) => !item?.pinned);
  const pinned = rows.filter((item) => item?.pinned);
  const display = ranked.slice(0, maxRows);
  const omitted = Math.max(0, ranked.length - display.length);
  const rankedHtml = display.length
    ? `<ol>${display.map((item, index) => {
      const docId = Array.isArray(item) ? item[1] : item?.id;
      const rank = Array.isArray(item) ? item[2] : (item?.rank ?? item?.organic_rank);
      const docIndex = Array.isArray(item) ? item[0] : item?.index;
      return `<li><span>${rank == null ? `${index + 1}위` : `${escapeHtml(rank)}위`}</span><code>${escapeHtml(docId ?? "ID 미상")}</code>${docIndex ? `<small>${escapeHtml(docIndex)}</small>` : ""}</li>`;
    }).join("")}</ol>${omitted ? `<p class="run-detail-empty">그 밖의 결과 ${omitted}개</p>` : ""}`
    : '<p class="run-detail-empty">일반 검색 순위 결과가 없습니다.</p>';
  const pinHtml = pinned.length
    ? `<div class="run-pin-hints"><strong>고정 배치 힌트 · 순위 점수나 관련도 평가가 아닙니다.</strong><ul>${pinned.slice(0, maxRows).map((item) => `<li><code>${escapeHtml(item?.id ?? "ID 미상")}</code>${item?.index ? `<small>${escapeHtml(item.index)}</small>` : ""}</li>`).join("")}</ul>${pinned.length > maxRows ? `<p class="run-detail-empty">그 밖의 고정 힌트 ${pinned.length - maxRows}개</p>` : ""}</div>`
    : "";
  return `<section class="run-detail-ranks"><h5>${escapeHtml(label)}</h5>${rankedHtml}${pinHtml}</section>`;
}

function runQueryTexts(artifact) {
  const entries = artifact.run?.input_snapshot?.concept?.queries || [];
  return Object.fromEntries(entries.map((entry) => [String(entry.id || ""), String(entry.query || "")]));
}

function runPinHints(artifact, queryId = "") {
  const judgments = artifact.run?.input_snapshot?.judgments || [];
  return judgments.filter((item) => item?.pinned && (!queryId || String(item.query_id || "") === String(queryId)));
}

function renderRunPinHints(artifact, maxRows = 20) {
  const pins = runPinHints(artifact);
  if (!pins.length) return "";
  return `<section class="run-pin-hints run-pin-hints-summary"><strong>고정 배치 힌트 · 순위 점수나 관련도 평가가 아닙니다.</strong><ul>${pins.slice(0, maxRows).map((item) => `<li><code>${escapeHtml(item.document_id ?? "ID 미상")}</code>${item.document_index ? `<small>${escapeHtml(item.document_index)}</small>` : ""}</li>`).join("")}</ul>${pins.length > maxRows ? `<p class="run-detail-empty">그 밖의 고정 힌트 ${pins.length - maxRows}개</p>` : ""}</section>`;
}

function renderPreviewRunDetails(artifact) {
  const run = artifact.run || {};
  const outputs = run.output_snapshot || {};
  const baseline = Array.isArray(outputs.baseline) ? outputs.baseline : [];
  const concept = Array.isArray(outputs.candidate) ? outputs.candidate : [];
  const pins = runPinHints(artifact);
  const pinData = pins.map((item) => ({ index: item.document_index, id: item.document_id, pinned: true }));
  const candidateRows = [...concept, ...pinData.filter((pin) => !concept.some((row) => String(row.id) === String(pin.id) && String(row.index) === String(pin.index)))];
  return `<section class="run-detail-content" aria-label="저장된 미리보기 실험 결과"><p class="run-detail-boundary">저장 당시 결과 ID와 순위입니다. 현재 문서 본문은 불러오지 않았습니다. 검색 점수는 확률이나 관련도 판정이 아닙니다.</p><p class="run-detail-query"><strong>저장 질의</strong><br>${escapeHtml(run.query || run.input_snapshot?.query?.query || "질의 정보 없음")}</p><div class="run-detail-columns">${runRankedRows("기준선 결과", baseline)}${runRankedRows("개념 적용 결과", candidateRows)}</div></section>`;
}

function renderTuneRunDetails(artifact) {
  const run = artifact.run || {};
  const output = run.output_snapshot || {};
  const train = run.train || {};
  const validation = run.validation;
  const queryTexts = runQueryTexts(artifact);
  const renderSet = (label, metrics, resultByQuery) => {
    const rows = metrics?.queries || [];
    if (!rows.length) return "";
    const visibleRows = rows.slice(0, 20);
    const omitted = Math.max(0, rows.length - visibleRows.length);
    return `<section class="run-query-set"><h5>${escapeHtml(label)} · 질의별 기록</h5>${omitted ? `<p class="run-query-omitted">이 화면에는 질의 20개까지 표시합니다. 나머지 ${omitted}개는 JSON 다운로드에서 확인할 수 있습니다.</p>` : ""}${visibleRows.map((row) => {
      const queryId = String(row.query_id || "");
      const queryOutput = resultByQuery?.[queryId] || [];
      const query = queryTexts[queryId] || "";
      const evidence = `<p class="run-query-metrics">nDCG ${formatNumber(row.ndcg_at_k)} · 평가 문서 포함률 ${formatNumber(row.judged_coverage_at_k)} · 관련 문서 회수율 ${formatNumber(row.recall_of_judged_relevant_at_k)} · 명시적 미평가 ${Number(row.explicit_unjudged_count || 0)} · 결과 내 미평가 ${Number(row.unjudged_retrieved_count || 0)}</p>`;
      return `<article class="run-query-card"><strong>${escapeHtml(queryId || "질의")}</strong>${query ? `<p class="run-query-text">${escapeHtml(query)}</p>` : ""}${evidence}${runRankedRows(label, queryOutput)}</article>`;
    }).join("")}</section>`;
  };
  const trainOutput = output.train || {};
  const validationOutput = output.validation || {};
  const validationHtml = validation
    ? `<div class="run-detail-columns">${runMetricCards("검증용 · 조정 전", validation.baseline)}${runMetricCards("검증용 · 조정 후", validation.tuned)}</div>${renderSet("검증용 · 조정 전", validation.baseline, validationOutput.baseline)}${renderSet("검증용 · 조정 후", validation.tuned, validationOutput.tuned)}`
    : '<section class="run-validation-empty"><strong>검증용 평가 기록 없음</strong><p>이 실행에는 검증용 질의 결과가 저장되지 않아 학습용 기록만 표시합니다.</p></section>';
  return `<section class="run-detail-content" aria-label="저장된 튜닝 실험 결과"><p class="run-detail-boundary">저장 당시 결과 ID와 순위입니다. 현재 문서 본문은 불러오지 않았습니다. 평가되지 않은 문서는 무관하다고 간주하지 않으며, 고정은 배치 힌트일 뿐 관련도 점수에 포함되지 않습니다.</p><div class="run-detail-columns">${runMetricCards("학습용 · 조정 전", train.baseline || run.baseline)}${runMetricCards("학습용 · 조정 후", train.tuned || run.tuned)}</div>${renderSet("학습용 · 조정 전", train.baseline || run.baseline, trainOutput.baseline)}${renderSet("학습용 · 조정 후", train.tuned || run.tuned, trainOutput.tuned)}${validationHtml}${renderRunPinHints(artifact)}</section>`;
}

function renderSavedRunDetails(artifact) {
  const run = artifact?.run || {};
  return run.kind === "preview" ? renderPreviewRunDetails(artifact) : renderTuneRunDetails(artifact);
}

function safeRunExportFilename(runId) {
  const safeRunId = String(runId || "run").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^\.+/, "").slice(0, 80) || "run";
  return `es-rag-run-${safeRunId}.json`;
}

async function fetchConceptRunArtifact(conceptId, runId, expectedKind = "") {
  const artifact = await api("/api/concepts/runs/export", { concept_id: conceptId, run_id: runId });
  const run = artifact?.run;
  if (artifact?.format !== "es-rag-experiment-run" || artifact?.version !== 1
      || String(run?.concept_id || "") !== conceptId || String(run?.run_id || "") !== runId
      || !["preview", "tune"].includes(run?.kind)
      || (expectedKind && run.kind !== expectedKind)) {
    throw new Error("서버가 선택한 실험 실행과 다른 저장 기록을 반환했습니다.");
  }
  return artifact;
}

function updateSavedPreviewSelection(message = "") {
  const checkboxes = [...$$(".preview-run-compare-select")];
  const selected = checkboxes.filter((input) => input.checked);
  const compareButton = $("#compare-saved-previews");
  const clearButton = $("#clear-saved-preview-selection");
  const status = $("#saved-preview-selection-status");
  if (!compareButton || !clearButton || !status) return;

  const conceptId = selected[0]?.dataset.conceptId;
  for (const input of checkboxes) {
    input.disabled = selected.length >= 2 && !input.checked;
    if (selected.length === 1 && input.dataset.conceptId !== conceptId && !input.checked) input.disabled = true;
  }
  compareButton.disabled = selected.length !== 2 || selected[0].dataset.conceptId !== selected[1]?.dataset.conceptId;
  clearButton.disabled = selected.length === 0;
  if (message) status.textContent = message;
  else if (selected.length === 0) status.textContent = "아직 선택하지 않았습니다.";
  else if (selected.length === 1) status.textContent = "같은 개념의 미리보기를 하나 더 선택하세요.";
  else status.textContent = "같은 개념의 미리보기 2개를 선택했습니다.";
}

function normalizePreviewRows(rows, allowPins = false) {
  if (!Array.isArray(rows)) return { valid: false, rows: [] };
  const normalized = [];
  const seen = new Set();
  let valid = true;
  for (const item of rows) {
    if (!item || typeof item !== "object" || Array.isArray(item)) { valid = false; continue; }
    const index = item.index == null ? "" : String(item.index);
    const id = item.id == null ? "" : String(item.id);
    const rawRank = item.rank ?? item.organic_rank;
    const rank = rawRank == null ? null : Number(rawRank);
    const organic = rank != null && Number.isInteger(rank) && rank >= 1;
    const pinOnly = !organic && allowPins && item.pinned === true;
    if (!index || !id || (!organic && !pinOnly)) valid = false;
    const key = JSON.stringify([index, id]);
    if (seen.has(key)) valid = false;
    seen.add(key);
    const sourceHash = item.source_sha256 == null ? "" : String(item.source_sha256);
    if (sourceHash && !/^[a-f0-9]{64}$/i.test(sourceHash)) valid = false;
    normalized.push({ index, id, rank: organic ? rank : null, pinned: item.pinned === true, sourceHash, key });
  }
  return { valid, rows: normalized };
}

function savedRunTimestamp(run) {
  return run.created_at || run.timestamp || "시간 정보 없음";
}

function renderPreviewSnapshotList(label, rows, options = {}) {
  const { maxRows = 20, allowPins = false, displaySize = null } = options;
  const normalized = normalizePreviewRows(rows, allowPins);
  const organic = normalized.rows.filter((row) => row.rank != null);
  const pins = normalized.rows.filter((row) => row.rank == null && row.pinned);
  const limit = displaySize != null && Number.isFinite(Number(displaySize)) && Number(displaySize) > 0
    ? Math.min(maxRows, Number(displaySize))
    : maxRows;
  const visible = organic.slice(0, limit);
  const organicHtml = visible.length
    ? `<ol>${visible.map((row) => `<li><span>${escapeHtml(row.rank)}위</span><code>${escapeHtml(row.index)} / ${escapeHtml(row.id)}</code>${row.pinned ? '<small class="saved-pin-badge">고정 힌트 있음</small>' : ""}</li>`).join("")}</ol>${organic.length > visible.length ? `<p class="run-detail-empty">저장된 일반 결과 ${organic.length}개 중 ${visible.length}개 표시 · 나머지 ${organic.length - visible.length}개</p>` : ""}`
    : '<p class="run-detail-empty">저장된 일반 검색 결과가 없습니다.</p>';
  const pinHtml = pins.length
    ? `<div class="run-pin-hints"><strong>고정 배치 힌트 · 순위 차이에 포함하지 않습니다.</strong><ul>${pins.slice(0, maxRows).map((row) => `<li><code>${escapeHtml(row.index)} / ${escapeHtml(row.id)}</code></li>`).join("")}</ul>${pins.length > maxRows ? `<p class="run-detail-empty">나머지 고정 힌트 ${pins.length - maxRows}개</p>` : ""}</div>`
    : "";
  const invalid = normalized.valid ? "" : '<p class="run-detail-empty">일부 저장 결과 행에 비교할 index, ID 또는 순위가 없어 순위 비교에서 제외했습니다.</p>';
  return `<section class="saved-preview-list"><h5>${escapeHtml(label)}</h5>${organicHtml}${pinHtml}${invalid}</section>`;
}

function previewRunRequirements(first, second) {
  const a = first.run;
  const b = second.run;
  const reasons = [];
  const reason = (ok, message) => { if (!ok) reasons.push(message); };
  reason(a.concept_id && a.concept_id === b.concept_id, "같은 개념에 저장된 두 실행이 아닙니다.");
  reason(a.kind === "preview" && b.kind === "preview", "두 실행 모두 미리보기여야 합니다.");

  const contextA = a.reproducibility || {};
  const contextB = b.reproducibility || {};
  const queryA = String(a.query ?? a.input_snapshot?.query?.query ?? "");
  const queryB = String(b.query ?? b.input_snapshot?.query?.query ?? "");
  reason(Boolean(contextA.query_fingerprint && contextB.query_fingerprint), "저장된 질의 정보를 확인할 수 없습니다.");
  reason(Boolean(contextA.query_fingerprint && contextA.query_fingerprint === contextB.query_fingerprint), "두 실행의 질의 기록이 서로 다릅니다.");
  reason(Boolean(queryA && queryB), "저장된 질의 문장이 없어 같은 질의인지 확인할 수 없습니다.");
  reason(queryA === queryB, "저장된 질의 문장이 서로 다릅니다.");

  const indexA = String(contextA.index || "");
  const indexB = String(contextB.index || "");
  reason(Boolean(indexA && indexB), "요청한 인덱스 이름이 기록되지 않았습니다.");
  reason(Boolean(indexA && indexA === indexB), "요청한 인덱스 이름이 서로 다릅니다.");
  const uuids = (identity) => {
    if (!identity || identity.available !== true || !Array.isArray(identity.uuids) || !identity.uuids.length) return null;
    const values = identity.uuids.map((item) => [String(item?.index || ""), String(item?.uuid || "")]);
    if (values.some(([name, uuid]) => !name || !uuid)) return null;
    return JSON.stringify(values.sort((left, right) => `${left[0]}\u001f${left[1]}`.localeCompare(`${right[0]}\u001f${right[1]}`)));
  };
  const uuidA = uuids(contextA.index_identity);
  const uuidB = uuids(contextB.index_identity);
  reason(Boolean(uuidA && uuidB), "같은 인덱스인지 확인할 정보가 부족합니다.");
  reason(Boolean(uuidA && uuidB && uuidA === uuidB
    && contextA.index_identity.requested_index === indexA
    && contextB.index_identity.requested_index === indexB), "두 실행이 같은 인덱스에서 수행됐는지 확인할 수 없습니다.");

  reason(Boolean(contextA.mapping_fingerprint && contextB.mapping_fingerprint), "필드 구성을 확인할 수 없습니다.");
  reason(Boolean(contextA.mapping_fingerprint && contextA.mapping_fingerprint === contextB.mapping_fingerprint), "두 실행의 필드 구성이 서로 다릅니다.");
  reason(Boolean(contextA.filters_fingerprint && contextB.filters_fingerprint), "검색 필터 기록을 확인할 수 없습니다.");
  reason(Boolean(contextA.filters_fingerprint && contextA.filters_fingerprint === contextB.filters_fingerprint), "두 실행의 검색 필터가 서로 다릅니다.");

  const settingsA = a.settings || {};
  const settingsB = b.settings || {};
  for (const [key, label] of [["mode", "검색 방식"], ["size", "화면 표시 개수"], ["candidate_size", "후보 검색 개수"]]) {
    const valueA = settingsA[key];
    const valueB = settingsB[key];
    const present = valueA != null && valueB != null && String(valueA) !== "" && String(valueB) !== "";
    reason(present, `${label} 기록이 없어 같은 조건인지 확인할 수 없습니다.`);
    reason(present && String(valueA) === String(valueB), `${label}이 서로 다릅니다.`);
  }

  reason(first.completeness?.truncated === false && second.completeness?.truncated === false, "저장 결과가 일부 잘렸거나 전체를 확인할 수 없습니다.");
  const baselineA = normalizePreviewRows(a.output_snapshot?.baseline);
  const baselineB = normalizePreviewRows(b.output_snapshot?.baseline);
  reason(baselineA.valid && baselineB.valid, "기준선의 문서 ID나 순위를 확인할 수 없습니다.");
  reason(baselineA.rows.every((row) => /^[a-f0-9]{64}$/i.test(row.sourceHash)) && baselineB.rows.every((row) => /^[a-f0-9]{64}$/i.test(row.sourceHash)), "기준선 문서의 저장 당시 내용을 비교할 정보가 부족합니다.");
  const exactBaseline = (rows) => JSON.stringify(rows.map((row) => [row.index, row.id, row.rank, row.sourceHash]));
  reason(baselineA.valid && baselineB.valid && exactBaseline(baselineA.rows) === exactBaseline(baselineB.rows), "두 실행의 기준선 결과 ID와 순위가 다릅니다.");

  const candidatesA = normalizePreviewRows(a.output_snapshot?.candidate, true);
  const candidatesB = normalizePreviewRows(b.output_snapshot?.candidate, true);
  reason(candidatesA.valid && candidatesB.valid, "개념 적용 결과 중 ID, 순위 또는 고정 힌트가 올바르지 않은 행이 있습니다.");
  const outputCountMatches = (artifact, normalizedBaseline, normalizedCandidate) => {
    const count = artifact.completeness?.output_entry_count;
    return Number.isInteger(count) && count >= 0 && count === normalizedBaseline.rows.length + normalizedCandidate.rows.length;
  };
  reason(outputCountMatches(first, baselineA, candidatesA) && outputCountMatches(second, baselineB, candidatesB), "저장 결과의 일부를 확인할 수 없습니다.");
  let hashMismatch = false;
  const hashesByKey = (rows) => rows.reduce((map, row) => {
    if (!map.has(row.key)) map.set(row.key, []);
    map.get(row.key).push(row.sourceHash);
    return map;
  }, new Map());
  const allRowsA = hashesByKey([...baselineA.rows, ...candidatesA.rows]);
  const allRowsB = hashesByKey([...baselineB.rows, ...candidatesB.rows]);
  for (const [key, rowA] of allRowsA) {
    const rowB = allRowsB.get(key);
    if (!rowB) continue;
    if (rowA.some((hashA) => !/^[a-f0-9]{64}$/i.test(hashA))
        || rowB.some((hashB) => !/^[a-f0-9]{64}$/i.test(hashB))
        || rowA.some((hashA) => rowB.some((hashB) => hashA !== hashB))) hashMismatch = true;
  }
  reason(!hashMismatch, "두 실행에 함께 나타난 문서의 저장 당시 내용이 다르거나 확인할 수 없습니다.");
  return { comparable: reasons.length === 0, reasons, candidatesA, candidatesB };
}

function renderCandidateMovement(first, second, requirements) {
  const aMap = new Map(requirements.candidatesA.rows.filter((row) => row.rank != null).map((row) => [row.key, row]));
  const bMap = new Map(requirements.candidatesB.rows.filter((row) => row.rank != null).map((row) => [row.key, row]));
  const keys = [...aMap.keys(), ...[...bMap.keys()].filter((key) => !aMap.has(key))];
  if (!keys.length) return '<p class="run-detail-empty">두 저장 결과에 비교할 일반 검색 결과가 없습니다.</p>';
  const visible = keys.slice(0, 20);
  const rows = visible.map((key) => {
    const rowA = aMap.get(key);
    const rowB = bMap.get(key);
    const row = rowA || rowB;
    let movement;
    if (!rowA) movement = "두 번째 저장 상위-N에만 포함 · 전체 인덱스에서 없다는 뜻은 아닙니다.";
    else if (!rowB) movement = "첫 번째 저장 상위-N에만 포함 · 전체 인덱스에서 없다는 뜻은 아닙니다.";
    else if (rowA.rank === rowB.rank) movement = `${rowA.rank}위 → ${rowB.rank}위 · 순위 변화 없음`;
    else {
      const change = rowA.rank - rowB.rank;
      movement = `${rowA.rank}위 → ${rowB.rank}위 · ${Math.abs(change)}계단 ${change > 0 ? "상승" : "하락"}`;
    }
    const fromTo = rowA && rowB ? `${rowA.rank}위 → ${rowB.rank}위` : (rowA ? `첫 번째 ${rowA.rank}위 → 두 번째 저장 상위-N에는 없음` : `첫 번째 저장 상위-N에는 없음 → 두 번째 ${rowB.rank}위`);
    return `<li><code>${escapeHtml(row.index)} / ${escapeHtml(row.id)}</code><span>${escapeHtml(fromTo)}</span><small>${escapeHtml(movement)}</small></li>`;
  }).join("");
  return `<ol class="saved-preview-movements">${rows}</ol>${keys.length > visible.length ? `<p class="run-detail-empty">그 밖의 후보 비교 ${keys.length - visible.length}개</p>` : ""}`;
}

function isPlainRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function canonicalSavedValue(value) {
  if (Array.isArray(value)) return value.map(canonicalSavedValue);
  if (isPlainRecord(value)) {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalSavedValue(value[key])]));
  }
  return value;
}

function savedConfigValue(run, path) {
  let value = run;
  for (const key of path) {
    if (!isPlainRecord(value) || !Object.prototype.hasOwnProperty.call(value, key)) return { present: false };
    value = value[key];
  }
  return { present: true, value };
}

function savedConfigSnapshot(run) {
  const snapshot = run?.input_snapshot;
  const concept = isPlainRecord(snapshot) && snapshot.concept;
  const corpus = isPlainRecord(concept) && concept.corpus;
  const settings = run?.settings;
  if (!isPlainRecord(run) || !isPlainRecord(snapshot) || !isPlainRecord(concept)
      || !isPlainRecord(corpus) || !isPlainRecord(settings)) return null;
  const has = (record, key) => Object.prototype.hasOwnProperty.call(record, key);
  const isStringList = (value) => Array.isArray(value) && value.every((item) => typeof item === "string");
  const isRelatedList = (value) => Array.isArray(value) && value.every((item) => isPlainRecord(item)
    && typeof item.term === "string"
    && (!has(item, "relation") || typeof item.relation === "string")
    && (!has(item, "weight") || typeof item.weight === "number"));
  const isFilterList = (value) => Array.isArray(value) && value.every((item) => isPlainRecord(item)
    && typeof item.field === "string" && has(item, "value"));
  const fieldTypes = [
    [concept, "name", (value) => typeof value === "string"],
    [concept, "description", (value) => typeof value === "string"],
    [concept, "aliases", isStringList],
    [concept, "related", isRelatedList],
    [concept, "excluded_terms", isStringList],
    [concept, "filters", isFilterList],
    [corpus, "text_fields", isStringList],
    [corpus, "title_field", (value) => typeof value === "string"],
    [corpus, "filter_fields", isStringList],
    [settings, "field_boosts", (value) => isPlainRecord(value) && Object.values(value).every((item) => typeof item === "number")],
    ...["concept_weight", "related_weight", "size", "candidate_size"].map((key) => [settings, key, (value) => typeof value === "number"]),
    [settings, "mode", (value) => typeof value === "string"],
  ];
  if (fieldTypes.some(([record, key, valid]) => has(record, key) && !valid(record[key]))) return null;
  if (has(run, "effective_filters") && !isFilterList(run.effective_filters)) return null;
  return { run };
}

function clipSavedConfigText(value, limit = 140) {
  const text = String(value);
  return text.length > limit ? `${text.slice(0, limit)}… (표시 제한)` : text;
}

function savedConfigDisplay(value, kind = "value") {
  if (!value.present) return "기록 없음";
  const itemText = (item) => {
    if (item === null) return "null";
    if (typeof item === "string") return item === "" ? "빈 값" : item;
    if (typeof item === "number" || typeof item === "boolean") return String(item);
    try {
      return JSON.stringify(canonicalSavedValue(item)) ?? "표시할 수 없는 기록";
    } catch {
      return "표시할 수 없는 기록";
    }
  };
  let display;
  if (kind === "list" || kind === "related" || kind === "filters" || kind === "boosts") {
    const items = value.value;
    if (kind === "list") display = items.length ? items.map(itemText).join(", ") : "비어 있음";
    if (kind === "related") display = items.length
      ? items.map((item) => `${itemText(item.term)} (관계: ${Object.prototype.hasOwnProperty.call(item, "relation") ? itemText(item.relation) : "기록 없음"}, 가중치: ${Object.prototype.hasOwnProperty.call(item, "weight") ? itemText(item.weight) : "기록 없음"})`).join("; ")
      : "비어 있음";
    if (kind === "filters") display = items.length
      ? items.map((item) => `${itemText(item.field)} = ${itemText(item.value)}`).join("; ")
      : "비어 있음";
    if (kind === "boosts") {
      const keys = Object.keys(items).sort();
      display = keys.length ? keys.map((key) => `${key}: ${itemText(items[key])}`).join(", ") : "비어 있음";
    }
    if (display === "비어 있음") return `[${display}]`;
    return clipSavedConfigText(display);
  }
  if (value.value === "") return "빈 값";
  return clipSavedConfigText(itemText(value.value));
}

function renderSavedConfigDiff(firstArtifact, secondArtifact) {
  const first = savedConfigSnapshot(firstArtifact?.run);
  const second = savedConfigSnapshot(secondArtifact?.run);
  const caveat = "저장된 설정의 관찰 차이이며, 차이가 결과의 원인이나 품질 개선을 증명하지 않습니다.";
  if (!first || !second) {
    return `<section class="saved-preview-config-diff"><h4>저장된 검색 설정 차이</h4><p>설정 기록을 비교할 수 없습니다.</p><p>${caveat}</p></section>`;
  }
  const fields = [
    ["개념 이름", ["input_snapshot", "concept", "name"]],
    ["설명 · 확장 검색어", ["input_snapshot", "concept", "description"]],
    ["다른 표현", ["input_snapshot", "concept", "aliases"], "list"],
    ["관련 용어 · 관계 · 가중치", ["input_snapshot", "concept", "related"], "related"],
    ["제외 표현", ["input_snapshot", "concept", "excluded_terms"], "list"],
    ["검색 본문 필드", ["input_snapshot", "concept", "corpus", "text_fields"], "list"],
    ["표시 제목 필드", ["input_snapshot", "concept", "corpus", "title_field"]],
    ["사용 가능한 필터 필드", ["input_snapshot", "concept", "corpus", "filter_fields"], "list"],
    ["저장 기본 필터", ["input_snapshot", "concept", "filters"], "filters"],
    ["개념 가중치", ["settings", "concept_weight"]],
    ["관련 용어 가중치", ["settings", "related_weight"]],
    ["필드별 가중치", ["settings", "field_boosts"], "boosts"],
    ["검색 방식", ["settings", "mode"]],
    ["화면 표시 개수", ["settings", "size"]],
    ["후보 검색 개수", ["settings", "candidate_size"]],
    ["실제 적용 필터", ["effective_filters"]],
  ];
  const changed = [];
  let incomplete = false;
  for (const [label, path, kind] of fields) {
    const a = savedConfigValue(first.run, path);
    const b = savedConfigValue(second.run, path);
    if (!a.present || !b.present) incomplete = true;
    const canonicalA = a.present ? JSON.stringify(canonicalSavedValue(a.value)) : "<absent>";
    const canonicalB = b.present ? JSON.stringify(canonicalSavedValue(b.value)) : "<absent>";
    if (canonicalA === canonicalB) continue;
    changed.push(`<li><strong>${escapeHtml(label)}</strong><span>첫 번째 · ${escapeHtml(savedConfigDisplay(a, kind))}</span><span>두 번째 · ${escapeHtml(savedConfigDisplay(b, kind))}</span></li>`);
  }
  const visible = changed.slice(0, 20);
  const omitted = changed.length - visible.length;
  const content = changed.length
    ? `<ul>${visible.join("")}</ul>${omitted ? `<p>추가 차이 ${omitted}개는 표시 한도로 생략했습니다.</p>` : ""}`
    : '<p>비교 가능한 기록 항목에서 차이가 없습니다.</p>';
  const completeness = incomplete ? "<p>일부 설정은 저장되지 않아 전체 비교가 아닙니다. ‘기록 없음’은 빈 설정과 다릅니다.</p>" : "";
  return `<section class="saved-preview-config-diff"><h4>저장된 검색 설정 차이</h4>${content}${completeness}<p>${caveat}</p></section>`;
}

function renderSavedPreviewComparison(first, second) {
  const requirements = previewRunRequirements(first, second);
  const renderSide = (artifact, sideLabel) => {
    const run = artifact.run;
    const outputs = run.output_snapshot || {};
    const settings = run.settings || {};
    const baseline = Array.isArray(outputs.baseline) ? outputs.baseline : null;
    const candidate = Array.isArray(outputs.candidate) ? outputs.candidate : null;
    const maxRows = 20;
    const requestedTopN = Number.isFinite(Number(settings.size)) && Number(settings.size) > 0 ? Number(settings.size) : null;
    return `<section class="saved-preview-side"><h4>${escapeHtml(sideLabel)} · ${escapeHtml(run.run_id || "실행 ID 미상")}</h4><p><strong>저장 시간</strong> · ${escapeHtml(savedRunTimestamp(run))}</p><p><strong>질의</strong> · ${escapeHtml(run.query || run.input_snapshot?.query?.query || "기록 없음")}</p><p><strong>요청 인덱스</strong> · ${escapeHtml(run.reproducibility?.index || "기록 없음")}</p><p class="saved-preview-topn">저장 당시 상위 ${requestedTopN == null ? "개수 미상" : escapeHtml(requestedTopN)} 결과 ID · 최대 ${maxRows}개 표시</p>${baseline ? renderPreviewSnapshotList("기준선", baseline, { maxRows, displaySize: requestedTopN }) : '<section class="saved-preview-list"><h5>기준선</h5><p class="run-detail-empty">저장된 기준선 목록이 없습니다.</p></section>'}${candidate ? renderPreviewSnapshotList("개념 적용", candidate, { maxRows, allowPins: true, displaySize: requestedTopN }) : '<section class="saved-preview-list"><h5>개념 적용</h5><p class="run-detail-empty">저장된 개념 적용 목록이 없습니다.</p></section>'}</section>`;
  };
  const warning = '<p class="saved-preview-history-warning">두 화면은 각 실행 시점에 저장된 기록입니다. 두 저장 결과에 차이가 있어도 전체 코퍼스가 같았다는 증거는 아니며, 관련도나 검색 품질 판정도 아닙니다.</p>';
  const result = requirements.comparable
    ? `<section class="saved-preview-direct"><h4>개념 적용 결과의 저장 순위 변화</h4><p>두 실행은 같은 질의·필드 구성·검색 방식·필터·후보 및 표시 개수·인덱스·기준선 기록을 공유합니다. 개념 설정 차이를 비교합니다. 결과에만 보이는 문서는 다른 저장 상위-N에 없다는 뜻이며 전체 인덱스에서 없다는 뜻은 아닙니다.</p>${renderCandidateMovement(first, second, requirements)}</section>`
    : `<section class="saved-preview-mismatch"><h4>직접 순위 비교를 표시하지 않았습니다</h4><p>두 기록은 나란히 볼 수 있지만 아래 조건이 달라 순위 이동으로 해석하지 않습니다.</p><ul>${requirements.reasons.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
  return `${warning}${renderSavedConfigDiff(first, second)}<div class="saved-preview-sides">${renderSide(first, "첫 번째 미리보기")}${renderSide(second, "두 번째 미리보기")}</div>${result}`;
}

async function compareSavedPreviews() {
  const selected = $$(".preview-run-compare-select").filter((input) => input.checked);
  const status = $("#saved-preview-selection-status");
  const compareButton = $("#compare-saved-previews");
  const output = $("#saved-preview-comparison");
  if (!status || !compareButton || !output) return;
  if (selected.length !== 2 || selected[0].dataset.conceptId !== selected[1].dataset.conceptId) {
    status.textContent = "같은 개념의 저장 미리보기 두 개를 선택하세요.";
    updateSavedPreviewSelection();
    return;
  }

  compareButton.disabled = true;
  output.innerHTML = '<p class="loading-inline"><i class="spinner"></i> 저장된 두 실행의 기록을 불러옵니다.</p>';
  status.textContent = "저장된 기록을 확인하고 있습니다.";
  try {
    const [first, second] = await Promise.all(selected.map((input) => fetchConceptRunArtifact(input.dataset.conceptId, input.dataset.runId, "preview")));
    output.innerHTML = renderSavedPreviewComparison(first, second);
    status.textContent = "저장된 미리보기 비교를 표시했습니다.";
  } catch (error) {
    output.textContent = "";
    status.textContent = `비교 기록을 불러오지 못했습니다: ${error.message} 다시 시도할 수 있습니다.`;
    showToast(error.message, true);
  } finally {
    updateSavedPreviewSelection(status.textContent);
  }
}

async function exportConceptRun(button) {
  const conceptId = button.dataset.conceptId;
  const runId = button.dataset.runId;
  if (!conceptId || !runId) return showToast("내보낼 실험 기록을 확인할 수 없습니다.", true);

  const status = button.closest(".run-row")?.querySelector(".run-export-status");
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "파일 만드는 중…";
  if (status) status.textContent = "";
  try {
    const result = await fetchConceptRunArtifact(conceptId, runId, button.dataset.runKind || "");
    downloadJson(JSON.stringify(result, null, 2), safeRunExportFilename(runId));
    if (status) status.textContent = "다운로드를 시작했습니다.";
  } catch (error) {
    if (status) status.textContent = `파일을 만들지 못했습니다: ${error.message}`;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function showConceptRunDetails(button) {
  const conceptId = button.dataset.conceptId;
  const runId = button.dataset.runId;
  if (!conceptId || !runId) return showToast("확인할 실험 기록을 찾을 수 없습니다.", true);
  const row = button.closest(".run-row");
  const status = row?.querySelector(".run-export-status");
  const details = row?.querySelector(".run-details-content");
  if (!details) return showToast("실험 결과를 표시할 영역을 찾을 수 없습니다.", true);
  if (!details.hidden) {
    details.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (status) status.textContent = "저장된 상세 결과를 접었습니다.";
    return;
  }

  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "저장 기록 불러오는 중…";
  if (status) status.textContent = "";
  try {
    const artifact = await fetchConceptRunArtifact(conceptId, runId, button.dataset.runKind || "");
    details.innerHTML = renderSavedRunDetails(artifact);
    details.hidden = false;
    button.setAttribute("aria-expanded", "true");
    if (status) status.textContent = "저장된 실험 기록을 표시했습니다.";
  } catch (error) {
    if (status) status.textContent = `저장 기록을 불러오지 못했습니다: ${error.message} 다시 눌러 시도할 수 있습니다.`;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function loadProfileVersions() {
  if (!state.conceptId) return showToast("먼저 개념을 저장하세요.", true);
  try {
    const result = await api("/api/concepts/versions", { concept_id: state.conceptId, limit: 50 });
    state.profileVersions = result.versions || [];
    const select = $("#profile-version-select");
    const previous = select.value;
    select.innerHTML = `<option value="">버전 선택</option>${state.profileVersions.map((version) => `<option value="${escapeHtml(version.version_id)}">v${Number(version.version_number)} · ${escapeHtml(version.created_at || "시간 미상")}</option>`).join("")}`;
    if (state.profileVersions.some((version) => version.version_id === previous)) select.value = previous;
    $("#refresh-profile-versions").disabled = false;
    $("#restore-profile-version").disabled = !state.profileVersions.length;
    $("#export-concept-profile").disabled = !state.profileVersions.length;
    $("#profile-version-status").textContent = `저장된 버전 ${state.profileVersions.length}개 · 복원은 현재 버전을 보존하고 새 버전을 만듭니다.`;
  } catch (error) { $("#profile-version-status").textContent = `버전을 불러오지 못했습니다: ${error.message}`; }
}

async function restoreProfileVersion() {
  const versionId = $("#profile-version-select").value;
  if (!state.conceptId || !versionId) return showToast("복원할 버전을 선택하세요.", true);
  try {
    const result = await api("/api/concepts/restore", { concept_id: state.conceptId, version_id: versionId });
    populateConcept(result.concept || {});
    await loadConcepts();
    await loadProfileVersions();
    await loadConceptRuns();
    $("#profile-version-status").textContent = "선택한 버전의 설정을 새 버전으로 복원했습니다. 다시 검색해 확인하세요.";
    showToast("설정을 복원했습니다. 과거 버전도 기록에 남아 있습니다.");
  } catch (error) { $("#profile-version-status").textContent = `복원하지 못했습니다: ${error.message}`; }
}

async function exportConceptProfile() {
  if (!state.conceptId) return showToast("먼저 개념을 저장하세요.", true);
  const versionId = $("#profile-version-select").value;
  try {
    const result = await api("/api/concepts/export", { connection: getConnection(), concept_id: state.conceptId, ...(versionId ? { version_id: versionId } : {}) });
    downloadJson(JSON.stringify(result, null, 2), `es-rag-profile-v${result.profile?.version_id || "current"}.json`);
    $("#profile-version-status").textContent = "앱 연동용 파일을 만들었습니다. 워크벤치에는 자동 적용하지 않았고, 다른 앱에도 설치하지 않았습니다.";
  } catch (error) { $("#profile-version-status").textContent = `파일을 만들지 못했습니다: ${error.message}`; }
}

async function runEvaluation() {
  if (!state.connected) return;
  const button = $("#evaluate-button");
  setBusy(button, true, "평가 중");
  $("#evaluation-status").innerHTML = '<span class="loading-inline"><i class="spinner"></i> Q01–Q10을 Elasticsearch에서 실행 중</span>';
  try {
    const result = await api("/api/evaluate", requestPayload({ boosts: readBoosts(), mode: $("#search-mode").value, rank_constant: Number($("#rank-constant").value) }));
    state.lastEvaluation = result.metrics;
    $("#evaluation-status").textContent = "평가 완료 · 동일한 10개 정답 질의 사용";
    $("#evaluation-results").innerHTML = renderMetrics(result.metrics, "현재 프로필");
  } catch (error) {
    $("#evaluation-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.innerHTML = "평가 실행";
    button.disabled = !state.connected;
  }
}

function renderMetrics(metrics, label) {
  const recallMet = metrics.recall_at_5 >= metrics.target.recall_at_5;
  const mrrMet = metrics.mrr_at_5 >= metrics.target.mrr_at_5;
  return `<div class="metrics-heading"><h3>${escapeHtml(label)}</h3><span class="target-state ${metrics.target_met ? "pass" : "fail"}">${metrics.target_met ? "● 1차 목표 달성" : "● 목표 미달"}</span></div>
    <div class="metric-grid">
      <div class="metric-card ${recallMet ? "pass" : "fail"}"><span>Recall@5</span><strong>${formatNumber(metrics.recall_at_5)}</strong><small>목표 ≥ ${formatNumber(metrics.target.recall_at_5)}</small></div>
      <div class="metric-card ${mrrMet ? "pass" : "fail"}"><span>MRR@5</span><strong>${formatNumber(metrics.mrr_at_5)}</strong><small>목표 ≥ ${formatNumber(metrics.target.mrr_at_5)}</small></div>
      <div class="metric-card"><span>Precision@5</span><strong>${formatNumber(metrics.precision_at_5)}</strong><small>평균 질의 기준</small></div>
      <div class="metric-card"><span>nDCG@5</span><strong>${formatNumber(metrics.ndcg_at_5)}</strong><small>${metrics.retrieved_relevant_count}/${metrics.expected_relevant_count} 정답 회수</small></div>
    </div>${renderEvaluationTable(metrics.queries)}`;
}

function renderEvaluationTable(rows) {
  return `<div class="eval-table-wrap"><table class="eval-table"><thead><tr><th>질의</th><th>정답 키</th><th>Top 5 순위</th><th>Recall</th><th>RR</th></tr></thead><tbody>${rows.map((row) => `
    <tr><td class="query-cell"><span class="query-id">${escapeHtml(row.query_id)}</span><br>${escapeHtml(row.query)}</td>
      <td><div class="key-list">${row.expected.map((key) => `<span class="meta-chip">${escapeHtml(key)}</span>`).join("")}</div><small>회수: ${row.found.map(escapeHtml).join(", ") || "없음"}</small></td>
      <td><div class="key-list">${row.ranked.map((key, index) => `<span class="meta-chip">${index + 1}. ${escapeHtml(key)}</span>`).join("") || "—"}</div></td>
      <td class="${row.recall_at_5 >= 1 ? "metric-good" : "metric-warn"}">${formatNumber(row.recall_at_5)}</td><td class="${row.reciprocal_rank_at_5 > 0 ? "metric-good" : "metric-warn"}">${formatNumber(row.reciprocal_rank_at_5)}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

async function runTune() {
  if (!state.connected) return;
  const button = $("#tune-button");
  const passes = Number($("#tune-passes").value);
  setBusy(button, true, `최대 ${passes}회 탐색 중`);
  $("#evaluation-status").innerHTML = `<span class="loading-inline"><i class="spinner"></i> ${passes}회 좌표 탐색 · Elasticsearch 질의를 반복 실행 중. 완료까지 잠시 걸릴 수 있습니다.</span>`;
  try {
    const result = await api("/api/tune", requestPayload({ boosts: readBoosts(), passes }));
    state.bestProfile = result.best.profile;
    const baseline = result.baseline.metrics;
    const best = result.best.metrics;
    $("#evaluation-status").textContent = result.target_met ? "목표 점수에 도달했습니다." : "탐색이 끝났습니다. 현재 최선의 프로필과 남은 실패 질의를 확인하세요.";
    const changed = Object.keys(DEFAULT_PROFILE).filter((field) => Number(result.best.profile[field]) !== Number(result.baseline.profile[field]));
    const profileHtml = Object.entries(result.best.profile).map(([field, value]) => `<span class="profile-chip ${changed.includes(field) ? "changed" : ""}"><span>${escapeHtml(field)}</span><strong>${escapeHtml(value)}</strong></span>`).join("");
    const roundsHtml = result.rounds.map((round) => `<div class="candidate-summary">탐색 ${round.pass}: ${round.candidate_count}개 후보 · 최고 점수 <strong>${formatNumber(round.best_candidate_score)}</strong> · ${round.improved ? "개선" : "개선 없음"}</div>`).join("");
    const exportData = JSON.stringify({
      title: "ES RAG BM25 tuned profile",
      created_at: new Date().toISOString(),
      index: $("#index-name").value.trim(),
      profile: result.best.profile,
      baseline_metrics: baseline,
      tuned_metrics: best,
      target_met: result.target_met,
      method: result.method,
    }, null, 2);
    $("#evaluation-results").innerHTML = `<div class="tuning-result card"><div class="tuning-result-head"><h3>튜닝 결과</h3><button id="apply-best-profile" class="button button-secondary button-small">최선 프로필 적용</button></div>
      ${renderMetrics(baseline, "튜닝 전")}
      ${renderMetrics(best, "탐색 후 최선")}
      <div class="profile-diff">${profileHtml}</div>${roundsHtml}
      <div class="boost-actions"><button id="download-tuned-profile" class="text-button">튜닝 결과 JSON 다운로드</button></div>
    </div>`;
    $("#apply-best-profile").addEventListener("click", () => {
      renderBoostInputs(result.best.profile);
      showToast("탐색 후 최선 프로필을 검색 실험에 적용했습니다.");
    });
    $("#download-tuned-profile").addEventListener("click", () => downloadJson(exportData, "es-rag-tuned-profile.json"));
  } catch (error) {
    $("#evaluation-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.innerHTML = "튜닝 시작";
    button.disabled = !state.connected;
  }
}

function downloadJson(contents, filename) {
  const blob = new Blob([contents], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function exportCurrentProfile() {
  const profile = {
    title: "ES RAG BM25 profile",
    created_at: new Date().toISOString(),
    index: $("#index-name").value.trim(),
    profile: readBoosts(),
    evaluation: state.lastEvaluation,
  };
  downloadJson(JSON.stringify(profile, null, 2), "es-rag-bm25-profile.json");
}

function addFilter() {
  const field = $("#filter-field").value;
  const value = $("#filter-value").value.trim();
  if (!value) return showToast("필터 값을 입력하세요.", true);
  state.filters.push({ field, value });
  $("#filter-value").value = "";
  renderFilters();
}

function fillConceptExample() {
  state.conceptId = null;
  clearVectorCandidatePool("");
  clearDocumentLocatorState();
  $("#saved-concepts").value = "";
  $("#concept-name").value = "요청 시간 초과 후 복구";
  $("#concept-description").value = "요청이 시간 초과된 뒤 재시도나 대기 조정으로 복구되는 상황";
  $("#concept-aliases").value = "timeout retry, 요청 재시도";
  $("#concept-exclusions").value = "연결 설정 안내";
  $("#guided-query-text").value = "요청 시간 초과 뒤 재시도가 필요한 경우";
  $("#related-terms").replaceChildren(); addRelatedTerm("지수형 대기", "재시도 방식", 1.2); addRelatedTerm("keepalive", "연결 유지", 0.8);
  $("#concept-queries").replaceChildren(); addConceptQuery("요청 시간 초과 뒤 재시도가 필요한 경우", "train"); addConceptQuery("응답 지연 이후 연결을 다시 살리는 방법", "validation");
  showToast("예시를 채웠습니다. 필드와 표현을 인덱스에 맞게 조정하세요.");
}

function init() {
  try {
    const savedUrl = localStorage.getItem("es-rag-url") || "";
    $("#es-url").value = safeEndpoint(savedUrl) || $("#es-url").value;
    if (savedUrl && !safeEndpoint(savedUrl)) localStorage.removeItem("es-rag-url");
    $("#index-name").value = localStorage.getItem("es-rag-index") || $("#index-name").value;
    $("#auth-type").value = localStorage.getItem("es-rag-auth-type") || "none";
  } catch { /* Private browsing can disable localStorage. */ }
  try { state.locale = localStorage.getItem("es-rag-locale") === "en" ? "en" : "ko"; } catch {}
  applyLocale(state.locale);
  renderConnectionProfiles();
  renderBoostInputs();
  addRelatedTerm();
  $("#concept-index-badge").textContent = $("#index-name").value.trim();
  $("#basic-fields").classList.toggle("hidden", $("#auth-type").value !== "basic");
  $("#api-key-fields").classList.toggle("hidden", $("#auth-type").value !== "api_key");
  $("#server-version").textContent = "ready";
  fetch("/api/health", { cache: "no-store" }).then((response) => response.json()).then((result) => { $("#server-version").textContent = `v${result.version}`; }).catch(() => {});
  refreshCodebaseStatus();
  loadEmbeddingProfiles();

  $$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  activateTab("concept-panel");
  bindKnowledgeControls();
  $("#ui-language").addEventListener("change", () => {
    applyLocale($("#ui-language").value);
    loadEmbeddingProfiles();
    try { localStorage.setItem("es-rag-locale", state.locale); } catch {}
  });
  $("#save-connection-profile").addEventListener("click", saveConnectionProfile);
  $("#load-connection-profile").addEventListener("click", loadConnectionProfile);
  $("#delete-connection-profile").addEventListener("click", deleteConnectionProfile);
  $("#connection-profile-select").addEventListener("change", () => { $("#delete-connection-profile").disabled = !$("#connection-profile-select").value; });
  $("#auth-type").addEventListener("change", () => {
    $("#basic-fields").classList.toggle("hidden", $("#auth-type").value !== "basic");
    $("#api-key-fields").classList.toggle("hidden", $("#auth-type").value !== "api_key");
    saveNonSecretPreferences();
    resetAiIfScopeChanged();
  });
  $("#auth-type").addEventListener("change", advanceConnectionGeneration);
  ["#es-user", "#es-password", "#es-api-key"].forEach((selector) => $(selector).addEventListener("change", () => { state.aiConnectionEpoch = Number(state.aiConnectionEpoch || 0) + 1; resetAiIfScopeChanged(); }));
  ["#es-url", "#es-user", "#es-password", "#es-api-key"].forEach((selector) => {
    $(selector).addEventListener("input", advanceConnectionGeneration);
    $(selector).addEventListener("change", advanceConnectionGeneration);
  });
  $("#connect-button").addEventListener("click", connect);
  $("#refresh-indices").addEventListener("click", connect);
  $("#load-sample-button").addEventListener("click", loadSample);
  $("#vectorize-button").addEventListener("click", vectorizeIndex);
  $("#index-name").addEventListener("change", () => {
    saveNonSecretPreferences();
    $("#concept-index-badge").textContent = $("#index-name").value.trim();
    renderSearchReadiness();
    renderSampleOnboarding();
    resetAiSession(true);
    if (state.connected) connect();
  });
  $("#index-name").addEventListener("input", renderSampleOnboarding);
  $("#es-url").addEventListener("change", () => {
    saveNonSecretPreferences();
    resetAiSession(true);
    setConnected(false);
    setConnectionStatus("idle", "새 주소에서 다시 연결하세요");
  });
  $("#search-button").addEventListener("click", runSearch);
  $("#embedding-profile-select").addEventListener("change", () => {
    state.sharedProfileId = $("#embedding-profile-select").value;
    $("#embedding-profile-select").dataset.touched = "true";
    renderEmbeddingProfileDetails();
    clearVectorCandidatePool("공유 임베딩 프로필이 바뀌어 이전 후보를 지웠습니다. 새 프로필과 색인 recipe를 확인하세요.");
    if (state.connected) connect();
    else renderSearchReadiness();
  });
  $("#knowledge-vector-profile-select").addEventListener("change", () => {
    state.privateProfileId = $("#knowledge-vector-profile-select").value;
    state.privateProfileTouched = true;
    renderEmbeddingProfileDetails();
    $("#knowledge-es-status").textContent = "선택한 프로필은 다음 명시적 벡터 동기화에서 사용됩니다. 기존 generation은 그대로 유지됩니다.";
  });
  $("#search-mode").addEventListener("change", () => {
    $("#rank-constant-wrap").classList.toggle("hidden", !["hybrid", "code_rag"].includes($("#search-mode").value));
    renderSearchReadiness();
  });
  $("#sample-onboarding-open").addEventListener("click", () => {
    const details = $(".sample-maintenance");
    const target = $("#load-sample-button");
    if (!details || !target || target.disabled) return;
    details.open = true;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("[data-open-embedding-setup]").addEventListener("click", () => {
    const details = $(".sample-maintenance");
    const target = $("#embedding-status");
    if (!details || !target) return;
    details.open = true;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("#search-query").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) runSearch();
  });
  $("#filter-toggle").addEventListener("click", () => $("#filter-row").classList.toggle("hidden"));
  $("#add-filter").addEventListener("click", addFilter);
  $("#filter-value").addEventListener("keydown", (event) => { if (event.key === "Enter") addFilter(); });
  $("#active-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-filter]");
    if (!button) return;
    state.filters.splice(Number(button.dataset.removeFilter), 1);
    renderFilters();
  });
  $("#reset-boosts").addEventListener("click", () => { renderBoostInputs(); showToast("기본 가중치로 복원했습니다."); });
  $("#export-profile").addEventListener("click", exportCurrentProfile);
  $("#search-results").addEventListener("click", (event) => {
    const askAi = event.target.closest("[data-stage-ai-result]");
    const explain = event.target.closest("[data-explain]");
    const open = event.target.closest("[data-open-document]");
    if (askAi) stageAiResultContext(askAi);
    if (explain) explainHit(explain);
    if (open) openDocument(open);
  });
  $("#ai-coach").addEventListener("click", (event) => {
    if (event.target.closest("[data-clear-ai-staged-context]")) {
      state.stagedAiResultContext = null;
      $("#ai-result-stage-status").textContent = "";
      renderAiContextReadouts();
    }
    if (event.target.closest("[data-clear-ai-retry-context]")) {
      state.aiLastContext = null;
      state.aiLastMessage = "";
      $("#ai-retry").disabled = true;
      renderAiContextReadouts();
    }
  });
  $("#evaluate-button").addEventListener("click", runEvaluation);
  $("#tune-button").addEventListener("click", runTune);
  $("#chunk-size").addEventListener("input", renderChunkPreview);
  $("#chunk-overlap").addEventListener("input", renderChunkPreview);
  $("#chunk-field-selectors").addEventListener("change", renderChunkPreview);
  $("#refresh-schema").addEventListener("click", loadCorpusSchema);
  $("#save-concept").addEventListener("click", saveConcept);
  $("#fill-concept-example").addEventListener("click", fillConceptExample);
  $("#new-concept").addEventListener("click", () => { resetAiSession(true); state.conceptId = null; populateConcept({ corpus: { index: $("#index-name").value.trim() } }); $("#concept-name").focus(); });
  $("#load-concept").addEventListener("click", () => {
    const concept = state.concepts.find((item) => item.id === $("#saved-concepts").value);
    if (!concept) return showToast("불러올 개념을 선택하세요.", true);
    resetAiSession(true);
    const index = concept.corpus?.index || $("#index-name").value.trim();
    const changedIndex = $("#index-name").value.trim() !== index;
    $("#index-name").value = index; saveNonSecretPreferences(); $("#concept-index-badge").textContent = index;
    Promise.resolve(changedIndex && state.connected ? loadCorpusSchema() : null).then(async () => {
      populateConcept(concept);
      refreshTuneMissHandoffs();
      await loadProfileVersions();
      showToast(`‘${concept.name}’ 개념을 불러왔습니다.`);
    });
  });
  $("#related-terms").addEventListener("click", (event) => { const button = event.target.closest(".related-remove"); if (button) { button.closest(".related-row").remove(); clearVectorCandidatePool("개념 표현이 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요."); } });
  $("#related-terms").addEventListener("input", (event) => { if (event.target.matches(".related-term, .related-relation, .related-weight")) event.target.setAttribute("aria-label", event.target.closest(".related-row").querySelector(".related-term").value || "함께 볼 표현"); });
  $("#add-related-term").addEventListener("click", () => { addRelatedTerm(); clearVectorCandidatePool("개념 표현이 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요."); });
  $("#add-concept-query").addEventListener("click", () => { addConceptQuery(); clearVectorCandidatePool("저장 질의가 바뀌었습니다. 같은 질의로 새 BM25 비교를 실행하세요."); refreshTuneMissHandoffs(); });
  $("#concept-queries").addEventListener("click", (event) => { const button = event.target.closest(".query-remove"); if (button) { button.closest(".concept-query-row").remove(); clearVectorCandidatePool("저장 질의가 바뀌었습니다. 같은 질의로 새 BM25 비교를 실행하세요."); refreshQueryChoices(); refreshInformationNeedSuggestions(); refreshTuneMissHandoffs(); } });
  $("#concept-queries").addEventListener("input", (event) => {
    refreshQueryChoices();
    if (event.target.matches(".saved-query-information-need")) refreshInformationNeedSuggestions();
  });
  $("#concept-text-fields").addEventListener("change", () => renderConceptFieldBoosts());
  $("#concept-query-select").addEventListener("change", () => {
    chooseQuery();
    updateInformationNeedPreviewAction();
    clearVectorCandidatePool("질의 선택이 바뀌었습니다. 새 질의로 ‘결과 비교’를 먼저 실행하세요.");
  });
  $("#concept-query").addEventListener("input", () => {
    const selected = $("#concept-query-select").value;
    const saved = [...$("#concept-queries").querySelectorAll(".concept-query-row")].find((row) => row.dataset.queryId === selected)?.querySelector(".saved-query-text").value.trim();
    if (selected && saved !== $("#concept-query").value.trim()) $("#concept-query-select").value = "";
    clearVectorCandidatePool("질의 문구가 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요.");
  });
  $("#concept-preview").addEventListener("click", runConceptPreview);
  $("#information-need-preview").addEventListener("click", runInformationNeedPreview);
  $("#concept-vector-candidates").addEventListener("click", loadVectorCandidates);
  $("#concept-mode-comparison").addEventListener("click", compareSavedQueryModes);
  $("#concept-mode-comparison-group").addEventListener("click", compareSavedQueryGroupModes);
  $("#concept-query").addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) runConceptPreview(); });
  $("#concept-preview-results").addEventListener("click", (event) => { const button = event.target.closest(".save-judgment"); if (button) saveJudgment(button); });
  $("#concept-preview-results").addEventListener("click", (event) => {
    const button = event.target.closest(".locate-document-cta");
    if (!button) return;
    const input = $("#locate-document-text");
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.focus({ preventScroll: true });
  });
  $("#concept-vector-results").addEventListener("click", (event) => { const button = event.target.closest(".save-judgment"); if (button) saveJudgment(button); });
  $("#manual-document-result").addEventListener("click", (event) => { const button = event.target.closest(".save-judgment"); if (button) saveJudgment(button); });
  $("#locate-document-button").addEventListener("click", locateManualDocument);
  $("#locate-document-text").addEventListener("input", clearDocumentLocatorState);
  $("#locate-document-text").addEventListener("keydown", (event) => { if (event.key === "Enter") locateManualDocument(); });
  $("#locate-document-results").addEventListener("click", (event) => { const button = event.target.closest(".locator-select"); if (button) selectLocatedDocument(button.dataset.documentIndex, button.dataset.documentId); });
  $("#fetch-manual-document").addEventListener("click", fetchManualDocument);
  $("#diagnose-manual-document").addEventListener("click", diagnoseManualDocument);
  $("#manual-document-id").addEventListener("input", () => { state.manualDocumentIndex = null; state.manualDocumentFromLocator = false; updateManualDocumentActions(); });
  $("#manual-query-id").addEventListener("change", updateManualDocumentActions);
  for (const selector of ["#es-url", "#es-user", "#es-password", "#es-api-key"]) {
    $(selector).addEventListener("input", clearDocumentLocatorState);
    $(selector).addEventListener("change", clearDocumentLocatorState);
    $(selector).addEventListener("input", () => clearVectorCandidatePool("연결 설정이 바뀌었습니다. 새로 연결하고 BM25 비교를 실행한 뒤 후보를 다시 불러오세요."));
    $(selector).addEventListener("change", () => clearVectorCandidatePool("연결 설정이 바뀌었습니다. 새로 연결하고 BM25 비교를 실행한 뒤 후보를 다시 불러오세요."));
  }
  $("#auth-type").addEventListener("change", clearDocumentLocatorState);
  $("#auth-type").addEventListener("change", () => clearVectorCandidatePool("연결 설정이 바뀌었습니다. 다시 연결하고 BM25 비교를 실행하세요."));
  $("#index-name").addEventListener("input", clearDocumentLocatorState);
  $("#index-name").addEventListener("input", refreshTuneMissHandoffs);
  $("#index-name").addEventListener("input", () => clearVectorCandidatePool("인덱스가 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요."));
  $("#index-name").addEventListener("change", clearDocumentLocatorState);
  $("#index-name").addEventListener("change", refreshTuneMissHandoffs);
  $("#index-name").addEventListener("change", () => clearVectorCandidatePool("인덱스가 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요."));
  $("#concept-title-field").addEventListener("change", clearDocumentLocatorState);
  $("#concept-text-fields").addEventListener("change", clearDocumentLocatorState);
  $("#add-concept-filter").addEventListener("click", () => {
    const fields = [...$("#concept-filter-fields").querySelectorAll("input:checked")].map((input) => input.value);
    if (!fields.length) return showToast("먼저 사용할 필터 필드를 선택하세요.", true);
    state.conceptFilters.push({ field: fields[0], value: "" }); renderConceptFilterRows();
    clearVectorCandidatePool("필터가 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요.");
  });
  $("#concept-filter-fields").addEventListener("change", renderConceptFilterRows);
  $("#concept-filter-rows").addEventListener("change", (event) => {
    const row = event.target.closest(".concept-filter-row"); if (!row) return;
    const index = Number(event.target.dataset.filterIndex);
    if (event.target.matches(".concept-filter-field")) state.conceptFilters[index].field = event.target.value;
    if (event.target.matches(".concept-filter-value")) state.conceptFilters[index].value = event.target.value;
    renderConceptFilterRows();
    clearVectorCandidatePool("필터가 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요.");
  });
  $("#concept-filter-rows").addEventListener("click", (event) => {
    const button = event.target.closest(".remove-concept-filter"); if (!button) return;
    state.conceptFilters.splice(Number(button.dataset.filterIndex), 1); renderConceptFilterRows();
    clearVectorCandidatePool("필터가 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요.");
  });
  $("#concept-tune").addEventListener("click", runConceptTune);
  $("#saved-concepts").addEventListener("change", refreshTuneMissHandoffs);
  $("#concept-tune-results").addEventListener("click", async (event) => {
    const handoff = event.target.closest(".tune-miss-handoff");
    if (handoff) { handoffTuneMiss(handoff); return; }
    const button = event.target.closest(".apply-tuned-settings"); if (!button) return;
    const settings = state.tunedSettings;
    if (!settings) return showToast("적용할 조정 설정이 없습니다.", true);
    applyTunedSettings(settings);
    if (!await saveConcept()) return;
    if ($("#concept-query").value.trim() || $("#concept-query-select").value) await runConceptPreview();
    else showToast("설정을 저장했습니다. 질의를 선택해 다시 비교하세요.");
  });
  $("#concept-editor").addEventListener("input", () => { clearVectorCandidatePool("개념 설정이 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요."); updateInformationNeedPreviewAction(); updateTuneReadiness(); resetAiIfScopeChanged(); refreshTuneMissHandoffs(); });
  $("#concept-editor").addEventListener("change", () => { clearVectorCandidatePool("개념 설정이 바뀌었습니다. 새 BM25 비교 후 벡터 후보를 다시 불러오세요."); updateInformationNeedPreviewAction(); updateTuneReadiness(); resetAiIfScopeChanged(); refreshTuneMissHandoffs(); });
  ["#es-url", "#auth-type", "#es-user", "#es-password", "#es-api-key"].forEach((selector) => {
    const input = $(selector);
    ["input", "change"].forEach((eventName) => input?.addEventListener(eventName, () => {
      state.informationNeedPreviewGeneration += 1;
      setConnected(false);
      updateInformationNeedPreviewAction();
    }));
  });
  $("#concept-queries").addEventListener("change", (event) => {
    if (event.target.matches(".saved-query-split")) refreshInformationNeedSuggestions();
    updateModeComparisonGroupAction();
    updateTuneReadiness(); resetAiIfScopeChanged();
  });
  $("#quickstart-fields").addEventListener("click", runQuickstart);
  $("#quickstart-preview").addEventListener("change", (event) => { if (event.target.matches("#quickstart-sample-select")) selectQuickstartSample(event.target.value); });
  $("#quickstart-preview").addEventListener("click", (event) => {
    if (event.target.closest("#apply-quickstart-fields")) applyQuickstartFields();
    const handoff = event.target.closest(".quickstart-query-handoff");
    if (handoff) {
      $("#guided-query-text").value = handoff.dataset.starterPhrase || "";
      $("#guided-query-text").focus();
    }
  });
  $("#guided-first-preview").addEventListener("click", runGuidedFirstPreview);
  $("#guided-query-text").addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) runGuidedFirstPreview(); });
  $("#ai-refresh-status").addEventListener("click", loadAiStatus);
  $("#ai-provider").addEventListener("change", async () => { await resetAiSession(true); renderAiProviderStatus(); });
  $("#ai-model").addEventListener("change", () => resetAiSession(true));
  $("#ai-send").addEventListener("click", () => sendAiMessage());
  $("#ai-message").addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendAiMessage(); });
  $("#ai-retry").addEventListener("click", retryAiMessage);
  $("#ai-cancel").addEventListener("click", cancelAiJob);
  $("#ai-reset").addEventListener("click", () => resetAiSession(false));
  $("#ai-draft-review").addEventListener("click", (event) => { if (event.target.closest("#adopt-ai-draft")) adoptAiDraft(); });
  $("#refresh-profile-versions").addEventListener("click", loadProfileVersions);
  $("#restore-profile-version").addEventListener("click", restoreProfileVersion);
  $("#export-concept-profile").addEventListener("click", exportConceptProfile);
  $("#token-preview-prepare").addEventListener("click", prepareTokenPreview);
  $("#profile-version-select").addEventListener("change", () => { $("#restore-profile-version").disabled = !$("#profile-version-select").value; });
  $("#refresh-concept-runs").addEventListener("click", loadConceptRuns);
  $("#concept-runs-list").addEventListener("change", (event) => {
    const input = event.target.closest(".preview-run-compare-select");
    if (!input) return;
    let message = "";
    if (input.checked) {
      const selected = $$(".preview-run-compare-select").filter((item) => item.checked);
      if (selected.length > 2) {
        input.checked = false;
        message = "한 번에 두 개의 미리보기만 비교할 수 있습니다.";
      } else if (selected.some((item) => item.dataset.conceptId !== input.dataset.conceptId)) {
        input.checked = false;
        message = "같은 개념에 저장된 미리보기만 함께 비교할 수 있습니다.";
      }
    }
    const comparison = $("#saved-preview-comparison");
    if (comparison) comparison.replaceChildren();
    updateSavedPreviewSelection(message);
  });
  $("#concept-runs-list").addEventListener("click", (event) => {
    if (event.target.closest("#compare-saved-previews")) { compareSavedPreviews(); return; }
    if (event.target.closest("#clear-saved-preview-selection")) {
      $$(".preview-run-compare-select").forEach((input) => { input.checked = false; input.disabled = false; });
      $("#saved-preview-comparison")?.replaceChildren();
      updateSavedPreviewSelection();
      return;
    }
    const button = event.target.closest(".run-export-button, .run-details-button");
    if (button?.matches(".run-details-button")) showConceptRunDetails(button);
    else if (button) exportConceptRun(button);
  });
  loadAiStatus();
  updateTuneReadiness();
  updateModeComparisonGroupAction();
}

let apiRequest = null;
let cycle44Feature = null;
const browserModulesReady = Promise.all([
  import("/api-client.js"),
  import("/cycle44-positive-target-misses.js"),
]).then(([apiModule, cycle44Module]) => {
  apiRequest = apiModule.createApiClient({
    fetchImpl: (...args) => fetch(...args),
    getCsrfToken: () => state.csrfToken,
    getIdentity: () => state.identity,
    onUnauthorized: () => {
      state.identity = null;
      state.csrfToken = null;
      showAuth("로그인 세션이 만료되었습니다. 다시 로그인하세요.");
      setTimeout(() => location.reload(), 0);
    },
  });
  cycle44Feature = cycle44Module.createCycle44Feature({
    state, $, $$, escapeHtml, collectConcept, updateManualDocumentActions, showToast,
  });
});

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await browserModulesReady;
    bindAuthControls();
    refreshAuthSession();
  } catch (error) {
    showAuth(`브라우저 모듈을 불러오지 못했습니다: ${error.message}`);
  }
});
