import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_notification(data, expect_answers: dict):
    """
    Синхронная отправка уведомления в Telegram через HTTP API.
    Эталон (ref) не меняем, подсвечиваем только сказанное пользователем на фронте.
    """
    logger.info(
        f"Попытка отправить уведомление в Telegram. "
        f"TELEGRAM_BOT_TOKEN: {'установлен' if TELEGRAM_BOT_TOKEN else 'не установлен'}, "
        f"TELEGRAM_CHAT_ID: {'установлен' if TELEGRAM_CHAT_ID else 'не установлен'}"
    )

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram не настроен (отсутствует TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID)")
        return

    lead_data = data.get("leadData", {})
    name = lead_data.get("name", "Не указано")
    contact = lead_data.get("contact", "Не указано")

    age = expect_answers.get("q1_age", "")
    gender = expect_answers.get("q2_gender", "")
    age_gender = ", ".join(filter(None, [age, gender]))

    frequency = expect_answers.get("q5_frequency", "")
    where = expect_answers.get("q6_where", "")
    reading_info = ", ".join(filter(None, [frequency, where]))

    level = expect_answers.get("q4_level", "")
    learning_style = expect_answers.get("q7_learning_style", "")
    important = expect_answers.get("q9_important", "")
    why = expect_answers.get("q11_why", "")

    message = (
        f"<b>Новый лид</b>\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>{name}:</b> {age_gender}\n\n"
        f"<b>Уровень знаний:</b> {level}\n"
        f"<b>Читает Коран:</b> {reading_info}\n"
        f"<b>Учится:</b> {learning_style}\n"
        f"<b>Важно в таджвиде:</b> {important}\n"
        f"<b>Желание:</b> {why}"
    )

    try:
        url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Ошибка Telegram API: {resp.status_code} {resp.text}")
        else:
            logger.info("✅ Уведомление успешно отправлено в Telegram")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления в Telegram: {type(e).__name__}: {str(e)}", exc_info=True)

