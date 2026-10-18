"""Static acceptance checks for the Cycle 21 novice README lookup flow."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    module = (ROOT / "es_rag_tuner" / "__init__.py").read_text(encoding="utf-8")
    html = (ROOT / "es_rag_tuner" / "web" / "index.html").read_text(encoding="utf-8")

    section_match = re.search(r"(?ms)^### 개념 검색 실험\s*$\n(.*?)(?=^## [^#]|\Z)", readme)
    assert section_match, "Concept-search workflow section was not found"
    section = section_match.group(1)
    step_match = re.search(r"(?m)^6\. (.+)$", section)
    assert step_match, "Concept workflow step 6 was not found"
    step = step_match.group(1)
    assert "ID를 모르면" in step and "문서가 결과에 없고 ID를 모르면" in step, step
    assert "문서 ID가 필요" not in step and "문서 ID를 입력해야" not in step, step

    links = re.findall(r"\[[^\]]+\]\((#[^)]+)\)", step)
    assert links, "Step 6 must link to the existing novice workflow heading"
    headings = re.findall(r"(?m)^#{1,6} +(.+?)\s*#*\s*$", readme)
    slug_map = {}
    for heading in headings:
        slug = re.sub(r"[^\w\- ]", "", heading.lower(), flags=re.UNICODE)
        slug = re.sub(r"\s", "-", slug.strip())
        slug_map[f"#{slug}"] = heading
    assert any(link in slug_map and "초보자" in slug_map[link] for link in links), (
        f"Step 6 internal link does not resolve to novice heading: {links}"
    )

    sequence = ["후보를 선택", "문서 ID가 채워집니다", "저장 질의를 선택", "빠진 이유 확인", "문서 불러와 평가"]
    positions = [step.find(phrase) for phrase in sequence]
    assert all(position >= 0 for position in positions) and positions == sorted(positions), (
        f"Candidate selection → query choice → diagnosis/load sequence incomplete or out of order: {step}"
    )
    assert "문서 ID를 알고 있다면 직접 입력" in step, "Manual ID entry alternative was removed"
    assert "후보가 없더라도 문서가 인덱스에 없다는 뜻은 아닙니다" in step, (
        "No-result limitation was removed or weakened"
    )

    project_version = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)', pyproject)
    module_version = re.search(r'(?m)^__version__\s*=\s*["\']([^"\']+)', module)
    ui_version = re.search(r'id="server-version">v([^<]+)</span>', html)
    versions = [match.group(1) if match else None for match in (project_version, module_version, ui_version)]
    assert versions == ["0.17.2"] * 3, f"Project/module/UI versions must all be 0.17.2, got {versions}"

    print("Cycle 21 README and version checks: PASS")
    print(f"Resolved link: {links} -> {slug_map[links[0]] if links[0] in slug_map else 'validated target'}")
    print(f"Versions: pyproject={versions[0]}, module={versions[1]}, UI={versions[2]}")


if __name__ == "__main__":
    check()
