import hashlib
from pathlib import Path

import yaml
from langchain_core.documents import Document


def _parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, text

    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx == -1:
        return {}, text

    front_matter_str = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    parsed = yaml.safe_load(front_matter_str) or {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, body


def _extract_first_h1(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _infer_product(source_path: str) -> str:
    stem = Path(source_path).stem
    if "_" in stem:
        return stem.split("_", 1)[0].strip()
    return ""


def load_markdown_documents(docs_dir: Path) -> list[Document]:
    """Load markdown files into LangChain Documents with normalized metadata."""
    if not docs_dir.exists():
        return []

    docs: list[Document] = []
    for path in sorted(docs_dir.rglob("*.md")):
        raw = path.read_text(encoding="utf-8", errors="replace")
        front_matter, body = _parse_front_matter(raw)
        relative = path.relative_to(docs_dir).as_posix()
        doc_id = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:12]
        doc_hash = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        title = str(front_matter.get("title") or _extract_first_h1(body) or path.stem)
        product = str(front_matter.get("product") or _infer_product(relative))
        metadata = {
            "doc_id": doc_id,
            "doc_hash": doc_hash,
            "source_path": relative,
            "title": title,
            "product": product,
            "platform": str(front_matter.get("platform", "")),
            "source_url": str(front_matter.get("exported_from", "")),
            "exported_file": str(front_matter.get("exported_file", "")),
            "exported_on": str(front_matter.get("exported_on", "")),
        }
        docs.append(Document(page_content=body, metadata=metadata))
    return docs
