import json
import datetime
import re
#группа вспомогательных функций

def format_iso_duration(duration_str):
    """
    Парсит полную длительность ГОСТ Р 7.0.64-2018 (ISO-8601)
    Поддерживает года (Y), месяцы (M), дни (D), часы (H), минуты (M), секунды (S) и отрицательные значения.
    """
    if not duration_str or not isinstance(duration_str, str):
        return "—"

    # Универсальный паттерн ISO-8601 / ГОСТ Р 7.0.64-2018
    pattern = r"(-)?P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?"
    match = re.match(pattern, duration_str)
    if not match:
        return duration_str

    sign, years, months, days, hours, minutes, seconds = match.groups()

    parts = []
    if years:
        parts.append(f"{years}г")
    if months:
        parts.append(f"{months}мес")
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if seconds:
        parts.append(f"{float(seconds)}с")

    formatted = " ".join(parts) if parts else "0с"

    return f"-{formatted}" if sign else formatted


def safe_parse_json(val):
    """Безопасный парсинг JSON"""
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            pass
    return {}

def format_local_datetime(utc_datetime_str):
    """Конвертация строки ГОСТ Р 7.0.64-2018 (ISO-8601) в локальное время"""
    if not utc_datetime_str:
        return "—"
    try:
        dt = datetime.datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_datetime_str

def get_bool_icon(val):
    """Преобразуем булевые значения в иконки"""
    if val is True:
        return "✅ Да"
    if val is False:
        return "❌ Нет"
    return "❔ Нет данных"

def safe_str(v):
    return str(v) if v is not None else ""
