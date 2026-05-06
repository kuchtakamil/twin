# Retrieval Debugging

This project includes a local CLI for checking which chunks would be returned from
`backend/data/search_index.json` for a given user question. It does not call Bedrock
or any LLM. It only runs the deterministic retrieval layer.

## Basic Usage

Run from the repository root:

```bash
uv run python backend/debug_retrieval.py "What was your last commercial experience?" --top-k 3 --no-content
```

The output shows the chunks that would be passed to the LLM, including:

- `score` - retrieval score used for ranking
- `source` - source document type, for example `cv`, `summary`, `facts`
- `metadata` - section and other helper fields used by scoring
- `matched_terms` - query terms that matched this chunk
- `keywords` - extra ranking hints stored in the search index

## Show Chunk Content

By default, the CLI prints full chunk content. Use `--no-content` when you only want
ranking metadata.

```bash
uv run python backend/debug_retrieval.py "What was your last commercial experience?" --top-k 3
```

## Interactive Mode

Use interactive mode to test many questions quickly:

```bash
uv run python backend/debug_retrieval.py --interactive --top-k 3 --no-content
```

Then type a query and press Enter. Use `Ctrl-D` to exit.

## JSON Output

Use JSON output when comparing results automatically or saving examples:

```bash
uv run python backend/debug_retrieval.py "What AI projects have you built?" --top-k 2 --json --no-content
```

## Useful Test Questions

```text
What was your last commercial experience?
What AWS and Bedrock experience do you have?
What are your key competences?
What AI projects have you built?
What is your dream job?
```

The retrieval layer also supports a small deterministic set of Polish aliases for
common professional questions:

```text
Jakie było twoje ostatnie doświadczenie komercyjne?
Jakie masz kluczowe kompetencje?
Jakie projekty AI zbudowałeś?
Jakie masz doświadczenie z AWS i Bedrock?
Jaka jest twoja aktualna rola?
Gdzie teraz pracujesz?
Gdzie jesteś teraz zatrudniony?
```

Polish support is intentionally limited. It is not a full Polish search index or
semantic translator. The scoring layer contains deterministic aliases and phrase
intents for common recruiter-style questions. If a Polish query returns the wrong
chunk, add either:

- a narrow alias in `DOMAIN_SYNONYMS`
- a phrase intent in `backend/retrieval/scoring.py`
- structured metadata/keywords on the relevant chunk

## Interpreting Results

The first returned chunk is the one with the highest retrieval score. If the top
chunk is not the chunk you would expect to ground the answer, inspect:

- whether the expected chunk contains the relevant terms in `content`
- whether it has useful `keywords`
- whether its `metadata.section` should receive an intent boost in
  `backend/retrieval/scoring.py`
- whether the query wording needs an alias or synonym in the scoring layer

For example, a question like `What was your last commercial experience?` should
return `CV: Work Experience` near the top, because that section contains the
chronological work history needed by the LLM.
