"""
Маппинг и конвертация кодов ответов лида в человекочитаемый вид.
"""

ANSWER_LABELS = {
    "age_under18": "До 18 лет",
    "age_18_25": "18–25 лет",
    "age_26_35": "26–35 лет",
    "age_36_45": "36–45 лет",
    "age_over45": "Старше 45 лет",
    "male": "Мужчина",
    "female": "Женщина",
    "basics": "Только изучал(а) основы",
    "forgot": "Проходил(а) курс, но многое забыл(а)",
    "know_no_practice": "Уверенно знаю правила, но не практикую",
    "practice_improve": "Практикую, но хочу улучшить произношение",
    "daily": "Ежедневно",
    "few_times_week": "Несколько раз в неделю",
    "sometimes": "Иногда",
    "rarely": "Почти не читаю сейчас",
    "home": "Дома, самостоятельно",
    "mosque": "В мечети",
    "online_group": "В онлайн-группе / с наставником",
    "not_regular": "Пока не читаю регулярно",
    "self_paced": "Самостоятельно, в удобное время",
    "with_mentor": "С наставником и обратной связью",
    "in_group": "В группе / с другими участниками",
    "short_videos": "Через короткие видео и тренировки",
    "spiritual": "Духовное ощущение близости к Аллаху",
    "beauty": "Красота и правильность чтения",
    "discipline": "Дисциплина и регулярность",
    "meaning": "Осознание смысла аятов",
    "after_prayer": "После молитвы",
    "morning": "Утром",
    "evening": "Вечером перед сном",
    "friday_ramadan": "В пятницу / Рамадан",
    "when_mood": "Когда есть настроение",
    "spiritual_connection": "Хочу укрепить духовную связь с Аллахом",
    "family_example": "Хочу быть примером для семьи / детей",
    "confident_reading": "Хочу читать уверенно и красиво",
    "refresh_knowledge": "Хочу вспомнить и закрепить знания",
    "5_10_min": "5–10 минут в день",
    "15_20_min": "15–20 минут в день",
    "one_long": "Один длинный урок в неделю",
    "auto_remind": "Хочу, чтобы система сама напоминала",
    "2_3_week": "Да, 2–3 раза в неделю",
    "new_tasks": "Только при новых заданиях",
    "no_self": "Нет, хочу сам контролировать",
    "progress": "Прогресс и результаты",
    "quran_hadith": "Слова из Корана и хадисы",
    "others_examples": "Примеры других учеников",
    "voice_beauty": "Голос и красота чтения",
}


def get_answer_label(answer_code: str) -> str:
    if not answer_code:
        return ""
    return ANSWER_LABELS.get(answer_code, answer_code)


def convert_answers_to_labels(answers: dict) -> dict:
    if not answers:
        return {}
    return {key: get_answer_label(value) for key, value in answers.items()}

