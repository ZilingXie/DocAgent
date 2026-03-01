import argparse
import sys
from pathlib import Path

from app.eval.runner import load_questions, run_evaluation
from app.qa.chain import answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run acceptance checks for Doc Agent.")
    parser.add_argument("--dataset", default="eval/questions.jsonl", help="Path to JSONL dataset.")
    parser.add_argument("--max-questions", type=int, default=0, help="Limit evaluated questions.")
    parser.add_argument(
        "--min-citation-presence",
        type=float,
        default=1.0,
        help="Minimum citation presence rate [0,1].",
    )
    parser.add_argument(
        "--max-avg-latency-ms",
        type=float,
        default=8000.0,
        help="Maximum average latency in milliseconds.",
    )
    parser.add_argument(
        "--max-insufficient-rate",
        type=float,
        default=0.4,
        help="Maximum insufficient evidence rate [0,1].",
    )
    parser.add_argument("--platform", default="", help="Metadata filter: platform")
    parser.add_argument("--product", default="", help="Metadata filter: product")
    args = parser.parse_args()

    questions = load_questions(Path(args.dataset))
    if args.max_questions > 0:
        questions = questions[: args.max_questions]

    answer_fn = lambda question: answer(
        question,
        platform=args.platform.strip() or None,
        product=args.product.strip() or None,
    )
    summary = run_evaluation(questions=questions, answer_fn=answer_fn)
    print(f"total={summary.total}")
    print(f"answered={summary.answered}")
    print(f"insufficient={summary.insufficient}")
    print(f"with_citations={summary.with_citations}")
    print(f"errors={summary.errors}")
    print(f"citation_presence={summary.citation_presence:.4f}")
    print(f"insufficient_rate={summary.insufficient_rate:.4f}")
    print(f"avg_latency_ms={summary.avg_latency_ms:.2f}")

    passed = summary.passes(
        min_citation_presence=args.min_citation_presence,
        max_avg_latency_ms=args.max_avg_latency_ms,
        max_insufficient_rate=args.max_insufficient_rate,
    )
    if passed:
        print("acceptance=PASS")
        return
    print("acceptance=FAIL")
    sys.exit(2)


if __name__ == "__main__":
    main()
