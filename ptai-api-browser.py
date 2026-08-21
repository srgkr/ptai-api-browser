import time
import json
import streamlit as st
import requests
import urllib3
import pandas as pd
import datetime
import re
from io import StringIO
import extra_streamlit_components as exc
from concurrent.futures import ThreadPoolExecutor, as_completed

import tempfile
import os
import sys
from dotenv import load_dotenv
from pathlib import Path

import urllib.parse

# внутренние
from ext_helper_functions_lib import *
from ext_stream_functions_lib import *
from ext_render_functions_lib import *
import ext_config
from ext_stream_functions_lib import add_debug_log, refresh_access_token, api_request

def get_version() -> str:
    version_file = Path(__file__).parent / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"

__version__ = get_version()

# ставим принудительно не проверять TLS/SSL сертификаты
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)



## cookie=False - использовать localStorage (передача токена через URL) или cookie=True - extra_streamlit_components.cookie_manager (глючный)
# todo: cookie=True - пока не всё дописано и задержки. устанавливается инит формой - st.checkbox
cookie=False



# if "access_token" not in st.session_state:
#     st.session_state.access_token = None
# if "refresh_token" not in st.session_state:
#     st.session_state.refresh_token = None


# группа функций для работы с localstorage
def clear_auth_from_localstorage():
    js_code = """
    <script>
      localStorage.removeItem('ptai_master_token');
      localStorage.removeItem('ptai_api_url');
    </script>
    """
    st.html(js_code, unsafe_allow_javascript=True)

def save_config_to_localstorage(token: str, api_url: str):
    js_code = f"""
    <script>
      localStorage.setItem('ptai_master_token', '{token}');
      localStorage.setItem('ptai_api_url', '{api_url}');
    </script>
    """
    st.html(js_code, unsafe_allow_javascript=True)

def load_config_from_localstorage():
    """
    Загрузка токена и api_url из localStorage через URL query_params
    """
    token_in_url = st.query_params.get("token")
    url_in_url = st.query_params.get("api_url")

    # Если параметры пришли через редирект JS
    if token_in_url or url_in_url:
        if token_in_url:
            st.session_state.master_token = token_in_url
            del st.query_params["token"]
        if url_in_url:
            st.session_state.api_url = url_in_url
            del st.query_params["api_url"]
        return token_in_url, url_in_url

    # Если в сессии еще нет данных — запрашиваем их из localStorage браузера
    if not st.session_state.get("master_token") or not st.session_state.get("api_url"):
        js_code = """
        <script>
            const token = localStorage.getItem('ptai_master_token') || '';
            const apiUrl = localStorage.getItem('ptai_api_url') || '';
            if (token || apiUrl) {
                const url = new URL(window.parent.location.href);
                if (token) url.searchParams.set('token', token);
                if (apiUrl) url.searchParams.set('api_url', apiUrl);
                window.parent.location.href = url.href;
            }
        </script>
        """
        st.html(js_code, unsafe_allow_javascript=True)
        token_in_url = st.query_params.get("token")
        url_in_url = st.query_params.get("api_url")

        #todo: фикс,повторяем повторно. Если параметры пришли через редирект JS
        if token_in_url or url_in_url:
            if token_in_url:
                st.session_state.master_token = token_in_url
                del st.query_params["token"]
            if url_in_url:
                st.session_state.api_url = url_in_url
                del st.query_params["api_url"]
            return token_in_url, url_in_url

    return st.session_state.get("master_token"), st.session_state.get("api_url")

# группа функций для работы с токенами PTAI
def initial_login(master_token, target_api_url):
    if not target_api_url:
        st.error("Укажите API URL серверов PT AI!")
        return False
    try:
        headers = {"Access-Token": master_token}
        response = requests.get(
            f"{target_api_url.rstrip('/')}/api/auth/signin?scopeType=AccessToken",
            headers=headers,
            verify=False
        )
        if response.status_code == 200:
            data = response.json()
            st.session_state.master_token = master_token
            st.session_state.access_token = data["accessToken"]
            st.session_state.refresh_token = data["refreshToken"]
            st.session_state.expiredAt = data["expiredAt"]
            st.session_state.api_url = target_api_url
            return True
        st.error(f"Ошибка входа [{response.status_code}]: {response.text}")
        return False
    except Exception as e:
        st.error(f"Ошибка сети при обращении к {target_api_url}: {e}")
        return False



def clear_all_caches_and_session():
    """Полная очистка кэшей Streamlit и текущего состояния авторизации"""
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.clear()
    st.session_state.access_token = None
    st.session_state.master_token = None
    st.session_state.expiredAt = None
    st.session_state.api_url = None
    if 'selected_scan' in st.session_state:
        del st.session_state.selected_scan
    #todo: добавить очистку TMP
    #add_debug_log(f"Полная очистка кэшей Streamlit и текущего состояния авторизации")


def render_scan_metrics(stats, deltas):
    """Отрисовка метрик уязвимостей"""
    st.markdown("---")
    st.markdown("#### 📊 Статистика уязвимостей")

    m1, m2, m3, m4, m5, m6 = st.columns([2,2,2,2,2,3], border=True)

    def render_metric(col, label, value, delta):
        formatted_delta = None
        if delta is not None:
            if isinstance(delta, (int, float)):
                if delta > 0:
                    formatted_delta = f"+{delta}"
                elif delta < 0:
                    formatted_delta = str(delta)
            elif isinstance(delta, str) and delta.strip() and delta not in ["—", "0с"]:
                formatted_delta = delta

        with col:
            st.metric(
                label=label,
                value=value,
                delta=formatted_delta,
                delta_color="inverse",
                height="content",
                width="stretch",
                border=False
            )

    # Длительность сканирования
    duration = stats.get('scanDuration', '')
    delta_duration = deltas.get('scanDuration', '')

    render_metric(m1, "Высокие (High)", stats.get("high", 0), deltas.get('high', 0))
    render_metric(m2, "Средние (Medium)", stats.get("medium", 0), deltas.get('medium', 0))
    render_metric(m3, "Низкие (Low)", stats.get("low", 0), deltas.get('low', 0))
    render_metric(m4, "Потенциальные", stats.get("potential", 0), deltas.get('potential', 0))
    render_metric(m5, "Всего (Total)", stats.get("total", 0), deltas.get('total', 0))
    render_metric(m6, "Длительность", format_iso_duration(duration), format_iso_duration(delta_duration))
    # Дополнительная метрика для отчетов
    render_metric(m5, "Всего (без потенциальных)", stats.get("total", 0)-stats.get("potential", 0), deltas.get('total', 0)-deltas.get('potential', 0))

    # Дополнительная статистика
    st.markdown(
        f"**Сканирование файлов:** `{stats.get('filesScanned', 0)} / {stats.get('filesTotal', 0)}` | "
        f"**Сканирование URL:** `{stats.get('urlsScanned', 0)} / {stats.get('urlsTotal', 0)}`"
    )

def render_scan_info(scan, env, initiator, agent):
    """Отрисовка информации о сканировании"""
    st.markdown("---")
    st.markdown("#### Дополнительная информация о сканировании")

    col_info_left, col_info_right, col3 = st.columns(3)

    with col_info_left:
        st.markdown(f"Дата запуска: `{format_local_datetime(scan.get('scanDate'))}`")
        st.markdown(f"В очереди с: `{format_local_datetime(scan.get('queueDate'))}`")
        st.markdown(f"Тип сканирования: `{scan.get('scanType', '—')}`")
    with col_info_right:
        st.markdown(f"Branch ID: `{scan.get('branchId', 'Unknown')}`")
        st.markdown(f"Настройки (Settings ID): `{scan.get('settingsId', '—')}`")
        if scan.get('previousScanResultId'):
            st.markdown(f"Прошлый скан: `{scan.get('previousScanResultId')}`")
        if scan.get('fullScanReason'):
            st.markdown(f"Причина полного скана: `{scan.get('fullScanReason')}`")
    with col3:
        agent_name = agent.get('name', '—')
        agent_os = agent.get('operatingSystem', '—')
        agent_ver = agent.get('version', '—')
        st.markdown(f"Сборочный агент: `{agent_name}` (`{agent_os}`, v`{agent_ver}`)")

        inst_info = env.get('installatorVersion', {})
        inst_type = inst_info.get('type', '—')
        inst_ver = inst_info.get('version', '—')
        st.markdown(f"Инструмент анализа: `{inst_type}` v`{inst_ver}`")
        init_type = initiator.get('type', '—')
        init_name = initiator.get('name', '—')
        st.markdown(f"Инициатор: `{init_name}` (тип: `{init_type}`)")


    st.markdown("---")
    b1, b2, b3, b4, b5 = st.columns(5, border=True)
    with b1:
        st.write(f"**Есть ошибки:**\n\n{get_bool_icon(scan.get('hasErrors'))}")
    with b2:
        st.write(f"**Есть SBOM:**\n\n{get_bool_icon(scan.get('hasSbom'))}")
    with b3:
        st.write(f"**Граф зависимостей:**\n\n{get_bool_icon(scan.get('hasDependencyGraph'))}")
    with b4:
        st.write(f"**Запуск из очереди:**\n\n{get_bool_icon(scan.get('isRunFromQueue'))}")
    with b5:
        st.write(f"**Родительский узел:**\n\n{get_bool_icon(scan.get('isParentNode'))}")


def render_download_action(*args, **kwargs):
    """
    Функция обертка для отображения кнопки скачивания.
    Автоматически выбирает метод скачивания:
    - Если установлена переменная окружения TMP_DATA_DIR или существует каталог используется скачивание через временный файл (render_download_action_from_tmpfile).
    - Иначе используется скачивание через session state (render_download_action_from_session_state).
    """
    # Извлекаем force_tmp (если он передан)
    force_tmp = kwargs.pop("force_tmp", False)

    # Проверяем условие
    if force_tmp or ext_config.USE_TEMP_DIR:
        return render_download_action_from_tmpfile(*args, **kwargs)
    else:
        return render_download_action_from_session_state(*args, **kwargs)


def render_actions(scan, project_id, scan_id, settings_id, branch_id, stage):
    """Отрисовка блока действий"""
    st.markdown("---")
    st.markdown("#### Доступные действия - сканирование")

    col_actions_1, col_actions_2, col_actions_3, col_actions_4, col_actions_5 = st.columns(5)

#    render_download_action(col=col_actions_2, action_id="aiproj_by_project",button_label="Скачать aiproj уровня проекта",file_prefix="aiproj_by_project",api_endpoint=f"/api/projects/{project_id}/aiproj", project_id=project_id, is_json=True)
#    render_download_action(col=col_actions_3, action_id="security_policies",button_label="Показать политики безопасности проекта",file_prefix="security_policies",api_endpoint=f"/api/projects/{project_id}/securityPolicies", project_id=project_id,accept_header="application/json",is_json=True)

    render_download_action(col=col_actions_1, action_id="scan_settings_aiproj",button_label="Показать настройки текущего сканирования (aiproj)",file_prefix="aiproj_by_settings",api_endpoint=f"/api/projects/{project_id}/scanSettings/{settings_id}/aiproj", project_id=project_id,settings_id=settings_id, is_json=True)
    render_download_action(col=col_actions_2,action_id="scan_settings_json",button_label="Показать настройки текущего сканирования (уровень ветки/проекта)",file_prefix="scan_settings",api_endpoint=f"/api/projects/{project_id}/scanSettings/{settings_id}", project_id=project_id,settings_id=settings_id,accept_header="application/json",is_json=True)
    source_download_action_proxy(col=col_actions_3,action_id="logs",button_label="Скачать логи результатов сканирования",file_prefix="logs",api_endpoint=f"/api/store/{project_id}/logs/{scan_id}", project_id=project_id,scan_id=scan_id)
    render_download_action(col=col_actions_4,action_id="graph",button_label="Скачать graph результатов сканирования",file_prefix="graph",api_endpoint=f"/api/store/{project_id}/graphs/{scan_id}", project_id=project_id,scan_id=scan_id) #todo: добавить расширения html, zip, json и т.п.
    render_download_action(col=col_actions_5,action_id="sbom",button_label="Скачать SBOM результатов сканирования",file_prefix="sbom",api_endpoint=f"/api/store/{project_id}/sboms/{scan_id}", project_id=project_id,scan_id=scan_id)
    show_api_master_detail(list_url=f"/api/projects/{project_id}", name_key="name", id_key="id", detail_endpoints={
     f"Генерировать отчет сканирования (общий) {scan_id}": {
            "url": "/api/reports/generate",
            "method": "POST",
            "is_file": True,
            "filename": f"report_{project_id}_{scan_id}.html",
            "payload": {
                "parameters": {
                    "useFilters": True,
                    "includeDFD": True,
                    "includeGlossary": True,
                    "includeComments": True,
                    "reportTemplateId": "a634ee11-3d87-40f1-9019-31abf8a4fb71"
                },
                "scanResultId": scan_id,
                "projectId": project_id,
                "localeId": "ru"
            }
     }
    }, key_prefix="scans_action32", single_item=True, show_json=False)

def render_actions_project(project_id, scan_settings_id, branch_id, project_settings_id):
    """Отрисовка блока действий"""
    st.markdown("---")
    st.markdown("#### Доступные действия - проекты")

    col_actions_1, col_actions_2, col_actions_3, col_actions_4  = st.columns(4)
    source_download_action_proxy(col=col_actions_1,action_id="source_project_branches_proxy",button_label="исходный код ветки",file_prefix="source",api_endpoint=f"/api/store/{project_id}/branches/{branch_id}/sources", project_id=project_id, branch_id=branch_id)
    source_download_action_proxy(col=col_actions_1,action_id="source_project_proxy",button_label="исходный код проекта (user main branch sources)",file_prefix="source",api_endpoint=f"/api/store/{project_id}/sources", project_id=project_id)
    source_download_action_proxy(col=col_actions_4,action_id="exportTriage_branch_proxy",button_label="exportTriage branch (Get a zip archive with scan results for export)",file_prefix="exportTriage",api_endpoint=f"/api/branches/{branch_id}/exportTriage", project_id=project_id, branch_id=branch_id)
    render_download_action(col=col_actions_1,action_id="source_project",button_label="Скачать исходный код ветки (in-memory)",file_prefix="source",api_endpoint=f"/api/store/{project_id}/branches/{branch_id}/sources", project_id=project_id, branch_id=branch_id)
    render_download_action(col=col_actions_1,action_id="source_project_branches",button_label="Скачать исходный код проекта (user main branch sources)(in-memory)",file_prefix="source",api_endpoint=f"/api/store/{project_id}/sources", project_id=project_id)
    render_download_action(col=col_actions_2,action_id="project_id_settings",button_label="Показать настройки проекта (settings)",file_prefix="project_id_settings",api_endpoint=f"/api/projects/{project_id}/settings", project_id=project_id,accept_header="application/json",is_json=True)
    render_download_action(col=col_actions_2, action_id="aiproj_by_project_project",button_label="Скачать настройки проекта (settings)(aiproj)",file_prefix="aiproj_by_project",api_endpoint=f"/api/projects/{project_id}/aiproj", project_id=project_id, is_json=True)
    render_download_action(col=col_actions_4, action_id="security_policies_project",button_label="Показать политики безопасности проекта",file_prefix="security_policies",api_endpoint=f"/api/projects/{project_id}/securityPolicies", project_id=project_id,accept_header="application/json",is_json=True)

    # scan_settings_id, project_settings_id из /api/projects/{projectId}  
    render_download_action(col=col_actions_2,action_id="scan_settings_project",button_label="Показать текущие настройки проекта (scanSettings)",file_prefix="scan_settings",api_endpoint=f"/api/projects/{project_id}/scanSettings/{scan_settings_id}", project_id=project_id,settings_id=scan_settings_id,accept_header="application/json",is_json=True)
    render_download_action(col=col_actions_2, action_id="aiproj_by_settings_project",button_label="Скачать текущие настройки проекта (scanSettings)(aiproj)",file_prefix="aiproj_by_settings",api_endpoint=f"/api/projects/{project_id}/scanSettings/{scan_settings_id}/aiproj", project_id=project_id,settings_id=scan_settings_id, is_json=True)

    # проверка можно ли также скачать project_settings_id
#    render_download_action(col=col_actions_3,action_id="project_settings_id_settings",button_label="Показать project_settings_id настройки сканирования проекта",file_prefix="project_settings_id_scan_settings",api_endpoint=f"/api/projects/{project_id}/scanSettings/{project_settings_id}", project_id=project_id,settings_id=project_settings_id,accept_header="application/json",is_json=True)
#    render_download_action(col=col_actions_3, action_id="project_settings_id_aiproj_by_settings",button_label="Скачать aiproj project_settings_id сканирования",file_prefix="project_settings_id_aiproj_by_settings",api_endpoint=f"/api/projects/{project_id}/scanSettings/{project_settings_id}/aiproj", project_id=project_id,settings_id=project_settings_id, is_json=True)

    render_download_action(col=col_actions_3,action_id="branch_id_settings",button_label="Показать текущие настройки ветки branch (sourcesSettings)",file_prefix="branch_id_settings",api_endpoint=f"/api/branches/{branch_id}/sourcesSettings", project_id=project_id,accept_header="application/json",is_json=True)
    render_download_action(col=col_actions_3,action_id="project_id",button_label="Показать информацию о проекте (JSON)",file_prefix="project_id",api_endpoint=f"/api/projects/{project_id}", project_id=project_id,accept_header="application/json",is_json=True)

    show_api_master_detail(list_url=f"/api/projects/{project_id}", name_key="name", id_key="id", detail_endpoints={
     f"Запустить сканирование (ветка branch {branch_id})": {
        "url": f"/api/scans/branches/{branch_id}/start",
        "method": "POST",
        "payload": {"scanType": "Full"}
     },
     f"Запустить сканирование (уровень проекта)": {
        "url": "/api/scans/{id}/start",
        "method": "POST",
        "payload": {"scanType": "Full"}
     },
    }, key_prefix="scans_action22", single_item=True, show_json=False)

def show_scan_results(branch_id):
    st.subheader("Список сканирований")

    if "selected_scan" not in st.session_state:
        st.session_state.selected_scan = None
    if "debug_logs" not in st.session_state:
        st.session_state.debug_logs = []

    # Сброс выбора при смене ветки
    if "current_branch_id" not in st.session_state:
        st.session_state.current_branch_id = branch_id
    elif st.session_state.current_branch_id != branch_id:
        st.session_state.current_branch_id = branch_id
        st.session_state.selected_scan = None
    if st.session_state.get('last_branch_id') != branch_id:
        st.session_state.last_branch_id = branch_id
        st.session_state.selected_scan = None

    add_debug_log(f"Запрос списка сканирований для branch_id: {branch_id}")
    res = api_request("GET", f"api/branches/{branch_id}/scanResults")

    if res and res.status_code == 200:
        df = pd.DataFrame(res.json())
        add_debug_log(f"Получено сканирований: {len(df)}")

        if not df.empty:
            # Таблица результатов
            selection = st.dataframe(
                df,
                width="stretch",
                column_config={
                    "scanDate": st.column_config.DatetimeColumn(format="localized"),
                    "queueDate": st.column_config.DatetimeColumn(format="localized")
                },
                on_select="rerun",
                key=f"scan_results_table_{branch_id}",
                selection_mode="single-row"
            )

            selected_rows = []
            #при выборе должен вернуть  {"selection": {"rows":, "columns":
            #fixed: здесь ошибка в том что не очищен кэш и применяется выделение к другому проекту. fix: scan_results_table_{branch_id}
            if selection:
                if hasattr(selection, "selection") and not callable(selection.selection):
                    if hasattr(selection.selection, "rows"):
                        selected_rows = selection.selection.rows
                elif isinstance(selection, dict) and "selection" in selection:
                    selected_rows = selection["selection"].get("rows", [])
            else:
                st.session_state.selected_scan = None

            if selected_rows:
                row_idx = selected_rows[0]
                selected_row = df.iloc[row_idx].to_dict()
                # добавлено
                add_debug_log(f"if selected_rows: {selected_row['id']}")
                st.session_state.selected_scan = selected_row
                #todo код ниже обдумать по логическим условиям - сейчас он не работает
                if (not st.session_state.selected_scan or
                    st.session_state.selected_scan.get('id') != selected_row['id']):
                    st.session_state.selected_scan = selected_row
                    add_debug_log(f"Выбрана строка. Scan ID: {selected_row['id']}")
            else:
                st.session_state.selected_scan = None

            #st.write(st.session_state.selected_scan)
            if st.session_state.selected_scan:
                scan = st.session_state.selected_scan
                scan_id = scan.get('id', 'Unknown')
                project_id = scan.get('projectId', 'Unknown')
                branch_id = scan.get('branchId', 'Unknown')
                settings_id = scan.get('settingsId', 'Unknown')

                stats = safe_parse_json(scan.get('statistic', {}))
                deltas = safe_parse_json(scan.get('statisticDelta', {}))
                progress = safe_parse_json(scan.get('progress', {}))
                env = safe_parse_json(scan.get('scanEnvironment', {}))
                initiator = safe_parse_json(scan.get('initiator', {}))
                agent = safe_parse_json(scan.get('scanAgentInfo', {}))

                stage = progress.get('stage', 'Unknown')

                st.write(f"Выбрано сканирование: `ScanID={scan_id} ProjectID={project_id}` (Статус: `{stage}`)")

                # Отображение статистики
                render_scan_metrics(stats, deltas)

                # Отображение информации
                render_scan_info(scan, env, initiator, agent)
                st.markdown("---")
                sscol1, sscol2, sscol3, sscol4 = st.columns([1,1,1,1])

                with sscol1:
                 if st.button(f"Показать информацию о уязвимостях", key=f"btn_issues_{scan_id or settings_id or project_id}",icon=":material/bolt:"):
                   with st.spinner(f"Показать информацию о уязвимостях"):
                       st.session_state['last_endpoint'] = f"/api/projects/{project_id}/scanResults/{scan_id}/issues"
                with sscol2:
                 if st.button(f"Показать информацию о errors", key=f"btn_errors_{scan_id or settings_id or project_id}",icon=":material/frame_bug:"):
                   with st.spinner(f"Показать информацию о errors"):
                       st.session_state['last_endpoint'] = f"/api/projects/{project_id}/scanResults/{scan_id}/errors"
                with sscol3:
                 if st.button("Скрыть результаты",icon=":material/close_fullscreen:"):
                    if 'last_endpoint' in st.session_state:
                        del st.session_state['last_endpoint']
                if 'last_endpoint' in st.session_state:
                    with st.spinner(f"Загрузка данных..."):
                        show_api_get_universal(st.session_state['last_endpoint'])

                # Отображение действий
                render_actions(scan, project_id, scan_id, settings_id, branch_id, stage)

        else:
            st.info("Сканирований не найдено.")
            st.session_state.selected_scan = None
    else:
        st.error("Не удалось загрузить результаты сканирования.")
        st.session_state.selected_scan = None


def show_branch_history(branch_id):
    """Отображение истории изменений ветки"""
    st.subheader("📜 История ветки (Branch History)")
    res = api_request("GET", f"api/history/branches/{branch_id}")
    if res and res.status_code == 200:
        df = pd.DataFrame(res.json())
        if not df.empty:

            st.dataframe(
                df, 
                width="stretch",
                column_config={
                    "changedDateTime": st.column_config.DatetimeColumn(format="localized")
                }
            )
        else:
            st.info("История пуста.")

def show_directory_content(project_id, branch_id):
    """Отображение файловой структуры (Sources)"""
    st.subheader("📁 Исходный код")

    if "current_path" not in st.session_state:
        st.session_state.current_path = ""

    path = st.session_state.current_path
    endpoint = f"api/directoryContent/{project_id}/branches/{branch_id}"
    if path:
        endpoint += f"/{path}"

    res = api_request("GET", endpoint)
    if res and res.status_code == 200:
        data = res.json()

        # Кнопка "Назад", если мы в поддиректории
        if path:
            if st.button("Назад",icon=":material/arrow_back:"):
                st.session_state.current_path = "/".join(path.split("/")[:-1])
                st.rerun()

        st.caption(f"Текущий путь: / {path}")

        # Показываем папки
        if data.get("_directories"):
            st.write("**Папки:**")
            for d in data["_directories"]:
                # d может быть строкой или объектом, проверяем структуру PT AI
                dir_name = d["name"] if isinstance(d, dict) else d
                if st.button(f"{dir_name}", key=f"dir_{dir_name}",icon="📂"):
                    st.session_state.current_path = f"{path}/{dir_name}".strip("/")
                    st.rerun()

        # Показываем файлы
        if data.get("_files"):
            st.write("**Файлы:**")
            st.table(data["_files"])

def enrich_single_project(project, token, local_api_url):
    """
    сбор данных по проекту в фоне.
    Возвращает структуру для обновления таблицы + сами ветки для кэша.
    """
    p_id = project['id']
    result = {
        "project_id": p_id,
        "LastChangeScanSettings": None,
        "LastScanDate": None,
        "branches_str": "",
        "branches_str2": "",
        "branches": []  # Возвращаем ветки обратно в главный поток для кэширования
    }

    # 1. Запрос даты изменения настроек
    #если вызов из головного потока: res_settings = api_request("GET", f"api/projects/{p_id}/settingsChangingDate", token=token)
    res_settings = api_request_plain("GET", f"api/projects/{p_id}/settingsChangingDate", token=token, local_api_url=local_api_url)
    if res_settings and res_settings.status_code == 200:
        result["LastChangeScanSettings"] = res_settings.text.strip('"')

    # 2. Запрос веток проекта
    res_branches = api_request_plain("GET", f"api/projects/{p_id}/branches", token=token, local_api_url=local_api_url)
    if res_branches and res_branches.status_code == 200:
        branches = res_branches.json()
        if isinstance(branches, list):
            result["branches"] = branches
            result["branches_str"] = "; ".join(map(str, branches))
            result["branches_str2"] = "; ".join(b.get("name") for b in branches if b.get("name"))
            scan_dates = []

            # Для каждой ветки ищем последнее сканирование
            for branch in branches:
                b_id = branch.get("id")
                if b_id:
                    res_last_scan = api_request_plain("GET", f"api/branches/{b_id}/scanResults/last", token=token, local_api_url=local_api_url)
                    if res_last_scan and res_last_scan.status_code == 200:
                        scan_data = res_last_scan.json()
                        s_date = scan_data.get("scanDate")
                        if s_date:
                            scan_dates.append(s_date)
            if scan_dates:
                result["LastScanDate"] = max(scan_dates)

    return result


# Функция параллельного сбора данных по проектам
def get_enriched_data_parallel(projects_list, token):
    enriched_results = []

    # для запука в разных изолированных потоках явно передаем переменные
    local_api_url = st.session_state.get("api_url")
    if not local_api_url:
        st.error("API URL не задан в сессии!")
        return []

    progress_text = "Обогащение данных проектов. Пожалуйста, подождите..."
    my_bar = st.progress(0, text=progress_text)

    total_projects = len(projects_list)

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(enrich_single_project, p, token, local_api_url): i for i, p in enumerate(projects_list)}

        for i, future in enumerate(as_completed(futures)):
            try:
                res = future.result()
                enriched_results.append(res)
            except Exception as e:
                st.error(f"Ошибка при обработке проекта: {e}")

            percent_complete = int(((i + 1) / total_projects) * 100)
            my_bar.progress(percent_complete, text=progress_text)

    my_bar.empty()
    return enriched_results

def show_projects():
    # Инициализация кэш-структур в session_state
    if "project_branches" not in st.session_state:
        st.session_state.project_branches = {}  # {project_id: [branches_list]}
    if "project_details" not in st.session_state:
        st.session_state.project_details = {}   # {project_id: {details_dict}}

    # Первичная загрузка списка проектов
    if "df_projects" not in st.session_state:
        res_projects = api_request("GET", "api/projects?limit=-1&offset=-1")
        if res_projects and res_projects.status_code == 200:
            df = pd.DataFrame(res_projects.json())
            df["LastChangeScanSettings"] = None
            df["LastScanDate"] = None

            st.session_state.df_projects = df
            st.session_state.is_enriched = False
            st.session_state.raw_projects_json = res_projects.json()
        else:
            st.error("Не удалось загрузить проекты.")
            return

    # Панель кнопок расширенной информации
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        st.subheader("Список проектов")
    with col2:    
        if not st.session_state.is_enriched:
            if st.button("Получить расширенную информацию о сканированиях", type="primary",icon=":material/stat_minus_3:"):
                token = st.session_state.access_token

                enriched_data = get_enriched_data_parallel(st.session_state.raw_projects_json, token)
                df_enriched_list = []
                for res in enriched_data:
                    p_id = res["project_id"]
                    st.session_state.project_branches[p_id] = res["branches"]

                    df_enriched_list.append({
                        "LastScanDate": res["LastScanDate"],
                        "branches_str2": res["branches_str2"],
                        "LastChangeScanSettings": res["LastChangeScanSettings"],
                        "project_id": p_id,
                        "branches_str": res["branches_str"],

                    })

                df_enriched = pd.DataFrame(df_enriched_list)
                if not df_enriched.empty:
                    df_merged = pd.merge(
                        st.session_state.df_projects.drop(columns=["LastChangeScanSettings", "LastScanDate"]), 
                        df_enriched, 
                        left_on="id", 
                        right_on="project_id", 
                        how="left"
                    ).drop(columns=["project_id"])

                    st.session_state.df_projects = df_merged
                    st.session_state.is_enriched = True
                    st.success("Данные успешно обогащены!")
                    st.rerun()
    with col3:
        if st.button("Сбросить кэш (обновить)",icon=":material/refresh:"):

            st.session_state.project_branches = {}
            st.session_state.project_details = {}
            if "df_projects" in st.session_state:
                del st.session_state.df_projects
            st.rerun()


    selection = st.dataframe(
        st.session_state.df_projects,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        column_config={
            "creationDate": st.column_config.DatetimeColumn(label="Дата создания", format="localized"), 
            "LastChangeScanSettings": st.column_config.DatetimeColumn(label="Изменение настроек", format="localized"),
            "LastScanDate": st.column_config.DatetimeColumn(label="Последний скан веток", format="localized")
        },
        column_order=["name","creationDate","branches_str2","LastScanDate","LastChangeScanSettings","id","settingsId","projectType","projectSettingsId","branches_str"]
    )


    if selection and selection.get("selection") and selection["selection"]["rows"]:
        row_idx = selection["selection"]["rows"][0]
        selected_project_row = st.session_state.df_projects.iloc[row_idx]

        project_id = selected_project_row['id']
        project_name = selected_project_row['name']

        st.write(f"Выбран проект: {project_name}")

        #todo: стоит ли кэшировать - проверить на тысячах проектах.
        if project_id not in st.session_state.project_details:
            with st.spinner("Загрузка деталей проекта с сервера..."):
                res_project = api_request("GET", f"api/projects/{project_id}")
                if res_project and res_project.status_code == 200:
                    st.session_state.project_details[project_id] = res_project.json()
                else:
                    st.session_state.project_details[project_id] = None

        project_data = st.session_state.project_details.get(project_id)

        if project_data:
            scan_settings_id = project_data.get('settingsId', '')
            project_settings_id = project_data.get('projectSettingsId', '')

            df_project = pd.DataFrame([project_data])
            st.table(df_project)
        else:
            st.warning("Не удалось получить детальные параметры проекта.")
            scan_settings_id = ''
            project_settings_id = ''

        if project_id not in st.session_state.project_branches:
            with st.spinner("Загрузка списка веток..."):
                res_branches = api_request("GET", f"api/projects/{project_id}/branches")
                if res_branches and res_branches.status_code == 200:
                    st.session_state.project_branches[project_id] = res_branches.json()
                else:
                    st.session_state.project_branches[project_id] = []

        branches_list = st.session_state.project_branches.get(project_id, [])

        if branches_list:
            df_branches = pd.DataFrame(branches_list)
            st.write("Список веток")
            st.table(df_branches)

            branch_names = df_branches['name'].tolist()
            is_working_list = [str(val).lower() == 'true' for val in df_branches['isWorking']]
            try:
                default_index = is_working_list.index(True)
            except ValueError:
                default_index = 0

            selected_branch = st.radio(
                "Выберите ветку", 
                options=branch_names, 
                index=default_index, 
                horizontal=True,
                key=f"branch_radio_{project_id}"
            )

            branch_id = df_branches[df_branches['name'] == selected_branch]['id'].values[0]
            st.write(f"Выбран ID ветки: {branch_id}")

            tab_scans, tab_history, tab_files = st.tabs(["🔍 Сканирования", "📜 История", "📁 Файлы"])

            with tab_scans:
                show_scan_results(branch_id)

            with tab_history:
                show_branch_history(branch_id)

            with tab_files:
                show_directory_content(project_id, branch_id)

        else:
            st.info("У проекта нет веток.")
            branch_id = ''

        # Кнопки действий уровня проекта
        render_actions_project(project_id, scan_settings_id, branch_id, project_settings_id)
        # Логи отладки
        st.write("---")
        with st.expander("🛠 Логи отладки (Debug Console)"):
            if st.session_state.debug_logs:
                for log in reversed(st.session_state.debug_logs):
                    st.text(log)
            else:
                st.write("Нет действий для логгирования")


def render_api_response(res, key_suffix):
    """
    Отрисовывает полученный ответ Response
    """
    status_code = res.status_code
    if 200 <= status_code < 300:
        pass
    elif 400 <= status_code < 500:
        st.warning(f"Ошибка на стороне клиента: Код {status_code}", icon="⚠️")
    else:
        st.error(f"Ошибка на стороне сервера: Код {status_code}", icon="🚨")

    tab_visual, tab_raw, tab_headers = st.tabs([
        "Интерактивный вид",
        "Текст",
        "Заголовки (Headers)"
    ])

    # Парсим JSON безопасно
    is_json = False
    parsed_data = None
    try:
        parsed_data = json.loads(res.text)
        if isinstance(parsed_data, (dict, list)):
            is_json = True
    except Exception:
        pass

    with tab_visual:
        if is_json:
            if isinstance(parsed_data, list) and len(parsed_data) > 0 and isinstance(parsed_data[0], dict):
                view_mode = st.radio(
                    "Режим отображения:",
                    ["Таблица (DataFrame)", "JSON"],
                    horizontal=True,
                    key=f"view_mode_{key_suffix}"
                )
                if view_mode == "Таблица (DataFrame)":
                    df = pd.DataFrame(parsed_data)
                    st.dataframe(df, width='stretch')
                else:
                    st.json(parsed_data)
            else:
                st.json(parsed_data)
        else:
            st.info("Ответ сервера не является JSON. Показан исходный текст:")
            st.download_button('Download file', res.content)
            st.text(res.text)

    with tab_raw:
        if is_json:
            pretty_json = json.dumps(parsed_data, indent=2, ensure_ascii=False)
            st.code(pretty_json, language="json")
        else:
            st.code(res.text, language="html" if "html" in res.headers.get("Content-Type", "") else "text")

    with tab_headers:
        st.write(f"**Статус-код:** `{status_code}`")
        st.json(dict(res.headers))

def resolve_url_template(url_template, selected_item, id_key, key_suffix):
    """
    Разбирает строку вида 'METHOD:path/to/{param}'
    Возвращает (method, resolved_url) или (None, None), если не заполнено.
    """
    # 1. Разделяем метод и шаблон
    if ":" in url_template:
        method, template = url_template.split(":", 1)
    else:
        # Если метод не указан, считаем по умолчанию GET
        method, template = "GET", url_template

    method = method.upper()

    # Логика замены
    placeholders = re.findall(r"\{([^}]+)\}", template)
    resolved_values = {}

    for p in placeholders:
        if p in ('id', id_key):
            resolved_values[p] = selected_item.get(id_key)
        elif p in selected_item:
            resolved_values[p] = selected_item.get(p)
        else:
            val = st.text_input(
                f"Заполните параметр `{p}` для {method} запроса:",
                key=f"inputₚ_{key_suffix}",
                placeholder="Введите значение"
            )
            if not val:
                st.warning(f"⚠️ Для вызова API заполните поле `{p}`.")
                return None, None
            resolved_values[p] = val

    return method, template.format(**resolved_values)

def show_api_master_detail(list_url, detail_endpoints, id_key='id', name_key='name', key_prefix="md", single_item=False, show_json=True):
    """
    Универсальное отображение "Список -> Подробности".

    Args:
        list_url: Эндпоинт для получения списка элементов (например, 'api/scanAgents')
        detail_endpoints: Словарь вида {"Имя вкладки": "api/scanAgents/{id}/sub_route"}
        id_key: Поле идентификатора в объекте (обычно 'id')
        name_key: Поле для отображения в селекторе (например, 'name' или 'hostName')
        key_prefix: Префикс для уникализации ключей виджетов Streamlit
    """
    st.markdown("---")
    st.markdown(f"#### **GET** `{list_url}`")

    try:
        with st.spinner("Загрузка списка с сервера..."):
            res_master = api_request("GET", list_url)

        if not res_master or res_master.status_code != 200:
            st.error(f"Не удалось получить список. Сервер вернул код {res_master.status_code if res_master else 'No Response'}")
            return

        master_data = res_master.json()
        if single_item:
            master_data = [master_data]

        if not isinstance(master_data, list) or len(master_data) == 0:
            st.info("Список пуст или формат ответа сервера не является списком.")
            return

    except Exception as e:
        st.error(f"Ошибка соединения при получении списка: {e}")
        return

    df_master = pd.DataFrame(master_data)

    item_names = df_master[name_key].tolist()

    selected_name = st.radio(
        f"Выберите объект из списка `{list_url}`:",
        options=item_names,
        horizontal=True,
        key=f"select_{key_prefix}"
    )

    selected_item = df_master[df_master[name_key] == selected_name].iloc[0].to_dict()
    selected_id = selected_item.get(id_key)

    st.success(f"Выбран объект: **{selected_name}** (ID: `{selected_id}`)")

    if show_json:
        st.json(selected_item)

    tabs_detail = st.tabs(list(detail_endpoints.keys()))

    for i, (tab_title, config) in enumerate(detail_endpoints.items()):
        tab_key = f"{key_prefix}{i}_tab"

        with tabs_detail[i]:

            if isinstance(config, str):
                method, resolved_url = resolve_url_template(config, selected_item, id_key, tab_key)
                config_dict = {"url": resolved_url, "method": method, "payload": None, "is_file": False}
            else:
                method, resolved_url = resolve_url_template(config['url'], selected_item, id_key, tab_key)
                method = config.get('method', method) #todo переделать resolve_url_template по оба варианта или переписать все вызовы под новый формат
                config_dict = {
                    "url": resolved_url,
                    "method": method,
                    "payload": config.get('payload'),
                    "is_file": config.get('is_file', False),
                    "filename": config.get('filename', f"file_{tab_key}.zip")
                }

            if resolved_url:
                st.write(f"Сформированный эндпоинт: **{method}** `{resolved_url}`")
                if config_dict['payload']:
                    st.caption(f"Payload: `{config_dict['payload']}`")

                if st.button(f"Выполнить {method} запрос '{tab_title}'", key=f"btn_{tab_key}", icon=":material/radio_button_unchecked:", help=resolved_url):
                    try:
                        with st.spinner(f"Выполнение запроса..."):
                            # Передаем stream=True только если это файл
                            res_detail = api_request(
                                method=method,
                                endpoint=resolved_url,
                                json=config_dict['payload'],
                                stream=config_dict['is_file']
                            )
                        #todo: проверить скачивается в память или ссылка stream.
                        if res_detail:
                            # Проверяем, нужно ли скачивать как файл
                            if config_dict['is_file'] and res_detail.status_code == 200:
                                if ext_config.USE_TEMP_DIR:
                                    handle_file_download(res_detail, config_dict['filename'])
                                else:
                                    st.download_button(label="💾 Сохранить полученный файл (memory)", data=res_detail.content, file_name=config_dict['filename'], mime=res_detail.headers.get("Content-Type", "application/octet-stream"))

                            else:
                                # Обычный рендеринг (JSON, таблицы)
                                render_api_response(res_detail, key_suffix=tab_key)
                        else:
                            st.error(f"Сервер не ответил на запрос {res_detail.status_code}")
                    except Exception as e:
                        st.error(f"Ошибка запроса: {e}")


def handle_file_download(response, filename):
    """
    Скачивает ответ во временный файл чанками и предоставляет кнопку скачивания.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:

            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    tmp.write(chunk)
            temp_path = tmp.name

        # Даем пользователю скачать файл из временного хранилища
        with open(temp_path, "rb") as f:
            st.download_button(
                label="💾 Сохранить полученный файл (tmpfile)",
                data=f,
                file_name=filename,
                mime=response.headers.get("Content-Type", "application/octet-stream")
            )
        st.success("Файл успешно сгенерирован и готов к скачиванию!")
    except Exception as e:
        st.error(f"Ошибка при записи файла: {e}")

def show_PTAI():
    tab_agents, tab_license, tab_info = st.tabs(["Агенты", "Лицензии", "Информация"])
    with tab_agents:
        show_api_get_universal("api/settings/scanAgent")
        show_api_get_universal("api/scanAgents/hasActive")
        show_api_get_universal("api/scanAgents/count")
        show_api_get_universal("api/scans")
        show_api_master_detail(list_url="/api/scans", name_key="projectName", id_key="id", detail_endpoints={
         "Start scan projectId": "POST:api/scans/{projectId}/start",
         "Start scan branchId": "POST:api/scans/branches/{branchId}/start", "Stop scan": "POST:api/scans/{scanResultId}/stop", "Stop all scans": "POST:api/scans/stop",
         }, key_prefix="scans_action", show_json=False)
        show_api_get_universal("/api/projects/activeScans")
        show_api_master_detail(list_url="/api/projects/activeScans", name_key="scanResultId", id_key="scanResultId", detail_endpoints={
         "Stop scan": "POST:api/scans/{scanResultId}/stop", "Stop all scans": "POST:api/scans/stop",
         }, key_prefix="activeScans_action", show_json=False)
        show_api_master_detail(list_url="api/scanAgents", name_key="name", id_key="id", detail_endpoints={
         "Основная информация": "GET:api/scanAgents/{id}",
         "Пауза Агента": "POST:api/scanAgents/{id}/pause","активация Агента": "POST:api/scanAgents/{id}/active",
         }, key_prefix="agents_view")


    with tab_license:
        show_api_get_universal("api/license")
        show_api_get_universal("api/license/base")

    with tab_info:
        show_api_get_universal("api/versions/package/current")
        show_api_get_universal("health/summary")
        show_api_get_universal("api/tracker/connections/light")
        show_api_get_universal("/api/auth/accessToken")
        show_api_get_universal("/api/settings/sso")
        show_api_get_universal("/api/settings/storage")
        show_api_get_universal("/api/settings/logs")
        show_api_master_detail(list_url="api/configs/pmGroups", name_key="name", id_key="id", detail_endpoints={"Get rule": "GET:api/configs/pmGroups/{id}", "Get Text Rule": "GET:api/configs/pmGroups/{id}/rules"},  key_prefix="pmGroups_action")
        #todo: api/configs/pmRules/export требует тела запроса
        show_api_master_detail(list_url="api/configs/pmRules", name_key="name", id_key="id", detail_endpoints={"Get rule": "GET:api/configs/pmRules/{id}", "export Text Rule": "POST:api/configs/pmRules/export"},  key_prefix="pmRules_action")

def show_api_get_universal(surl, headers=None, params=None):
    """
    Универсальный виджет для отправки GET запросов и интерактивного отображения ответов.
    """
    st.markdown(f"#### **GET** `{surl}`")

    try:
        with st.spinner("Запрос данных..."):
            res_projects = api_request("GET", surl)

        status_code = res_projects.status_code
        if 200 <= status_code < 300:
            pass #st.text(f"Успешно! Код {status_code}")
        elif 400 <= status_code < 500:
            st.warning(f"⚠️ Ошибка клиента: Код {status_code}")
        else:
            st.error(f"🚨 Ошибка сервера: Код {status_code}")

        tab_visual, tab_raw, tab_headers = st.tabs(["Интерактивный вид","Текст","Заголовки (Headers)"])

        # Проверяем, является ли ответ JSON-ом
        is_json = False
        parsed_data = None
        if is_json == False:
         try:
            parsed_data = json.loads(res_projects.text)
            if isinstance(parsed_data, (dict, list)):
              is_json = True
         except Exception as e:
            pass

        with tab_visual:
            if is_json:
                if (isinstance(parsed_data, list) and len(parsed_data) > 0 and isinstance(parsed_data[0], dict)):
                    view_mode = st.radio("Режим отображения:", ["Таблица (DataFrame)", "JSON"], horizontal=True, key=f"view_mode_{surl}")
                    if view_mode == "Таблица (DataFrame)":
                        # Получаем все ключи (колонки) на основе первого элемента
                        headers2 = list(parsed_data[0].keys())
                        num_cols = len(headers2)

                        # Ограничим создание колонок (Streamlit плохо рендерит > 12 колонок)
                        if num_cols > 6:
                            df = pd.DataFrame(parsed_data)
                            st.dataframe(df, width='stretch')
                        else:
                         header_cols = st.columns(num_cols)
                         for col, header in zip(header_cols, headers2):
                             col.markdown(f"**{header.upper()}**")
                         for row_idx, item in enumerate(parsed_data):
                             row_cols = st.columns(num_cols)

                             for col, header in zip(row_cols, headers2):
                                 cell_value = item.get(header)
                                 with col:
                                     render_cell_content(cell_value)

                             # разделитель между строками таблицы
                             #st.markdown("<hr style='margin: 8px 0px; border-top: 1px dashed #bbb;'>",unsafe_allow_html=True,)
                    else:
                        st.json(parsed_data)

                else:
                    # если пришел пустой список или не список словарей
                    st.json(parsed_data)
            else:
                st.code(res_projects.text, language="html" if "html" in res_projects.headers.get("Content-Type", "") else "text")

        with tab_raw:
            if is_json:
                pretty_json = json.dumps(parsed_data, indent=2, ensure_ascii=False)
                st.code(pretty_json, language="json")
            else:
                st.code(res_projects.text, language="html" if "html" in res_projects.headers.get("Content-Type", "") else "text")

        with tab_headers:
            st.write(f"**Статус-код:** `{status_code}`")
            st.json(dict(res_projects.headers))

    except requests.exceptions.RequestException as e:
        st.error(f"❌ Не удалось установить соединение с сервером.")
        st.exception(e)
    except Exception as e:
        st.error(f"show_api_get_universal: Произошла непредвиденная ошибка: {e}")

# main
st.set_page_config(layout="wide")
@st.fragment
def get_manager():
    return exc.CookieManager()

if "master_token" not in st.session_state:
    st.session_state.master_token = None
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "expiredAt" not in st.session_state:
    st.session_state.expiredAt = None
if "api_url" not in st.session_state:
    st.session_state.api_url = ""
if "debug_logs" not in st.session_state:
    st.session_state.debug_logs = []

if cookie:
    cookie_manager = get_manager() #key="ptai_cookie_manager")
    time.sleep(1)
#cookies = cookie_manager.get_all() # нужен , иначе почему то не видит (задержка? + time.sleep(5) )
#time.sleep(5) # обязяательно для streamlit

if cookie:
    saved_master_token = cookie_manager.get(cookie="ptai_master_token")
    time.sleep(1)
    saved_master_token = cookie_manager.get(cookie="ptai_master_token")

else:
    saved_master_token, saved_api_url = load_config_from_localstorage()
    if saved_api_url and not st.session_state.api_url:
        st.session_state.api_url = saved_api_url

API_URL = st.session_state.api_url



# автоматический вход
if saved_master_token and st.session_state.api_url and not st.session_state.access_token:
    initial_login(saved_master_token, st.session_state.api_url)

# форма ввода данных, если нет bearer токена аутентицикации
if not st.session_state.access_token:
    st.subheader("Авторизация в PT AI")
    with st.form("login_form"):

        with st.container(border=True):
            selected_url_option = st.selectbox("Выберите или укажите API URL сервера", options=ext_config.DEFAULT_API_URLS)

        target_api_url = selected_url_option

        if st.session_state.master_token:
            master_tkn = st.text_input("Введите мастер Access-Token", type="password", value=st.session_state.master_token)
        else:
            master_tkn = st.text_input("Введите мастер Access-Token", type="password")
        cookie = st.checkbox("Предпочитаемое хранилище: Cookie", help="Выключено, в разработке", disabled=True)

        if st.form_submit_button("Войти", use_container_width=True):

            if not target_api_url or target_api_url == "https://":
                st.error("Пожалуйста, укажите корректный API URL сервера!")
            else:
                if initial_login(master_tkn, target_api_url):
                    if cookie:
                        cookie_manager.set(cookie="ptai_master_token", val=master_tkn, max_age = 60*60*24*3)
                    else:
                        save_config_to_localstorage(master_tkn, target_api_url)
                        time.sleep(1)

                    st.success("Авторизация успешна! Загрузка...")
                    if cookie:
                        # обязательно, иначе не успевает
                        time.sleep(5)
                    st.rerun()
                else:
                    st.error("Неверный мастер-токен или ошибка сервера.")

    st.stop()


with st.sidebar:
    st.write(f"PTAI API Browser v{__version__}")
    st.link_button("Открыть на GitHub", "https://github.com/srgkr/ptai-api-browser")

    st.caption("Текущий сервер:")
    st.write(API_URL)

    #if st.sidebar.button("Выйти"):
    if st.button("Выйти из аккаунта", use_container_width=True):
        if cookie:
          try:
            cookie_manager.delete("ptai_master_token")
            time.sleep(5) # обязяательно для streamlit
          except Exception as e:
            st.write(f"cookie: Unable to delete {e}")
        else:
            clear_auth_from_localstorage()
            time.sleep(1)
        clear_all_caches_and_session()
        st.rerun()

    st.divider()
    page = st.radio("Выбрать страницу", ["Проекты", "PTAI"], index=0)

    with st.expander("Показать токен"):
        st.write(f"JWT Token: bearer {st.session_state.access_token}")
        st.write(f"Expired At: {st.session_state.get('expiredAt')}")


if page == "Проекты":
    show_projects()
elif page == "PTAI":
    show_PTAI()
