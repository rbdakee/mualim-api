import logging
import os
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    logger.error("gspread не установлен. Установите: pip install gspread google-auth")

SHEET_ID = os.getenv("SHEET_ID", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS", "")
CREDENTIALS_PATH = Path(__file__).parent.parent / "credentials.json"
if not CREDENTIALS_PATH.exists():
    CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"


def get_google_sheets_client():
    if not GSPREAD_AVAILABLE:
        raise RuntimeError("gspread не установлен. Установите: pip install gspread google-auth")

    if not SHEET_ID:
        raise ValueError("SHEET_ID должен быть установлен в переменных окружения")

    try:
        if GOOGLE_CREDENTIALS_JSON:
            creds_data = json.loads(GOOGLE_CREDENTIALS_JSON)
            service_account_email = creds_data.get('client_email', 'неизвестен')
            logger.info(f"Используется Service Account из переменной окружения GOOGLE_CREDENTIALS: {service_account_email}")
        elif CREDENTIALS_PATH.exists():
            with open(CREDENTIALS_PATH, 'r', encoding='utf-8') as f:
                creds_data = json.load(f)
                service_account_email = creds_data.get('client_email', 'неизвестен')
            logger.info(f"Используется Service Account из файла {CREDENTIALS_PATH}: {service_account_email}")
        else:
            logger.warning(f"Не удалось найти credentials: файл {CREDENTIALS_PATH} не существует и GOOGLE_CREDENTIALS не установлен")
    except Exception as e:
        logger.warning(f"Не удалось прочитать email Service Account: {e}")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if GOOGLE_CREDENTIALS_JSON:
        creds_data = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(creds_data, scopes=scope)
        logger.info("✅ Используются credentials из переменной окружения GOOGLE_CREDENTIALS (.env)")
    elif CREDENTIALS_PATH.exists():
        creds = Credentials.from_service_account_file(
            str(CREDENTIALS_PATH),
            scopes=scope
        )
        logger.info(f"✅ Используются credentials из файла: {CREDENTIALS_PATH}")
    else:
        error_msg = (
            f"❌ Не найдены credentials для Google Sheets.\n"
            f"   Файл credentials.json не найден по пути: {CREDENTIALS_PATH}\n"
            f"   И переменная окружения GOOGLE_CREDENTIALS не установлена.\n"
            f"   Решение: Добавьте GOOGLE_CREDENTIALS в .env файл (весь JSON в одну строку) "
            f"или разместите credentials.json в корне проекта."
        )
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    client = gspread.authorize(creds)
    logger.info("Успешно подключено к Google Sheets")
    return client


def ensure_worksheet(spreadsheet):
    try:
        worksheet = spreadsheet.sheet1
        logger.info("Используется существующий лист 'sheet1'")
    except gspread.exceptions.WorksheetNotFound:
        logger.info("Лист 'sheet1' не найден, создаем новый лист 'Leads'")
        worksheet = spreadsheet.add_worksheet(title="Leads", rows=1000, cols=20)
    except Exception as e:
        logger.warning(f"Ошибка при получении листа: {e}, создаем новый")
        worksheet = spreadsheet.add_worksheet(title="Leads", rows=1000, cols=20)
    return worksheet


def find_next_row(worksheet):
    all_values = worksheet.get_all_values()
    next_row = 1
    if len(all_values) > 0:
        for i in range(len(all_values) - 1, -1, -1):
            if any(cell.strip() for cell in all_values[i] if cell):
                next_row = i + 2
                break
        else:
            next_row = 2 if len(all_values) > 0 else 1
    return next_row


def write_headers_if_needed(worksheet, next_row):
    if next_row != 1:
        return
    headers = [
        "Дата и время",
        "Имя",
        "Контакт",
        "Возраст",
        "Пол",
        "Уровень таджвида",
        "Частота чтения",
        "Где читает",
        "Стиль обучения",
        "Что важно",
        "Вдохновение",
        "Зачем вернуться",
        "Длительность занятий",
        "Напоминания",
        "Источник вдохновения",
        "Результат басмалы (%)",
        "Правильно аятов (всего)",
        "Процент слов (Аль-Фатиха)",
        "Все ответы (JSON)"
    ]
    worksheet.update('A1:S1', [headers])


def append_row(worksheet, row_data, next_row):
    range_name = f'A{next_row}:S{next_row}'
    worksheet.update(range_name, [row_data])
    logger.info(f"✅ Данные успешно сохранены в Google Sheets, строка {next_row}, диапазон {range_name}")
    return range_name


def save_lead(data, answers_with_labels):
    client = get_google_sheets_client()
    if not SHEET_ID:
        raise ValueError("SHEET_ID не установлен в переменных окружения")

    logger.info(f"Открываем таблицу с ID: {SHEET_ID}")
    try:
        spreadsheet = client.open_by_key(SHEET_ID)
    except gspread.exceptions.APIError as api_error:
        if api_error.response.status_code == 403:
            error_msg = (
                "Ошибка доступа к Google Sheets (403 Forbidden). "
                "Убедитесь, что:\n"
                "1. Service Account email из credentials.json добавлен в таблицу с правами редактора\n"
                "2. Таблица существует и ID правильный\n"
                "3. Google Sheets API включен в Google Cloud Console"
            )
            logger.error(error_msg)
            raise PermissionError(error_msg) from api_error
        raise

    worksheet = ensure_worksheet(spreadsheet)
    next_row = find_next_row(worksheet)
    write_headers_if_needed(worksheet, next_row)
    if next_row == 1:
        next_row = 2

    row_data = [
        data.get("timestamp", ""),
        data.get("leadData", {}).get("name", ""),
        data.get("leadData", {}).get("contact", ""),
        answers_with_labels.get("q1_age", ""),
        answers_with_labels.get("q2_gender", ""),
        answers_with_labels.get("q4_level", ""),
        answers_with_labels.get("q5_frequency", ""),
        answers_with_labels.get("q6_where", ""),
        answers_with_labels.get("q7_learning_style", ""),
        answers_with_labels.get("q9_important", ""),
        answers_with_labels.get("q10_inspiration", ""),
        answers_with_labels.get("q11_why", ""),
        answers_with_labels.get("q13_duration", ""),
        answers_with_labels.get("q14_reminders", ""),
        answers_with_labels.get("q15_inspiration_source", ""),
        "",
        "",
        "",
        json.dumps(answers_with_labels, ensure_ascii=False)
    ]

    analysis = data.get("analysisResult")
    if analysis:
        message_type = analysis.get("message_type", "")
        if message_type == "text" or ("score_percent" in analysis and "total_ayahs" not in analysis):
            row_data[15] = analysis.get("score_percent", "")
        if message_type == "surah" or ("correct_ayahs" in analysis and "total_ayahs" in analysis):
            row_data[16] = f"{analysis.get('correct_ayahs', 0)}/{analysis.get('total_ayahs', 0)}"
            row_data[17] = analysis.get("score_percent", "")

    append_row(worksheet, row_data, next_row)
    return next_row

