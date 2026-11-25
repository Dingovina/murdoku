# Мурдоку

Детективная вариация судоку-подобных пазлов (в духе LinkedIn Queens). На поле из
комнат расставлены объекты и люди — подозреваемые и убитый. Набор подсказок
однозначно определяет позиции всех людей; игрок расставляет портреты
перетаскиванием, вычисляет комнату убийства и указывает убийцу. Проверка — по
кнопке «Обвинить»: сервер не хранит состояния, решение передаётся в
шифрованном токене (Fernet), клиент решение не видит.

Правила игры — в [`SPEC.md`](SPEC.md), технические контракты — в
[`ARCHITECTURE.md`](ARCHITECTURE.md), ход работ — в [`PROGRESS.md`](PROGRESS.md).

## Стек

- Бэкенд: Python 3.12+ (разработка на 3.14). Ядро (модель, солвер, генератор,
  подсказки) — только стандартная библиотека; сервер — Starlette + uvicorn;
  токены — `cryptography` (Fernet). Тесты — pytest.
- Фронтенд: ванильный JS (ES-модули, без сборки), отдаётся бэкендом как статика.
  Чистая логика (`clueToText`, портреты) покрыта `node --test`.

## Quickstart

Требуется Python ≥ 3.12 и Node ≥ 23 (для тестов фронтенда).

```sh
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
```

**Windows (cmd или PowerShell):**

```bat
py -3 -m venv .venv
.venv\Scripts\pip install -e backend[dev]
```

**Windows (Git Bash):**

```sh
py -3 -m venv .venv
.venv/Scripts/pip install -e 'backend[dev]'
```

**Примечание для Ubuntu:** в системном Python без `ensurepip` создание venv
падает. Один из двух вариантов:

```sh
# вариант 1: доустановить venv-модуль с pip
sudo apt install python3.14-venv

# вариант 2: bootstrap pip через get-pip.py
python3 -m venv --without-pip .venv
.venv/bin/python get-pip.py   # скачайте с https://bootstrap.pypa.io/get-pip.py
```

### Запуск сервера

```sh
MURDOKU_SECRET=какой-нибудь-секрет .venv/bin/python -m murdoku.server
```

**Windows (cmd):**

```bat
set MURDOKU_SECRET=какой-нибудь-секрет
.venv\Scripts\python.exe -m murdoku.server
```

**Windows (PowerShell):**

```powershell
$env:MURDOKU_SECRET = "какой-нибудь-секрет"
.venv\Scripts\python.exe -m murdoku.server
```

**Windows (Git Bash):**

```sh
MURDOKU_SECRET=какой-нибудь-секрет .venv/Scripts/python.exe -m murdoku.server
```

- `MURDOKU_SECRET` — обязателен (ключ токенов). Если не задан: при
  `MURDOKU_DEV=1` сервер стартует со случайным ключом процесса (токены
  недействительны после рестарта, в stderr печатается предупреждение), иначе —
  отказ старта.
- `MURDOKU_HOST` / `MURDOKU_PORT` — адрес и порт (по умолчанию `127.0.0.1:8000`).

Открыть <http://127.0.0.1:8000/>.

**Демо-режим без бэкенда:** `http://127.0.0.1:8000/?mock=1` — фронтенд
работает на встроенном мок-пазле (удобно для UI-разработки и оффлайн-демо).
Без `?mock=1` фронтенд ходит в реальный API.

### Тесты

```sh
cd backend && ../.venv/bin/python -m pytest -q   # бэкенд (включая e2e)
cd frontend && node --test                       # фронтенд (чистая логика)
```

**Windows:** в cmd/PowerShell — `..\.venv\Scripts\python.exe -m pytest -q`
из `backend\`; в Git Bash те же команды, что и выше
(`../.venv/Scripts/python.exe`):

```sh
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd frontend && node --test
```

### Бенчмарки

```sh
.venv/bin/python backend/scripts/bench_solver.py     # count_solutions на 9x9/N=9 (бюджет < 100 мс)
.venv/bin/python backend/scripts/bench_generator.py  # время генерации по сложностям (expert < 3 с в среднем)
```

**Windows (Git Bash / cmd):** тот же путь через `.venv/Scripts/python.exe`
(в cmd — `.venv\Scripts\python.exe backend\scripts\bench_solver.py`).

## Структура репозитория

```
backend/
  pyproject.toml          # пакет murdoku (+ dev-зависимости)
  murdoku/
    model.py              # реестр типов, дата-классы, валидация, SPEC §4 JSON
    solver.py             # count_solutions / solutions (MRV, битмаски)
    clues.py              # перечисление истинных подсказок + жадное прореживание
    generator.py          # полный пайплайн генерации (детерминированный по seed)
    server/
      app.py              # Starlette: /api/puzzle, /api/check, статика
      tokens.py           # Fernet-токены (ключ из MURDOKU_SECRET)
  tests/                  # pytest, включая этап 5: test_e2e.py (реальный генератор)
  scripts/
    bench_solver.py       # бенчмарк солвера
    bench_generator.py    # бенчмарк генератора
    export_clue_fixtures.py  # выгрузка фикстур для тестов фронтенда
frontend/
  index.html, styles.css
  js/                     # main, api, mock, board, clues, portraits
  tests/                  # node --test (*.test.mjs) + fixtures/ (реальные пазлы)
```

## API

- `GET /api/puzzle?difficulty={easy|medium|hard|expert}[&seed=N]` →
  `200 {"puzzle": {...}, "token": "..."}`; без `seed` — случайный seed (при неудаче
  генерации сервер сам делает до 5 попыток с новыми seed); с явным `seed` — ровно
  одна детерминированная попытка; неизвестная сложность/плохой seed → `400 {"error"}`;
  исчерпание попыток генератора → `503 {"error"}`.
- `POST /api/check` с телом `{"token", "placements": [{person_id, r, c}...],
  "accusation": person_id}`:
  - победа: `{"won": true, "solution": {...}}`;
  - есть неверные расстановки: `{"won": false, "misplaced_person_id": "..."}` —
    ровно один id, первый неверный в порядке «подозреваемые по номерам, убитый
    последним»;
  - расстановка верна, обвинение нет: `{"won": false, "correct_accusation": false}`;
  - альтернативная победа (расстановка отличается от серверной, но удовлетворяет
    всем подсказкам и правилам — возможна только из-за бага генерации, логируется
    сервером): `{"won": true, "solution": {...}, "alternative": true}`;
  - битый запрос/токен: `400 {"error"}`.
- `GET /api/solution?token=...` → `200 {"solution": {...}, "killer_id": "..."}` —
  сдаться и увидеть ответ (битый токен → `400 {"error"}`).
- `/` — статика фронтенда.
