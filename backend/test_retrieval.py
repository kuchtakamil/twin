import json

from ingest import (
    CV_SECTION_TITLES,
    infer_keywords,
    join_pdf_lines,
    make_chunk,
    redact_sensitive_data,
    split_titled_sections,
    write_index,
)
from retrieval.index import SearchIndex, read_index_file
from retrieval.scoring import tokenize
from retrieval.schemas import DocumentChunk


def test_tokenize_normalizes_accents_and_removes_stop_words():
    assert tokenize("What is your experience in Kraków with AWS?") == (
        "experience",
        "krakow",
        "aws",
    )


def test_retrieve_ranks_technology_match_first():
    index = SearchIndex(
        [
            DocumentChunk(
                id="style-1",
                source="style",
                title="Communication style",
                content="Professional, concise, and practical communication.",
                keywords=["communication", "style"],
                priority=1,
            ),
            DocumentChunk(
                id="cv-aws-1",
                source="cv",
                title="Cloud infrastructure experience",
                content="Built backend services on AWS Lambda, S3, CloudFront, and Terraform.",
                metadata={"section": "cv", "skills": ["aws", "lambda", "terraform"]},
                keywords=["aws", "lambda", "terraform", "cloud"],
                priority=3,
            ),
        ]
    )

    results = index.retrieve("What AWS and Terraform experience do you have?", top_k=2)

    assert results[0].chunk.id == "cv-aws-1"
    assert {"aws", "terraform"} <= set(results[0].matched_terms)


def test_retrieve_handles_polish_query_aliases():
    index = SearchIndex(
        [
            DocumentChunk(
                id="facts-previous-role",
                source="facts",
                title="Previous Role",
                content="Previous Role: Senior Software Engineer",
                metadata={"field": "previous_role"},
                keywords=["previous role", "senior software engineer"],
                priority=3,
            ),
            DocumentChunk(
                id="cv-work-experience",
                source="cv",
                title="CV: Work Experience",
                content="09.2024 – 10.2025 Senior Software Engineer, Jacobs. Tech stack: Java, Python, AWS.",
                metadata={"section": "work_experience"},
                keywords=["jacobs", "java", "python", "aws"],
                priority=4,
            ),
            DocumentChunk(
                id="summary",
                source="summary",
                title="Professional summary",
                content="I do not have commercial experience in AI/ML.",
                metadata={"section": "professional_summary"},
                keywords=["commercial", "ai/ml"],
                priority=4,
            ),
        ]
    )

    results = index.retrieve("Jakie było twoje ostatnie doświadczenie komercyjne?", top_k=3)

    assert results[0].chunk.id == "cv-work-experience"
    assert {"experience", "work"} <= set(results[0].matched_terms)


def test_retrieve_handles_polish_current_employment_questions():
    index = SearchIndex(
        [
            DocumentChunk(
                id="facts-current-role",
                source="facts",
                title="Current Role",
                content="Current Role: unemployed, during a transition to become AI Engineer",
                metadata={"field": "current_role", "is_current": True},
                keywords=["current role", "ai engineer"],
                priority=5,
            ),
            DocumentChunk(
                id="facts-previous-role",
                source="facts",
                title="Previous Role",
                content="Previous Role: Senior Software Engineer",
                metadata={"field": "previous_role"},
                keywords=["previous role", "senior software engineer"],
                priority=3,
            ),
        ]
    )

    first_results = index.retrieve("gdzie teraz pracujesz", top_k=2)
    second_results = index.retrieve("gdzie jesteś teraz zatrudniony", top_k=2)

    assert first_results[0].chunk.id == "facts-current-role"
    assert second_results[0].chunk.id == "facts-current-role"
    assert "intent:current_role" in first_results[0].matched_terms
    assert "intent:current_role" in second_results[0].matched_terms


def test_retrieve_boosts_project_section_for_project_questions():
    index = SearchIndex(
        [
            DocumentChunk(
                id="summary-dream",
                source="summary",
                title="Dream job",
                content="I want to work deeply with AI, LLMs, and inference.",
                metadata={"section": "dream_job"},
                keywords=["ai engineer", "llm"],
                priority=4,
            ),
            DocumentChunk(
                id="cv-projects",
                source="cv",
                title="CV: Projects",
                content="Built a digital twin with RAG, Python, FastAPI, AWS Bedrock, Lambda, and S3.",
                metadata={"section": "projects"},
                keywords=["digital twin", "rag", "python", "aws bedrock"],
                priority=4,
            ),
        ]
    )

    results = index.retrieve("What AI projects have you built?", top_k=2)

    assert results[0].chunk.id == "cv-projects"


def test_retrieve_respects_max_chars_after_first_result():
    index = SearchIndex(
        [
            DocumentChunk(
                id="cv-1",
                source="cv",
                title="AWS Lambda",
                content="AWS Lambda " * 30,
                keywords=["aws", "lambda"],
            ),
            DocumentChunk(
                id="cv-2",
                source="cv",
                title="AWS Terraform",
                content="AWS Terraform " * 30,
                keywords=["aws", "terraform"],
            ),
        ]
    )

    results = index.retrieve("AWS", top_k=2, max_chars=50)

    assert len(results) == 1


def test_make_chunk_redacts_private_phone_numbers():
    chunk = make_chunk(
        source="cv",
        title="Contact",
        content="Phone: +48 602 731 889. Email: work@example.com",
    )

    assert "+48" not in chunk.content
    assert "602" not in chunk.content
    assert "[private phone redacted]" in chunk.content


def test_cv_sections_are_split_by_known_headings():
    text = """KAMIL KUCHTA
Senior Software Engineer
ABOUT ME
About content.
KEY COMPETENCES
Skills content.
WORK EXPERIENCE
Experience content.
"""

    sections = split_titled_sections(text, CV_SECTION_TITLES)

    assert [(title, key) for title, key, _ in sections] == [
        ("About Me", "about_me"),
        ("Key Competences", "skills"),
        ("Work Experience", "work_experience"),
    ]
    assert sections[2][2] == ["Experience content."]


def test_join_pdf_lines_repairs_hyphenated_line_breaks_and_keeps_entries_separate():
    content = join_pdf_lines(
        [
            "Project: Built secure backend services for mission-critical com-",
            "munications.",
            "Tech stack: Java, Python",
            "03.2023 – 08.2024 Senior Software Engineer, Motorola Solutions",
        ]
    )

    assert "communications" in content
    assert "com- munications" not in content
    assert "Tech stack: Java, Python\n03.2023" in content


def test_infer_keywords_prefers_domain_phrases_over_generic_terms():
    keywords = infer_keywords(
        "Project: Digital Twin. Tech stack: Python, FastAPI, AWS Bedrock, Lambda, S3, Terraform."
    )

    assert keywords[:7] == [
        "digital twin",
        "aws",
        "aws bedrock",
        "bedrock",
        "lambda",
        "s3",
        "terraform",
    ]
    assert "project" not in keywords
    assert "tech" not in keywords


def test_redact_sensitive_data_keeps_non_phone_dates():
    text = "Worked from 09.2024 to 10.2025. Phone +48 602 731 889."

    redacted = redact_sensitive_data(text)

    assert "09.2024" in redacted
    assert "10.2025" in redacted
    assert "+48" not in redacted


def test_index_file_round_trip(tmp_path):
    output_path = tmp_path / "search_index.json"
    chunks = [
        DocumentChunk(
            id="facts-current-role",
            source="facts",
            title="Current Role",
            content="Current Role: AI Engineer",
            metadata={"is_current": True},
            keywords=["current role", "ai engineer"],
            priority=5,
        )
    ]

    write_index(chunks, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    loaded_chunks = read_index_file(output_path)

    assert payload["schema_version"] == 1
    assert payload["chunk_count"] == 1
    assert loaded_chunks == chunks
