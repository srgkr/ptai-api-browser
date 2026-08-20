import os
import tempfile
from pathlib import Path
import sys
import streamlit as st
from dotenv import load_dotenv

# обрабатываем .env и переменные окружения
load_dotenv()
raw_env = os.environ.get("DEFAULT_API_URLS")
if not raw_env or not raw_env.strip():
    error_msg = "CRITICAL ERROR: Переменная окружения DEFAULT_API_URLS не задана!"
    print(error_msg, file=sys.stderr)
    st.error(error_msg)
    st.stop()
    sys.exit(1)

DEFAULT_API_URLS = [url.strip() for url in raw_env.split(",") if url.strip()]

if not DEFAULT_API_URLS:
    error_msg = "CRITICAL ERROR: Переменная окружения DEFAULT_API_URLS не содержит валидных URL!"
    print(error_msg, file=sys.stderr)
    st.error(error_msg)
    st.stop()
    sys.exit(1)

# для контейнеров: mount временный каталог ./tmp_data -> /app/tmp_data
# глобальная инициализация временного каталога
tmp_dir_env = os.getenv("TMP_DATA_DIR")

USE_TEMP_DIR = False
TEMP_DIR = None

if tmp_dir_env:
  TEMP_DIR = Path(tmp_dir_env)
  try:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    if TEMP_DIR.is_dir():
      USE_TEMP_DIR = True
      tempfile.tempdir = str(TEMP_DIR)
  except Exception as e:
    print(f"Ошибка проверки каталога {TEMP_DIR}: {e} \r\nИгнорируем TMP_DATA_DIR")
