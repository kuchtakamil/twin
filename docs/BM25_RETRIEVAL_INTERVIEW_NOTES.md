# BM25 Retrieval - Interview Notes

## Context

The first lightweight RAG approach used a deterministic lexical retrieval layer.
The goal was to avoid introducing a vector database for a very small knowledge
base, while still separating the system into clear RAG stages:

- ingestion
- chunking
- search index generation
- retrieval
- prompt composition
- LLM generation

The retrieval layer was designed to run fully in memory. At runtime, the backend
loads a small `search_index.json`, scores all chunks against the user query, and
passes only the highest-ranking chunks to the LLM.

This approach is conceptually similar to BM25, although the current
implementation is not a full BM25Okapi implementation.

## What BM25 Is

BM25 is a classic ranking algorithm used in text search systems. It ranks
documents by estimating how relevant each document is to a search query.

It is a lexical algorithm, which means it works mainly with exact terms and term
statistics. It does not understand meaning in the way an embedding model does.

For example, if the user asks:

```text
latest commercial experience
```

BM25 looks for documents that contain important query terms such as `latest`,
`commercial`, and `experience`, or terms that were normalized into similar forms.

BM25 is commonly used as a strong baseline for search because it is:

- fast
- deterministic
- cheap to run
- easy to debug
- effective for keyword-based queries

## What BM25 Measures

BM25 scores a document based mainly on three ideas.

### 1. Term Frequency

If a query term appears in a document, that document becomes more relevant.

If the term appears several times, the document may become even more relevant,
but BM25 does not reward repetition linearly forever. After a point, repeating a
word many times adds less and less value.

This prevents a long document from winning only because it repeats the same word.

### 2. Inverse Document Frequency

Rare terms are more useful than common terms.

For example, a term like `Bedrock` or `Terraform` is more informative than a term
like `work` or `experience`.

BM25 gives more weight to terms that appear in fewer documents, because rare
terms help distinguish the best matching chunk from the rest of the corpus.

### 3. Document Length Normalization

Long documents naturally contain more words, so they have a higher chance of
matching a query accidentally.

BM25 compensates for this by normalizing the score based on document length.
This helps prevent large chunks from dominating smaller, more precise chunks.

## Why This Was Useful For The Project

For this project, the knowledge base is small and mostly structured:

- profile facts
- professional summary
- CV sections
- work experience
- projects
- skills

Because of that, a simple in-memory retrieval layer was attractive. It allowed
the backend to behave more like a RAG system without adding operational
complexity such as PostgreSQL, pgvector, OpenSearch, or a managed vector
database.

The main benefits were:

- no additional infrastructure
- no database migrations
- very low latency
- deterministic behavior
- easy local testing
- simple debugging through a CLI tool

For a small personal AI profile, this is a reasonable first step because the
retrieval problem is limited and the corpus can be inspected manually.

## How Our Implementation Was BM25-Like

The implemented scoring was inspired by BM25, but simplified.

It used:

- query tokenization
- stop-word filtering
- matching query terms against chunk content and keywords
- stronger weighting for rare or domain-specific terms
- metadata boosts for important facts
- section-level boosts for intents like current role, projects, skills, and work
  experience

In other words, the system did not just concatenate all profile information into
the prompt. It first selected likely relevant chunks and only then passed them to
the LLM.

That is the important architectural point for an interview:

```text
I separated retrieval from generation. Before calling the LLM, the backend runs a
deterministic retrieval step over a small local index and injects only the most
relevant chunks into the prompt.
```

## Why It Was Not Full BM25

The implementation was intentionally lighter than full BM25.

It did not use the complete BM25Okapi formula with tuned `k1` and `b`
parameters. It also added project-specific rules that classical BM25 does not
know about, such as:

- boosting the current role chunk for questions about current employment
- boosting the projects section for project-related questions
- boosting the work experience section for experience-related questions
- using curated keywords generated during ingestion

This made sense because the corpus was small and domain-specific. For a personal
CV assistant, metadata can be more useful than pure statistical ranking.

## Limitations Discovered

The main limitation was that lexical retrieval depends heavily on words matching.

It works well when the user query and the indexed text use similar vocabulary.
It becomes weaker when the user uses:

- another language
- paraphrases
- synonyms
- informal phrasing
- questions that imply meaning without sharing the same words

For example, English queries like:

```text
What was your last commercial experience?
```

can be handled reasonably well if the index contains related words such as
`work`, `experience`, `commercial`, `current`, or `previous`.

However, Polish questions like:

```text
Gdzie teraz pracujesz?
Gdzie jestes teraz zatrudniony?
```

are much harder for lexical scoring if the source content is in English. The
retrieval layer would need to know that:

- `pracujesz` relates to `work`
- `zatrudniony` relates to `employed`
- `teraz` relates to `current`
- the whole phrase asks about current employment

Some of this can be patched with aliases and intent rules, but that approach
does not scale. It becomes a manually maintained synonym map rather than robust
semantic retrieval.

## Why We Decided To Explore Another Approach

The BM25-like approach proved useful as a first stage because it created a real,
testable retrieval pipeline. It also made the system more transparent: we could
inspect exactly which chunks were selected and why.

But the quality issues showed that keyword retrieval is not enough for a
multilingual conversational assistant.

The next logical step is multilingual semantic retrieval with embeddings. In that
approach, the query and chunks are compared by meaning rather than by exact word
overlap. That should handle Polish questions against English CV content much
better, without requiring a manually curated synonym list for every possible
phrase.

## Interview Summary

A concise way to describe this stage:

```text
I first implemented a lightweight, in-memory RAG retrieval layer inspired by
BM25. The system generated structured chunks from profile and CV data, built a
small JSON search index, and scored all chunks against the user query before
calling the LLM. This gave me a cheap and deterministic retrieval baseline
without adding a vector database.

During evaluation I found the expected limitation of lexical search: it works
well for matching vocabulary, but it struggles with paraphrases and multilingual
queries, especially Polish questions over English CV content. That evaluation
led me to move toward multilingual embeddings and hybrid retrieval, keeping the
debuggable BM25-style layer as a baseline or secondary signal.
```

## Useful Interview Phrases

- "I treated BM25-style retrieval as a baseline before introducing vector
  search."
- "The first version was intentionally infrastructure-light: a JSON index loaded
  into memory inside Lambda."
- "The system separated retrieval from generation, which is the core RAG
  architectural improvement over context stuffing."
- "The main tradeoff was transparency and simplicity versus semantic recall."
- "The evaluation showed that lexical retrieval is not robust enough for
  multilingual queries, so embeddings are the next step."
- "I would keep keyword retrieval as part of a hybrid search strategy, because it
  is still useful for exact technologies, company names, and proper nouns."
