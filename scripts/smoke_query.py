import argparse

from app.qa.chain import answer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--q", required=True, help="Question")
    parser.add_argument("--platform", default="", help="Metadata filter: platform")
    parser.add_argument("--product", default="", help="Metadata filter: product")
    args = parser.parse_args()
    result = answer(
        args.q,
        platform=args.platform.strip() or None,
        product=args.product.strip() or None,
    )
    print(result.answer_text)
    if result.citations:
        print("\nSources:")
        for citation in result.citations:
            print(f"- {citation.chunk_id} | {citation.source_path} | {citation.heading}")


if __name__ == "__main__":
    main()
