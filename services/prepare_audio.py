import logging
import os
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Проверяем наличие imageio-ffmpeg для конвертации аудио
try:
    import imageio_ffmpeg as iio_ffmpeg

    FFMPEG_AVAILABLE = True
except ImportError:
    FFMPEG_AVAILABLE = False
    logger.warning("imageio-ffmpeg не установлен. Установите: pip install imageio-ffmpeg")


def convert_webm_to_wav(webm_path: str) -> str:
    """Конвертирует webm (или совместимый формат) в wav через ffmpeg и возвращает путь к временному файлу."""
    if not FFMPEG_AVAILABLE:
        raise RuntimeError("imageio-ffmpeg не установлен. Необходим для конвертации webm в wav.")

    try:
        fd_wav, wav_path = tempfile.mkstemp(suffix=".wav", prefix="tajwid_audio_")
        os.close(fd_wav)

        ffmpeg_path = iio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            webm_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            wav_path,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode("utf-8", errors="ignore")
            os.unlink(wav_path)
            raise RuntimeError(f"Ошибка конвертации webm в wav: {error_msg}")

        return wav_path

    except Exception as e:
        logger.error(f"Ошибка при конвертации webm в wav: {e}")
        raise e


def prepare_audio_file(file_path: str) -> str:
    """Готовит аудиофайл к отправке в API: при необходимости конвертирует в wav и возвращает путь."""
    temp_wav_path = None
    try:
        lower = file_path.lower()
        if lower.endswith(".webm"):
            if not FFMPEG_AVAILABLE:
                raise RuntimeError("imageio-ffmpeg не установлен. Необходим для обработки webm файлов.")
            temp_wav_path = convert_webm_to_wav(file_path)
            return temp_wav_path

        if lower.endswith(".wav"):
            return file_path

        if not FFMPEG_AVAILABLE:
            raise RuntimeError("imageio-ffmpeg не установлен. Необходим для конвертации аудио.")

        temp_wav_path = convert_webm_to_wav(file_path)
        return temp_wav_path

    except Exception as e:
        logger.error(f"Ошибка при подготовке аудио: {e}")
        raise e


