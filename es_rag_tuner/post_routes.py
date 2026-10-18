"""POST route table separated from HTTP transport and security gates."""

from __future__ import annotations

from typing import Any, Callable


def resolve_post(handler: Any, path: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    """Resolve an authenticated, CSRF-checked POST path to its feature handler.

    Authentication, role checks, request origin/host validation, and owner scope
    deliberately remain in the HTTP handler before this dispatch boundary.
    """
    from . import knowledge

    routes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "/api/connect": handler._connect,
        "/api/sample-info": handler._sample_info,
        "/api/sample-import": handler._sample_import,
        "/api/vectorize": handler._vectorize,
        "/api/mapping": handler._mapping,
        "/api/search": handler._search,
        "/api/reranker/prepare": handler._reranker_prepare,
        "/api/code-rag": handler._code_rag,
        "/api/explain": handler._explain,
        "/api/document": handler._document,
        "/api/token-preview": handler._token_preview,
        "/api/token-preview/prepare": handler._token_preview_prepare,
        "/api/evaluate": handler._evaluate,
        "/api/tune": handler._tune,
        "/api/corpus/schema": handler._concept_schema,
        "/api/concepts/list": handler._concept_list,
        "/api/concepts/save": handler._concept_save,
        "/api/concepts/quickstart": handler._concept_quickstart,
        "/api/concepts/ensure-query": handler._concept_ensure_query,
        "/api/concepts/diagnose": handler._concept_diagnose,
        "/api/concepts/versions": handler._concept_versions,
        "/api/concepts/restore": handler._concept_restore,
        "/api/concepts/export": handler._concept_export,
        "/api/concepts/preview": handler._concept_preview,
        "/api/concepts/information-need-preview": handler._concept_information_need_preview,
        "/api/concepts/vector-candidates": handler._concept_vector_candidates,
        "/api/concepts/mode-comparison": handler._concept_mode_comparison,
        "/api/concepts/mode-comparison-group": handler._concept_mode_comparison_group,
        "/api/concepts/locate-document": handler._concept_locate_document,
        "/api/concepts/document": handler._concept_document,
        "/api/concepts/judge": handler._concept_judge,
        "/api/concepts/tune/readiness": handler._concept_tune_readiness,
        "/api/concepts/tune": handler._concept_tune,
        "/api/concepts/runs": handler._concept_runs,
        "/api/concepts/runs/export": handler._concept_run_export,
        "/api/evaluation/datasets/create": handler._evaluation_dataset_create,
        "/api/evaluation/datasets/versions/create": handler._evaluation_dataset_version_create,
        "/api/evaluation/datasets/import": handler._evaluation_dataset_import,
        "/api/evaluation/datasets/list": handler._evaluation_dataset_list,
        "/api/evaluation/datasets/detail": handler._evaluation_dataset_detail,
        "/api/evaluation/datasets/export": handler._evaluation_dataset_export,
        "/api/evaluation/datasets/evaluate": handler._evaluation_dataset_evaluate,
        "/api/evaluation/runs/list": handler._evaluation_runs_list,
        "/api/evaluation/runs/export": handler._evaluation_run_export,
        "/api/evaluation/runs/compare": handler._evaluation_runs_compare,
        "/api/knowledge/list": lambda payload: knowledge.list_documents(),
        "/api/knowledge/preview": knowledge.preview,
        "/api/knowledge/chunks/preview": knowledge.preview_chunks,
        "/api/knowledge/chunks/policy": knowledge.set_chunk_policy,
        "/api/knowledge/chunks/policy/get": lambda payload: knowledge.get_chunk_policy(),
        "/api/knowledge/reindex/start": lambda payload: knowledge.reindex_start(payload, handler._connection(payload)),
        "/api/knowledge/reindex/status": knowledge.reindex_status,
        "/api/knowledge/reindex/latest": knowledge.reindex_latest,
        "/api/knowledge/reindex/cancel": knowledge.reindex_cancel,
        "/api/knowledge/reindex/retry": lambda payload: knowledge.reindex_retry(payload, handler._connection(payload)),
        "/api/knowledge/save": knowledge.save_document,
        "/api/knowledge/import/preview": knowledge.import_preview,
        "/api/knowledge/import/commit": knowledge.import_commit,
        "/api/knowledge/export": knowledge.export_archive,
        "/api/knowledge/restore/preview": knowledge.restore_preview,
        "/api/knowledge/restore/commit": knowledge.restore_commit,
        "/api/knowledge/get": knowledge.get_document,
        "/api/knowledge/delete": knowledge.delete_document,
        "/api/knowledge/search": knowledge.search,
        "/api/knowledge/es-sync": lambda payload: knowledge.sync_es(handler._connection(payload)),
        "/api/knowledge/es-vector-sync": lambda payload: knowledge.sync_es(handler._connection(payload), vector=True, allow_model_download=payload.get("allow_model_download") is True, profile_id=payload.get("profile_id")),
        "/api/knowledge/concept-preview": knowledge.concept_preview,
        "/api/knowledge/judge": knowledge.judge,
        "/api/ai/status": handler._ai_status,
        "/api/ai/sessions/create": handler._ai_create_session,
        "/api/ai/sessions/message": handler._ai_message,
        "/api/ai/sessions/history": handler._ai_history,
        "/api/ai/sessions/reset": handler._ai_reset,
        "/api/ai/jobs/get": handler._ai_job,
        "/api/ai/jobs/cancel": handler._ai_cancel,
    }
    return routes.get(path)
