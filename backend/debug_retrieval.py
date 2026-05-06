from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from retrieval.index import load_search_index
from retrieval.schemas import RetrievedChunk


def result_to_dict(result: RetrievedChunk, include_content: bool = True) -> dict[str, Any]:
    chunk = result.chunk
    payload: dict[str, Any] = {
        "score": round(result.score, 3),
        "matched_terms": result.matched_terms,
        "id": chunk.id,
        "source": chunk.source,
        "title": chunk.title,
        "metadata": chunk.metadata,
        "keywords": chunk.keywords,
    }
    if include_content:
        payload["content"] = chunk.content
    return payload


def print_text_results(query: str, results: list[RetrievedChunk], show_content: bool) -> None:
    print(f"Query: {query}")
    print(f"Returned chunks: {len(results)}")
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        print()
        print(f"{index}. {chunk.title}")
        print(f"   score: {result.score:.3f}")
        print(f"   source: {chunk.source}")
        print(f"   metadata: {json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True)}")
        print(f"   matched_terms: {', '.join(result.matched_terms) or '-'}")
        print(f"   keywords: {', '.join(chunk.keywords) or '-'}")
        if show_content:
            print("   content:")
            print(indent(chunk.content, "     "))


def indent(value: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in value.splitlines())


def retrieve_once(
    query: str,
    top_k: int,
    max_chars: int,
    index_path: str | None,
) -> list[RetrievedChunk]:
    index = load_search_index(index_path)
    return index.retrieve(query, top_k=top_k, max_chars=max_chars)


def run_query(args: argparse.Namespace, query: str) -> None:
    results = retrieve_once(
        query=query,
        top_k=args.top_k,
        max_chars=args.max_chars,
        index_path=args.index_path,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "query": query,
                    "returned_chunk_count": len(results),
                    "chunks": [result_to_dict(result, include_content=not args.no_content) for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_text_results(query, results, show_content=not args.no_content)


def run_interactive(args: argparse.Namespace) -> None:
    print("Retrieval debug mode. Type a query and press Enter. Ctrl-D exits.")
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            print()
            return
        if not query:
            continue
        run_query(args, query)
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug lightweight RAG retrieval results.")
    parser.add_argument("query", nargs="*", help="Question to retrieve chunks for.")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum number of chunks to return.")
    parser.add_argument("--max-chars", type=int, default=10_000, help="Maximum total content characters.")
    parser.add_argument("--index-path", help="Path to search_index.json. Defaults to backend/data/search_index.json.")
    parser.add_argument("--no-content", action="store_true", help="Hide chunk content in the output.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--interactive", "-i", action="store_true", help="Read multiple queries interactively.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    query = " ".join(args.query).strip()
    if query:
        run_query(args, query)
        return
    if args.interactive or sys.stdin.isatty():
        run_interactive(args)
        return
    stdin_query = sys.stdin.read().strip()
    if not stdin_query:
        raise SystemExit("Provide a query argument, stdin input, or use --interactive.")
    run_query(args, stdin_query)


if __name__ == "__main__":
    main()
