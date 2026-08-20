import requests
import datetime
import streamlit as st
import tempfile
import os

#вспомогательные функции для реализации возможностей скачивания больших объемов информации разными методами: проксирования, перенаправления, временные каталоги и так далее
#выбор от вычислительных ресурсов доступных контейнеру при установке
#ver.0.5 проксирование через nginx - загрузка исходного кода, логов . остальное через память.

def stream_zip_from_api(endpoint, token=None, **kwargs):
    """
    Возвращает генератор байтов для стриминга ZIP-файла из API.
    Поддерживает автообновление токена при 401.
    """
    current_token = token if token else st.session_state.get("access_token")
    if not current_token:
        raise RuntimeError("Нет токена доступа")

    API_URL = st.session_state.api_url
    url = f"{API_URL}/{endpoint.lstrip('/')}"

    # Подготавливаем заголовки
    headers = kwargs.get("headers", {})
    headers["Authorization"] = f"Bearer {current_token}"
    kwargs["headers"] = headers

    # Первый запрос со стримингом
    response = requests.request("GET", url, stream=True, verify=False, **kwargs)

    # Обработка 401 и повтор запроса
    if response.status_code == 401 and not token:
        if refresh_access_token():
            # Обновляем токен в session_state
            new_token = st.session_state.access_token
            headers["Authorization"] = f"Bearer {new_token}"
            # Делаем повторный запрос со стримингом
            response = requests.request("GET", url, stream=True, verify=False, headers=headers)
        else:
            st.session_state.access_token = None
            st.rerun()

    response.raise_for_status()  # выбросит ошибку, если не 2xx

    # Возвращаем генератор чанков
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            yield chunk

def stream_zip_tmp(endpoint, token=None, **kwargs):
    """
    Скачивает ZIP чанками во временный файл, затем возвращает байты через память.
    Пример:
        if st.button("Скачать"):
         st.download_button(
            label=button_label,
            data=stream_zip_tmp(endpoint),
            file_name=file_name,
            mime="application/zip",
         )
    """
    current_token = token if token else st.session_state.get("access_token")
    if not current_token:
        raise RuntimeError("Нет токена доступа")
    API_URL = st.session_state.api_url
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    headers = kwargs.get("headers", {})
    headers["Authorization"] = f"Bearer {current_token}"
    kwargs["headers"] = headers

    # Скачиваем чанками во временный файл
    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            response = requests.get(url, stream=True, verify=False, **kwargs)

            if response.status_code == 401 and not token:
                if refresh_access_token():
                    new_token = st.session_state.access_token
                    headers["Authorization"] = f"Bearer {new_token}"
                    response = requests.get(url, stream=True, verify=False, headers=headers)
                else:
                    st.session_state["access_token"] = None
                    st.rerun()

            response.raise_for_status()

            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    tmp_file.write(chunk)

        # Читаем байты из файла и возвращаем их через память
        with open(temp_path, "rb") as f:
            return f.read()
    finally:
        # Удаляем временный файл сразу после чтения
        if os.path.exists(temp_path):
            os.remove(temp_path)


#todo: убрать повторы и перенести в global st.session_state.debug_logs
def add_debug_log(message):
        """Логирование с отметкой времени"""
        # datetime.now(tz=ZoneInfo('localtime'))
        #todo: разобраться с датой в контейнере, требуется возвратить МСК пояс
        current_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        st.session_state.debug_logs.append(f"[{current_time}] {message}")
        if len(st.session_state.debug_logs) > 10:
            st.session_state.debug_logs.pop(0)

def refresh_access_token():
    if not st.session_state.refresh_token:
        return False
    try:
        payload = {"refreshToken": st.session_state.refresh_token}
        API_URL=st.session_state.get("api_url")
        response = requests.post(f"{API_URL}/api/auth/refreshToken", json=payload, verify=False)
        if response.status_code == 200:
            data = response.json()
            st.session_state.access_token = data["accessToken"]
            st.session_state.refresh_token = data["refreshToken"]
            st.session_state.expiredAt = data["expiredAt"]
            return True
        return False
    except Exception:
        return False

def api_request(method, endpoint, token=None, **kwargs):
    """API запрос с поддержкой передачи токена для многопоточности (вызов в головном потоке) и автообновлением токена"""

    # Если токен передан аргументом (для потоков) — берем его.
    # Если нет — берем из st.session_state (для главного потока)
    current_token = token if token else st.session_state.get("access_token")

    if not current_token:
        return None
    API_URL=st.session_state.get("api_url")
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    add_debug_log(f"API запрос {url}")

    if "headers" not in kwargs:
        kwargs["headers"] = {}
    kwargs["headers"]["Authorization"] = f"Bearer {current_token}"

    response = requests.request(method, url, verify=False, **kwargs)

    # автообновление токена при 401 ошибке
    if response.status_code == 401 and not token:
        if refresh_access_token():
            kwargs["headers"]["Authorization"] = f"Bearer {st.session_state.access_token}"
            response = requests.request(method, url, verify=False, **kwargs)
        else:
            st.session_state.access_token = None
            #нежелательно при многопоточности
            st.rerun()

    return response

def api_request_plain(method, endpoint, token=None, local_api_url=None, **kwargs):
    """API запрос с поддержкой передачи токена для многопоточности (вызов в изолированных потоках)"""
    if not token or not local_api_url:
        return None

    url = f"{local_api_url}/{endpoint.lstrip('/')}"

    if "headers" not in kwargs:
        kwargs["headers"] = {}
    kwargs["headers"]["Authorization"] = f"Bearer {token}"

    response = requests.request(method, url, verify=False, **kwargs)
    return response
