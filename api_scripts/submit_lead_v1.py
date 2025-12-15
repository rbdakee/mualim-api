#!/usr/bin/env python3
"""
submit_lead_v1
--------------

Прослойка между FastAPI (`main_api.py`) и сервисами работы с лидами:
- конвертация кодов ответов в человекочитаемый вид;
- сохранение лида в Google Sheets;
- отправка уведомления в Telegram.
"""

import json
import logging
import sys
from typing import Any, Dict

from services.google_sheets import save_lead
from services.lead_answers import convert_answers_to_labels
from services.telegram_notify import send_telegram_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def save_to_sheets(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Конвертирует ответы анкеты, сохраняет лид в Google Sheets и отправляет Telegram-уведомление.
    Используется эндпоинтом `/api/submit-lead`.
    """
    answers = data.get("answers", {}) or {}
    answers_with_labels = convert_answers_to_labels(answers)

    # Сохранение в Sheets
    row = save_lead(data, answers_with_labels)

    # Уведомление в Telegram (ошибки не ломают сохранение в таблицу)
    try:
        send_telegram_notification(data, answers_with_labels)
    except Exception as telegram_error:
        logger.warning(f"Telegram уведомление не отправлено (данные сохранены): {telegram_error}")

    return {
        "success": True,
        "row": row,
        "message": f"Данные сохранены в строку {row}",
    }


def main() -> None:
    """
    CLI-обёртка для отладки/скриптов:

    ```bash
    python api_scripts/submit_lead_v1.py '{...json...}'
    ```
    """
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "Необходимо передать JSON данные в качестве аргумента",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        sys.exit(1)

    try:
        data_json = sys.argv[1]
        data = json.loads(data_json)
        result = save_to_sheets(data)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    except json.JSONDecodeError as e:
        error_result = {
            "success": False,
            "error": f"Ошибка парсинга JSON: {str(e)}",
        }
        print(json.dumps(error_result, ensure_ascii=False), flush=True)
        sys.exit(1)
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        error_result = {
            "success": False,
            "error": f"Ошибка при сохранении: {error_type}: {error_msg}",
        }
        logger.error(f"Критическая ошибка в main(): {error_type}: {error_msg}", exc_info=True)
        print(json.dumps(error_result, ensure_ascii=False), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()


