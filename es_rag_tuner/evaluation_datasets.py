"""Account-scoped immutable evaluation datasets and auditable evaluation runs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import time
import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Any

from . import concepts
from .es_client import Connection, ElasticsearchError, guard_shared_index_access, request, validate_index
from .retrieval import FILTER_FIELDS, search as retrieve


FORMAT = "es-rag-evaluation-dataset"
FORMAT_VERSION = 1
RUN_FORMAT = "es-rag-evaluation-run"
JUDGMENT_SOURCES = {"synthetic", "public_qrels", "human", "ai_suggestion"}
PERMISSION_STATUSES = {"permission_cleared", "user_authorized", "synthetic", "not_verified"}
UNJUDGED_POLICIES = {"judged_only", "unjudged_as_nonrelevant"}
SPLITS = {"train", "validation", "test"}
MAX_QUERIES = 1000
MAX_QRELS = 100_000
MAX_ARTIFACT_CHARS = 8_000_000
CSV_FIELDS = (
    "record_type", "format", "version", "dataset_id", "dataset_name", "version_id",
    "version_number", "fingerprint", "unjudged_policy", "qrels_complete", "provenance_json",
    "query_id", "query", "split", "information_need", "related_query_group",
    "document_index", "document_id", "grade", "document_family_id",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _error(message: str, status: int | None = None) -> ElasticsearchError:
    return ElasticsearchError(message, status)


def _text(value: Any, field: str, *, maximum: int = 2000, required: bool = True) -> str:
    if not isinstance(value, str):
        raise _error(f"{field} must be a string")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise _error(f"{field} must contain {1 if required else 0}..{maximum} characters")
    return value


def _normalize_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _trigrams(value: str) -> set[str]:
    compact = " " + value + " "
    if len(compact) < 3:
        return {compact}
    return {compact[index:index + 3] for index in range(len(compact) - 2)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _validate_provenance(value: Any) -> dict[str, Any]:
    required = {
        "source_uri": (2000, False),
        "source_name": (500, True),
        "source_license": (500, True),
        "permission_status": (100, True),
        "collection_date": (40, True),
        "extraction_rules": (4000, True),
        "omitted_known_relevant_items": (4000, True),
        "judgment_source": (100, True),
        "assessor": (500, True),
    }
    if not isinstance(value, dict):
        raise _error("provenance must be an object")
    result = {key: _text(value.get(key, ""), f"provenance.{key}", maximum=maximum, required=must_exist)
              for key, (maximum, must_exist) in required.items()}
    if result["permission_status"] not in PERMISSION_STATUSES:
        raise _error("provenance.permission_status must be permission_cleared, user_authorized, synthetic, or not_verified")
    if result["judgment_source"] not in JUDGMENT_SOURCES:
        raise _error("provenance.judgment_source must be synthetic, public_qrels, human, or ai_suggestion")
    try:
        date.fromisoformat(result["collection_date"][:10])
    except ValueError:
        raise _error("provenance.collection_date must start with an ISO date") from None
    extra = {key: item for key, item in value.items() if key not in required}
    try:
        json.dumps(extra, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise _error("provenance extra fields must be finite JSON values") from None
    result.update(extra)
    return result


def _validate_content(
    *, name: Any, provenance: Any, queries: Any, qrels: Any,
    unjudged_policy: Any = "judged_only", qrels_complete: Any = False,
) -> dict[str, Any]:
    name = _text(name, "dataset.name", maximum=200)
    provenance = _validate_provenance(provenance)
    if unjudged_policy not in UNJUDGED_POLICIES:
        raise _error("unjudged_policy must be judged_only or unjudged_as_nonrelevant")
    if not isinstance(qrels_complete, bool):
        raise _error("qrels_complete must be boolean")
    if unjudged_policy == "unjudged_as_nonrelevant" and qrels_complete is not True:
        raise _error("unjudged_as_nonrelevant requires qrels_complete=true")
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
        raise _error(f"queries must contain 1..{MAX_QUERIES} rows")
    clean_queries: list[dict[str, Any]] = []
    query_map: dict[str, dict[str, Any]] = {}
    for row_number, row in enumerate(queries, start=1):
        prefix = f"queries[{row_number}]"
        if not isinstance(row, dict):
            raise _error(f"{prefix} must be an object")
        query_id = _text(row.get("query_id"), f"{prefix}.query_id", maximum=128)
        query = _text(row.get("query"), f"{prefix}.query", maximum=4000)
        split = row.get("split")
        if split not in SPLITS:
            raise _error(f"{prefix}.split must be train, validation, or test")
        item = {"query_id": query_id, "query": query, "split": split}
        for field in ("information_need", "related_query_group"):
            value = _text(row.get(field, ""), f"{prefix}.{field}", maximum=200, required=False)
            if value:
                item[field] = value
        if query_id in query_map:
            raise _error(f"{prefix}.query_id duplicates {query_id}")
        query_map[query_id] = item
        clean_queries.append(item)
    if not isinstance(qrels, list) or len(qrels) > MAX_QRELS:
        raise _error(f"qrels must be an array of at most {MAX_QRELS} rows")
    clean_qrels: list[dict[str, Any]] = []
    seen_qrels: set[tuple[str, str, str]] = set()
    for row_number, row in enumerate(qrels, start=1):
        prefix = f"qrels[{row_number}]"
        if not isinstance(row, dict):
            raise _error(f"{prefix} must be an object")
        query_id = _text(row.get("query_id"), f"{prefix}.query_id", maximum=128)
        if query_id not in query_map:
            raise _error(f"{prefix}.query_id does not identify a query")
        try:
            document_index = validate_index(row.get("document_index"))
        except ElasticsearchError as exc:
            raise _error(f"{prefix}.document_index is invalid: {exc}") from None
        document_id = row.get("document_id")
        if not isinstance(document_id, (str, int)) or isinstance(document_id, bool) or str(document_id) == "":
            raise _error(f"{prefix}.document_id must be a non-empty string or integer")
        document_id = str(document_id)
        if len(document_id.encode("utf-8")) > 512:
            raise _error(f"{prefix}.document_id exceeds 512 UTF-8 bytes")
        identity = (query_id, document_index, document_id)
        if identity in seen_qrels:
            raise _error(f"{prefix} duplicates the query/document qrel identity")
        seen_qrels.add(identity)
        grade = row.get("grade")
        if grade is not None:
            if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
                raise _error(f"{prefix}.grade must be null or an integer from 0 to 3")
        item = {"query_id": query_id, "document_index": document_index, "document_id": document_id, "grade": grade}
        family = _text(row.get("document_family_id", ""), f"{prefix}.document_family_id", maximum=200, required=False)
        if family:
            item["document_family_id"] = family
        clean_qrels.append(item)
    _validate_split_leakage(clean_queries, clean_qrels)
    return {"name": name, "provenance": provenance, "queries": clean_queries, "qrels": clean_qrels,
            "unjudged_policy": unjudged_policy, "qrels_complete": qrels_complete,
            "relevance_threshold": 2, "near_duplicate_rule": "character-trigram Jaccard >= 0.80 after NFKC, casefold, and whitespace normalization"}


def _validate_split_leakage(queries: list[dict[str, Any]], qrels: list[dict[str, Any]]) -> None:
    by_id = {item["query_id"]: item for item in queries}
    groups: dict[str, dict[Any, str]] = {
        "information_need": {}, "related_query_group": {}, "document_family_id": {},
        "document_identity": {},
    }
    for item in queries:
        for field in ("information_need", "related_query_group"):
            label = item.get(field)
            if label:
                prior = groups[field].setdefault(label.casefold(), item["split"])
                if prior != item["split"]:
                    raise _error(f"split leakage: {field}={label!r} appears in {prior} and {item['split']}")
    for row in qrels:
        split = by_id[row["query_id"]]["split"]
        identity = (row["document_index"], row["document_id"])
        prior_identity_split = groups["document_identity"].setdefault(identity, split)
        if prior_identity_split != split:
            raise _error(
                "split leakage: concrete document identity "
                f"({row['document_index']!r}, {row['document_id']!r}) appears in "
                f"{prior_identity_split} and {split}"
            )
        family = row.get("document_family_id")
        if family:
            prior = groups["document_family_id"].setdefault(family.casefold(), split)
            if prior != split:
                raise _error(f"split leakage: document_family_id={family!r} appears in {prior} and {split}")
    normalized: list[tuple[dict[str, Any], str, set[str]]] = []
    for item in queries:
        value = _normalize_query(item["query"])
        grams = _trigrams(value)
        for previous, prior_value, prior_grams in normalized:
            if previous["split"] == item["split"]:
                continue
            similarity = 1.0 if value == prior_value else _jaccard(grams, prior_grams)
            if similarity >= 0.80:
                raise _error(f"split leakage: queries {previous['query_id']} and {item['query_id']} have normalized character-trigram Jaccard {similarity:.3f} across splits")
        normalized.append((item, value, grams))


def _fingerprint(content: dict[str, Any]) -> str:
    return _json_hash(content)


def _version_payload(dataset_id: str, version_id: str, version_number: int, fingerprint: str,
                     created_at: str, content: dict[str, Any]) -> dict[str, Any]:
    return {"format": FORMAT, "version": FORMAT_VERSION,
            "dataset": {"dataset_id": dataset_id, "name": content["name"]},
            "dataset_version": {"version_id": version_id, "version_number": version_number,
                                "fingerprint": fingerprint, "created_at": created_at,
                                "provenance": content["provenance"],
                                "unjudged_policy": content["unjudged_policy"],
                                "qrels_complete": content["qrels_complete"],
                                "relevance_threshold": content["relevance_threshold"],
                                "near_duplicate_rule": content["near_duplicate_rule"]},
            "queries": content["queries"], "qrels": content["qrels"]}


def _content_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("format") != FORMAT or payload.get("version") != FORMAT_VERSION:
        raise _error(f"Unsupported dataset format; expected {FORMAT} version {FORMAT_VERSION}")
    dataset = payload.get("dataset")
    version = payload.get("dataset_version")
    if not isinstance(dataset, dict) or not isinstance(version, dict):
        raise _error("Dataset artifact requires dataset and dataset_version objects")
    content = _validate_content(name=dataset.get("name"), provenance=version.get("provenance"),
                                queries=payload.get("queries"), qrels=payload.get("qrels"),
                                unjudged_policy=version.get("unjudged_policy", "judged_only"),
                                qrels_complete=version.get("qrels_complete", False))
    # A format-level extension may not redefine policy semantics on import.
    if version.get("relevance_threshold", 2) != 2:
        raise _error("Only relevance_threshold=2 is supported in this dataset format version")
    return content


def _version_record(db: sqlite3.Connection, version_id: str, *, dataset_id: str | None = None) -> tuple[sqlite3.Row, dict[str, Any]]:
    if dataset_id:
        row = db.execute("SELECT * FROM evaluation_dataset_versions WHERE dataset_id=? AND version_id=?", (dataset_id, version_id)).fetchone()
    else:
        row = db.execute("SELECT * FROM evaluation_dataset_versions WHERE version_id=?", (version_id,)).fetchone()
    if row is None:
        raise _error("Evaluation dataset version was not found", 404)
    return row, json.loads(row["body"])


def _insert_version(db: sqlite3.Connection, dataset_id: str, version_id: str, version_number: int,
                    content: dict[str, Any], *, created_at: str | None = None, expected_fingerprint: str | None = None) -> dict[str, Any]:
    fingerprint = _fingerprint(content)
    if expected_fingerprint and expected_fingerprint != fingerprint:
        raise _error("Dataset artifact fingerprint does not match its canonical content")
    created_at = created_at or _now()
    record = _version_payload(dataset_id, version_id, version_number, fingerprint, created_at, content)
    db.execute("INSERT INTO evaluation_dataset_versions(version_id,dataset_id,version_number,fingerprint,body,created_at) VALUES(?,?,?,?,?,?)",
               (version_id, dataset_id, version_number, fingerprint,
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False), created_at))
    return {"version_id": version_id, "version_number": version_number, "fingerprint": fingerprint,
            "created_at": created_at, "query_count": len(content["queries"]), "qrel_count": len(content["qrels"]),
            "unjudged_policy": content["unjudged_policy"]}


def create_dataset(name: Any, provenance: Any, queries: Any, qrels: Any,
                   unjudged_policy: Any = "judged_only", qrels_complete: Any = False) -> dict[str, Any]:
    content = _validate_content(name=name, provenance=provenance, queries=queries, qrels=qrels,
                                unjudged_policy=unjudged_policy, qrels_complete=qrels_complete)
    dataset_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    with concepts._connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO evaluation_datasets(dataset_id,name,created_at) VALUES(?,?,?)", (dataset_id, content["name"], _now()))
        version = _insert_version(db, dataset_id, version_id, 1, content)
    return {"dataset_id": dataset_id, "name": content["name"], "version": version}


def create_version(dataset_id: Any, base_version_id: Any, name: Any, provenance: Any,
                   queries: Any, qrels: Any, unjudged_policy: Any = "judged_only",
                   qrels_complete: Any = False) -> dict[str, Any]:
    dataset_id = _text(dataset_id, "dataset_id", maximum=128)
    base_version_id = _text(base_version_id, "base_version_id", maximum=128)
    content = _validate_content(name=name, provenance=provenance, queries=queries, qrels=qrels,
                                unjudged_policy=unjudged_policy, qrels_complete=qrels_complete)
    version_id = str(uuid.uuid4())
    with concepts._connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        dataset = db.execute("SELECT * FROM evaluation_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        if dataset is None:
            raise _error("Evaluation dataset was not found", 404)
        if dataset["name"] != content["name"]:
            raise _error("Dataset name is immutable after creation")
        latest = db.execute("SELECT version_id,version_number FROM evaluation_dataset_versions WHERE dataset_id=? ORDER BY version_number DESC LIMIT 1", (dataset_id,)).fetchone()
        if latest is None or latest["version_id"] != base_version_id:
            raise _error("base_version_id must identify the latest version; reload the dataset before editing", 409)
        version = _insert_version(db, dataset_id, version_id, int(latest["version_number"]) + 1, content)
    return {"dataset_id": dataset_id, "name": content["name"], "version": version}


def _decode_artifact(content: Any, fmt: Any) -> tuple[dict[str, Any], str | None, str | None, int | None, str | None]:
    if not isinstance(content, str) or len(content) > MAX_ARTIFACT_CHARS:
        raise _error(f"content must be text of at most {MAX_ARTIFACT_CHARS} characters")
    if fmt not in {"csv", "jsonl"}:
        raise _error("format must be csv or jsonl")
    try:
        if fmt == "jsonl":
            records = [json.loads(line) for line in content.splitlines() if line.strip()]
        else:
            reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
            if reader.fieldnames is None or set(CSV_FIELDS) - set(reader.fieldnames):
                raise _error("CSV header is missing required fields")
            records = list(reader)
    except (json.JSONDecodeError, csv.Error) as exc:
        raise _error(f"Invalid {fmt.upper()} artifact syntax: {exc}") from None
    if not records:
        raise _error("Dataset artifact is empty")
    if fmt == "jsonl":
        header = records[0]
        if not isinstance(header, dict) or header.get("record_type") != "dataset":
            raise _error("JSONL first record must be record_type=dataset")
        queries, qrels = [], []
        for number, row in enumerate(records[1:], start=2):
            if not isinstance(row, dict):
                raise _error(f"JSONL row {number} must be an object")
            if row.get("record_type") == "query":
                queries.append({key: row[key] for key in ("query_id", "query", "split", "information_need", "related_query_group") if key in row})
            elif row.get("record_type") == "qrel":
                qrels.append({key: row[key] for key in ("query_id", "document_index", "document_id", "grade", "document_family_id") if key in row})
            else:
                raise _error(f"JSONL row {number}.record_type must be query or qrel")
        envelope = {key: header.get(key) for key in ("format", "version", "dataset", "dataset_version")}
    else:
        first = records[0]
        if first.get("record_type") != "dataset":
            raise _error("CSV first row must have record_type=dataset")
        try:
            provenance = json.loads(first.get("provenance_json") or "{}")
            envelope = {"format": first.get("format"), "version": int(first.get("version", "0")),
                        "dataset": {"dataset_id": first.get("dataset_id"), "name": first.get("dataset_name")},
                        "dataset_version": {"version_id": first.get("version_id"),
                                            "version_number": int(first.get("version_number", "0")),
                                            "fingerprint": first.get("fingerprint"), "provenance": provenance,
                                            "unjudged_policy": first.get("unjudged_policy"),
                                            "qrels_complete": str(first.get("qrels_complete", "")).lower() == "true"}}
        except (json.JSONDecodeError, TypeError, ValueError):
            raise _error("CSV dataset metadata row contains invalid JSON or version values") from None
        queries, qrels = [], []
        for number, row in enumerate(records[1:], start=3):
            if row.get("record_type") == "query":
                queries.append({"query_id": row.get("query_id"), "query": row.get("query"), "split": row.get("split"),
                                "information_need": row.get("information_need", ""), "related_query_group": row.get("related_query_group", "")})
            elif row.get("record_type") == "qrel":
                raw_grade = row.get("grade", "")
                try:
                    grade = None if raw_grade.strip().lower() in {"", "null"} else int(raw_grade)
                except ValueError:
                    raise _error(f"CSV row {number}.grade must be null or an integer from 0 to 3") from None
                qrels.append({"query_id": row.get("query_id"), "document_index": row.get("document_index"),
                              "document_id": row.get("document_id"), "grade": grade,
                              "document_family_id": row.get("document_family_id", "")})
            else:
                raise _error(f"CSV row {number}.record_type must be query or qrel")
    envelope["queries"], envelope["qrels"] = queries, qrels
    content_value = _content_from_payload(envelope)
    version = envelope["dataset_version"]
    return (content_value, envelope["dataset"].get("dataset_id"), version.get("version_id"),
            version.get("version_number"), version.get("fingerprint"))


def import_dataset(fmt: Any, content: Any) -> dict[str, Any]:
    parsed, raw_dataset_id, raw_version_id, raw_number, raw_fingerprint = _decode_artifact(content, fmt)
    dataset_id = str(raw_dataset_id or uuid.uuid4())
    version_id = str(raw_version_id or uuid.uuid4())
    if len(dataset_id) > 128 or len(version_id) > 128:
        raise _error("Dataset and version IDs must be at most 128 characters")
    try:
        version_number = int(raw_number) if raw_number is not None else 1
    except (TypeError, ValueError):
        raise _error("dataset_version.version_number must be a positive integer") from None
    if isinstance(raw_number, bool) or version_number < 1:
        raise _error("dataset_version.version_number must be a positive integer")
    expected = str(raw_fingerprint or "") or None
    if expected and not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise _error("dataset_version.fingerprint must be a lowercase SHA-256")
    with concepts._connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        dataset = db.execute("SELECT * FROM evaluation_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        fingerprint = _fingerprint(parsed)
        if expected and expected != fingerprint:
            raise _error("Dataset artifact fingerprint does not match its canonical content")
        existing_version = db.execute("SELECT * FROM evaluation_dataset_versions WHERE version_id=?", (version_id,)).fetchone()
        if existing_version is not None:
            if existing_version["dataset_id"] == dataset_id and existing_version["fingerprint"] == fingerprint:
                saved = json.loads(existing_version["body"])
                return {"dataset": saved["dataset"], "version": saved["dataset_version"], "fingerprint": fingerprint, "idempotent": True}
            raise _error("Imported version_id already exists with different identity or content", 409)
        if dataset is None:
            db.execute("INSERT INTO evaluation_datasets(dataset_id,name,created_at) VALUES(?,?,?)", (dataset_id, parsed["name"], _now()))
        else:
            if dataset["name"] != parsed["name"]:
                raise _error("Imported dataset_id already exists with a different name", 409)
            max_version = db.execute("SELECT COALESCE(MAX(version_number),0) FROM evaluation_dataset_versions WHERE dataset_id=?", (dataset_id,)).fetchone()[0]
            if version_number <= max_version:
                raise _error("Imported version number conflicts with existing immutable history", 409)
        version = _insert_version(db, dataset_id, version_id, version_number, parsed,
                                  expected_fingerprint=expected)
    return {"dataset_id": dataset_id, "name": parsed["name"], "version": version, "idempotent": False}


def list_datasets(dataset_id: str = "") -> dict[str, Any]:
    with concepts._connect_db() as db:
        if dataset_id:
            datasets = db.execute("SELECT * FROM evaluation_datasets WHERE dataset_id=?", (dataset_id,)).fetchall()
        else:
            datasets = db.execute("SELECT * FROM evaluation_datasets ORDER BY created_at DESC,dataset_id").fetchall()
        result = []
        for dataset in datasets:
            versions = db.execute("SELECT version_id,version_number,fingerprint,created_at,body FROM evaluation_dataset_versions WHERE dataset_id=? ORDER BY version_number DESC", (dataset["dataset_id"],)).fetchall()
            summaries = []
            for row in versions:
                body = json.loads(row["body"])
                summaries.append({"version_id": row["version_id"], "version_number": row["version_number"],
                                  "fingerprint": row["fingerprint"], "created_at": row["created_at"],
                                  "provenance": body["dataset_version"]["provenance"],
                                  "unjudged_policy": body["dataset_version"]["unjudged_policy"],
                                  "qrels_complete": body["dataset_version"]["qrels_complete"],
                                  "query_count": len(body["queries"]), "qrel_count": len(body["qrels"])})
            if summaries:
                result.append({"dataset_id": dataset["dataset_id"], "name": dataset["name"],
                               "created_at": dataset["created_at"], "versions": summaries})
    return {"datasets": result}


def get_dataset_version(dataset_id: Any, version_id: Any) -> dict[str, Any]:
    dataset_id = _text(dataset_id, "dataset_id", maximum=128)
    version_id = _text(version_id, "version_id", maximum=128)
    with concepts._connect_db() as db:
        row, body = _version_record(db, version_id, dataset_id=dataset_id)
    return {"dataset": body["dataset"], "version": body["dataset_version"],
            "queries": body["queries"], "qrels": body["qrels"], "fingerprint": row["fingerprint"]}


def _artifact_records(body: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    header = {"record_type": "dataset", "format": body["format"], "version": body["version"],
              "dataset": body["dataset"], "dataset_version": body["dataset_version"]}
    records = [header]
    records.extend({"record_type": "query", **item} for item in body["queries"])
    records.extend({"record_type": "qrel", **item} for item in body["qrels"])
    return header, records


def export_dataset(dataset_id: Any, version_id: Any, fmt: Any) -> dict[str, Any]:
    if fmt not in {"csv", "jsonl"}:
        raise _error("format must be csv or jsonl")
    exported = get_dataset_version(dataset_id, version_id)
    body = {"format": FORMAT, "version": FORMAT_VERSION, "dataset": exported["dataset"],
            "dataset_version": exported["version"], "queries": exported["queries"], "qrels": exported["qrels"]}
    header, records = _artifact_records(body)
    if fmt == "jsonl":
        text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) for row in records) + "\n"
    else:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerow({"record_type": "dataset", "format": FORMAT, "version": FORMAT_VERSION,
                         "dataset_id": body["dataset"]["dataset_id"], "dataset_name": body["dataset"]["name"],
                         "version_id": body["dataset_version"]["version_id"],
                         "version_number": body["dataset_version"]["version_number"],
                         "fingerprint": body["dataset_version"]["fingerprint"],
                         "unjudged_policy": body["dataset_version"]["unjudged_policy"],
                         "qrels_complete": str(body["dataset_version"]["qrels_complete"]).lower(),
                         "provenance_json": json.dumps(body["dataset_version"]["provenance"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))})
        for row in body["queries"]:
            writer.writerow({"record_type": "query", **row})
        for row in body["qrels"]:
            writer.writerow({"record_type": "qrel", **{**row, "grade": "null" if row["grade"] is None else row["grade"]}})
        text = output.getvalue()
    filename = f"{body['dataset']['dataset_id']}-{body['dataset_version']['version_number']}.{fmt}"
    return {"format": fmt, "filename": filename, "content": text, "dataset": body["dataset"],
            "version": body["dataset_version"], "fingerprint": body["dataset_version"]["fingerprint"]}


def _failure_category(exc: Exception) -> str:
    if isinstance(exc, ElasticsearchError):
        if exc.status in {401, 403}:
            return "authorization"
        if exc.status in {404, 409}:
            return "mapping_or_index"
        if exc.status and exc.status >= 500:
            return "elasticsearch_unavailable"
        return "search_request"
    return "internal"


def _metrics_for_query(hits: list[dict[str, Any]], qrels: list[dict[str, Any]], cutoff: int,
                       policy: str, threshold: int = 2) -> dict[str, Any]:
    qrel_by_identity = {(row["document_index"], row["document_id"]): row for row in qrels}
    top = hits[:cutoff]
    numeric = [hit for hit in top if (str(hit.get("_index", "")), str(hit.get("_id", ""))) in qrel_by_identity
               and qrel_by_identity[(str(hit.get("_index", "")), str(hit.get("_id", "")))]["grade"] is not None]
    judged_ranking = numeric
    all_known_relevant = [row for row in qrels if isinstance(row["grade"], int) and row["grade"] >= threshold]
    if policy == "unjudged_as_nonrelevant":
        metric_ranking = top
        denominator = cutoff
        gains = [int(qrel_by_identity.get((str(hit.get("_index", "")), str(hit.get("_id", ""))), {}).get("grade") or 0) for hit in metric_ranking]
        known_relevant_total = len(all_known_relevant)
        judged_hit_count = len(numeric)
        unjudged_state = "counted_as_nonrelevant_by_explicit_policy"
    else:
        metric_ranking = judged_ranking
        denominator = min(cutoff, len(numeric))
        gains = [int(qrel_by_identity[(str(hit.get("_index", "")), str(hit.get("_id", "")))]["grade"]) for hit in metric_ranking]
        known_relevant_total = len(all_known_relevant)
        judged_hit_count = len(numeric)
        unjudged_state = "excluded_from_judged_only_metrics"
    relevant_positions = [rank for rank, grade in enumerate(gains, start=1) if grade >= threshold]
    found = len(relevant_positions)
    no_positive = known_relevant_total == 0
    precision = (found / denominator) if denominator > 0 else None
    recall = found / known_relevant_total if known_relevant_total else None
    reciprocal_rank = (1 / relevant_positions[0]) if relevant_positions else (0.0 if known_relevant_total else None)
    dcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(gains, start=1))
    ideal_gains = sorted((int(row["grade"]) for row in qrels if row["grade"] is not None), reverse=True)[:cutoff]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal_gains, start=1))
    ndcg = dcg / idcg if idcg else None
    if no_positive:
        recall = reciprocal_rank = ndcg = None
    qrel_states = []
    retrieved_numeric = retrieved_explicit_null = retrieved_absent = 0
    ranked = []
    judged_rank = 0
    missed = []
    retrieved_keys = set()
    for original_rank, hit in enumerate(top, start=1):
        identity = (str(hit.get("_index", "")), str(hit.get("_id", "")))
        qrel = qrel_by_identity.get(identity)
        if qrel is None:
            state = "absent"
            retrieved_absent += 1
        elif qrel["grade"] is None:
            state = "explicit_null"
            retrieved_explicit_null += 1
        else:
            state = "numeric"
            retrieved_numeric += 1
            judged_rank += 1
        retrieved_keys.add(identity)
        ranked.append({"document_index": identity[0], "document_id": identity[1], "original_rank": original_rank,
                       "judged_rank": judged_rank if state == "numeric" else None,
                       "qrel_state": state, "grade": qrel["grade"] if qrel else None,
                       "score": hit.get("_score")})
    for row in all_known_relevant:
        identity = (row["document_index"], row["document_id"])
        if identity not in retrieved_keys:
            missed.append({"document_index": identity[0], "document_id": identity[1], "grade": row["grade"]})
    counts = {"numeric_qrels_total": sum(row["grade"] is not None for row in qrels),
              "explicit_null_qrels_total": sum(row["grade"] is None for row in qrels),
              "returned_at_k": len(top), "numeric_judged_retrieved": retrieved_numeric,
              "explicit_null_retrieved": retrieved_explicit_null, "absent_qrel_retrieved": retrieved_absent,
              "known_relevant": known_relevant_total, "relevant_retrieved_at_k": found,
              "missed_known_relevant": len(missed)}
    unavailable = {}
    if precision is None:
        unavailable["precision_at_k"] = "no_numeric_judged_hits_at_k"
    if no_positive:
        for key in ("recall_at_k", "mrr_at_k", "ndcg_at_k"):
            unavailable[key] = "no_explicitly_judged_relevant_documents"
    return {"metrics": {"precision_at_k": precision, "recall_at_k": recall,
                         "mrr_at_k": reciprocal_rank, "ndcg_at_k": ndcg,
                         "judged_coverage_at_k": retrieved_numeric / len(top) if top else 0.0},
            "denominators": {"precision_at_k": denominator, "recall_at_k": known_relevant_total,
                             "mrr_at_k": "queries_with_known_relevant_documents",
                             "ndcg_at_k": "all_numeric_qrels_ideal; judged ranking at cutoff",
                             "judged_coverage_at_k": len(top)},
            "counts": counts, "unavailable_reasons": unavailable,
            "ranked_hits": ranked, "missed_known_relevant": missed,
            "unjudged_policy_consequence": unjudged_state}


def _macro(query_rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = [row["metrics"][metric] for row in query_rows if row["status"] == "complete" and row["metrics"].get(metric) is not None]
    return {"mean": sum(values) / len(values) if values else None, "query_count": len(values),
            "unavailable_count": sum(row["status"] == "complete" and row["metrics"].get(metric) is None for row in query_rows)}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def evaluate(connection: Connection, index: Any, dataset_id: Any, version_id: Any,
             split: Any, mode: Any, settings: Any, cutoff: Any,
             configuration_frozen: Any = False) -> dict[str, Any]:
    dataset_id = _text(dataset_id, "dataset_id", maximum=128)
    version_id = _text(version_id, "version_id", maximum=128)
    if split not in SPLITS:
        raise _error("split must be train, validation, or test")
    if split == "test" and configuration_frozen is not True:
        raise _error("test split evaluation requires configuration_frozen=true")
    if not isinstance(configuration_frozen, bool):
        raise _error("configuration_frozen must be boolean")
    if mode not in {"bm25", "vector", "hybrid"}:
        raise _error("mode must be bm25, vector, or hybrid")
    try:
        index = validate_index(index)
    except ElasticsearchError as exc:
        raise _error(f"index is invalid: {exc}") from None
    if not isinstance(cutoff, int) or isinstance(cutoff, bool) or not 1 <= cutoff <= 50:
        raise _error("cutoff must be an integer from 1 to 50")
    if not isinstance(settings, dict):
        raise _error("settings must be an object")
    size = settings.get("size", cutoff)
    candidate_pool = settings.get("candidate_pool", size)
    rank_constant = settings.get("rank_constant", 60)
    if not isinstance(size, int) or isinstance(size, bool) or not cutoff <= size <= 50:
        raise _error("settings.size must be cutoff..50")
    if not isinstance(candidate_pool, int) or isinstance(candidate_pool, bool) or not size <= candidate_pool <= 200:
        raise _error("settings.candidate_pool must be size..200")
    if not isinstance(rank_constant, int) or isinstance(rank_constant, bool) or not 1 <= rank_constant <= 200:
        raise _error("settings.rank_constant must be 1..200")
    from . import evaluation
    boosts = settings.get("boosts", evaluation.DEFAULT_PROFILE)
    if not isinstance(boosts, dict):
        raise _error("settings.boosts must be an object")
    clean_boosts: dict[str, float] = {}
    for field, value in boosts.items():
        if field not in evaluation.DEFAULT_PROFILE:
            raise _error(f"settings.boosts contains unsupported field {field!r}")
        if isinstance(value, bool):
            raise _error(f"settings.boosts.{field} must be a finite number from 0 to 100")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise _error(f"settings.boosts.{field} must be a finite number from 0 to 100") from None
        if not math.isfinite(number) or not 0 <= number <= 100:
            raise _error(f"settings.boosts.{field} must be a finite number from 0 to 100")
        clean_boosts[field] = number
    filters = settings.get("filters", [])
    if not isinstance(filters, list) or len(filters) > 50:
        raise _error("settings.filters must be an array of at most 50 filters")
    clean_filters = []
    for number, item in enumerate(filters, start=1):
        if not isinstance(item, dict):
            raise _error(f"settings.filters[{number}] must be an object")
        field = _text(item.get("field"), f"settings.filters[{number}].field", maximum=256)
        value = _text(item.get("value"), f"settings.filters[{number}].value", maximum=2000)
        if field not in FILTER_FIELDS:
            raise _error(f"settings.filters[{number}].field is unsupported")
        clean_filters.append({"field": field, "value": value})
    profile_id = settings.get("profile_id")
    if profile_id is not None and (not isinstance(profile_id, str) or not profile_id.strip() or len(profile_id) > 128):
        raise _error("settings.profile_id must be a non-empty string of at most 128 characters")
    settings_record = {"mode": mode, "size": size, "candidate_pool": candidate_pool,
                       "rank_constant": rank_constant, "boosts": clean_boosts,
                       "filters": clean_filters, "profile_id": profile_id,
                       "rerank": settings.get("rerank", False)}
    if not isinstance(settings_record["rerank"], bool):
        raise _error("settings.rerank must be boolean")
    if mode == "vector" or mode == "hybrid":
        guard_shared_index_access(index)
    with concepts._connect_db() as db:
        row, body = _version_record(db, version_id, dataset_id=dataset_id)
    content = _content_from_payload(body)
    if content["provenance"]["judgment_source"] == "ai_suggestion":
        raise _error("AI-suggested judgments are not ground truth; review them and create a new dataset version with the correct judgment_source before evaluation")
    qrel_by_query: dict[str, list[dict[str, Any]]] = {}
    for qrel in content["qrels"]:
        qrel_by_query.setdefault(qrel["query_id"], []).append(qrel)
    queries = [query for query in content["queries"] if query["split"] == split]
    if not queries:
        raise _error(f"dataset has no {split} queries")
    try:
        corpus_identity, identity_warning = concepts._index_identity(connection, index)
    except Exception:
        corpus_identity, identity_warning = {"requested_index": index, "uuids": [], "available": False}, "index identity unavailable"
    mapping_fingerprint = None
    mapping_warning = None
    try:
        mapping = request(connection, "GET", f"{index}/_mapping")
        mapping_fingerprint = _json_hash(mapping)
    except Exception:
        mapping_warning = "index mapping unavailable"
    query_rows = []
    latencies: list[float] = []
    for query in queries:
        started = time.perf_counter()
        try:
            result = retrieve(connection, index, query["query"], size, clean_boosts,
                              clean_filters, mode=mode,
                              rank_constant=rank_constant, candidate_pool=candidate_pool,
                              profile_id=profile_id,
                              rerank=settings_record["rerank"])
            duration = max(0.0, (time.perf_counter() - started) * 1000)
            latencies.append(duration)
            measured = _metrics_for_query(result["hits"], qrel_by_query.get(query["query_id"], []), cutoff,
                                          content["unjudged_policy"], content["relevance_threshold"])
            query_rows.append({"query_id": query["query_id"], "query": query["query"], "split": split,
                               "status": "complete", **measured, "elapsed_ms": round(duration, 3)})
        except Exception as exc:
            duration = max(0.0, (time.perf_counter() - started) * 1000)
            query_rows.append({"query_id": query["query_id"], "query": query["query"], "split": split,
                               "status": "failed", "failure_category": _failure_category(exc),
                               "error": (str(exc)[:500] if isinstance(exc, ElasticsearchError) and exc.safe_for_user else "Search failed; inspect connection and index settings."),
                               "elapsed_ms": round(duration, 3)})
    policy = {"name": content["unjudged_policy"], "qrels_complete": content["qrels_complete"],
              "explicit_null_is_unjudged": True, "absent_qrel_is_unknown": True,
              "numeric_judgment_range": [0, 3], "relevance_threshold": content["relevance_threshold"],
              "definitions": {"precision": "relevant numeric hits among first k judged hits / min(k, numeric judged hits returned at k)",
                              "recall": "known relevant qrels retrieved at k / all known relevant qrels for query",
                              "mrr": "reciprocal rank of first relevant hit in judged ranking at k",
                              "ndcg": "graded gain 2^grade-1 on judged ranking at k, divided by ideal over numeric qrels",
                              "judged_coverage": "numeric judged hits among first k results / all results returned at k",
                              "tie_policy": "preserve retrieval backend order for equal-score hits"}}
    aggregate = {metric: _macro(query_rows, metric) for metric in
                 ("precision_at_k", "recall_at_k", "mrr_at_k", "ndcg_at_k", "judged_coverage_at_k")}
    run_body = {"format": RUN_FORMAT, "version": 1, "dataset_id": dataset_id,
                "dataset_version_id": version_id, "dataset_version_number": body["dataset_version"]["version_number"],
                "dataset_fingerprint": row["fingerprint"], "dataset_provenance": body["dataset_version"]["provenance"],
                "split": split, "index": index, "corpus_identity": corpus_identity,
                "mapping_fingerprint": mapping_fingerprint, "mapping_warning": mapping_warning,
                "corpus_identity_warning": identity_warning, "settings": settings_record,
                "configuration_frozen": configuration_frozen, "cutoff": cutoff, "metric_policy": policy,
                "query_count": len(queries), "completed_query_count": sum(q["status"] == "complete" for q in query_rows),
                "failed_query_count": sum(q["status"] == "failed" for q in query_rows),
                "aggregate": aggregate, "queries": query_rows,
                "latency_ms": {"p50": _percentile(latencies, .50), "p95": _percentile(latencies, .95)}}
    run_body["configuration_fingerprint"] = _json_hash({"settings": settings_record, "cutoff": cutoff})
    if split == "test" and run_body["failed_query_count"]:
        # An incomplete test batch must not reserve the one final test run.
        failures = [{"query_id": item["query_id"], "failure_category": item["failure_category"]}
                    for item in query_rows if item["status"] == "failed"]
        return {"run_id": None, "persisted": False, "test_run_consumed": False,
                "dataset_id": dataset_id, "dataset_version_id": version_id,
                "dataset_fingerprint": row["fingerprint"], "split": split,
                "query_count": len(queries), "failed_query_count": len(failures),
                "failures": failures}
    run_id = str(uuid.uuid4())
    with concepts._connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if split == "test":
            if not corpus_identity.get("available", True) or not corpus_identity.get("uuids"):
                raise _error("A final test run requires an available Elasticsearch corpus UUID identity")
            prior_rows = db.execute(
                "SELECT body FROM evaluation_runs WHERE dataset_id=? AND version_id=?",
                (dataset_id, version_id),
            ).fetchall()
            for prior_row in prior_rows:
                prior = json.loads(prior_row["body"])
                if prior.get("split") == "test" and prior.get("corpus_identity") == corpus_identity:
                    raise _error("The final test run for this dataset version and corpus identity has already been consumed", 409)
        db.execute("INSERT INTO evaluation_runs(id,dataset_id,version_id,created_at,body) VALUES(?,?,?,?,?)",
                   (run_id, dataset_id, version_id, _now(), json.dumps(run_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)))
    return {"run_id": run_id, "persisted": True,
            "test_run_consumed": split == "test", **run_body}


def _load_run(db: sqlite3.Connection, dataset_id: str, version_id: str, run_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM evaluation_runs WHERE id=? AND dataset_id=? AND version_id=?", (run_id, dataset_id, version_id)).fetchone()
    if row is None:
        raise _error("Evaluation run was not found for this dataset version", 404)
    return json.loads(row["body"])


def list_runs(dataset_id: Any, version_id: Any) -> dict[str, Any]:
    dataset_id = _text(dataset_id, "dataset_id", maximum=128)
    version_id = _text(version_id, "version_id", maximum=128)
    with concepts._connect_db() as db:
        rows = db.execute("SELECT id,created_at,body FROM evaluation_runs WHERE dataset_id=? AND version_id=? ORDER BY created_at DESC", (dataset_id, version_id)).fetchall()
    return {"runs": [{"run_id": row["id"], "created_at": row["created_at"], **{
        key: json.loads(row["body"]).get(key) for key in ("split", "index", "settings", "cutoff", "aggregate", "failed_query_count", "dataset_fingerprint")
    }} for row in rows]}


def export_run(dataset_id: Any, version_id: Any, run_id: Any) -> dict[str, Any]:
    dataset_id = _text(dataset_id, "dataset_id", maximum=128)
    version_id = _text(version_id, "version_id", maximum=128)
    run_id = _text(run_id, "run_id", maximum=128)
    with concepts._connect_db() as db:
        body = _load_run(db, dataset_id, version_id, run_id)
    return {"format": RUN_FORMAT, "version": 1, "run_id": run_id, "dataset_id": dataset_id,
            "dataset_version_id": version_id, "dataset_fingerprint": body["dataset_fingerprint"], "run": body}


def compare_runs(dataset_id: Any, version_id: Any, left_run_id: Any, right_run_id: Any) -> dict[str, Any]:
    dataset_id = _text(dataset_id, "dataset_id", maximum=128)
    version_id = _text(version_id, "version_id", maximum=128)
    with concepts._connect_db() as db:
        left = _load_run(db, dataset_id, version_id, _text(left_run_id, "left_run_id", maximum=128))
        right = _load_run(db, dataset_id, version_id, _text(right_run_id, "right_run_id", maximum=128))
    for field in ("dataset_fingerprint", "split", "index", "corpus_identity", "mapping_fingerprint", "cutoff", "metric_policy"):
        if left.get(field) != right.get(field):
            raise _error(f"Runs cannot be compared because {field} differs", 409)
    left_queries = {row["query_id"]: row for row in left["queries"]}
    right_queries = {row["query_id"]: row for row in right["queries"]}
    rows = []
    for query_id in sorted(set(left_queries) | set(right_queries)):
        a, b = left_queries.get(query_id), right_queries.get(query_id)
        if not a or not b:
            rows.append({"query_id": query_id, "status": "failed", "failure_category": "query_set_mismatch"})
            continue
        if a.get("status") != "complete" or b.get("status") != "complete":
            rows.append({"query_id": query_id, "status": "failed", "failure_category": "search_failure",
                         "left_failure": a.get("failure_category"), "right_failure": b.get("failure_category")})
            continue
        metric_deltas = {name: (b["metrics"].get(name) - a["metrics"].get(name)
                                if isinstance(a["metrics"].get(name), (int, float)) and isinstance(b["metrics"].get(name), (int, float)) else None)
                         for name in ("precision_at_k", "recall_at_k", "mrr_at_k", "ndcg_at_k", "judged_coverage_at_k")}
        left_misses = {(item["document_index"], item["document_id"]): item for item in a["missed_known_relevant"]}
        right_misses = {(item["document_index"], item["document_id"]): item for item in b["missed_known_relevant"]}
        regressions = [name for name, delta in metric_deltas.items() if delta is not None and delta < 0]
        rows.append({"query_id": query_id, "query": b["query"], "status": "complete",
                     "metric_deltas": metric_deltas, "regressions": regressions,
                     "left_missed_known_relevant": list(left_misses.values()),
                     "right_missed_known_relevant": list(right_misses.values()),
                     "missed_relevant_added": [right_misses[key] for key in sorted(right_misses.keys() - left_misses.keys())],
                     "missed_relevant_fixed": [left_misses[key] for key in sorted(left_misses.keys() - right_misses.keys())],
                     "left_retrieved_unjudged_count": a["counts"]["explicit_null_retrieved"] + a["counts"]["absent_qrel_retrieved"],
                     "right_retrieved_unjudged_count": b["counts"]["explicit_null_retrieved"] + b["counts"]["absent_qrel_retrieved"],
                     "left_coverage": a["metrics"]["judged_coverage_at_k"],
                     "right_coverage": b["metrics"]["judged_coverage_at_k"]})
    return {"dataset_id": dataset_id, "dataset_version_id": version_id,
            "dataset_fingerprint": left["dataset_fingerprint"], "split": left["split"],
            "cutoff": left["cutoff"], "left_run_id": left_run_id, "right_run_id": right_run_id,
            "queries": rows, "failed_query_count": sum(row["status"] != "complete" for row in rows)}
