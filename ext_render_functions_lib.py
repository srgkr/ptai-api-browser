import streamlit as st
import pandas as pd
import tempfile
import os
import requests
import json
import urllib.parse
import time
import ext_config
from ext_stream_functions_lib import add_debug_log, refresh_access_token, api_request
from ext_helper_functions_lib import safe_str

# Вспомогательная функция для парсинга и отображения содержимого ячейки от типа
def render_cell_content(val):
    # парсим строку как JSON, если она похожа на JSON-строку
    if isinstance(val, str):
        val_striped = val.strip()
        if (val_striped.startswith("{") and val_striped.endswith("}")) or (
            val_striped.startswith("[") and val_striped.endswith("]")
        ):
            try:
                val = json.loads(val_striped)
            except Exception:
                pass

    # Отображаем от типа данных
    if isinstance(val, dict):
        data = [(safe_str(k), safe_str(v)) for k, v in val.items()] #иначе ошибка pyarrow.lib.ArrowTypeError: ("Expected bytes, got a 'int' object", 'Conversion failed for column Value with type object')
        df_dict = pd.DataFrame(data, columns=["Key", "Value"])
        st.table(df_dict)

    elif isinstance(val, list):
        # Если это список словарей (вложенная таблица)
        if len(val) > 0 and isinstance(val[0], dict):
            ##st.table(pd.DataFrame(val))
            df = pd.DataFrame(val).astype(str)
            st.table(df)
        else:
            # Обычный плоский список
            ##st.table(pd.DataFrame(val, columns=["spisok"]))
            df = pd.DataFrame([safe_str(v) for v in val], columns=["spisok"])
            st.table(df)

    elif val is None or val == "":
        st.write("—")

    else:
        # Для базовых типов (текст, числа, bool)
        st.write(safe_str(val))


def render_download_action_from_tmpfile(col, action_id, button_label, file_prefix, api_endpoint,
                          project_id, scan_id=None, settings_id=None, branch_id=None,
                          accept_header="application/zip", is_json=False):
    """
    Универсальная функция для отрисовки блока скачивания файлов/данных

    Args:
        col: Колонка Streamlit, в которой будет отрисовываться блок
        action_id: Идентификатор действия (для ключей элементов)
        button_label: Текст на кнопке скачивания
        file_prefix: Префикс для имени файла
        api_endpoint: Шаблон URL API (может содержать {project_id}, {scan_id}, {settings_id})
        project_id: ID проекта
        scan_id: ID сканирования (опционально)
        settings_id: ID настроек сканирования (опционально)
        accept_header: Заголовок Accept для API запроса
        is_json: Флаг, что ответ в JSON
    """
    with col:
        # исправление: ошибки зависания chromium при вложении кнопок в st.button - вынесение логики st.download_button на уровень st.button.
        # ключи для session_state
        uniq_id = f"{action_id}_{scan_id or settings_id or project_id}"
        json_session_key = f"json_data_{uniq_id}"
        zip_session_key = f"zip_path_{uniq_id}"
        # URL API запроса
        endpoint = api_endpoint.format(
            project_id=project_id,
            scan_id=scan_id if scan_id else '',
            settings_id=settings_id if settings_id else '',
            branch_id=branch_id if branch_id else ''
        )
        # запрашиваем в session_state
        if st.button(f"Запрос:\n\r {button_label}", key=f"btn_{uniq_id}", icon=":material/search:", help=endpoint):
            with st.spinner(f"Загрузка {action_id} с сервера..."):
                res = api_request(
                    "GET",
                    endpoint,
                    headers={"Accept": accept_header},
                    stream=not is_json
                )

                if res and res.status_code == 200:
                    if is_json:
                        # Сохраняем JSON в session_state
                        st.session_state[json_session_key] = res.json()
                    else:
                        # Сохраняем ZIP во временный файл
                        if zip_session_key in st.session_state and os.path.exists(st.session_state[zip_session_key]):
                            try:
                                os.remove(st.session_state[zip_session_key])
                            except Exception:
                                pass

                        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                            for chunk in res.iter_content(chunk_size=65536):
                                if chunk:
                                    tmp.write(chunk)
                            st.session_state[zip_session_key] = tmp.name

                        #st.toast(f"{action_id} успешно подготовлен к скачиванию!", icon="📦")
                else:
                    status_code = res.status_code if res else "No Response"
                    st.error(f"Сервер вернул код {status_code}")


        # отрисовка st.download_button на уровне st.button

        # Вариант: Если загружен JSON
        if is_json and json_session_key in st.session_state:
            json_data = st.session_state[json_session_key]

            st.json(json_data)
            # Формируем строку для скачивания
            text_to_download = json.dumps(json_data, indent=2, ensure_ascii=False)
            st.download_button(
                label=f"Скачать {action_id} как JSON",
                data=text_to_download,
                file_name=f"{file_prefix}_proj_{project_id}{f'_scan_{scan_id}' if scan_id else ''}.json",
                mime="application/json",
                width='stretch',
                icon=":material/download:",
                key=f"dl_json_{uniq_id}"
            )

        # Вариант: Если загружен ZIP / Бинарный файл
        elif not is_json and zip_session_key in st.session_state:
            file_path = st.session_state[zip_session_key]
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    st.download_button(
                        label=button_label,
                        data=f,
                        file_name=f"{file_prefix}_proj_{project_id}{f'_scan_{scan_id}' if scan_id else ''}.zip",
                        mime="application/zip",
                        width='stretch',
                        icon=":material/download:",
                        key=f"dl_zip_{uniq_id}"
                    )


def render_download_action_from_session_state(col, action_id, button_label, file_prefix, api_endpoint,
                          project_id, scan_id=None, settings_id=None, branch_id=None,
                          accept_header="application/zip", is_json=False):
    """
    Универсальная функция для отрисовки блока скачивания файлов/данных

    Args:
        col: Колонка Streamlit, в которой будет отрисовываться блок
        action_id: Идентификатор действия (для ключей элементов)
        button_label: Текст на кнопке скачивания
        file_prefix: Префикс для имени файла
        api_endpoint: Шаблон URL API (может содержать {project_id}, {scan_id}, {settings_id})
        project_id: ID проекта
        scan_id: ID сканирования (опционально)
        settings_id: ID настроек сканирования (опционально)
        accept_header: Заголовок Accept для API запроса
        is_json: Флаг, что ответ в JSON (не нужно сохранять в session_state)
    """
    with col:
        # Формируем URL API запроса
        endpoint = api_endpoint.format(
            project_id=project_id,
            scan_id=scan_id if scan_id else '',
            settings_id=settings_id if settings_id else '',
            branch_id=branch_id if branch_id else ''
        )

        # Кнопка запроса данных
        if st.button(f"Запрос:\n\r {button_label}",
                    key=f"btn_{action_id}_{scan_id or settings_id or project_id}", icon=":material/search:", help=endpoint):
            with st.spinner(f"Загрузка {action_id} с сервера..."):
                res = api_request("GET", endpoint, headers={"Accept": accept_header})

                if res:
                    if res.status_code == 200:
                        if is_json:
                            # Для JSON просто показываем содержимое
                            st.json(res.json())
                            # Предлагаем скачать как текстовый файл
                            text_to_download = json.dumps(res.json(), indent=2)
                            st.download_button(
                                label=f"Скачать {action_id} как JSON",
                                data=text_to_download,
                                file_name=f"{file_prefix}_proj_{project_id}{f'_scan_{scan_id}' if scan_id else ''}.json",
                                mime="application/json",
                                width='stretch', icon=":material/download:"
                            )
                        else:
                            # Для бинарных данных сохраняем в session_state
                            session_key = f"zip_{action_id}_{scan_id or settings_id or project_id}"
                            st.session_state[session_key] = res.content
                            #st.toast(f"{action_id} загружены в буфер!", icon="📥")
                    else:
                        st.error(f"Сервер вернул код {res.status_code}")
                        text_to_download = f"HTTP {res.status_code}\n\n{res.text}"
                        st.download_button(
                            label=f"Скачать ответ сервера в виде текста",
                            data=text_to_download,
                            file_name=f"error_{res.status_code}_{action_id}_{project_id}{f'_scan_{scan_id}' if scan_id else ''}.txt",
                            mime="text/plain", icon=":material/download:"
                        )
                else:
                    st.error(f"Сервер не ответил на запрос {action_id} {res.status_code}")

        # Кнопка скачивания, если данные загружены
        session_key = f"zip_{action_id}_{scan_id or settings_id or project_id}"
        if session_key in st.session_state:
            st.download_button(
                label=button_label,
                data=st.session_state[session_key],
                file_name=f"{file_prefix}_proj_{project_id}{f'_scan_{scan_id}' if scan_id else ''}{f'_settings_{settings_id}' if settings_id else ''}.zip",
                mime="application/zip",
                width='stretch',
                key=f"dl_{action_id}_{scan_id or settings_id or project_id}", icon=":material/download:"
            )

# проксирование через nginx , он скачивает через endpoint proxy-download
def get_proxy_download_url(api_endpoint, project_id, branch_id=None, file_name="Source.zip"):
    current_token = st.session_state.get("access_token", "")
    endpoint = api_endpoint.format(project_id=project_id, branch_id=branch_id if branch_id else '')

    API_URL = st.session_state.api_url
    target_url = f"{API_URL}/{endpoint.lstrip('/')}"

    proxy_secret = getattr(ext_config, "PROXY_SECRET_KEY", os.getenv("PROXY_SECRET_KEY", ""))

    # Кодируем переменные для передачи в параметрах
    encoded_token = urllib.parse.quote(current_token, safe="")
    encoded_filename = urllib.parse.quote(file_name, safe="")
    #encoded_target = urllib.parse.quote(target_url, safe="")
    timestamp = int(time.time())
    # Формируем URL для Nginx-прокси
    return f"/proxy-download/?target={target_url}&secret={proxy_secret}&token={encoded_token}&filename={encoded_filename}&_t={timestamp}"

def source_download_action_proxy(col, action_id, button_label, file_prefix, api_endpoint,
                          project_id, scan_id=None, settings_id=None, branch_id=None,
                          accept_header="application/zip", is_json=False):
    with col:
        endpoint = api_endpoint.format(
            project_id=project_id,
            scan_id=scan_id if scan_id else '',
            settings_id=settings_id if settings_id else '',
            branch_id=branch_id if branch_id else ''
        )

        file_version_hash = scan_id if scan_id else int(time.time())
        safe_file_name = f"{file_prefix}_proj_{project_id}{f'_br_{branch_id}' if branch_id else ''}_v{file_version_hash}.zip"

        # скачивание через проксирование
        if st.button(f"Запрос скачивания через прокси:\n\r {button_label}", icon=":material/search:", key=f"btn_dl_{action_id}_{scan_id or settings_id or project_id}_proxy", help=endpoint):
                        proxy_url = get_proxy_download_url(
                            api_endpoint=endpoint,
                            project_id=project_id,
                            branch_id=branch_id,
                            file_name=safe_file_name
                        )
                        download_label=f"📥 Скачать:\n\r {button_label}"
                        st.markdown(
                            f'''
                            <a href="{proxy_url}" download="{safe_file_name}" target="_blank">
                                <button style="width: 100%; padding: 0.5rem; background: #4CAF50; color: white; border: none; border-radius: 4px;">{download_label}</button>
                            </a>
                            ''',
                            unsafe_allow_html=True
                        )

# скачивает сам streamlit в tmp и раздает nginx из общего tmp - обязательно каталог tmp должен быть подмонтирован и в nginx
def source_download_action_tmp(col, action_id, button_label, file_prefix, api_endpoint,
                          project_id, scan_id=None, settings_id=None, branch_id=None,
                          accept_header="application/zip", is_json=False):
    with col:
        endpoint = api_endpoint.format(
            project_id=project_id,
            scan_id=scan_id if scan_id else '',
            settings_id=settings_id if settings_id else '',
            branch_id=branch_id if branch_id else ''
        )

        file_version_hash = scan_id if scan_id else int(time.time())
        safe_file_name = f"{file_prefix}_proj_{project_id}{f'_br_{branch_id}' if branch_id else ''}_v{file_version_hash}.zip"

        # todo: доп проверка по config.USE_TEMP_DIR
        target_dir = config.TEMP_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        local_file_path = target_dir / safe_file_name

        # Кнопка запуска скачивания с PTAI-сервера во временную папку
        if st.button(f"Запрос скачивания:\n\r {button_label}", key=f"btn_dl_{project_id}_{branch_id}", help=endpoint):
            current_token = st.session_state.get("access_token")
            if not current_token:
                st.error("Нет токена доступа")
                return
            API_URL = st.session_state.api_url
            url = f"{API_URL}/{endpoint.lstrip('/')}"
            headers = {"Authorization": f"Bearer {current_token}", "Accept": accept_header}

            with st.spinner(f"Загрузка архива с сервера в хранилище..."):
                try:
                    # Скачиваем стримом с сервера PTAI на диск
                    response = requests.get(url, headers=headers, stream=True, verify=False)
                    response.raise_for_status()

                    with open(local_file_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)

                    st.success("Файл успешно подготовлен!")
                except Exception as e:
                    st.error(f"Ошибка скачивания: {e}")
                    return


        if local_file_path.exists():
            # Формируем прямую ссылку через Nginx (минуя Streamlit)
            file_url = f"/downloads/{safe_file_name}"

            download_label=f"📥 Скачать файл напрямую ({local_file_path.stat().st_size // (1024*1024)} МБ):\n\r {button_label}"
            st.markdown(
                f'''
                <div style="margin-top: 10px;">
                    <a href="{file_url}" download="{safe_file_name}" target="_blank" style="text-decoration: none;">
                        <button style="
                            width: 100%;
                            background-color: #ff4b4b;
                            color: white;
                            padding: 0.5rem 1rem;
                            border: none;
                            border-radius: 4px;
                            font-weight: 600;
                            cursor: pointer;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            gap: 8px;
                        ">{download_label}</button>
                    </a>
                </div>
                ''',
                unsafe_allow_html=True
            )
