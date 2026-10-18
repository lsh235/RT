"use strict";

export function createCycle44Feature({ state, $, $$, escapeHtml, collectConcept, updateManualDocumentActions, showToast }) {
function tuneMissConceptScope(concept) {
  const settings = concept?.settings || {};
  const corpus = concept?.corpus || {};
  return JSON.stringify({
    id: String(concept?.id || ""), name: String(concept?.name || "").trim(), description: String(concept?.description || ""),
    aliases: Array.isArray(concept?.aliases) ? concept.aliases : [],
    related: Array.isArray(concept?.related) ? concept.related : [],
    excluded_terms: Array.isArray(concept?.excluded_terms) ? concept.excluded_terms : [],
    corpus: { index: String(corpus.index || "").trim(), title_field: String(corpus.title_field || "").trim(), text_fields: corpus.text_fields || [], filter_fields: corpus.filter_fields || [] },
    filters: Array.isArray(concept?.filters) ? concept.filters : [],
    settings: {
      mode: String(settings.mode || "bm25").toLowerCase(), size: Number(settings.size), candidate_size: Number(settings.candidate_size),
      concept_weight: Number(settings.concept_weight), related_weight: Number(settings.related_weight), field_boosts: settings.field_boosts || {},
    },
    queries: (Array.isArray(concept?.queries) ? concept.queries : []).map((query) => {
      const informationNeed = String(query?.information_need || "").trim().replace(/\s+/g, " ");
      return { id: String(query?.id || "").trim(), query: String(query?.query || "").trim(), split: String(query?.split || "train"), ...(informationNeed ? { information_need: informationNeed } : {}) };
    }),
  });
}

function tuneMissScopeCurrent() {
  const report = state.tuneMisses;
  if (!report || state.connectionAttemptInProgress) return false;
  try {
    const currentScope = tuneMissConceptScope(collectConcept());
    return currentScope === report.inputConceptScope
      && currentScope === report.requestConceptScope
      && state.conceptId === report.conceptId
      && $("#saved-concepts").value === report.savedConceptSelection
      && state.connectionGeneration === report.connectionGeneration;
  } catch { return false; }
}

function refreshTuneMissHandoffs() {
  const enabled = tuneMissScopeCurrent();
  $$(".tune-miss-handoff").forEach((button) => { button.disabled = !enabled; });
}

function advanceConnectionGeneration() {
  state.connectionGeneration += 1;
  refreshTuneMissHandoffs();
}

function renderTuneMisses(result, sentConcept, connectionGeneration) {
  const input = result?.input_snapshot;
  const output = result?.output_snapshot;
  const inputConcept = input?.concept;
  const inputJudgments = input?.judgments;
  const savedQueries = inputConcept?.queries;
  const settings = result?.settings;
  const k = Number(settings?.size);
  const savedQueryIds = Array.isArray(savedQueries) ? savedQueries.map((query) => String(query?.id ?? "")) : [];
  const savedQueryIdSet = new Set(savedQueryIds);
  const querySnapshotValid = Array.isArray(savedQueries)
    && savedQueries.every((query) => query && query.id != null && ["train", "validation"].includes(query.split))
    && savedQueryIdSet.size === savedQueryIds.length
    && Array.isArray(inputJudgments)
    && !inputJudgments.some((judgment) => judgment && Number.isInteger(judgment.rating) && judgment.rating >= 1 && judgment.rating <= 3
      && (judgment.query_id == null || !savedQueryIdSet.has(String(judgment.query_id))));
  const commonValid = inputConcept && typeof inputConcept === "object" && !Array.isArray(inputConcept)
    && querySnapshotValid && Number.isInteger(k) && k > 0
    && !(Number(input?.judgments_truncated_count) > 0) && !(Number(result?.judged_count) > inputJudgments.length)
    && !result?.output_snapshot_truncated;
  state.tuneMisses = commonValid ? {
    inputConceptScope: tuneMissConceptScope(inputConcept), requestConceptScope: tuneMissConceptScope(sentConcept),
    conceptId: sentConcept.id || null, savedConceptSelection: $("#saved-concepts").value,
    connectionGeneration,
  } : null;
  const split = (label, key, available) => {
    const savedLaneQueryIds = new Set((Array.isArray(savedQueries) ? savedQueries : []).filter((query) => query && query.id != null && query.split === key).map((query) => String(query.id)));
    const lanePositiveLabels = Array.isArray(inputJudgments) ? inputJudgments.filter((judgment) => judgment && judgment.query_id != null
      && savedLaneQueryIds.has(String(judgment.query_id)) && Number.isInteger(judgment.rating) && judgment.rating >= 1 && judgment.rating <= 3) : [];
    const nonEmptyIdentity = (value) => typeof value === "string" && value.trim().length > 0;
    if (lanePositiveLabels.some((judgment) => !nonEmptyIdentity(judgment.document_index) || !nonEmptyIdentity(judgment.document_id))) {
      return `<section class="tune-misses-lane"><h4>${label}</h4><p class="tune-misses-status">긍정 평가 대상의 인덱스 또는 문서 ID가 비어 있어 누락 여부를 판정하지 않았습니다.</p></section>`;
    }
    if (!available) {
      const hasPositiveTargets = lanePositiveLabels.length > 0;
      const status = commonValid && !hasPositiveTargets
        ? `긍정 평가가 없어 아직 비교할 대상이 없습니다. ${key === "validation" ? "검증용 결과 스냅샷도 없습니다." : "결과 스냅샷을 사용할 수 없습니다."}`
        : key === "validation" ? "검증용 스냅샷을 사용할 수 없어 누락 대상을 판정하지 않았습니다." : "학습용 스냅샷이 없거나 형식이 올바르지 않아 누락 대상을 판정하지 않았습니다.";
      return `<section class="tune-misses-lane"><h4>${label}</h4><p class="tune-misses-status">${status}</p></section>`;
    }
    const baseline = output[key].baseline;
    const tuned = output[key].tuned;
    const judgedQueryIds = new Set(inputJudgments.filter((judgment) => judgment && judgment.query_id != null).map((judgment) => String(judgment.query_id)));
    const laneQueries = savedQueries.filter((query) => query && query.id != null && query.split === key && judgedQueryIds.has(String(query.id)));
    const queryIds = [...new Set(laneQueries.map((query) => String(query.id)))];
    if (!queryIds.length) return `<section class="tune-misses-lane"><h4>${label}</h4><p class="tune-misses-status">긍정 평가가 없어 아직 누락 대상을 비교할 수 없습니다. ${key === "validation" ? "검증용으로 저장된 평가 질의가 없어 결과 스냅샷도 없습니다." : "학습용으로 저장된 평가 질의가 없어 결과 스냅샷도 없습니다."}</p></section>`;
    const validRows = (rows) => rows && typeof rows === "object" && !Array.isArray(rows)
      && Object.values(rows).every((list) => Array.isArray(list) && list.every((row) => row && Number.isInteger(row.rank) && row.rank > 0 && row.index != null && row.id != null));
    if (!validRows(baseline) || !validRows(tuned)) return `<section class="tune-misses-lane"><h4>${label}</h4><p class="tune-misses-status">스냅샷의 순위 행 형식이 올바르지 않아 누락 대상을 판정하지 않았습니다.</p></section>`;
    if (queryIds.some((qid) => !Object.prototype.hasOwnProperty.call(baseline, qid) || !Object.prototype.hasOwnProperty.call(tuned, qid))) {
      return `<section class="tune-misses-lane"><h4>${label}</h4><p class="tune-misses-status">${label} 질의의 기본 또는 조정 순위 기록이 빠져 있어 누락 대상을 판정하지 않았습니다.</p></section>`;
    }
    const queryById = new Map(laneQueries.map((query) => [String(query.id), query]));
    const laneQueryIds = new Set(queryIds);
    const judgments = inputJudgments.filter((j) => j && j.query_id != null && laneQueryIds.has(String(j.query_id)) && j.document_index != null && j.document_id != null && Number.isInteger(j.rating) && j.rating >= 1 && j.rating <= 3);
    if (!judgments.length) return `<section class="tune-misses-lane"><h4>${label} · 상위 ${k}개</h4><p class="tune-misses-status">긍정 평가가 없어 아직 비교할 대상이 없습니다. 누락 여부를 확인하려면 이 구분에 저장된 질의에서 문서에 1–3점을 평가하세요.</p></section>`;
    const targets = new Map();
    for (const j of judgments) {
      const key = JSON.stringify([String(j.query_id), String(j.document_index), String(j.document_id)]);
      const prior = targets.get(key);
      if (!prior || Number(j.rating) > Number(prior.rating)) targets.set(key, j);
    }
    const misses = [];
    for (const [identity, judgment] of targets) {
      const qid = String(judgment.query_id);
      const matches = (rows) => rows[qid].find((row) => JSON.stringify([qid, String(row.index), String(row.id)]) === identity);
      if (matches(tuned)?.rank <= k) continue;
      misses.push({ judgment, baseline: matches(baseline) });
    }
    const shown = misses.slice(0, 20);
    const handoffEnabled = tuneMissScopeCurrent();
    const grouped = new Map();
    for (const item of misses) {
      const qid = String(item.judgment.query_id);
      if (!grouped.has(qid)) grouped.set(qid, []);
      grouped.get(qid).push(item);
    }
    const shownItems = new Set(shown);
    const content = shown.length ? `<div class="tune-misses-queries">${[...grouped].map(([qid, items]) => {
      const visibleItems = items.filter((item) => shownItems.has(item));
      if (!visibleItems.length) return "";
      const query = queryById.get(qid);
      return `<section class="tune-misses-query" data-query-id="${escapeHtml(qid)}"><h5>${escapeHtml(qid)} · ${escapeHtml(query?.query || "저장 질의")} · 누락 ${items.length}개${visibleItems.length < items.length ? ` · ${visibleItems.length}개 표시` : ""}</h5><ul class="tune-misses-list">${visibleItems.map(({ judgment, baseline: base }) => `<li data-testid="positive-target-miss"><div><strong>질의 ${escapeHtml(judgment.query_id)}</strong><span>인덱스 ${escapeHtml(judgment.document_index)} · 문서 ${escapeHtml(judgment.document_id)}</span><small>사람이 기록한 긍정 판단 ${Number(judgment.rating)}점 · ${base ? `기본 순위 ${base.rank}` : `저장된 기본 상위 ${k}개에 없음`} · 조정 결과 상위 ${k}개에 없음</small></div><button type="button" data-testid="positive-target-handoff" class="button button-secondary button-small tune-miss-handoff" data-query-id="${escapeHtml(judgment.query_id)}" data-document-index="${escapeHtml(judgment.document_index)}" data-document-id="${escapeHtml(judgment.document_id)}" ${handoffEnabled ? "" : "disabled"}>정확한 문서 진단으로 전달</button></li>`).join("")}</ul></section>`;
    }).join("")}</div>` : `<p class="tune-misses-status">긍정 판단 대상 ${targets.size}개를 확인했으며, 저장된 조정 결과 상위 ${k}개에서 빠진 대상은 없습니다.</p>`;
    return `<section class="tune-misses-lane"><h4>${label} · 상위 ${k}개</h4>${content}${misses.length > 20 ? `<p class="tune-misses-status">그 밖의 누락 대상 ${misses.length - 20}개는 표시하지 않았습니다.</p>` : ""}</section>`;
  };
  const validationAvailable = commonValid && output?.validation && typeof output.validation === "object" && !Array.isArray(output.validation);
  const trainAvailable = commonValid && output?.train && typeof output.train === "object" && !Array.isArray(output.train);
  const train = split("학습용", "train", trainAvailable);
  const validation = validationAvailable ? split("검증용", "validation", true) : split("검증용", "validation", false);
  return `<section class="tune-misses" id="tune-positive-target-misses"><h3>조정 후 상위 결과에서 빠진 긍정 판단 문서</h3><p>저장된 질의 중 각 학습/검증 구분에 속한 질의만 따로 확인합니다. 사람이 긍정(1–3점)으로 평가한 문서가 저장된 조정 결과 상위 ${commonValid ? k : "설정"}개에 있는지 보여줍니다. 이 기록에서 빠졌다는 뜻이며, 인덱스에 문서가 없거나 전체 재현율이 완전하거나 답변이 좋다는 뜻은 아닙니다. 검증용 평가는 설정 조정에 사용되지 않은 별도 확인입니다.</p>${train}${validation}</section>`;
}

function handoffTuneMiss(button) {
  if (!tuneMissScopeCurrent()) { button.disabled = true; return; }
  const queryId = button.dataset.queryId;
  if (![...$("#manual-query-id").options].some((option) => option.value === queryId)) return;
  state.manualDocumentIndex = button.dataset.documentIndex;
  state.manualDocumentFromLocator = true;
  $("#manual-document-id").value = button.dataset.documentId;
  $("#manual-query-id").value = queryId;
  updateManualDocumentActions();
  showToast("문서 ID와 저장 질의를 입력했습니다. 읽기 전용 진단은 직접 실행하세요.");
}

  return { tuneMissConceptScope, tuneMissScopeCurrent, refreshTuneMissHandoffs, advanceConnectionGeneration, renderTuneMisses, handoffTuneMiss };
}
