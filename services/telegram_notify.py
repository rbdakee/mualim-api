import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram_notification(data, answers_with_labels):
    logger.info(
        f"Попытка отправить уведомление в Telegram. "
        f"TELEGRAM_BOT_TOKEN: {'установлен' if TELEGRAM_BOT_TOKEN else 'не установлен'}, "
        f"TELEGRAM_CHAT_ID: {'установлен' if TELEGRAM_CHAT_ID else 'не установлен'}"
    )

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram не настроен (отсутствует TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID)")
        return

    try:
        from telegram import Bot
        import asyncio

        lead_data = data.get("leadData", {})
        name = lead_data.get("name", "Не указано")
        contact = lead_data.get("contact", "Не указано")

        age = answers_with_labels.get("q1_age", "")
        gender = answers_with_labels.get("q2_gender", "")
        age_gender = ", ".join(filter(None, [age, gender]))

        frequency = answers_with_labels.get("q5_frequency", "")
        where = answers_with_labels.get("q6_where", "")
        reading_info = ", ".join(filter(None, [frequency, where]))

        level = answers_with_labels.get("q4_level", "")
        learning_style = answers_with_labels.get("q7_learning_style", "")
        important = answers_with_labels.get("q9_important", "")
        why = answers_with_labels.get("q11_why", "")

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

        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        async def send_async():
            return await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="HTML")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(send_async())
        logger.info(f"✅ Уведомление успешно отправлено в Telegram. Message ID: {result.message_id}")

    except ImportError as import_error:
        logger.error(f"python-telegram-bot не установлен. Установите: pip install python-telegram-bot. Ошибка: {import_error}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления в Telegram: {type(e).__name__}: {str(e)}", exc_info=True)

