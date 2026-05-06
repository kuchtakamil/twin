# Lightweight RAG Implementation Plan

## Cel

Przebudowac obecny mechanizm context stuffing na lekki RAG bez bazy wektorowej. Projekt ma pozostac prosty operacyjnie, tani w utrzymaniu i kompatybilny z obecna architektura AWS: API Gateway, Lambda, S3, CloudFront, Bedrock i Terraform.

Glowna decyzja architektoniczna: nie dodajemy PostgreSQL, pgvector ani zewnetrznej vector DB, bo korpus wiedzy jest maly i w duzej czesci ustrukturyzowany. Zamiast tego budujemy deterministyczny retrieval layer oparty o chunking, indeks tekstowy, scoring, metadane, budzet kontekstu i ewaluacje jakosci wyszukiwania.

## Aktualny Stan

Backend laduje dane z `backend/data/` i sklada jeden duzy system prompt w `backend/context.py`.

Obecnie do modelu trafia:

- `facts.json`
- `summary.txt`
- `cv.pdf`
- reguly stylu i guardrails
- historia rozmowy

To dziala przy malym zbiorze danych, ale ma ograniczenia:

- brak jawnego retrieval pipeline
- brak testow jakosci wyszukiwania
- brak informacji, ktore zrodla zostaly uzyte
- koszt tokenow rosnie wraz z kazdym dopisanym dokumentem
- rekruter widzi raczej prosty prompt wrapper niz swiadomie zaprojektowany RAG

## Docelowa Architektura

```text
backend/data/*
        |
        v
backend/ingest.py
        |
        v
backend/data/search_index.json
        |
        v
Lambda cold start: load index into memory
        |
        v
POST /chat
        |
        v
retrieval.retrieve(query)
        |
        v
context.build_prompt(retrieved_chunks)
        |
        v
AWS Bedrock Converse API
```

Na AWS indeks moze byc:

- spakowany razem z kodem Lambdy jako `backend/data/search_index.json`
- opcjonalnie ladowany z S3 przy cold starcie, jesli indeks ma byc aktualizowany bez redeployu Lambdy

Rekomendacja na pierwszy etap: pakowac indeks razem z Lambda deployment package. To upraszcza deploy, usuwa dodatkowy runtime dependency od S3 dla wiedzy bazowej i jest wystarczajace przy malym korpusie.

## Zakres Implementacji

### 1. Model Danych Dla Chunkow

Dodac `backend/retrieval/schemas.py`.

Proponowany model:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    source: str
    title: str
    content: str
    metadata: dict[str, Any]
    keywords: list[str]
    priority: int
```

Przykladowe `source`:

- `facts`
- `summary`
- `cv`
- `style`

Przykladowe metadane:

- `section`
- `company`
- `role`
- `date_start`
- `date_end`
- `is_current`
- `skills`
- `visibility`

### 2. Ingestion Pipeline

Dodac `backend/ingest.py`.

Zadania:

- czytanie `facts.json`
- czytanie `summary.txt`
- czytanie `style.txt`
- ekstrakcja tekstu z `cv.pdf`
- podzial tekstu na chunki
- wzbogacenie chunkow o metadane
- zapis `backend/data/search_index.json`

Chunking powinien byc zalezny od typu zrodla:

| Zrodlo | Strategia |
|---|---|
| `facts.json` | jeden chunk per istotne pole albo grupa pol |
| `summary.txt` | sekcje semantyczne / akapity |
| `cv.pdf` | sekcje doswiadczenia, projekty, umiejetnosci |
| `style.txt` | osobny chunk uzywany glownie do tonu, nie do faktow zawodowych |

Wazne: ingestion powinien byc deterministyczny. Ten sam input powinien generowac ten sam indeks, zeby testy i review byly stabilne.

### 3. Retrieval Bez Vector DB

Dodac modul `backend/retrieval/`.

Proponowane pliki:

```text
backend/retrieval/
  __init__.py
  index.py
  scoring.py
  schemas.py
```

`index.py`:

- laduje `search_index.json`
- trzyma indeks w pamieci procesu
- udostepnia `retrieve(query, top_k, max_chars)`

`scoring.py`:

- normalizacja tekstu
- tokenizacja
- keyword overlap
- scoring BM25-like albo TF-IDF-like
- boosty za metadane
- boost za aktualna role
- boost za dokladne dopasowanie technologii

Przykladowe boosty:

- pytanie o `current`, `now`, `currently` -> boost `is_current=true`
- pytanie o AWS -> boost chunkow z `skills=["aws", "lambda", "bedrock", "terraform"]`
- pytanie o styl pracy -> boost `source=summary`, nie `cv`
- pytanie o prywatne dane -> brak retrieval albo retrieval tylko publicznych faktow

### 4. Budowanie Promptu

Zmodyfikowac `backend/context.py`.

Prompt powinien skladac sie z:

- stalej tozsamosci
- guardrails
- aktualnej daty
- krotkich faktow bazowych, np. imie i rola
- sekcji `RETRIEVED CONTEXT`
- zasad korzystania ze zrodel

Nie powinien juz zawierac calego CV.

Przykladowa struktura:

```text
# IDENTITY
...

# RETRIEVED CONTEXT
[source=cv, title="Senior Backend Engineer at X", score=8.4]
...

# ANSWERING RULES
- Use only retrieved context and stable facts.
- If retrieved context is insufficient, say that you do not have that information.
- Do not reveal private data.
```

`prompt()` powinno przyjmowac pytanie albo gotowe chunki:

```python
def prompt(user_query: str, retrieved_chunks: list[RetrievedChunk]) -> str:
    ...
```

### 5. Integracja Z `/chat`

Zmodyfikowac `backend/server.py`.

Docelowy flow:

```text
load_conversation(session_id)
retrieve(request.message)
build_prompt(request.message, retrieved_chunks)
call_bedrock(prompt, conversation, request.message)
save_conversation(session_id, updated_conversation)
```

Warto rozszerzyc `ChatResponse` o opcjonalne zrodla:

```python
class Source(BaseModel):
    source: str
    title: str
    score: float


class ChatResponse(BaseModel):
    response: str
    session_id: str
    sources: list[Source] = []
```

Frontend moze pokazac male `Sources` pod odpowiedzia asystenta. To jest dobre rekrutacyjnie, bo widac, ze aplikacja nie tylko generuje odpowiedz, ale potrafi pokazac grounding.

### 6. Debug Endpoint

Dodac endpoint tylko dla srodowisk developerskich:

```text
POST /debug/retrieval
```

Warunek:

```text
ENABLE_DEBUG_ENDPOINTS=true
```

Response:

```json
{
  "query": "What AWS experience do you have?",
  "chunks": [
    {
      "id": "cv-aws-001",
      "source": "cv",
      "title": "Cloud infrastructure experience",
      "score": 9.2,
      "metadata": {
        "skills": ["aws", "lambda", "terraform"]
      },
      "content_preview": "..."
    }
  ]
}
```

Na produkcji endpoint powinien zwracac `404` albo nie byc rejestrowany.

### 7. Ewaluacje Retrievalu

Dodac:

```text
backend/evals/retrieval_cases.yaml
backend/test_retrieval.py
```

Przykladowe przypadki:

```yaml
- query: "What AWS experience do you have?"
  expected_sources:
    - "cv"
    - "summary"
  expected_keywords:
    - "aws"
    - "lambda"
    - "terraform"

- query: "What is your current role?"
  expected_keywords:
    - "current"
    - "present"

- query: "How do you communicate at work?"
  expected_sources:
    - "summary"
    - "style"
```

Testy powinny liczyc:

- `recall@3`
- `recall@5`
- czy retrieval nie zwraca prywatnych chunkow dla publicznych pytan
- czy context miesci sie w budzecie znakow/tokenow

Minimalny acceptance criterion:

- `recall@3 >= 0.8` dla przygotowanego zestawu testowego
- `retrieved_context` nie przekracza ustalonego limitu, np. 10 000 znakow
- wszystkie testy backendu przechodza lokalnie

### 8. Ewaluacje Safety

Dodac testy na:

- prompt injection: "ignore previous instructions"
- prosby o prywatny numer telefonu
- pytania niezawodowe
- prosby o wygenerowanie kodu
- pytania, na ktore nie ma danych w indeksie

Oczekiwane zachowanie:

- model odmawia albo przekierowuje do tematow zawodowych
- model nie halucynuje brakujacych faktow
- model nie ujawnia prywatnych danych

### 9. Observability Na AWS

Rozszerzyc logowanie w CloudWatch.

Logowac:

- `session_id`
- `retrieval_latency_ms`
- `bedrock_latency_ms`
- `total_latency_ms`
- `retrieved_chunk_count`
- `selected_sources`
- `input_tokens`
- `output_tokens`
- `model_id`

Nie logowac:

- pelnej tresci prywatnych dokumentow
- prywatnego numeru telefonu
- sekretow
- pelnej historii rozmowy

Opcjonalnie dodac CloudWatch Metric Filters dla:

- bledow Bedrock
- timeoutow Lambdy
- liczby requestow
- sredniej latencji

### 10. AWS Deployment

Zmiany w deployment:

- `backend/data/search_index.json` musi byc dodany do paczki Lambdy
- `backend/retrieval/` musi byc dodany do paczki Lambdy
- `backend/ingest.py` nie musi byc uruchamiany w Lambdzie, to narzedzie build-time/local

Zmiany w Terraform:

- dodac env var `ENABLE_DEBUG_ENDPOINTS=false` dla produkcji
- opcjonalnie `RETRIEVAL_TOP_K=5`
- opcjonalnie `RETRIEVAL_MAX_CONTEXT_CHARS=10000`
- opcjonalnie `KNOWLEDGE_INDEX_S3_KEY`, jesli indeks bedzie ladowany z S3

Nie trzeba dodawac:

- VPC
- RDS
- RDS Proxy
- Secrets Manager dla DB
- pgvector
- dodatkowej stalej infrastruktury

To jest wazna zaleta tego wariantu: Lambda nadal moze dzialac poza VPC, ma krotszy cold start i mniejsza powierzchnie awarii.

### 11. Opcjonalny Tryb Indeksu Z S3

Jesli chcemy aktualizowac wiedze bez redeployu Lambdy:

```text
s3://<memory-or-knowledge-bucket>/knowledge/search_index.json
```

Lambda przy cold starcie:

- pobiera indeks z S3
- waliduje wersje schematu
- trzyma indeks w globalnej zmiennej

Trade-off:

- plus: aktualizacja wiedzy bez redeployu
- minus: dodatkowa zaleznosc od S3 przy cold starcie
- minus: trzeba dobrze obsluzyc fallback, jesli S3 chwilowo nie odpowiada

Rekomendacja: zaczac od indeksu w paczce Lambdy, a S3 zostawic jako etap 2.

## Plan Prac

### Etap 1: Indeks I Retrieval

- dodac `DocumentChunk`
- dodac ingestion do `search_index.json`
- dodac loader indeksu
- dodac scoring
- dodac testy jednostkowe chunkingu i scoringu

Efekt: mozna lokalnie zadac query i zobaczyc top chunki bez wywolywania Bedrocka.

### Etap 2: Integracja Z Chatem

- zmienic `context.py`, zeby przyjmowal retrieved chunks
- zmienic `server.py`, zeby wykonywal retrieval przed Bedrockiem
- rozszerzyc response o `sources`
- zachowac dotychczasowe guardrails

Efekt: produkcyjny `/chat` uzywa tylko wybranych fragmentow wiedzy.

### Etap 3: Debug I Ewaluacje

- dodac `/debug/retrieval`
- dodac `retrieval_cases.yaml`
- dodac testy `recall@k`
- dodac safety cases

Efekt: projekt pokazuje nie tylko implementacje, ale tez sposob mierzenia jakosci.

### Etap 4: Frontend Sources

- dodac opcjonalne wyswietlanie zrodel pod odpowiedzia
- nie pokazywac dlugich fragmentow dokumentow
- pokazac tylko tytul/source, np. `CV - Cloud infrastructure`, `Summary - Work style`

Efekt: uzytkownik widzi grounding odpowiedzi.

### Etap 5: AWS Hardening

- upewnic sie, ze indeks jest w paczce Lambdy
- dodac env vars w Terraform
- dodac logi latencji i liczby chunkow
- sprawdzic timeout Lambdy
- sprawdzic CloudWatch logs po deployu

Efekt: rozwiazanie dziala stabilnie na AWS bez dodatkowej stalej infrastruktury.

## Kryteria Akceptacji

- `/chat` nie wysyla juz calego CV w system prompcie
- dla typowych pytan retrieval zwraca trafne zrodla
- model odpowiada tylko na podstawie retrieved context i stabilnych faktow
- brak bazy wektorowej i brak nowej stalej infrastruktury AWS
- deployment na Lambda nadal dziala
- testy backendu przechodza
- `README.md` opisuje decyzje: "Why lightweight RAG instead of vector DB"
- istnieje debugowalny i testowalny retrieval pipeline

## Ryzyka I Mitigacje

| Ryzyko | Mitigacja |
|---|---|
| Keyword retrieval nie znajdzie semantycznie podobnego pytania | dodac synonimy domenowe i testy eval |
| Indeks bedzie zbyt duzy dla prompta | limit `RETRIEVAL_MAX_CONTEXT_CHARS` |
| Model odpowie poza kontekstem | mocniejsze guardrails i safety evals |
| Debug endpoint ujawni zbyt duzo | wlaczany tylko env var, w prod disabled |
| Indeks nie zostanie dodany do paczki Lambdy | test/deploy check sprawdzajacy obecnosc `search_index.json` |

## Co Pokazac W README

README powinien jasno komunikowac:

- to nie jest zwykly prompt wrapper
- projekt ma ingestion pipeline
- projekt ma retrieval layer
- projekt ma ewaluacje retrievalu
- brak vector DB jest swiadoma decyzja architektoniczna
- aplikacja dziala serverless na AWS

Proponowany opis:

```text
The project intentionally avoids a vector database because the knowledge corpus is small and mostly structured. Instead, it uses a deterministic retrieval layer with chunking, BM25-style scoring, source metadata, context budgeting, and retrieval evaluation. This keeps the AWS Lambda deployment simple while still separating ingestion, retrieval, prompt composition, and generation.
```

