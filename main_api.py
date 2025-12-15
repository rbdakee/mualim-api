"""
FastAPI для анализа чтения Корана.

Подключена бизнес-логика из `api_scripts/check_surah_v1.py`.
Эндпоинты:
- GET /health — проверка здоровья
- POST /api/analyze — анализ аудио (webm/wav/mp3). Параметры: surah, ayah_number.
  Если `ayah_number` указан — проверяется конкретный аят, иначе вся сура (пропуская басмалу).
Документация Swagger доступна на /docs.
"""

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv()

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SECRET_TOKEN_API = os.getenv("SECRET_TOKEN_API", "")

# Убедимся, что корень проекта в sys.path (на случай запуска из подкаталогов)
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Импорт бизнес-логики
from api_scripts.check_surah_v1 import (  # type: ignore
    check_quran_ayah_soft,
    format_result_for_api,
    get_full_surah_texts,
    get_surah_data,
)

from api_scripts.submit_lead_v1 import save_to_sheets

app = FastAPI(
    title="Mualim API",
    description=(
        "API для проверки правильности чтения Корана.\n\n"
        "Передавайте аудио (webm/wav/mp3) и параметры surah/ayah_number.\n"
        "При отсутствии ayah_number анализируется вся сура, пропуская басмалу.\n\n"
        "В ответе приходят два уровня выравнивания:\n"
        "- words_check_data — пословно (equal/replace/insert/delete) с индексами слов.\n"
        "- spells_check_data — побуквенно внутри слов, подсветка по hyp (что сказал пользователь).\n"
        "Специализированно для фронта: используются hyp_error_ranges в spells_check_data.words[]."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Health", "description": "Проверка работоспособности сервиса"},
        {
            "name": "Tajwid",
            "description": "Анализ аудио на соответствие тексту Корана",
        },
        {
            "name": "Leads",
            "description": "Сохранение лидов в Google Sheets и уведомления в Telegram (если настроено)",
        },
    ],
)

# CORS (разрешаем всё; для продакшена лучше сузить)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_secret_token(x_api_token: str | None = Header(default=None, alias="X-API-TOKEN")):
    """
    Простая защита API по токену:
    - ожидает заголовок `X-API-TOKEN`;
    - сравнивает с `SECRET_TOKEN_API` из env;
    - если в env токен не задан — выдаёт 500 (конфигурационная ошибка).
    """
    if not SECRET_TOKEN_API:
        raise HTTPException(
            status_code=500,
            detail="SECRET_TOKEN_API не настроен на сервере",
        )
    if x_api_token is None or x_api_token != SECRET_TOKEN_API:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@app.get("/health", tags=["Health"])
async def health():
    """Проверка статуса API."""
    return {"status": "ok", "service": "mualim-api"}


@app.post(
    "/api/analyze",
    tags=["Tajwid"],
    summary="Анализ аудио чтения Корана",
    response_class=JSONResponse,
)
async def analyze(
    audio: UploadFile = File(
        ...,
        description="Аудио-файл (webm/wav/mp3). Для микрофона отправьте blob как multipart/form-data.",
    ),
    surah_raw: str = Form("1", description="Номер суры (по умолчанию 1 — Аль-Фатиха)"),
    ayah_number_raw: Optional[str] = Form(
        None,
        description="Номер аята. Если пусто/не передан — проверяется вся сура (басмала пропускается).",
    ),
    _: None = Depends(verify_secret_token),
):
    """
    Анализирует аудио: сравнивает распознанный текст с эталонным.

    - Если `ayah_number` указан — проверяется конкретный аят (например, басмала 1:1).
    - Если `ayah_number` не указан — проверяется вся сура, басмала пропускается.
    """
    temp_path = None
    try:
        # Разбираем номера суры и аята: пустая строка в форме не должна падать с 422
        try:
            surah = int(surah_raw) if str(surah_raw).strip() else 1
        except ValueError:
            raise HTTPException(status_code=400, detail="surah должен быть целым числом")

        ayah_number: Optional[int]
        if ayah_number_raw is None or str(ayah_number_raw).strip() == "":
            ayah_number = None
        else:
            try:
                ayah_number = int(ayah_number_raw)
            except ValueError:
                raise HTTPException(status_code=400, detail="ayah_number должен быть целым числом")

        logger.info(f"Запрос анализа: surah={surah}, ayah_number={ayah_number}, file={audio.filename}")

        # Сохраняем загруженное аудио во временный файл
        suffix = Path(audio.filename or "").suffix or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            if not content:
                raise HTTPException(status_code=400, detail="Пустой файл")
            tmp.write(content)
            temp_path = tmp.name

        # Анализ конкретного аята
        if ayah_number is not None:
            surah_data = get_surah_data(surah)
            ayah_data = surah_data.get(str(ayah_number))
            if not ayah_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"Аят {ayah_number} не найден в суре {surah}",
                )

            ayah_text = ayah_data[0] if isinstance(ayah_data, list) else ayah_data

            status, score, transcription, details = check_quran_ayah_soft(
                temp_path,
                ayah_text,
                ayahs_info=None,
                verbose=False,
            )

            result = format_result_for_api(
                status,
                score,
                transcription,
                details,
                is_basmalah=(ayah_number == 1),
                surah_number=surah,
            )
        else:
            # Анализ всей суры (басмала пропускается)
            full_surah_norm, _ = get_full_surah_texts(surah, skip_first_ayah=True)
            if not full_surah_norm:
                raise HTTPException(
                    status_code=400,
                    detail=f"Не удалось загрузить текст суры {surah}",
                )

            surah_data = get_surah_data(surah)
            ayahs_info = {str(surah): {}}
            for ayah_num in range(2, len(surah_data) + 1):
                ayah_key = str(ayah_num)
                if ayah_key in surah_data:
                    ayahs_info[str(surah)][ayah_key] = surah_data[ayah_key]

            status, score, transcription, details = check_quran_ayah_soft(
                temp_path,
                full_surah_norm,
                ayahs_info=ayahs_info,
                verbose=False,
            )

            result = format_result_for_api(
                status,
                score,
                transcription,
                details,
                is_basmalah=False,
                surah_number=surah,
            )

        return result

    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover - для логирования
        logger.error(f"Ошибка анализа аудио: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка анализа аудио: {e}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as cleanup_err:  # pragma: no cover
                logger.warning(f"Не удалось удалить временный файл: {cleanup_err}")


class LeadData(BaseModel):
    name: str = Field(..., description="Имя пользователя")
    contact: str = Field(..., description="Контакт (телефон/username и т.д.)")


class SubmitLeadRequest(BaseModel):
    timestamp: Optional[str] = Field(None, description="ISO timestamp (строка)")
    leadData: LeadData = Field(..., description="Данные лида")
    answers: dict = Field(default_factory=dict, description="Ответы анкеты (коды)")
    analysisResult: Optional[dict] = Field(
        None,
        description="Результат анализа (опционально). Можно передавать ответ /api/analyze или его часть.",
    )


@app.post(
    "/api/submit-lead",
    tags=["Leads"],
    summary="Сохранить лид в Google Sheets (и отправить уведомление в Telegram при настройке)",
)
async def submit_lead(payload: SubmitLeadRequest, _: None = Depends(verify_secret_token)):
    """
    Сохраняет данные лида в Google Sheets и (опционально) отправляет уведомление в Telegram.

    Важные требования:
    - `SHEET_ID` должен быть задан в env.
    - `GOOGLE_CREDENTIALS` (JSON одной строкой) или файл `credentials.json` в корне проекта.
    - Для Telegram: `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`.

    Примечание: конвертация ответов (коды -> текст) и отправка Telegram уже реализованы внутри `services/save_new_lead.py`.
    """
    try:
        data = payload.model_dump()
        logger.info(f"Получен лид: {data.get('leadData', {}).get('name', 'Unknown')}")
        result = save_to_sheets(data)
        return result
    except Exception as e:
        logger.error(f"Ошибка при сохранении лида: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при сохранении лида: {e}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 5000))
    logger.info(f"Запуск сервера на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

