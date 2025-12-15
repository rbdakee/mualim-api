# Tajwid API (mualim-api)

REST API и скрипты для проверки чтения Корана.

## Архитектура
- `main_api.py` — FastAPI-приложение (эндпоинты, Swagger).
- `api_scripts/`
  - `check_surah_v1.py` — логика анализа аятов/сур.
  - `submit_lead_v1.py` — логика сохранения лида (оркестрация сервисов).
- `services/`
  - `prepare_audio.py` — подготовка/конвертация аудио.
  - `model_api.py` — вызов Hugging Face Inference API (ASR).
  - `google_sheets.py` — сохранение лидов в Google Sheets.
  - `telegram_notify.py` — уведомления в Telegram.
  - `lead_answers.py` — маппинг кодов ответов в человекочитаемый вид.

## Запуск
```bash
pip install -r requirements.txt
uvicorn main_api:app --host 0.0.0.0 --port 5000
```
Нужны переменные окружения:
- `HF_ENDPOINT_URL` — endpoint модели HF
- `HF_API_KEY` — токен
- `SECRET_TOKEN_API` — секретный токен для доступа к API (см. секцию "Безопасность")

## Docker
Сборка и запуск:
```bash
docker build -t mualim-api .
docker run --rm -p 5000:5000 \
  -e HF_ENDPOINT_URL=... \
  -e HF_API_KEY=... \
  mualim-api
```
Образ основан на python:3.11-slim, включает ffmpeg для конвертации аудио.

## Эндпоинт /api/analyze
`POST /api/analyze`
- form-data:
  - `audio` (file, webm/wav/mp3)
  - `surah` (int, default 1)
  - `ayah_number` (int, optional) — если не указан, проверяется вся сура (басмала пропускается).

## Эндпоинт /api/submit-lead
`POST /api/submit-lead`

Сохраняет лид в Google Sheets и (если настроено) отправляет уведомление в Telegram.

Требования по env:
- `SHEET_ID`
- `GOOGLE_CREDENTIALS` (JSON одной строкой) **или** `credentials.json` в корне проекта
- (опционально) `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

Пример запроса:
```json
{
  "timestamp": "2025-12-15T12:00:00Z",
  "leadData": { "name": "Имя", "contact": "+77001234567" },
  "answers": {
    "q1_age": "age_18_25",
    "q2_gender": "male"
  },
  "analysisResult": {
    "score_percent": 87.59,
    "message_type": "surah"
  }
}
```

## Безопасность (SECRET_TOKEN_API)
Все защищённые эндпоинты (`/api/analyze`, `/api/submit-lead`) требуют заголовок:

- `X-API-TOKEN: <значение SECRET_TOKEN_API из .env>`

Правила:
- Если `SECRET_TOKEN_API` **не настроен** в окружении — сервер вернёт `500` (конфигурационная ошибка).
- Если заголовок отсутствует или токен не совпадает — `401 Invalid or missing API token`.

### Ключевые поля ответа
- `message_type`: `"text"` (один аят) или `"surah"` (вся сура)
- `score`, `score_percent`, `is_correct`, `transcription`
- `ayahs`: список аятов с детальным выравниванием

#### words_check_data (пословное выравнивание)
В каждом `ayahs[i]`:
```json
"words_check_data": {
  "ref_words": ["مالك", "يوم", "الدين"],
  "hyp_words": ["ما", "لليوم", "الدين"],
  "word_ops": [
    { "op": "replace", "ref_start": 0, "ref_end": 1, "hyp_start": 0, "hyp_end": 1,
      "ref_words": ["مالك"], "hyp_words": ["ما"] },
    { "op": "replace", "ref_start": 1, "ref_end": 2, "hyp_start": 1, "hyp_end": 2,
      "ref_words": ["يوم"], "hyp_words": ["لليوم"] },
    { "op": "equal", "ref_start": 2, "ref_end": 3, "hyp_start": 2, "hyp_end": 3,
      "ref_words": ["الدين"], "hyp_words": ["الدين"] }
  ]
}
```
`op` ∈ {`equal`, `replace`, `insert`, `delete`}. Индексы — позиции слов в ref/hyp.

#### spells_check_data (побуквенное внутри слов, подсветка по hyp)
В каждом `ayahs[i]`:
```json
"spells_check_data": {
  "normalization": {
    "tool": "quran_transcript.normalize_aya" | "regex_fallback",
    "remove_spaces": true,
    "ignore_hamazat": true,
    "ignore_alef_maksoora": true,
    "ignore_taa_marboota": true,
    "normalize_taat": false,
    "remove_small_alef": true,
    "remove_tashkeel": true
  },
  "words": [
    {
      "op": "replace",
      "ref_idx": 1,
      "hyp_idx": 1,
      "ref_word": "يوم",
      "hyp_word": "لليوم",
      "ref_norm": "يوم",
      "hyp_norm": "لليوم",
      "hyp_char_ops": [
        { "op": "insert",  "ref_span": [0,0], "hyp_span": [0,2], "ref": "",  "hyp": "لل" },
        { "op": "equal",   "ref_span": [0,1], "hyp_span": [2,3], "ref": "ي", "hyp": "ي" },
        { "op": "equal",   "ref_span": [1,2], "hyp_span": [3,4], "ref": "و", "hyp": "و" },
        { "op": "equal",   "ref_span": [2,3], "hyp_span": [4,5], "ref": "م", "hyp": "م" }
      ],
      "hyp_error_ranges": [[0,2]],
      "has_missing": false
    }
  ]
}
```
Как подсвечивать на фронте:
- Берёте `hyp_word` и подсвечиваете диапазоны `hyp_error_ranges` (список [start,end) по символам нормализованного `hyp_word`).
- `op` на уровне слов: `equal/replace/insert/delete`. На уровне букв — в `hyp_char_ops` (slice-подход, а не посимвольно), но для подсветки достаточно `hyp_error_ranges`.
- Если слово пропущено (op=delete) — подсветки букв нет, можно показать “missing”.

## Выравнивание в API-ответе (кратко)
- Пословно: `words_check_data.word_ops` (индексы + op).
- Побуквенно: `spells_check_data.words[].hyp_error_ranges` — подсветка по сказанному пользователем.
- Эталонный текст не подсвечиваем, только hyp.

## Нормализация
Используется `quran_transcript.normalize_aya` с параметрами:
```
remove_spaces=True
ignore_hamazat=True
ignore_alef_maksoora=True
ignore_taa_marboota=True
normalize_taat=False
remove_small_alef=True
remove_tashkeel=True
```
Если библиотека недоступна, включается regex-fallback.

## Быстрый чек для фронта
- Смотрите `ayahs[].words_check_data.word_ops` → определяете проблемные слова.
- Смотрите `ayahs[].spells_check_data.words[].hyp_error_ranges` → подсвечиваете буквы в hyp_word.
- Для вставок (insert) — подсвечиваются диапазоны вставленных символов в hyp.
- Для замен (replace) — подсвечиваются заменённые фрагменты в hyp.
- Для пропусков (delete) — подсветки в hyp нет, можно показать маркер “missing”.

