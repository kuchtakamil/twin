from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache

from .schemas import DocumentChunk


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*")

STOP_WORDS = {
    "a",
    "about",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "don",
    "either",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "just",
    "me",
    "not",
    "my",
    "of",
    "on",
    "or",
    "rather",
    "tell",
    "that",
    "than",
    "the",
    "this",
    "to",
    "under",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "you",
    "your",
    "albo",
    "byl",
    "byla",
    "bylo",
    "byly",
    "byo",
    "czy",
    "dla",
    "do",
    "jak",
    "jaka",
    "jakie",
    "jaki",
    "jest",
    "jestes",
    "gdzie",
    "masz",
    "miales",
    "mial",
    "miala",
    "moje",
    "moja",
    "moj",
    "na",
    "nad",
    "o",
    "opowiedz",
    "oraz",
    "po",
    "podaj",
    "twoje",
    "twoja",
    "twoj",
    "w",
    "we",
    "z",
    "ze",
}

CURRENT_ROLE_PATTERNS = (
    re.compile(r"\b(gdzie|u kogo)\b.*\b(pracuj\w*|zatrudnion\w*)\b"),
    re.compile(r"\b(pracuj\w*|zatrudnion\w*)\b.*\b(teraz|obecnie|aktualnie)\b"),
    re.compile(r"\b(teraz|obecnie|aktualnie)\b.*\b(pracuj\w*|zatrudnion\w*)\b"),
)

DOMAIN_SYNONYMS = {
    "ai": {"artificial", "intelligence", "llm", "llms", "ml", "machine", "learning"},
    "ml": {"ai", "machine", "learning", "llm", "llms"},
    "llm": {"ai", "ml", "bedrock", "rag", "openai"},
    "rag": {"retrieval", "augmented", "generation", "llm", "ai"},
    "aws": {"amazon", "cloud", "lambda", "bedrock", "s3", "cloudfront", "terraform"},
    "cloud": {"aws", "lambda", "s3", "cloudfront", "terraform"},
    "serverless": {"lambda", "aws", "api", "gateway"},
    "infrastructure": {"terraform", "aws", "cloud"},
    "backend": {"java", "python", "api", "fastapi", "microservices"},
    "lead": {"leadership", "mentor", "mentoring", "team"},
    "leading": {"leadership", "lead", "mentor", "mentoring"},
    "communication": {"style", "communicate", "approach", "collaboration"},
    "current": {"now", "present", "currently"},
    "now": {"current", "present", "currently"},
    "aktualna": {"current", "currently", "now", "present"},
    "aktualne": {"current", "currently", "now", "present"},
    "aktualnie": {"current", "currently", "now", "present"},
    "angielski": {"english", "language", "languages"},
    "chmura": {"cloud", "aws", "lambda", "s3", "terraform"},
    "doswiadczenia": {"experience", "work", "worked"},
    "doswiadczenie": {"experience", "work", "worked"},
    "edukacja": {"education", "university", "degree"},
    "firma": {"company", "companies"},
    "firmach": {"company", "companies"},
    "firmy": {"company", "companies"},
    "jezyki": {"language", "languages", "english", "polish"},
    "komercyjne": {"commercial", "professional", "work", "experience"},
    "komercyjnego": {"commercial", "professional", "work", "experience"},
    "komercyjnym": {"commercial", "professional", "work", "experience"},
    "kompetencje": {"competence", "competences", "skill", "skills", "technology", "technologies", "stack"},
    "kontakt": {"contact", "email", "website", "linkedin"},
    "lokalizacja": {"location"},
    "mail": {"email", "contact"},
    "najnowsze": {"latest", "last", "recent"},
    "najnowszy": {"latest", "last", "recent"},
    "ostatnia": {"latest", "last", "recent"},
    "ostatnie": {"latest", "last", "recent"},
    "ostatni": {"latest", "last", "recent"},
    "poprzednia": {"previous", "last", "role", "work"},
    "poprzednie": {"previous", "last", "role", "work"},
    "poprzedni": {"previous", "last", "role", "work"},
    "praca": {"work", "job", "role"},
    "prace": {"work", "job", "role"},
    "pracujesz": {"work", "job", "role", "current"},
    "pracowales": {"worked", "work", "experience"},
    "pracowal": {"worked", "work", "experience"},
    "projekt": {"project", "projects", "built", "build", "portfolio"},
    "projektach": {"project", "projects", "built", "build", "portfolio"},
    "projekty": {"project", "projects", "built", "build", "portfolio"},
    "rola": {"role", "job", "work"},
    "stanowisko": {"role", "job", "work"},
    "styl": {"style", "communication", "communicate", "collaboration"},
    "technologia": {"technology", "technologies", "stack"},
    "technologie": {"technology", "technologies", "stack"},
    "umiejetnosci": {"skill", "skills", "competence", "competences"},
    "zbudowales": {"built", "build", "project", "projects"},
    "zbudowal": {"built", "build", "project", "projects"},
    "teraz": {"current", "currently", "now", "present"},
    "zatrudniony": {"employed", "employment", "work", "job", "role", "current"},
    "zatrudniona": {"employed", "employment", "work", "job", "role", "current"},
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


@lru_cache(maxsize=2048)
def tokenize(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    return tuple(
        token
        for raw_token in TOKEN_RE.findall(normalized)
        if (token := raw_token.strip(".-"))
        if len(token) > 1 and token not in STOP_WORDS
    )


def expand_terms(tokens: tuple[str, ...]) -> set[str]:
    expanded = set(tokens)
    for token in tokens:
        expanded.update(DOMAIN_SYNONYMS.get(token, set()))
    return expanded


def chunk_terms(chunk: DocumentChunk) -> Counter[str]:
    fields = [
        chunk.title,
        chunk.content,
        " ".join(chunk.keywords),
        " ".join(str(value) for value in chunk.metadata.values()),
    ]
    return Counter(tokenize(" ".join(fields)))


def infer_query_intents(query: str, query_terms: set[str]) -> set[str]:
    intents = set()
    normalized_query = normalize_text(query)
    if query_terms & {"current", "currently", "now", "present"}:
        intents.add("current_role")
    if any(pattern.search(normalized_query) for pattern in CURRENT_ROLE_PATTERNS):
        intents.add("current_role")
    if query_terms & {"communication", "communicate", "style", "collaboration"}:
        intents.add("work_style")
    if query_terms & {"email", "website", "linkedin", "location", "contact"}:
        intents.add("facts")
    if query_terms & {"experience", "worked", "work", "role", "company", "companies", "project", "projects"}:
        intents.add("experience")
    if query_terms & {"built", "build", "project", "projects", "portfolio"}:
        intents.add("projects")
    if query_terms & {"competence", "competences", "skill", "skills", "technology", "technologies", "stack"}:
        intents.add("skills")
    return intents


def score_chunk(
    query: str,
    chunk: DocumentChunk,
    document_frequency: dict[str, int],
    document_count: int,
) -> tuple[float, list[str]]:
    query_tokens = tokenize(query)
    query_terms = expand_terms(query_tokens)
    intents = infer_query_intents(query, query_terms)
    if not query_terms and not intents:
        return 0.0, []

    terms = chunk_terms(chunk)
    if not terms and not intents:
        return 0.0, []

    matched_terms = sorted(term for term in query_terms if term in terms)

    score = 0.0
    chunk_length = max(sum(terms.values()), 1)
    for term in matched_terms:
        tf = terms[term]
        df = document_frequency.get(term, 0)
        idf = math.log((document_count + 1) / (df + 0.5)) + 1
        score += (tf / math.sqrt(chunk_length)) * idf

    title_terms = set(tokenize(chunk.title))
    keyword_terms = set(tokenize(" ".join(chunk.keywords)))
    metadata_terms = set(tokenize(" ".join(str(value) for value in chunk.metadata.values())))

    score += len(query_terms & title_terms) * 1.5
    score += len(query_terms & keyword_terms) * 1.2
    score += len(query_terms & metadata_terms) * 0.6

    has_retrieval_signal = bool(matched_terms)
    if "current_role" in intents and chunk.metadata.get("is_current"):
        score += 3.0
        matched_terms.append("intent:current_role")
        has_retrieval_signal = True
    if "work_style" in intents and chunk.source in {"summary", "style"}:
        score += 1.5
        has_retrieval_signal = True
    if "facts" in intents and chunk.source == "facts":
        score += 2.0
        has_retrieval_signal = True
    if "experience" in intents and chunk.source == "cv":
        score += 1.0
        has_retrieval_signal = True
    if "projects" in intents and chunk.metadata.get("section") == "projects":
        score += 3.0
        has_retrieval_signal = True
    if "skills" in intents and (chunk.metadata.get("section") == "skills" or chunk.source == "summary"):
        score += 1.0
        has_retrieval_signal = True

    normalized_query = normalize_text(query)
    normalized_content = normalize_text(f"{chunk.title} {chunk.content}")
    if normalized_query and normalized_query in normalized_content:
        score += 2.0
        has_retrieval_signal = True

    if not has_retrieval_signal:
        return 0.0, []

    score += chunk.priority * 0.15

    return score, sorted(set(matched_terms))
