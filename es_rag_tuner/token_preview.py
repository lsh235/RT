"""Opt-in, local preview of FastEmbed's E5 tokenizer truncation boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import threading
from pathlib import Path
from typing import Any


MODEL = "intfloat/multilingual-e5-large"
REPOSITORY = "Qdrant/multilingual-e5-large-onnx"
REVISION = "ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b"
MAX_TOKENS = 512
ASSETS = {
    "tokenizer.json": "f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af",
    "tokenizer_config.json": "f90024142df07163e5e6c5b9a6ad7c8c68b22a9112af11e3db4559a9ff90f737",
    "config.json": "1de8c3be1f344c0eefa4962480a006f8639f416dfafaa95a770e3cf4bceae6a4",
    "special_tokens_map.json": "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
}
# Fixed limits for the immutable four-file bundle. Check these before hashing or
# parsing so a damaged cache cannot force an unbounded read during status checks.
ASSET_MAX_BYTES = {
    "tokenizer.json": 18 * 1024 * 1024,
    "tokenizer_config.json": 16 * 1024,
    "config.json": 16 * 1024,
    "special_tokens_map.json": 16 * 1024,
}
_LOCK = threading.Lock()
_ENCODE_LOCK = threading.Lock()
_TOKENIZER: Any = None


def cache_path() -> Path:
    """A cache isolated from FastEmbed's model cache."""
    configured = os.environ.get("ES_RAG_TOKEN_PREVIEW_CACHE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "es-rag-workbench" / "token-preview"


def _dependencies() -> tuple[bool, bool]:
    return importlib.util.find_spec("tokenizers") is not None, importlib.util.find_spec("huggingface_hub") is not None


def _cached_assets() -> dict[str, Path]:
    """Resolve only the four pinned files without network access."""
    from huggingface_hub import hf_hub_download

    result: dict[str, Path] = {}
    for filename in ASSETS:
        result[filename] = Path(hf_hub_download(
            repo_id=REPOSITORY, filename=filename, revision=REVISION,
            cache_dir=str(cache_path()), local_files_only=True,
        ))
    return result


def _verify_assets(paths: dict[str, Path]) -> None:
    for filename, expected in ASSETS.items():
        path = paths[filename]
        size = path.stat().st_size
        if size <= 0 or size > ASSET_MAX_BYTES[filename]:
            raise ValueError(f"토크나이저 파일 크기가 허용 범위를 벗어났습니다: {filename}")
        digest_builder = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest_builder.update(chunk)
        digest = digest_builder.hexdigest()
        if digest != expected:
            raise ValueError(f"검증되지 않은 토크나이저 파일입니다: {filename}")


def status() -> dict[str, Any]:
    tokenizers_installed, hub_installed = _dependencies()
    base: dict[str, Any] = {
        "available": False, "model": MODEL, "revision": REVISION,
        "max_tokens": MAX_TOKENS, "cache_path": str(cache_path()),
        "tokenizers_installed": tokenizers_installed,
        "huggingface_hub_installed": hub_installed,
        "cached": False, "reason": None,
    }
    if not tokenizers_installed:
        base["reason"] = "tokenizers 의존성이 없습니다. `python -m pip install -e '.[token-preview]'`로 설치하세요."
        return base
    if not hub_installed:
        base["reason"] = "huggingface-hub 의존성이 없습니다. `python -m pip install -e '.[token-preview]'`로 설치하세요."
        return base
    try:
        paths = _cached_assets()
        _verify_assets(paths)
        base.update(available=True, cached=True)
    except Exception as exc:
        # local_files_only guarantees this status check never downloads.
        reason = str(exc)
        base["reason"] = "토크나이저 파일이 캐시에 없거나 읽을 수 없습니다. 준비 버튼을 눌러 고정 파일을 내려받으세요." if "LocalEntryNotFound" in type(exc).__name__ or "Cannot find the requested files" in reason else f"토크나이저 캐시를 사용할 수 없습니다: {reason[:300]}"
    return base


def _load_tokenizer() -> Any:
    global _TOKENIZER
    if _TOKENIZER is not None:
        return _TOKENIZER
    with _LOCK:
        if _TOKENIZER is None:
            paths = _cached_assets()
            _verify_assets(paths)
            from tokenizers import AddedToken, Tokenizer

            with paths["tokenizer_config.json"].open(encoding="utf-8") as stream:
                tokenizer_config = json.load(stream)
            with paths["config.json"].open(encoding="utf-8") as stream:
                model_config = json.load(stream)
            with paths["special_tokens_map.json"].open(encoding="utf-8") as stream:
                special_tokens_map = json.load(stream)

            # Mirror FastEmbed 0.9.0's context resolution for the pinned bundle.
            contexts = [
                value for value in (
                    tokenizer_config.get("model_max_length"),
                    tokenizer_config.get("max_length"),
                )
                if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_TOKENS
            ]
            if not contexts or min(contexts) != MAX_TOKENS:
                raise ValueError("고정 토크나이저 설정의 컨텍스트 길이가 512가 아닙니다.")

            _TOKENIZER = Tokenizer.from_file(str(paths["tokenizer.json"]))
            serialized_truncation = _TOKENIZER.truncation or {}
            truncation_side = (
                tokenizer_config.get("truncation_side")
                or serialized_truncation.get("direction", "right")
            )
            if truncation_side != "right":
                raise ValueError("고정 토크나이저가 오른쪽 절단을 사용하지 않습니다.")
            _TOKENIZER.enable_truncation(max_length=MAX_TOKENS, direction=truncation_side)

            for value in special_tokens_map.values():
                values = value if isinstance(value, list) else [value]
                for token in values:
                    if isinstance(token, str):
                        _TOKENIZER.add_special_tokens([token])
                    elif isinstance(token, dict):
                        _TOKENIZER.add_special_tokens([AddedToken(**token)])

            serialized_padding = _TOKENIZER.padding or {}
            pad_token = serialized_padding.get("pad_token") or tokenizer_config.get("pad_token")
            if pad_token is None:
                raise ValueError("고정 토크나이저 설정에 pad token이 없습니다.")
            pad_id = serialized_padding.get("pad_id", model_config.get("pad_token_id"))
            if pad_id is None:
                pad_id = _TOKENIZER.token_to_id(pad_token)
            if pad_id is None:
                raise ValueError("고정 토크나이저의 pad token ID를 확인할 수 없습니다.")
            _TOKENIZER.enable_padding(
                direction=tokenizer_config.get("padding_side") or serialized_padding.get("direction", "right"),
                pad_id=pad_id,
                pad_type_id=serialized_padding.get("pad_type_id", 0),
                pad_token=pad_token,
                pad_to_multiple_of=serialized_padding.get("pad_to_multiple_of"),
                length=None,
            )
    return _TOKENIZER


class _TokenizerAdapter:
    """Expose the stable encode protocol while applying right truncation."""

    def __init__(self, tokenizer: Any):
        self.tokenizer = tokenizer

    def encode(self, text: str, *, truncation: bool = False, max_length: int | None = None) -> Any:
        with _ENCODE_LOCK:
            if truncation:
                self.tokenizer.enable_truncation(max_length=max_length or MAX_TOKENS, direction="right")
            else:
                self.tokenizer.no_truncation()
            try:
                return self.tokenizer.encode(text, add_special_tokens=True)
            finally:
                # Restore the FastEmbed-configured right truncation state after
                # the full-count pass; the next request cannot observe mutation.
                self.tokenizer.enable_truncation(max_length=MAX_TOKENS, direction="right")


def preview_input(input_text: str, tokenizer: Any = None) -> dict[str, Any]:
    """Count the exact already-prefixed input and show its source-text cutoff.

    ``tokenizer`` is an injectable object with ``encode(text, *, truncation,
    max_length)`` returning ``ids`` and source-character ``offsets``. The input
    string is never changed or prefixed here.
    """
    if not isinstance(input_text, str):
        raise TypeError("input_text must be a string")
    result: dict[str, Any] = {
        "available": False, "model": MODEL, "revision": REVISION,
        "max_tokens": MAX_TOKENS, "full_token_count": 0,
        "retained_token_count": 0, "truncated": False,
        "input_text": input_text, "retained_text": "", "removed_text": "",
        "cut_char_offset": 0, "reason": None,
    }
    if not input_text.strip():
        result["reason"] = "임베딩 대상 텍스트가 비어 있습니다."
        return result
    try:
        encoder = tokenizer if tokenizer is not None else _TokenizerAdapter(_load_tokenizer())
        full = encoder.encode(input_text, truncation=False, max_length=None)
        full_count = len(full.ids)
        if full_count <= MAX_TOKENS:
            result.update(available=True, full_token_count=full_count,
                          retained_token_count=full_count, retained_text=input_text,
                          cut_char_offset=len(input_text))
            return result
        retained = encoder.encode(input_text, truncation=True, max_length=MAX_TOKENS)
        offsets = [tuple(offset) for offset in retained.offsets if tuple(offset) != (0, 0)]
        cut = max((end for _, end in offsets), default=0)
        cut = max(0, min(len(input_text), int(cut)))
        retained_text = input_text[:cut]
        result.update(available=True, full_token_count=full_count,
                      retained_token_count=len(retained.ids), truncated=True,
                      retained_text=retained_text, removed_text=input_text[cut:],
                      cut_char_offset=cut)
        return result
    except Exception as exc:
        result["reason"] = f"토큰 미리보기를 사용할 수 없습니다: {str(exc)[:300]}"
        return result


def prepare() -> dict[str, Any]:
    """Explicitly download and hash-check the four public tokenizer assets."""
    tokenizers_installed, hub_installed = _dependencies()
    if not tokenizers_installed or not hub_installed:
        return status()
    try:
        from huggingface_hub import hf_hub_download

        root = cache_path()
        root.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        # Never accept a caller-controlled repository, revision, or filename.
        for filename in ASSETS:
            paths[filename] = Path(hf_hub_download(
                repo_id=REPOSITORY, filename=filename, revision=REVISION,
                cache_dir=str(root), local_files_only=False,
            ))
        _verify_assets(paths)
        _load_tokenizer()
        return status()
    except Exception as exc:
        return {
            "available": False, "cached": False, "model": MODEL,
            "revision": REVISION, "max_tokens": MAX_TOKENS,
            "cache_path": str(cache_path()),
            "reason": f"토크나이저 준비에 실패했습니다. 네트워크와 캐시 파일을 확인한 뒤 다시 시도하세요. ({str(exc)[:300]})",
        }
