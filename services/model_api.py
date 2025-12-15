import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Конфигурация Hugging Face Inference API
ENDPOINT_URL = os.getenv("HF_ENDPOINT_URL", "")
API_KEY = os.getenv("HF_API_KEY", "")


def transcribe_audio_api(file_path: str) -> str:
    """Отправляет аудиофайл в Hugging Face Inference API и возвращает транскрипт."""
    try:
        if not ENDPOINT_URL:
            raise RuntimeError("HF_ENDPOINT_URL не установлен в переменных окружения")
        if not API_KEY:
            raise RuntimeError("HF_API_KEY не установлен в переменных окружения")

        with open(file_path, "rb") as f:
            audio_bytes = f.read()

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "audio/wav",
        }

        logger.info(f"Отправка запроса к Hugging Face API: {ENDPOINT_URL}")
        response = requests.post(
            ENDPOINT_URL,
            headers=headers,
            data=audio_bytes,
            timeout=60,
        )

        if response.status_code != 200:
            error_msg = f"API вернул ошибку: {response.status_code} - {response.text}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        result = response.json()

        if isinstance(result, dict):
            transcription = result.get("text") or result.get("transcription") or result.get("output")
            if not transcription and "text" in result:
                transcription = result["text"]
        elif isinstance(result, str):
            transcription = result
        else:
            transcription = result[0] if isinstance(result, list) and len(result) > 0 else str(result)

        if not transcription:
            logger.warning(f"Неожиданный формат ответа API: {result}")
            transcription = str(result)

        logger.info(f"Транскрипция: {transcription}")
        return transcription

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к API: {e}")
        return f"[ERROR] Ошибка при запросе к API: {str(e)}"
    except Exception as e:
        logger.error(f"Ошибка при транскрипции: {e}")
        return f"[ERROR] Ошибка при обработке аудио: {str(e)}"

