import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.models import QAResult


@dataclass
class EvalSummary:
    total: int
    answered: int
    insufficient: int
    with_citations: int
    avg_latency_ms: float
    errors: int

    @property
    def citation_presence(self) -> float:
        if self.total == 0:
            return 0.0
        return self.with_citations / self.total

    @property
    def insufficient_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.insufficient / self.total

    def passes(
        self,
        min_citation_presence: float,
        max_avg_latency_ms: float,
        max_insufficient_rate: float,
    ) -> bool:
        if self.total == 0:
            return False
        return (
            self.citation_presence >= min_citation_presence
            and self.avg_latency_ms <= max_avg_latency_ms
            and self.insufficient_rate <= max_insufficient_rate
        )


def load_questions(dataset: Path) -> list[str]:
    if not dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset}")

    questions: list[str] = []
    with dataset.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}") from exc
            question = str(item.get("question") or item.get("q") or "").strip()
            if not question:
                raise ValueError(f"Missing question at line {line_no}")
            questions.append(question)
    return questions


def run_evaluation(
    questions: list[str],
    answer_fn: Callable[[str], QAResult] | None = None,
) -> EvalSummary:
    if answer_fn is None:
        from app.qa.chain import answer as rag_answer

        answer_fn = rag_answer

    total = len(questions)
    answered = 0
    insufficient = 0
    with_citations = 0
    latency_total = 0
    errors = 0

    for question in questions:
        try:
            result = answer_fn(question)
        except Exception:
            errors += 1
            continue

        latency_total += result.latency_ms
        if result.citations:
            with_citations += 1

        if result.answer_text.strip() == "Not enough evidence in provided docs.":
            insufficient += 1
        else:
            answered += 1

    avg_latency = 0.0 if total == 0 else latency_total / total
    return EvalSummary(
        total=total,
        answered=answered,
        insufficient=insufficient,
        with_citations=with_citations,
        avg_latency_ms=avg_latency,
        errors=errors,
    )
