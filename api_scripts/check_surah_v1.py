import os, re, logging, sys, argparse, json
from difflib import SequenceMatcher
from typing import Dict, List, Optional
from dotenv import load_dotenv

from services.model_api import transcribe_audio_api
from services.prepare_audio import prepare_audio_file
# Устанавливаем правильную кодировку для Windows
if sys.platform == 'win32':
    try:
        import codecs
        # Проверяем, есть ли buffer (не все потоки имеют buffer)
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except (AttributeError, OSError):
        # Если не удалось установить кодировку, продолжаем работу
        pass

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Попытка использовать нормализацию из quran_transcript
try:
    from quran_transcript import normalize_aya as _normalize_aya_lib  # type: ignore
except Exception:
    _normalize_aya_lib = None  # type: ignore

# Регулярное выражение для удаления харакатов (диакритических знаков) — fallback
HARAKAT_RE = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")

# Пороговые значения для мягкой оценки
THRESHOLD_CORRECT = 0.92    # ≥ 92% — считаем правильным
THRESHOLD_PARTIAL = 0.70    # ≥ 70% — частично правильно
# < 70% — неправильное чтение

_surah_cache: Dict[str, Dict[str, str]] = {}


def fetch_surah_from_library(surah_number: int) -> Dict[str, str]:
    """
    Загружает аяты суры через библиотеку quran-transcript.
    Возвращает словарь {str(ayah_num): ayah_text_imlaey}.
    """
    try:
        from quran_transcript import Aya  # type: ignore
    except Exception:
        raise RuntimeError(
            "Библиотека quran-transcript не установлена. Установите: pip install quran-transcript"
        )

    ayahs: List[str] = []
    try:
        # Идем по аятам, пока не встретим исключение (ограничиваемся безопасным максимумом)
        for ayah_num in range(1, 301):
            try:
                aya_obj = Aya(surah_number, ayah_num)
                aya_info = aya_obj.get()  # dataclass AyaFormat
                ayahs.append(aya_info.imlaey)
            except Exception:
                break
    except Exception as e:
        logger.error(f"Ошибка при получении суры {surah_number} через quran-transcript: {e}")

    if not ayahs:
        raise RuntimeError(
            f"Не удалось загрузить суру {surah_number} через quran-transcript. "
            "Проверьте установку пакета и доступность данных."
        )

    return {str(idx + 1): ayah for idx, ayah in enumerate(ayahs)}


def get_surah_data(surah_number: int) -> Dict[str, str]:
    """
    Возвращает словарь аятов для указанной суры из кэша или, при отсутствии, грузит через quran-transcript.
    """
    surah_key = str(surah_number)
    if surah_key not in _surah_cache:
        _surah_cache[surah_key] = fetch_surah_from_library(surah_number)
        logger.info(f"✅ Сура {surah_number} загружена из quran-transcript")
    return _surah_cache[surah_key]



def normalize_arabic(text: str) -> str:
    """
    Нормализация арабского текста.
    Приоритет: quran_transcript.normalize_aya с заданными параметрами.
    Fallback: прежняя regex-нормализация.
    """
    if _normalize_aya_lib:
        try:
            return _normalize_aya_lib(
                text,
                remove_spaces=False,
                ignore_hamazat=True,
                ignore_alef_maksoora=True,
                ignore_taa_marboota=True,  # предпочтительно для ASR
                normalize_taat=False,      # не заменяем ة -> ت
                remove_small_alef=True,
                remove_tashkeel=True,
            )
        except Exception as e:
            logger.warning(f"normalize_aya fallback из-за ошибки: {e}")

    # Fallback: базовая регекс-нормализация
    text = HARAKAT_RE.sub("", text)
    text = re.sub("[ٱأإآا]", "ا", text)
    text = text.replace("ـ", "")
    text = re.sub(r"[۞۩۝ۣ۪ۭۚۗۛۜ۟۠ۢۤۧۨ۫۬ۮۯ]", "", text)
    text = " ".join(text.split())
    return text


def merge_ranges(ranges: List[List[int]]) -> List[List[int]]:
    """Сливает пересекающиеся/смежные интервалы [start, end)."""
    if not ranges:
        return []
    ranges = sorted(ranges, key=lambda r: r[0])
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # пересекаются или касаются
            merged[-1][1] = max(last_end, end)
        else:
            merged.append([start, end])
    return merged


def build_word_ops(ref_words: List[str], hyp_words: List[str]) -> List[Dict]:
    """Возвращает список операций выравнивания по словам (SequenceMatcher opcodes)."""
    ops = []
    matcher = SequenceMatcher(None, ref_words, hyp_words)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        ops.append(
            {
                "op": tag,
                "ref_start": i1,
                "ref_end": i2,
                "hyp_start": j1,
                "hyp_end": j2,
                "ref_words": ref_words[i1:i2],
                "hyp_words": hyp_words[j1:j2],
            }
        )
    return ops


def build_char_ops(ref_word: str, hyp_word: str) -> Dict:
    """
    Посимвольное выравнивание одного слова.
    Возвращает char_ops (срезы), hyp_error_ranges и флаг has_missing.
    """
    matcher = SequenceMatcher(None, ref_word, hyp_word)
    char_ops = []
    hyp_error_ranges: List[List[int]] = []
    has_missing = False

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        segment = {
            "op": tag,
            "ref_span": [i1, i2],
            "hyp_span": [j1, j2],
            "ref": ref_word[i1:i2],
            "hyp": hyp_word[j1:j2],
        }
        char_ops.append(segment)

        if tag in ("replace", "insert"):
            if j1 != j2:
                hyp_error_ranges.append([j1, j2])
        if tag == "delete":
            has_missing = True

    hyp_error_ranges = merge_ranges(hyp_error_ranges)

    return {
        "char_ops": char_ops,
        "hyp_error_ranges": hyp_error_ranges,
        "has_missing": has_missing,
    }


def build_spells_for_word_pair(ref_word: str, hyp_word: str, ref_idx: Optional[int], hyp_idx: Optional[int]) -> Dict:
    """Формирует spells-запись для пары слов (или вставки/пропуска)."""
    ref_norm = normalize_arabic(ref_word) if ref_word else ""
    hyp_norm = normalize_arabic(hyp_word) if hyp_word else ""

    if hyp_word == "":
        # слово пропущено в гипотезе
        return {
            "op": "delete",
            "ref_idx": ref_idx,
            "hyp_idx": hyp_idx,
            "ref_word": ref_word,
            "hyp_word": hyp_word,
            "ref_norm": ref_norm,
            "hyp_norm": hyp_norm,
            "hyp_char_ops": [],
            "hyp_error_ranges": [],
            "has_missing": True,
        }

    char_diff = build_char_ops(ref_norm, hyp_norm)

    return {
        "op": "equal" if not char_diff["hyp_error_ranges"] and not char_diff["has_missing"] else "replace",
        "ref_idx": ref_idx,
        "hyp_idx": hyp_idx,
        "ref_word": ref_word,
        "hyp_word": hyp_word,
        "ref_norm": ref_norm,
        "hyp_norm": hyp_norm,
        "hyp_char_ops": char_diff["char_ops"],
        "hyp_error_ranges": char_diff["hyp_error_ranges"],
        "has_missing": char_diff["has_missing"],
    }

def similarity_ratio(a: str, b: str) -> float:
    """Возвращает коэффициент схожести (0.0-1.0) двух строк"""
    return SequenceMatcher(None, a, b).ratio()

def highlight_differences(ref: str, hyp: str, max_items: int = 5):
    """
    Находит слова, которые не совпали, и возвращает короткий список проблемных фрагментов.
    """
    ref_words = ref.split()
    hyp_words = hyp.split()
    diffs = []
    
    # Проходим по парам (ограниченно)
    for i, rw in enumerate(ref_words):
        if i < len(hyp_words):
            hw = hyp_words[i]
            if rw != hw:
                diffs.append((rw, hw))
        else:
            diffs.append((rw, "<пропущено>"))
        if len(diffs) >= max_items:
            break
    
    # Проверяем лишние слова в гипотезе
    if len(hyp_words) > len(ref_words) and len(diffs) < max_items:
        for i in range(len(ref_words), len(hyp_words)):
            if len(diffs) >= max_items:
                break
            diffs.append(("<лишнее>", hyp_words[i]))
    
    return diffs

def align_text_to_ayahs(ref_words, hyp_words, ayah_boundaries):
    """
    Выравнивает распознанный текст по аятам.
    
    Args:
        ref_words: список слов эталонного текста (все аяты вместе)
        hyp_words: список слов распознанного текста
        ayah_boundaries: список границ аятов в ref_words [(start_idx, end_idx), ...]
    
    Returns:
        list: список кортежей (start_idx, end_idx) для каждого аята в hyp_words
    """
    if not ayah_boundaries:
        return []
    
    # Используем SequenceMatcher для выравнивания
    matcher = SequenceMatcher(None, ref_words, hyp_words)
    matches = []
    
    # Собираем все совпадения
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or tag == "replace":
            matches.append((i1, i2, j1, j2))
    
    # Для каждого аята находим соответствующий фрагмент в распознанном тексте
    hyp_boundaries = []
    for ref_start, ref_end in ayah_boundaries:
        # Ищем совпадения, которые пересекаются с границами аята
        hyp_start = None
        hyp_end = None
        
        for i1, i2, j1, j2 in matches:
            # Если совпадение пересекается с аятом
            if i1 < ref_end and i2 > ref_start:
                if hyp_start is None:
                    hyp_start = j1
                hyp_end = j2
        
        # Если не нашли точного совпадения, используем пропорциональное распределение
        if hyp_start is None:
            total_ref_words = len(ref_words)
            if total_ref_words > 0:
                ref_ratio_start = ref_start / total_ref_words
                ref_ratio_end = ref_end / total_ref_words
                hyp_start = int(ref_ratio_start * len(hyp_words))
                hyp_end = int(ref_ratio_end * len(hyp_words))
            else:
                hyp_start = 0
                hyp_end = 0
        
        hyp_boundaries.append((hyp_start, hyp_end))
    
    return hyp_boundaries

def get_full_surah_texts(surah_number, skip_first_ayah: bool = False):
    """
    Получает полный текст суры из всех аятов в двух вариантах:
    - нормализованный (без харакатов) — для проверки
    - с харакатами — для отображения пользователю
    
    Returns:
        tuple[str, str]: (normalized_text, display_text)
    """
    surah = get_surah_data(surah_number)
    
    norm_ayahs = []
    display_ayahs = []
    # Если нужно, пропускаем первый аят (Бисмиллях)
    start_index = 2 if skip_first_ayah else 1
    for i in range(start_index, len(surah) + 1):
        ayah_data = surah.get(str(i))
        if not ayah_data:
            continue
        # quran-transcript возвращает строку — используем как есть
        norm_ayahs.append(ayah_data)
        display_ayahs.append(ayah_data)
    
    return " ".join(norm_ayahs), " ".join(display_ayahs)

def check_quran_ayah_soft(file_path, correct_ayah, ayahs_info=None, verbose=False):
    """
    Мягкая проверка с процентным совпадением и градацией.
    
    Args:
        file_path: путь к аудиофайлу
        correct_ayah: правильный текст (может быть весь текст суры или один аят)
        ayahs_info: опционально, словарь с информацией об аятах для разбивки результата
                   Формат: {surah_num: {ayah_num: [normalized, display], ...}, ...}
        verbose: выводить ли подробную информацию в лог
    
    Returns:
        tuple: (status, score, transcription, details)
            - status: "correct", "partial", "incorrect" или "error"
            - score: float от 0.0 до 1.0 (процент совпадения)
            - transcription: распознанный текст
            - details: словарь с дополнительной информацией, включая "ayahs_breakdown" если передан ayahs_info
    """
    try:
        # Готовим аудио (конвертация в wav при необходимости) и отправляем в модель
        prepared_path = prepare_audio_file(file_path)
        transcription = transcribe_audio_api(prepared_path)
        if transcription.startswith("[ERROR]") or transcription.startswith("❌"):
            return "error", 0.0, transcription.replace("❌", "[ERROR]"), {"msg": transcription.replace("❌", "[ERROR]")}
        
        # Нормализуем оба текста
        hyp = normalize_arabic(transcription)
        ref = normalize_arabic(correct_ayah)
        
        # Вычисляем похожесть
        score = similarity_ratio(ref, hyp)
        
        # Градация по пороговым значениям
        if score >= THRESHOLD_CORRECT:
            status = "correct"
        elif score >= THRESHOLD_PARTIAL:
            status = "partial"
        else:
            status = "incorrect"
        
        # Собираем детали для обратной связи
        details = {
            "normalized_ref": ref,
            "normalized_hyp": hyp,
            "score": round(score, 4),
            "score_percent": round(score * 100, 2),
            "diffs": highlight_differences(ref, hyp),
            "advice": None,
        }
        
        # Если передан ayahs_info, создаем разбивку по аятам
        if ayahs_info:
            ayahs_breakdown = {}
            ref_words = ref.split()
            hyp_words = hyp.split()
            
            for surah_num, ayahs in ayahs_info.items():
                ayahs_breakdown[surah_num] = {}
                ayah_boundaries = []
                current_idx = 0
                
        # Собираем границы аятов в эталонном тексте
                for ayah_num in sorted(ayahs.keys(), key=int):
                    ayah_data = ayahs[ayah_num]
                    if isinstance(ayah_data, list):
                        ayah_norm = ayah_data[0]
                    else:
                        ayah_norm = ayah_data
                    
                    ayah_words = ayah_norm.split()
                    ayah_start = current_idx
                    ayah_end = current_idx + len(ayah_words)
                    ayah_boundaries.append((ayah_start, ayah_end))
                    current_idx = ayah_end
                
                # Выравниваем распознанный текст по аятам
                hyp_boundaries = align_text_to_ayahs(ref_words, hyp_words, ayah_boundaries)
                
                # Собираем результат для каждого аята
                for idx, (ayah_num, ayah_data) in enumerate(sorted(ayahs.items(), key=lambda x: int(x[0]))):
                    if isinstance(ayah_data, list):
                        ayah_display = ayah_data[1] if len(ayah_data) > 1 else ayah_data[0]
                        ayah_norm = ayah_data[0]
                    else:
                        ayah_display = ayah_data
                        ayah_norm = ayah_data
                    
                    # Получаем распознанный фрагмент для этого аята
                    if idx < len(hyp_boundaries):
                        hyp_start, hyp_end = hyp_boundaries[idx]
                        read_text = " ".join(hyp_words[hyp_start:hyp_end]) if hyp_words else ""
                    else:
                        read_text = ""
                    
                    # Подготовка word-level и char-level данных
                    ref_words_norm = normalize_arabic(ayah_norm).split()
                    hyp_words_norm = normalize_arabic(read_text).split()

                    word_ops = build_word_ops(ref_words_norm, hyp_words_norm)

                    spells_words = []
                    for op in word_ops:
                        ref_slice = op["ref_words"]
                        hyp_slice = op["hyp_words"]
                        ref_start = op["ref_start"]
                        hyp_start = op["hyp_start"]

                        max_len = max(len(ref_slice), len(hyp_slice))
                        for offset in range(max_len):
                            ref_word = ref_slice[offset] if offset < len(ref_slice) else ""
                            hyp_word = hyp_slice[offset] if offset < len(hyp_slice) else ""
                            ref_idx = ref_start + offset if ref_word else None
                            hyp_idx = hyp_start + offset if hyp_word else None

                            spell_entry = build_spells_for_word_pair(ref_word, hyp_word, ref_idx, hyp_idx)
                            # Для оп insert/delete оставляем исходный op, иначе берём вычисленный
                            if op["op"] in ("insert", "delete"):
                                spell_entry["op"] = op["op"]
                            spells_words.append(spell_entry)

                    ayahs_breakdown[surah_num][ayah_num] = {
                        "ayah": ayah_display,
                        "normalized": ayah_norm,
                        "read": read_text,
                        "words_check_data": {
                            "ref_words": ref_words_norm,
                            "hyp_words": hyp_words_norm,
                            "word_ops": word_ops,
                        },
                        "spells_check_data": {
                            "normalization": {
                                "tool": "quran_transcript.normalize_aya" if _normalize_aya_lib else "regex_fallback",
                                "remove_spaces": True,
                                "ignore_hamazat": True,
                                "ignore_alef_maksoora": True,
                                "ignore_taa_marboota": True,
                                "normalize_taat": False,
                                "remove_small_alef": True,
                                "remove_tashkeel": True,
                            },
                            "words": spells_words,
                        },
                    }
            
            details["ayahs_breakdown"] = ayahs_breakdown
        
        # Генерируем дружелюбные советы в зависимости от статуса
        if status == "correct":
            details["advice"] = "[OK] Отлично — аят прочитан верно (или близко к верному)."
        elif status == "partial":
            details["advice"] = "[WARN] Частично верно — обратите внимание на отдельные слова. Попробуйте медленнее и четче."
        else:
            details["advice"] = "[ERROR] Похоже, надо повторить. Попробуйте медленнее, сфокусируйтесь на артикуляции сомнительных слов."
        
        if verbose:
            logger.info(f"Status: {status}, score={score:.4f}, diffs={details['diffs']}")
            if ayahs_info:
                logger.info(f"Ayahs breakdown: {details.get('ayahs_breakdown', {})}")
        
        return status, score, transcription, details
        
    except Exception as e:
        logger.error(f"Ошибка при мягкой проверке: {e}")
        return "error", 0.0, f"[ERROR] Ошибка при проверке: {e}", {"msg": str(e)}

def format_result_for_api(status, score, transcription, details, is_basmalah=False, surah_number=1):
    """
    Форматирует результат проверки для API в формате, ожидаемом фронтендом.
    """
    result = {
        "success": status != "error",
        "transcription": transcription,
        "is_correct": status == "correct",
        "score": details.get("score", 0),
        "score_percent": details.get("score_percent", 0),
        "advice": details.get("advice", ""),
        "normalized_ref": details.get("normalized_ref", ""),
        "normalized_hyp": details.get("normalized_hyp", ""),
        "diffs": details.get("diffs", [])
    }
    
    if status == "error":
        result["error"] = transcription
        return result
    
    # Для басмалы (один аят)
    if is_basmalah:
        result["message_type"] = "text"
        result["reference"] = details.get("normalized_ref", "")
        # Создаем простое выравнивание для басмалы
        ref_words = result["reference"].split()
        hyp_words = result["normalized_hyp"].split()
        alignment = []
        matcher = SequenceMatcher(None, ref_words, hyp_words)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for idx in range(i1, i2):
                    if idx < len(ref_words):
                        alignment.append({
                            "op": "equal",
                            "ref_word": ref_words[idx],
                            "ref_idx": idx
                        })
            elif tag == "replace":
                for idx in range(i1, i2):
                    if idx < len(ref_words):
                        alignment.append({
                            "op": "replace",
                            "ref_word": ref_words[idx],
                            "ref_idx": idx
                        })
            elif tag == "delete":
                for idx in range(i1, i2):
                    if idx < len(ref_words):
                        alignment.append({
                            "op": "delete",
                            "ref_word": ref_words[idx],
                            "ref_idx": idx
                        })
            elif tag == "insert":
                for idx in range(j1, j2):
                    if idx < len(hyp_words):
                        alignment.append({
                            "op": "insert",
                            "hyp_word": hyp_words[idx]
                        })
        result["alignment"] = {"word": alignment}
        result["metrics"] = {
            "wer": 1 - score
        }
        return result
    
    # Для всей суры (с разбивкой по аятам)
    ayahs_breakdown = details.get("ayahs_breakdown", {})
    if ayahs_breakdown:
        result["message_type"] = "surah"
        ayahs = []
        surah_data = ayahs_breakdown.get(str(surah_number), {})
        
        for ayah_num in sorted(surah_data.keys(), key=int):
            ayah_info = surah_data[ayah_num]
            ayah_norm = ayah_info.get("normalized", "")
            ayah_display = ayah_info.get("ayah", "")
            read_text = ayah_info.get("read", "")
            
            # Вычисляем score для этого аята
            ayah_score = similarity_ratio(normalize_arabic(ayah_norm), normalize_arabic(read_text))
            ayah_is_correct = ayah_score >= THRESHOLD_CORRECT
            
            # Создаем выравнивание для аята
            ref_words = normalize_arabic(ayah_norm).split()
            hyp_words = normalize_arabic(read_text).split()
            alignment = []
            matcher = SequenceMatcher(None, ref_words, hyp_words)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    for idx in range(i1, i2):
                        if idx < len(ref_words):
                            alignment.append({
                                "op": "equal",
                                "ref_word": ref_words[idx],
                                "ref_idx": idx
                            })
                elif tag == "replace":
                    for idx in range(i1, i2):
                        if idx < len(ref_words):
                            alignment.append({
                                "op": "replace",
                                "ref_word": ref_words[idx],
                                "ref_idx": idx
                            })
                elif tag == "delete":
                    for idx in range(i1, i2):
                        if idx < len(ref_words):
                            alignment.append({
                                "op": "delete",
                                "ref_word": ref_words[idx],
                                "ref_idx": idx
                            })
                elif tag == "insert":
                    for idx in range(j1, j2):
                        if idx < len(hyp_words):
                            alignment.append({
                                "op": "insert",
                                "hyp_word": hyp_words[idx]
                            })
            
            ayahs.append({
                "ayah_number": int(ayah_num),
                "ayah_text": ayah_display,
                "is_correct": ayah_is_correct,
                "score": round(ayah_score, 4),
                "alignment": {"word": alignment},
                "read_words": read_text.split() if read_text else [],
                "remaining_words": []
            })
        
        result["ayahs"] = ayahs
        result["correct_ayahs"] = sum(1 for a in ayahs if a["is_correct"])
        result["total_ayahs"] = len(ayahs)
        result["all_correct"] = result["correct_ayahs"] == result["total_ayahs"]
    
    return result

def main():
    parser = argparse.ArgumentParser(description="Проверка чтения Корана с помощью AI")
    parser.add_argument("audio_file", type=str, help="Путь к аудиофайлу")
    parser.add_argument("--surah", type=int, default=1, help="Номер суры (по умолчанию 1 - Аль-Фатиха)")
    parser.add_argument("--ayah-number", type=int, dest="ayah_number", default=None, help="Номер аята для проверки (опционально, для басмалы используйте 1)")
    
    args = parser.parse_args()
    
    file_path = args.audio_file
    surah_number = args.surah
    ayah_number = args.ayah_number
    
    if not os.path.exists(file_path):
        result = {
            "success": False,
            "error": f"Файл не найден: {file_path}"
        }
        result_json = json.dumps(result, ensure_ascii=False)
        print(result_json, flush=True)
        sys.exit(1)
    
    try:
        # Если указан номер аята, проверяем только этот аят (для басмалы)
        if ayah_number is not None:
            surah = get_surah_data(surah_number)
            ayah_data = surah.get(str(ayah_number))
            if not ayah_data:
                result = {
                    "success": False,
                    "error": f"Аят {ayah_number} не найден в суре {surah_number}"
                }
                result_json = json.dumps(result, ensure_ascii=False)
                print(result_json, flush=True)
                sys.exit(1)
            
            # Получаем нормализованный текст аята
            ayah_text = ayah_data
            
            # Проверяем аят
            status, score, transcription, details = check_quran_ayah_soft(
                file_path,
                ayah_text,
                verbose=False
            )
            
            # Форматируем результат для API
            result = format_result_for_api(status, score, transcription, details, is_basmalah=(ayah_number == 1))
            
        else:
            # Проверяем всю суру (без басмалы)
            full_surah_norm, full_surah_display = get_full_surah_texts(surah_number, skip_first_ayah=True)
            
            if not full_surah_norm:
                result = {
                    "success": False,
                    "error": f"Не удалось загрузить текст суры {surah_number}"
                }
                result_json = json.dumps(result, ensure_ascii=False)
                print(result_json, flush=True)
                sys.exit(1)
            
            # Подготавливаем информацию об аятах для разбивки
            surah_data = get_surah_data(surah_number)
            ayahs_info = {str(surah_number): {}}
            
            # Пропускаем первый аят (басмала)
            for ayah_num in range(2, len(surah_data) + 1):
                ayah_key = str(ayah_num)
                if ayah_key in surah_data:
                    ayahs_info[str(surah_number)][ayah_key] = surah_data[ayah_key]
            
            # Проверяем всю суру
            status, score, transcription, details = check_quran_ayah_soft(
                file_path,
                full_surah_norm,
                ayahs_info=ayahs_info,
                verbose=False
            )
            
            # Форматируем результат для API
            result = format_result_for_api(status, score, transcription, details, is_basmalah=False, surah_number=surah_number)
        
        # Выводим результат в формате JSON (без эмодзи в сообщениях об ошибках для совместимости с Windows)
        result_json = json.dumps(result, ensure_ascii=False, indent=2)
        # Заменяем эмодзи на текстовые символы для совместимости
        result_json = result_json.replace('❌', '[ERROR]').replace('✅', '[OK]').replace('⚠️', '[WARN]')
        print(result_json, flush=True)
        
    except Exception as e:
        logger.error(f"Ошибка в main: {e}", exc_info=True)
        error_msg = str(e).replace('❌', '[ERROR]').replace('✅', '[OK]').replace('⚠️', '[WARN]')
        result = {
            "success": False,
            "error": f"Ошибка при обработке: {error_msg}"
        }
        result_json = json.dumps(result, ensure_ascii=False)
        result_json = result_json.replace('❌', '[ERROR]').replace('✅', '[OK]').replace('⚠️', '[WARN]')
        print(result_json, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

