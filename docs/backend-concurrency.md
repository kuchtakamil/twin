# Backend Concurrency & Lambda Execution Model

## Problem: blokujące wywolania w async endpointach

Endpointy w `server.py` byly zdefiniowane jako `async def`, ale wewnatrz wywolywaly synchroniczne, blokujace operacje:

1. **`boto3` Bedrock** (`bedrock_client.converse()`) - synchroniczne wywolanie HTTP, moze trwac sekundy. Blokuje event loop.
2. **`boto3` S3** (`s3_client.get_object()` / `put_object()`) - synchroniczne.
3. **File I/O** (`open()`, `json.load()`, `json.dump()`) - blokujace.

FastAPI traktuje `async def` jako korutyny uruchamiane bezposrednio na event loop. Kiedy taka korutyna wykonuje blokujaca operacje, caly event loop stoi - zaden inny request nie jest obslugiwany w tym czasie.

### Race condition na sesji

Dwa rownoczesne requesty z tym samym `session_id` moga:
1. Oba odczytac te sama historie
2. Oba dodac swoje wiadomosci
3. Drugi zapis nadpisze pierwszy - utrata wiadomosci

## Rozwiazanie: `asyncio.to_thread` + per-session locks

### Opcja A (prostsza): `def` zamiast `async def`

Zamiana `async def` na zwykle `def` - FastAPI automatycznie uruchomi endpointy w thread pool.

### Opcja B (zaimplementowana): `asyncio.to_thread`

Blokujace wywolania sa odladowane do thread pool:

```python
conversation = await asyncio.to_thread(load_conversation, session_id)
assistant_response = await asyncio.to_thread(call_bedrock, conversation, request.message)
await asyncio.to_thread(save_conversation, session_id, conversation)
```

Event loop jest wolny i moze obslugiwac inne requesty w tym czasie.

### Per-session `asyncio.Lock`

Mechanizm lockow per-sesja zapobiega race conditions na historii konwersacji:

```python
_session_locks: Dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()

async def get_session_lock(session_id: str) -> asyncio.Lock:
    async with _session_locks_guard:
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]
```

- `_session_locks` - slownik `session_id -> Lock`
- `_session_locks_guard` - guard na sam slownik (zeby dwa requesty nie stworzyly jednoczesnie dwoch lockow dla tej samej sesji)
- Lock obejmuje caly cykl load -> bedrock -> save w `/chat`
- `/conversation` (sam odczyt) nie wymaga locka - najgorsze co sie stanie to odczyt nieaktualnych danych

## Lambda: model wykonania

### Architektura

```
API Gateway -> Lambda (1 request = 1 invocation) -> Mangum -> FastAPI
```

Mangum (`lambda_handler.py`) tlumaczy pojedyncze zdarzenie API Gateway na jedno zadanie FastAPI i zwraca odpowiedz. To jest synchroniczny model - Lambda dostaje event, przekazuje go do Mangum, Mangum odpala FastAPI, czeka na odpowiedz, i zwraca ja.

### Instancje Lambda

| Scenariusz | Co sie dzieje |
|---|---|
| Request A konczy sie, potem Request B | B trafia na te sama instancje (warm), jesli minelo < ~5-15 min. Zmienne globalne (`_session_locks`, klienci boto3) sa zachowane. |
| Request A jeszcze trwa, przychodzi Request B | Lambda tworzy nowa instancje (cold start). Kazda instancja obsluguje dokladnie 1 request naraz. |

### Konsekwencje dla lockow

Skoro Lambda obsluguje 1 request na instancje, to `asyncio.Lock` nigdy nie bedzie mial okazji zablokowac drugiego requestu - bo drugi request trafia na inna instancje z wlasnym, pustym `_session_locks`.

Race condition na sesji nadal istnieje na poziomie S3:

```
Instancja 1: load("abc") -> [msg1, msg2]
Instancja 2: load("abc") -> [msg1, msg2]        <- ten sam stan!
Instancja 1: save("abc", [msg1, msg2, msg3])
Instancja 2: save("abc", [msg1, msg2, msg4])    <- nadpisuje msg3!
```

### Kiedy locki sa przydatne

Locki maja sens gdy:
- Serwer uruchamiany jest lokalnie (`uvicorn`) - wiele requestow na jednym procesie
- Aplikacja migruje z Lambdy na ECS, EC2, itp.

Nie szkodza na Lambdzie (nigdy nie blokuja), a chronia w srodowisku deweloperskim.

### Ochrona na poziomie Lambdy (niezaimplementowane)

Gdyby potrzeba bylo pelnej ochrony przed race conditions miedzy instancjami Lambdy, mozliwe rozwiazania to:
- **DynamoDB conditional write** - rozproszony lock
- **S3 conditional put** (`If-None-Match` header)

W praktyce dla chatbota ryzyko jest minimalne - uzytkownicy rzadko wysylaja dwie wiadomosci jednoczesnie.

## Podsumowanie zmian

| Problem | Wplyw | Rozwiazanie |
|---|---|---|
| Blokujace boto3 w `async def` | Event loop stoi, 1 request blokuje wszystkie | `asyncio.to_thread` |
| Blokujace file I/O w `async def` | j.w. (mniejszy efekt) | `asyncio.to_thread` |
| Race condition na sesji (single process) | Utrata wiadomosci | `asyncio.Lock` per-sesja |
| Race condition na sesji (multi-Lambda) | Utrata wiadomosci | Nie rozwiazane - niskie ryzyko |
| Brak rate limitingu | Latwy DoS | Czesciowo rozwiazane przez API Gateway throttling w Terraform |




Jak Lambda zarządza instancjami

  Krótko: to zależy od timingu i współbieżności.

  Sekwencyjne wywołania (jedno po drugim)

  Request A ──────► [Instancja 1] ──► odpowiedź
                                          ... kilka sekund/minut ...
  Request B ──────► [Instancja 1] ──► odpowiedź   ← ta sama ("warm")

  Lambda utrzymuje instancję przy życiu przez ~5-15 minut po ostatnim wywołaniu (czas nie jest gwarantowany). Jeśli kolejny request przyjdzie w tym oknie — dostaje tę samą instancję z
  zachowaną pamięcią (zmienne globalne, połączenia, locki).

  Równoczesne wywołania

  Request A ──────► [Instancja 1] ──────────► odpowiedź
  Request B ──────► [Instancja 2] ──────────► odpowiedź   ← nowa ("cold start")

  Jedna instancja Lambda obsługuje dokładnie jeden request naraz. Jeśli Request B przychodzi gdy Instancja 1 jest zajęta, Lambda tworzy nową instancję.

  Co to oznacza dla naszych locków

  Locki asyncio.Lock żyją w _session_locks — zmiennej globalnej danej instancji. Są przydatne tylko jeśli jedna instancja obsługuje wiele requestów współbieżnie. A Lambda tego
  standardowo nie robi.

  Ale — jest wyjątek: jeśli używasz Mangum z API Gateway, a w konfiguracji Lambda masz provisioned concurrency lub Lambda Web Adapter ze streamingiem, to wewnątrz jednej instancji
  FastAPI może obsługiwać wiele requestów jednocześnie. Sprawdźmy jak to jest skonfigurowane u ciebie.

● OK, widzę pełny obraz. Oto jak to działa w twoim przypadku:

  Twoja konfiguracja: Mangum + API Gateway

  API Gateway → Lambda (1 request = 1 invocation) → Mangum → FastAPI

  Mangum (lambda_handler.py:13) tłumaczy pojedyncze zdarzenie API Gateway na jedno żądanie FastAPI i zwraca odpowiedź. To jest synchroniczny model — Lambda dostaje event, przekazuje go
  do Mangum, Mangum odpala FastAPI, czeka na odpowiedź, i zwraca ją.

  Odpowiedź na twoje pytanie
  ┌──────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                  Scenariusz                  │                                                         Co się dzieje                                                          │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Request A kończy się, potem Request B        │ B trafia na tę samą instancję (warm), jeśli minęło < ~5-15 min. Zmienne globalne (_session_locks, klienci boto3) są zachowane. │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Request A jeszcze trwa, przychodzi Request B │ Lambda tworzy nową instancję (cold start). Każda instancja obsługuje dokładnie 1 request naraz.                                │
  └──────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
  Konsekwencja: nasze locki nie działają na Lambdzie

  Skoro Lambda obsługuje 1 request na instancję, to asyncio.Lock nigdy nie będzie miał okazji zablokować drugiego requestu — bo drugi request trafia na inną instancję z własnym, pustym
  _session_locks.

  Race condition na sesji nadal istnieje — ale na poziomie S3, nie pamięci procesu:

  Instancja 1: load("abc") → [msg1, msg2]
  Instancja 2: load("abc") → [msg1, msg2]        ← ten sam stan!
  Instancja 1: save("abc", [msg1, msg2, msg3])
  Instancja 2: save("abc", [msg1, msg2, msg4])    ← nadpisuje msg3!

  Kiedy locki są przydatne

  Locki, które dodaliśmy, mają sens gdy:
  - Uruchamiasz serwer lokalnie (uvicorn) — wiele requestów na jednym procesie
  - Kiedykolwiek odejdziesz od Lambdy (ECS, EC2, itp.)

  Więc warto je zostawić — nie szkodzą na Lambdzie (nigdy nie blokują), a chronią w środowisku deweloperskim i przy ewentualnej migracji.

  Gdybyś chciał ochronić się na Lambdzie

  Musiałbyś użyć rozproszonego locka — np. DynamoDB conditional write lub S3 conditional put (nowy feature: If-None-Match). Ale w praktyce, dla chatbota z jednym użytkownikiem na sesję,
  ryzyko jest minimalne — ludzie rzadko wysyłają dwie wiadomości jednocześnie.
  

Krótko: nie, w tej architekturze asyncio nie daje żadnej korzyści. Oto dlaczego:

  Na Lambdzie (Mangum)

  Event loop obsługuje 1 request → nie ma komu ustąpić miejsca podczas await. Cały przepływ:

  await asyncio.to_thread(call_bedrock, ...)
         ↓
    tworzy wątek, czeka na niego
         ↓
    event loop jest wolny... ale nie ma innych requestów
         ↓
    wątek kończy, event loop odbiera wynik

  To samo co zwykłe synchroniczne wywołanie, ale z dodatkowym narzutem thread pool.

  Na uvicorn (lokalnie)

  FastAPI automatycznie uruchamia zwykłe def endpointy w thread pool — czyli robi dokładnie to co asyncio.to_thread, tylko bez ręcznego pisania wrapperów.

  Rekomendacja: wróć do Opcji A

  Zamienię na proste def — działa poprawnie w obu środowiskach, zero narzutu, prostszy kod. Lock zmieniam na threading.Lock (bo def endpointy działają w wątkach, nie na event loop).


      229 -            conversation = await asyncio.to_thread(load_conversation, session_id)                                                                                       
      229 +            conversation = load_conversation(session_id)   
      231 -            # Call Bedrock for response (longest blocking call)                                                                                                         
      232 -            assistant_response = await asyncio.to_thread(call_bedrock, conversation, request.message)                                                                   
      231 +            # Call Bedrock for response                                                                                                                                 
      232 +            assistant_response = call_bedrock(conversation, request.message)  

 a w jakim przypadku gdy użyta jest lambda jakoś środowisko działania, użycie asyncio jednak byłoby uzasadnione?                                                                         
                                                                                                                  
● Kiedy asyncio na Lambdzie ma sens                                                                                                                                                       
                                                                                                                                                                                        
  Kluczowy warunek: masz wiele niezależnych operacji I/O w ramach jednego requestu, które mogą lecieć równolegle.                                                                         
   
  1. Fan-out — wiele równoległych wywołań                                                                                                                                                 
                                                           
  Załóżmy, że w jednym requeście musisz odpytać 3 źródła:

  # Synchronicznie — sekwencyjnie, ~3s łącznie
  profile = fetch_user_profile(user_id)      # ~1s
  history = load_conversation(session_id)     # ~1s
  context = fetch_rag_documents(query)        # ~1s

  # Async — równolegle, ~1s łącznie
  profile, history, context = await asyncio.gather(
      fetch_user_profile(user_id),
      load_conversation(session_id),
      fetch_rag_documents(query),
  )

  Jeden request, ale zyskujesz ~3x na czasie odpowiedzi. Lambda nadal obsługuje 1 request, ale event loop zarządza wieloma współbieżnymi operacjami I/O wewnątrz tego requestu.

  2. Natywnie asynchroniczne biblioteki

  Jeśli używasz aioboto3, httpx, aiohttp — one zwracają korutyny, nie da się ich użyć bez async/await. I faktycznie są wydajniejsze niż synchroniczne odpowiedniki, bo nie tworzą wątków —
   korzystają z nieblokującego I/O.

  3. Lambda Web Adapter (zamiast Mangum)

  AWS Lambda Web Adapter uruchamia prawdziwy serwer HTTP w kontenerze Lambda. W połączeniu z response streaming Lambda może obsługiwać wiele requestów na jednej instancji — wtedy asyncio
   działa tak samo jak na zwykłym serwerze.

  Twój przypadek

  load_conversation → call_bedrock → save_conversation

  Operacje są sekwencyjne i zależne — nie możesz wywołać Bedrocka bez historii, nie możesz zapisać bez odpowiedzi. Nie ma czego zrównoleglać, więc asyncio nic nie daje.

  Gdybyś np. dodał RAG (wyszukiwanie dokumentów), asyncio zaczęłoby mieć sens:

  # historia i dokumenty RAG mogą być pobierane równolegle
  history, rag_docs = await asyncio.gather(
      load_conversation(session_id),
      search_knowledge_base(query),
  )
  response = await call_bedrock(history, rag_docs, message)

  TL;DR
  ┌──────────────────────────────────────────────────┬──────────────────────────────────────────┐
  │                     Sytuacja                     │           asyncio na Lambdzie            │
  ├──────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ Sekwencyjne I/O (twój przypadek)                 │ Bez sensu — zero zysku                   │
  ├──────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ Fan-out (wiele równoległych I/O w 1 requeście)   │ Tak — realny zysk czasowy                │
  ├──────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ Natywne async biblioteki (aioboto3, httpx)       │ Tak — wymagane przez API                 │
  ├──────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ Lambda Web Adapter (wielu klientów na instancję) │ Tak — pełny sens jak na zwykłym serwerze │
  └──────────────────────────────────────────────────┴──────────────────────────────────────────┘


a jak trzeba byłoby to ustawić żeby zostając przy rozwiązaniu lambda, mimo wszystko mieć wiele requestów na instancję?                                                                  
                                                                                                                         
● Potrzebowałbyś Lambda Web Adapter zamiast Mangum. To oficjalne rozszerzenie AWS, które uruchamia prawdziwy serwer HTTP (uvicorn) wewnątrz kontenera Lambda.                             
                                                                                                                                                                                          
  Mangum vs Lambda Web Adapter                                                                                                                                                            
                                                                                                                                                                                          
  Teraz (Mangum):                                                                                                                                                                         
    API Gateway → Lambda invoke → Mangum → tworzy ASGI request → FastAPI → odpowiedź                                                                                                      
    (1 invoke = 1 request, Mangum kończy, Lambda czeka na następny invoke)

  Lambda Web Adapter:
    API Gateway → Lambda invoke → [uvicorn działa ciągle na localhost:8000] → FastAPI
    (uvicorn żyje cały czas, jak normalny serwer)

  Co trzeba zmienić

  1. Dockerfile zamiast ZIP — Web Adapter wymaga obrazu kontenerowego:

  FROM public.ecr.aws/docker/library/python:3.13-slim
  COPY --from=public.ecr.aws/awsguru/aws-lambda-web-adapter:0.8.4 /lambda-adapter /opt/extensions/

  WORKDIR /app
  COPY . .
  RUN pip install -r requirements.txt

  CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]

  2. Zmienna środowiskowa w Lambda:

  AWS_LWA_PORT=8080

  3. Terraform — zmiana z runtime = "python3.13" + ZIP na image_uri + ECR.
  4. Wrócić do async def z asyncio.to_thread (lub aioboto3) — bo teraz uvicorn naprawdę obsługuje wiele requestów.

  Ale...

  Nawet z Web Adapterem, Lambda domyślnie nadal wysyła 1 request na instancję. Żeby uzyskać prawdziwą współbieżność, potrzebujesz response streaming (Lambda Function URL z
  RESPONSE_STREAM invoke mode) — wtedy Lambda może wysłać nowy request do instancji, która jeszcze streamuje odpowiedź na poprzedni.

  To jest dość skomplikowane i powiązane z Function URL, a nie standardowym API Gateway.

  Pragmatyczna odpowiedź

  Jeśli chcesz wielu requestów na instancję, łatwiej jest odejść od Lambdy:
  ┌──────────────────────────────────┬───────────────────┬───────────┬─────────────────────────┐
  │              Opcja               │ Wielorequestowość │ Złożoność │ Koszt przy niskim ruchu │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ Lambda + Mangum (teraz)          │ 1 req/instancję   │ Niska     │ Najniższy               │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ Lambda + Web Adapter + streaming │ Ograniczona       │ Wysoka    │ Niski                   │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ AWS App Runner                   │ Pełna             │ Niska     │ Niski (skaluje do 0)    │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ ECS Fargate                      │ Pełna             │ Średnia   │ Wyższy (min. 1 task)    │
  └──────────────────────────────────┴───────────────────┴───────────┴─────────────────────────┘
  App Runner to prawdopodobnie najlepsza opcja jeśli chcesz zostać serverless ale mieć normalny serwer HTTP — podajesz obraz Dockera, AWS zarządza skalowaniem, a koszt jest zbliżony do
  Lambdy przy niskim ruchu.


a jak trzeba byłoby to ustawić żeby zostając przy rozwiązaniu lambda, mimo wszystko mieć wiele requestów na instancję? 

● Potrzebowałbyś Lambda Web Adapter zamiast Mangum. To oficjalne rozszerzenie AWS, które uruchamia prawdziwy serwer HTTP (uvicorn) wewnątrz kontenera Lambda.

  Mangum vs Lambda Web Adapter

  Teraz (Mangum):
    API Gateway → Lambda invoke → Mangum → tworzy ASGI request → FastAPI → odpowiedź
    (1 invoke = 1 request, Mangum kończy, Lambda czeka na następny invoke)

  Lambda Web Adapter:
    API Gateway → Lambda invoke → [uvicorn działa ciągle na localhost:8000] → FastAPI
    (uvicorn żyje cały czas, jak normalny serwer)

  Co trzeba zmienić

  1. Dockerfile zamiast ZIP — Web Adapter wymaga obrazu kontenerowego:

  FROM public.ecr.aws/docker/library/python:3.13-slim
  COPY --from=public.ecr.aws/awsguru/aws-lambda-web-adapter:0.8.4 /lambda-adapter /opt/extensions/

  WORKDIR /app
  COPY . .
  RUN pip install -r requirements.txt

  CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]

  2. Zmienna środowiskowa w Lambda:

  AWS_LWA_PORT=8080

  3. Terraform — zmiana z runtime = "python3.13" + ZIP na image_uri + ECR.
  4. Wrócić do async def z asyncio.to_thread (lub aioboto3) — bo teraz uvicorn naprawdę obsługuje wiele requestów.

  Ale...

  Nawet z Web Adapterem, Lambda domyślnie nadal wysyła 1 request na instancję. Żeby uzyskać prawdziwą współbieżność, potrzebujesz response streaming (Lambda Function URL z
  RESPONSE_STREAM invoke mode) — wtedy Lambda może wysłać nowy request do instancji, która jeszcze streamuje odpowiedź na poprzedni.

  To jest dość skomplikowane i powiązane z Function URL, a nie standardowym API Gateway.

  Pragmatyczna odpowiedź

  Jeśli chcesz wielu requestów na instancję, łatwiej jest odejść od Lambdy:
  ┌──────────────────────────────────┬───────────────────┬───────────┬─────────────────────────┐
  │              Opcja               │ Wielorequestowość │ Złożoność │ Koszt przy niskim ruchu │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ Lambda + Mangum (teraz)          │ 1 req/instancję   │ Niska     │ Najniższy               │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ Lambda + Web Adapter + streaming │ Ograniczona       │ Wysoka    │ Niski                   │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ AWS App Runner                   │ Pełna             │ Niska     │ Niski (skaluje do 0)    │
  ├──────────────────────────────────┼───────────────────┼───────────┼─────────────────────────┤
  │ ECS Fargate                      │ Pełna             │ Średnia   │ Wyższy (min. 1 task)    │
  └──────────────────────────────────┴───────────────────┴───────────┴─────────────────────────┘
  App Runner to prawdopodobnie najlepsza opcja jeśli chcesz zostać serverless ale mieć normalny serwer HTTP — podajesz obraz Dockera, AWS zarządza skalowaniem, a koszt jest zbliżony do
  Lambdy przy niskim ruchu.