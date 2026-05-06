# Lightweight RAG - Stage 1 Implementation Notes

## Cel Etapu 1

Etap 1 mial przygotowac fundament pod lekki RAG bez bazy wektorowej i bez zmian w endpointzie `/chat`.

Zakres tego etapu:

- zbudowac deterministyczny proces ingestion
- wygenerowac lokalny indeks wiedzy w pliku `search_index.json`
- dodac modul retrievalu dzialajacy w pamieci procesu
- dodac scoring tekstowy bez vector DB
- dodac testy jednostkowe dla nowego mechanizmu
- upewnic sie, ze prywatny numer telefonu nie trafia do indeksu

Na tym etapie nie zostala jeszcze wykonana integracja z Bedrockiem ani zmiana prompta produkcyjnego. Obecny `/chat` nadal dziala po staremu. Etap 1 dostarcza niezalezny retrieval layer, ktory mozna testowac lokalnie bez wywolywania modelu.

## Dodane Pliki

### `backend/ingest.py`

Skrypt build-time do generowania indeksu wiedzy.

Czyta dane z:

- `backend/data/facts.json`
- `backend/data/summary.txt`
- `backend/data/style.txt`
- `backend/data/cv.pdf`

Nastepnie:

- dzieli dane na chunki
- nadaje im stabilne identyfikatory
- dodaje metadane
- inferuje proste keywordy
- redaguje prywatne numery telefonow
- zapisuje wynik do `backend/data/search_index.json`

Ten skrypt nie musi dzialac w Lambdzie. Jest narzedziem uruchamianym lokalnie albo w procesie budowania/deployu.

### `backend/data/search_index.json`

Statyczny indeks wiedzy wygenerowany przez `backend/ingest.py`.

Aktualnie zawiera 13 chunkow ze zrodel:

- `cv`
- `facts`
- `summary`
- `style`

To jest plik, ktory w kolejnych etapach Lambda bedzie mogla zaladowac przy cold starcie i trzymac w pamieci.

### `backend/retrieval/schemas.py`

Definiuje podstawowe struktury danych:

- `DocumentChunk`
- `RetrievedChunk`

`DocumentChunk` reprezentuje pojedynczy fragment wiedzy.

`RetrievedChunk` reprezentuje fragment zwrocony przez retrieval razem ze scorem i lista dopasowanych terminow.

### `backend/retrieval/scoring.py`

Zawiera logike:

- normalizacji tekstu
- tokenizacji
- usuwania prostych stop words
- rozszerzania zapytania o synonimy domenowe
- liczenia score dla chunkow
- dodawania boostow na podstawie metadanych i intencji pytania

To tutaj znajduje sie obecny mechanizm scoringu podobny koncepcyjnie do BM25.

### `backend/retrieval/index.py`

Zawiera klase `SearchIndex`.

Jej odpowiedzialnosci:

- przyjecie listy chunkow
- policzenie document frequency
- wykonanie retrievalu dla query
- posortowanie wynikow po score
- ograniczenie liczby wynikow przez `top_k`
- ograniczenie lacznego rozmiaru kontekstu przez `max_chars`

Zawiera tez funkcje `load_search_index()`, ktora laduje `search_index.json`.

### `backend/retrieval/__init__.py`

Eksportuje publiczne elementy modulu retrievalu.

### `backend/test_retrieval.py`

Dodaje testy dla Etapu 1:

- tokenizacja normalizuje znaki diakrytyczne i usuwa stop words
- retrieval poprawnie wybiera chunk technologiczny
- `max_chars` ogranicza liczbe zwracanych chunkow
- numery telefonow sa redagowane
- daty nie sa mylone z numerami telefonow
- indeks da sie zapisac i odczytac bez utraty danych

## Koncept `search_index.json`

`search_index.json` to statyczna, materializowana reprezentacja wiedzy aplikacji.

Zamiast przy kazdym requescie:

- czytac PDF
- parsowac JSON
- skladac cale CV do prompta
- dawac modelowi wszystko naraz

robimy to raz w procesie ingestion:

```text
facts.json / summary.txt / style.txt / cv.pdf
        |
        v
backend/ingest.py
        |
        v
backend/data/search_index.json
```

Indeks sklada sie z listy chunkow. Kazdy chunk jest malym, samodzielnym fragmentem wiedzy, ktory moze zostac wybrany do prompta, jesli pasuje do pytania uzytkownika.

Przykladowa struktura chunku:

```json
{
  "id": "facts-current-role-696ff38715c7",
  "source": "facts",
  "title": "Current Role",
  "content": "Current Role: unemployed, during a transition to become AI Engineer",
  "metadata": {
    "field": "current_role",
    "is_current": true,
    "visibility": "public"
  },
  "keywords": [
    "current role",
    "unemployed, during a transition to become AI Engineer"
  ],
  "priority": 5
}
```

Najwazniejsze pola:

- `id` - stabilny identyfikator chunku, generowany deterministycznie
- `source` - zrodlo danych, np. `cv`, `facts`, `summary`, `style`
- `title` - krotki opis fragmentu
- `content` - tresc, ktora moze trafic do prompta
- `metadata` - dane pomocnicze do filtrowania i boostowania wynikow
- `keywords` - slowa pomocnicze dla scoringu
- `priority` - reczny priorytet chunku

To nie jest indeks wektorowy. Nie zawiera embeddingow. Nie wymaga zewnetrznej bazy danych. Jest zwyklym JSON-em, ktory mozna spakowac razem z kodem Lambdy.

## Dlaczego Taki Indeks Ma Sens Na AWS

Ten projekt dziala serverless na AWS Lambda. Dla malego korpusu wiedzy lokalny indeks JSON ma kilka zalet:

- brak RDS, VPC, RDS Proxy i migracji DB
- brak cold startu zwiazanego z VPC
- brak zaleznosci od zewnetrznej vector DB
- brak dodatkowych kosztow stalej infrastruktury
- indeks moze zostac zaladowany raz przy cold starcie
- retrieval odbywa sie w pamieci procesu

Docelowo flow na Lambdzie bedzie wygladal tak:

```text
Lambda cold start
        |
        v
load search_index.json into memory
        |
        v
request /chat
        |
        v
score chunks in memory
        |
        v
put top chunks into prompt
        |
        v
call Bedrock
```

Dzieki temu dodatkowy koszt retrievalu powinien byc bardzo maly. Dla kilkunastu albo kilkudziesieciu chunkow scoring w pamieci jest praktycznie pomijalny w porownaniu z latencja wywolania Bedrocka.

## Zwiazek Z BM25

Obecny scoring ma zwiazek z BM25, ale nie jest pelna implementacja BM25.

Najuczciwiej opisac go jako:

```text
BM25-like lexical retrieval with domain-specific boosts
```

Albo po polsku:

```text
leksykalny retrieval inspirowany BM25, rozszerzony o boosty domenowe
```

## Czym Jest BM25

BM25 to klasyczny algorytm rankingu dokumentow w wyszukiwarkach tekstowych.

Jego zadaniem jest odpowiedziec na pytanie:

> Ktore dokumenty najlepiej pasuja do zapytania tekstowego?

BM25 bierze pod uwage glownie trzy rzeczy:

1. Czy slowa z query wystepuja w dokumencie.
2. Jak czesto te slowa wystepuja w danym dokumencie.
3. Jak rzadkie sa te slowa w calym korpusie.

Intuicja jest prosta:

- jesli dokument zawiera slowo z pytania, powinien dostac punkty
- jesli zawiera je kilka razy, powinien dostac wiecej punktow
- jesli slowo jest rzadkie w korpusie, powinno byc wazniejsze
- jesli slowo wystepuje prawie wszedzie, powinno miec mniejsze znaczenie
- bardzo dlugie dokumenty nie powinny wygrywac tylko dlatego, ze maja wiecej slow

Klasyczna formula BM25 uzywa m.in.:

- `tf` - term frequency, czyli ile razy termin wystepuje w dokumencie
- `df` - document frequency, czyli w ilu dokumentach termin wystepuje
- `idf` - inverse document frequency, czyli jak informacyjny/rzadki jest termin
- dlugosci dokumentu
- sredniej dlugosci dokumentu w korpusie
- parametrow `k1` i `b`, ktore kontroluja saturacje czestosci i normalizacje dlugosci

W uproszczeniu:

```text
rzadkie slowo z query + wystepuje w dokumencie = wysoki score
popularne slowo z query + wystepuje wszedzie = niski score
```

## Co W Tej Implementacji Jest Podobne Do BM25

Obecny scoring ma kilka elementow zgodnych z idea BM25:

### 1. Tokenizacja Query I Chunkow

Zapytanie i chunki sa zamieniane na tokeny.

Przyklad:

```text
"What AWS and Terraform experience do you have?"
```

po normalizacji daje istotne tokeny w stylu:

```text
aws, terraform, experience
```

### 2. Document Frequency

`SearchIndex` liczy, w ilu chunkach wystepuje dany termin.

To jest odpowiednik `df` w BM25.

Jesli `aws` wystepuje w niewielu chunkach, jest bardziej informacyjne. Jesli `software` wystepuje prawie wszedzie, powinno miec mniejszy wplyw.

### 3. IDF-Like Weight

W `score_chunk()` uzywany jest wariant wagi podobnej do IDF:

```python
idf = math.log((document_count + 1) / (df + 0.5)) + 1
```

To powoduje, ze rzadsze terminy maja wieksza wage.

### 4. Term Frequency

Scoring bierze pod uwage, ile razy termin wystapil w chunku.

```python
tf = terms[term]
```

Jesli termin pojawia sie czesciej w danym chunku, ma wiekszy wplyw na score.

### 5. Normalizacja Przez Dlugosc Chunku

Score jest dzielony przez pierwiastek z dlugosci chunku:

```python
score += (tf / math.sqrt(chunk_length)) * idf
```

To jest uproszczony odpowiednik normalizacji dlugosci dokumentu. Chodzi o to, zeby dlugi chunk nie wygrywal tylko dlatego, ze zawiera wiecej slow.

## Czego Tu Jeszcze Nie Ma W Porownaniu Do Pelnego BM25

To nie jest pelne BM25, bo nie ma:

- parametrow `k1` i `b`
- sredniej dlugosci dokumentu w korpusie
- klasycznej saturacji `tf`
- dokladnej formuly BM25Okapi
- indeksu odwroconego

Obecnie kazde query przechodzi po wszystkich chunkach i liczy score w pamieci. Przy obecnej skali to jest swiadoma i dobra decyzja, bo korpus jest maly.

Pelny BM25 moglby zostac dodany pozniej, jesli:

- liczba chunkow wzrosnie do tysiecy
- retrieval stanie sie waskim gardlem
- potrzebna bedzie bardziej standardowa metryka rankingowa
- pojawi sie wiekszy zestaw evali i potrzeba strojenia parametrow

## Boosty Domenowe

Poza scoringiem BM25-like implementacja dodaje reguly specyficzne dla tego projektu.

Przyklady:

- pytania o aktualna sytuacje zawodowa boostuja chunki z `is_current=true`
- pytania o styl komunikacji boostuja `summary` i `style`
- pytania o kontakt boostuja `facts`
- pytania o doswiadczenie zawodowe boostuja `cv`
- pytania o technologie boostuja chunki z sekcja `skills` albo `summary`

To jest celowe. W malym personalnym RAG-u metadane czesto sa bardziej wartosciowe niz czysto statystyczny ranking.

Przyklad:

```text
Query: "What is your current role?"
```

Chunk z `facts.current_role` powinien wygrac nawet jesli w CV jest wiele slow zwiazanych z rolami zawodowymi. Dlatego `is_current=true` dostaje dodatkowy boost.

## Synonimy Domenowe

Scoring rozszerza query o proste synonimy domenowe.

Przyklady:

- `aws` rozszerza sie o `cloud`, `lambda`, `bedrock`, `s3`, `cloudfront`, `terraform`
- `llm` rozszerza sie o `ai`, `ml`, `bedrock`, `rag`, `openai`
- `communication` rozszerza sie o `style`, `communicate`, `approach`, `collaboration`

To pomaga przy pytaniach, ktore semantycznie pasuja do danych, ale nie uzywaja dokladnie tych samych slow.

To nadal nie jest semantic search w sensie embeddingow. To kontrolowana, prosta warstwa leksykalna.

## Dlaczego Nie Vector DB Na Tym Etapie

Vector DB bylaby tutaj technicznie mozliwa, ale nie jest potrzebna dla Etapu 1.

Powody:

- korpus jest maly
- dane sa osobiste i w duzej czesci ustrukturyzowane
- Lambda moze trzymac caly indeks w pamieci
- lexical retrieval jest szybki i latwy do debugowania
- nie dochodzi nowa infrastruktura AWS
- mozna latwo napisac testy rankingowe

Dla rekrutera to jest wazny sygnal: projekt nie dodaje technologii tylko dlatego, ze jest modna. Zamiast tego pokazuje decyzje dopasowana do skali problemu.

## Bezpieczenstwo Danych

Podczas generowania indeksu okazalo sie, ze tekst wyciagniety z `cv.pdf` zawieral prywatny numer telefonu.

W Etapie 1 dodano redakcje numerow telefonow w `backend/ingest.py`, zanim tresc zostanie zapisana do `search_index.json`.

Testy sprawdzaja, ze:

- numer telefonu nie trafia do chunku
- daty typu `09.2024` i `10.2025` nie sa usuwane jako numery telefonow

To jest istotne, bo `search_index.json` bedzie w kolejnych etapach zrodlem kontekstu dla modelu.

## Wynik Etapu 1

Etap 1 dostarcza dzialajacy fundament:

- dane sa przetwarzane do statycznego indeksu
- indeks jest gotowy do spakowania z Lambda
- retrieval moze dzialac lokalnie w pamieci
- scoring jest deterministyczny i testowalny
- prywatny numer telefonu jest redagowany
- backendowe testy przechodza

Uruchomione komendy weryfikacyjne:

```bash
uv run --project backend pytest
uv run ruff check backend/ingest.py backend/retrieval backend/test_retrieval.py
uv run mypy backend/ingest.py backend/retrieval
```

Wynik:

- `34 passed`
- `ruff` bez bledow
- `mypy` bez bledow

## Co Dalej

Nastepny etap to podlaczenie retrievalu do `/chat`:

```text
request.message
        |
        v
SearchIndex.retrieve()
        |
        v
top chunks
        |
        v
context.prompt(...)
        |
        v
Bedrock Converse API
```

Wtedy aplikacja przestanie wysylac cale CV do modelu i zacznie budowac prompt tylko z wybranych fragmentow wiedzy.

