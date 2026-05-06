from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from retrieval.schemas import DocumentChunk
from retrieval.scoring import tokenize


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_OUTPUT_PATH = DATA_DIR / "search_index.json"

SECTION_RE = re.compile(r"\n\s*\n+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\d[\s.-]?){8,14}(?!\w)")
CV_CONSENT_RE = re.compile(r"\bI hereby consent to my personal data\b.*", re.IGNORECASE | re.DOTALL)
CV_SECTION_TITLES = {
    "ABOUT ME": "about_me",
    "KEY COMPETENCES": "skills",
    "WORK EXPERIENCE": "work_experience",
    "EDUCATION": "education",
    "LANGUAGES": "languages",
    "PROJECTS": "projects",
    "TRAININGS": "trainings",
}
SUMMARY_SECTION_RE = re.compile(r"(?im)^([A-Z][A-Za-z /&+-]{2,40}):\s*$")

DOMAIN_KEYWORD_PHRASES = (
    "ai engineer",
    "ai engineer lead",
    "artificial intelligence",
    "large language models",
    "machine learning",
    "ai/ml",
    "ai-driven",
    "digital twin",
    "equity valuation",
    "youtube transcript",
    "infographic generator",
    "generative ai",
    "prompt engineering",
    "context engineering",
    "rag architecture",
    "retrieval augmented generation",
    "vector databases",
    "llm integration",
    "multi-agent orchestration",
    "agentic workflows",
    "backend services",
    "backend development",
    "microservices architecture",
    "rest api",
    "api design",
    "api development",
    "cloud infrastructure",
    "mission-critical systems",
    "fault tolerance",
    "high availability",
    "public key infrastructure",
    "automated data ingestion",
    "document parsing",
    "code review",
    "knowledge sharing",
    "requirements analysis",
    "aws",
    "aws bedrock",
    "aws lambda",
    "bedrock",
    "lambda",
    "s3",
    "amazon s3",
    "cloudfront",
    "terraform",
    "kubernetes",
    "docker",
    "jenkins",
    "fastapi",
    "llm",
    "llms",
    "rag",
    "python",
    "java",
    "erlang",
    "elixir",
    "kotlin",
    "typescript",
    "angular",
    "spring",
    "spring boot",
    "postgresql",
    "sql",
    "bash",
    "agile",
    "scrum",
    "kanban",
    "langchain",
    "langgraph",
    "chromadb",
    "gemini api",
    "luigi",
    "github actions",
    "jacobs",
    "motorola solutions",
    "uk home office",
    "pa consulting",
    "dimetra",
    "astro",
    "pslte",
    "b2b",
    "remote",
    "hybrid",
)
GENERIC_KEYWORD_TERMS = {
    "actually",
    "advertised",
    "although",
    "application",
    "applications",
    "architectures",
    "automates",
    "automation",
    "based",
    "become",
    "bridging",
    "build",
    "building",
    "built",
    "case",
    "component",
    "considering",
    "consent",
    "contact",
    "consume",
    "course",
    "currently",
    "daily",
    "data",
    "days",
    "deep",
    "defect",
    "degree",
    "department",
    "developed",
    "designed",
    "development",
    "domain",
    "dream",
    "either",
    "eager",
    "engineer",
    "engineering",
    "experience",
    "field",
    "feature",
    "focused",
    "framework",
    "frameworks",
    "fully",
    "genuinely",
    "hands-on",
    "hardware",
    "helps",
    "hood",
    "ideally",
    "implemented",
    "impact",
    "inference",
    "integration",
    "innovative",
    "job",
    "latest",
    "mainly",
    "manager",
    "maturity",
    "models",
    "mostly",
    "native",
    "office",
    "ongoing",
    "part",
    "people",
    "permanent",
    "practice",
    "practical",
    "processing",
    "product",
    "professional",
    "project",
    "projects",
    "public",
    "purpose",
    "real-world",
    "recently",
    "role",
    "senior",
    "ship",
    "simple",
    "something",
    "software",
    "solution",
    "solutions",
    "stack",
    "study",
    "studying",
    "systems",
    "tech",
    "technologies",
    "technology",
    "transition",
    "training",
    "understand",
    "vacancy",
    "want",
    "work",
    "worked",
    "working",
    "wrappers",
}


def stable_chunk_id(source: str, title: str, content: str) -> str:
    digest = hashlib.sha1(f"{source}\n{title}\n{content}".encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return f"{source}-{slug}-{digest}"


def make_chunk(
    source: str,
    title: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    keywords: list[str] | None = None,
    priority: int = 0,
) -> DocumentChunk:
    cleaned_content = normalize_whitespace(redact_sensitive_data(content))
    cleaned_title = normalize_whitespace(title)
    cleaned_keywords = list(dict.fromkeys(keywords or infer_keywords(f"{cleaned_title} {cleaned_content}")))
    return DocumentChunk(
        id=stable_chunk_id(source, cleaned_title, cleaned_content),
        source=source,
        title=cleaned_title,
        content=cleaned_content,
        metadata=metadata or {},
        keywords=cleaned_keywords,
        priority=priority,
    )


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def redact_sensitive_data(value: str) -> str:
    return PHONE_RE.sub("[private phone redacted]", value)


def infer_keywords(value: str, limit: int = 24) -> list[str]:
    normalized_value = f" {normalize_whitespace(value).lower()} "
    value_tokens = tokenize(value)
    keywords: list[str] = []
    for phrase in DOMAIN_KEYWORD_PHRASES:
        phrase_tokens = tokenize(phrase)
        if phrase in normalized_value or contains_token_sequence(value_tokens, phrase_tokens):
            keywords.append(phrase)

    tokens = tokenize(value)
    counts: dict[str, int] = {}
    for token in tokens:
        if not is_keyword_candidate(token):
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts, key=lambda token: (-counts[token], token))
    keywords.extend(ranked)
    return list(dict.fromkeys(keywords))[:limit]


def contains_token_sequence(tokens: tuple[str, ...], phrase_tokens: tuple[str, ...]) -> bool:
    if not phrase_tokens or len(phrase_tokens) > len(tokens):
        return False
    window_size = len(phrase_tokens)
    return any(tokens[index : index + window_size] == phrase_tokens for index in range(len(tokens) - window_size + 1))


def is_keyword_candidate(token: str) -> bool:
    if len(token) < 3:
        return False
    if token in GENERIC_KEYWORD_TERMS:
        return False
    if any(character.isdigit() for character in token):
        return False
    return True


def chunk_long_text(
    source: str,
    title: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    target_words: int = 180,
    overlap_words: int = 25,
    priority: int = 0,
) -> list[DocumentChunk]:
    paragraphs = [normalize_whitespace(part) for part in SECTION_RE.split(text) if normalize_whitespace(part)]
    chunks: list[DocumentChunk] = []
    current: list[str] = []
    current_word_count = 0

    def flush() -> None:
        nonlocal current, current_word_count
        if not current:
            return
        content = "\n\n".join(current)
        chunk_number = len(chunks) + 1
        chunk_title = title if len(paragraphs) == 1 else f"{title} #{chunk_number}"
        chunks.append(
            make_chunk(
                source=source,
                title=chunk_title,
                content=content,
                metadata={**(metadata or {}), "chunk_number": chunk_number},
                priority=priority,
            )
        )
        words = content.split()
        overlap = " ".join(words[-overlap_words:]) if overlap_words > 0 else ""
        current = [overlap] if overlap else []
        current_word_count = len(overlap.split())

    for paragraph in paragraphs:
        paragraph_word_count = len(paragraph.split())
        if current and current_word_count + paragraph_word_count > target_words:
            flush()
        current.append(paragraph)
        current_word_count += paragraph_word_count

    flush()
    return chunks


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as file:
        return file.read()


def read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def split_titled_sections(
    text: str,
    known_titles: dict[str, str],
) -> list[tuple[str, str, list[str]]]:
    sections: list[tuple[str, str, list[str]]] = []
    current_title: str | None = None
    current_key: str | None = None
    current_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper_line = line.upper()
        if upper_line in known_titles:
            if current_title and current_key and current_lines:
                sections.append((current_title, current_key, current_lines))
            current_title = upper_line.title()
            current_key = known_titles[upper_line]
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)

    if current_title and current_key and current_lines:
        sections.append((current_title, current_key, current_lines))

    return sections


def join_pdf_lines(lines: list[str]) -> str:
    paragraphs: list[str] = []
    current = ""
    for line in lines:
        if not current:
            current = line
            continue
        if current.endswith("-"):
            current = f"{current[:-1]}{line}"
        elif line.startswith(("•", "-", "Tech stack:", "Tech:")) or re.match(r"^\d{2}\.\d{4}\s+[–-]\s+\d{2}\.\d{4}", line):
            paragraphs.append(current)
            current = line
        else:
            current = f"{current} {line}"
    if current:
        paragraphs.append(current)
    return "\n".join(paragraphs)


def split_summary_sections(text: str) -> list[tuple[str, str]]:
    matches = list(SUMMARY_SECTION_RE.finditer(text))
    if not matches:
        return [("Professional summary", text)]

    sections: list[tuple[str, str]] = []
    first_match = matches[0]
    intro = text[: first_match.start()].strip()
    if intro:
        sections.append(("Professional summary", intro))

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            sections.append((match.group(1).strip(), content))

    return sections


def build_facts_chunks(data_dir: Path) -> list[DocumentChunk]:
    facts = read_json(data_dir / "facts.json")
    public_fields = {
        "full_name",
        "name",
        "previous_role",
        "current_role",
        "location",
        "email",
        "website",
        "linkedin",
    }
    chunks: list[DocumentChunk] = []
    for key in sorted(public_fields & facts.keys()):
        value = facts[key]
        title = key.replace("_", " ").title()
        chunks.append(
            make_chunk(
                source="facts",
                title=title,
                content=f"{title}: {value}",
                metadata={"field": key, "visibility": "public", "is_current": key == "current_role"},
                keywords=[key.replace("_", " "), str(value)],
                priority=5 if key in {"current_role", "full_name", "name"} else 3,
            )
        )
    return chunks


def build_summary_chunks(data_dir: Path) -> list[DocumentChunk]:
    text = read_text(data_dir / "summary.txt")
    return [
        make_chunk(
            source="summary",
            title=title,
            content=content,
            metadata={"section": re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_"), "visibility": "public"},
            priority=4,
        )
        for title, content in split_summary_sections(text)
    ]


def build_style_chunks(data_dir: Path) -> list[DocumentChunk]:
    text = read_text(data_dir / "style.txt")
    return [
        make_chunk(
            source="style",
            title="Communication style",
            content=text,
            metadata={"section": "style", "visibility": "public"},
            priority=2,
        )
    ]


def build_cv_chunks(data_dir: Path) -> list[DocumentChunk]:
    cv_path = data_dir / "cv.pdf"
    if not cv_path.exists():
        return []
    text = read_pdf_text(cv_path)
    if not normalize_whitespace(text):
        return []
    text = CV_CONSENT_RE.sub("", text)
    sections = split_titled_sections(text, CV_SECTION_TITLES)
    if not sections:
        return chunk_long_text(
            source="cv",
            title="CV",
            text=text,
            metadata={"section": "cv", "visibility": "public"},
            target_words=240,
            overlap_words=0,
            priority=3,
        )

    chunks: list[DocumentChunk] = []
    for title, section_key, lines in sections:
        content = join_pdf_lines(lines)
        chunks.append(
            make_chunk(
                source="cv",
                title=f"CV: {title}",
                content=content,
                metadata={"section": section_key, "visibility": "public"},
                priority=4 if section_key in {"skills", "work_experience", "projects"} else 3,
            )
        )
    return chunks


def build_index(data_dir: Path = DATA_DIR) -> list[DocumentChunk]:
    return [
        *build_facts_chunks(data_dir),
        *build_summary_chunks(data_dir),
        *build_style_chunks(data_dir),
        *build_cv_chunks(data_dir),
    ]


def write_index(chunks: list[DocumentChunk], output_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    payload = {
        "schema_version": 1,
        "chunk_count": len(chunks),
        "chunks": [chunk.to_dict() for chunk in chunks],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the lightweight RAG search index.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    chunks = build_index(args.data_dir)
    write_index(chunks, args.output)
    print(f"Wrote {len(chunks)} chunks to {args.output}")


if __name__ == "__main__":
    main()
