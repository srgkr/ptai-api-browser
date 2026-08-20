# PTAI API Browser

Просмотр и управление [Positive Technologies Application Inspector (PTAI)](https://ptsecurity.com/ru-ru/products/ai/) (Анализатор исходного кода приложений) через API.

сделан на основе [Streamlit](https://streamlit.io/), проксирование через Nginx.

Возможности:

1. Просмотр проектов, веток, сканирований через веб-интерфейс

- просмотр настроек, скачивание логов, исходных кодов.
- генерация отчета сканирования
- остановка, старт заданий
и т.п.

2. Запрос расширенной информации по проектам.

3. Просмотр и управление агентами

---

## Установка:
### Получение данных

Склонируйте репозиторий с помощью `git`:

```bash
git clone https://github.com/srgkr/ptai-api-browser.git
cd ptai-api-browser
```

*или скачайте ZIP-архив через браузер/`wget` и распакуйте в рабочий каталог*

---

### Подготовка конфигурации

1. Скопируйте шаблон файла переменных окружения:
   ```bash
   cp .env.example .env
   ```

2. Отредактируйте `.env` указав реальный адрес(а) сервера PTAI:
   ```env
   DEFAULT_API_URLS=https://ptai-api-server.local
   ```

3. *(Необязательно)* Отредактируйте `docker-compose.yml` в части лимитов ресурсов при необходимости.

---

### Сборка образов через `build.sh`

Запустите скрипт автоматической подготовки окружения:

```bash
chmod +x build.sh
./build.sh
```

**Что делает скрипт:**
* **Определяет Container Engine:** если в системе установлен `podman`, скрипт автоматически выберет `sudo podman` (обход проблем с резолвом DNS в Astra Linux в rootless-режиме), иначе будет использован `docker`.
* **Генерирует SSL-сертификаты** для Nginx в nginx/certs/.
* **Подтягивает базовые образы** и производит сборку.

**Дополнительные флаги скрипта `build.sh`:**
* `--github` — использовать `Dockerfile-github` вместо стандартного `Dockerfile`.
* `--requirements` — запустить изолированный контейнер Python для перегенерации файла зависимостей `requirements.txt`.

*Пример запуска с флагами:*
```bash
./build.sh --github
```

---

### Запуск контейнеров

После успешного выполнения скрипта запустите контейнеры в фоновом режиме:

**Если используется Docker:**
```bash
docker compose up -d
```

**Если используется Podman:**
```bash
sudo podman compose up -d
```

---

## Внутри приложения

1. Откройте браузер и перейдите по адресу:
   **[https://localhost:2443/](https://localhost:2443/)**
   *(Так как используются самоподписанные сертификаты, подтвердите предупреждение безопасности в браузере).*

2. **Укажите initialAccessToken из PTAI для авторизации:**
   * Перейдите в веб-интерфейс вашего сервера **PTAI**.
   * Откройте раздел: **Настройки ➔ Токены доступа**.
   * Выпустите токен с ролью: **«Для легкого агента и плагинов CI/CD»**.
   * Скопируйте полученный `initialAccessToken` и вставьте его в поле ввода в приложении `PTAI API Browser`.

---

## Остановка и управление

* **Просмотр логов:**
  ```bash
  docker compose logs -f
  # или: sudo podman compose logs -f
  ```

* **Остановка приложения:**
  ```bash
  docker compose down
  # или: sudo podman compose down
  ```

## Дополнительные возможности

1. Для удобства локальной разработки можно пробросить текущий каталог в app контейнера
   ```bash
   cp docker-compose.override.yml.example_for_local_dev docker-compose.override.yml
   ```
   Таким образом при обновлении основного файла (только его) можно делать Rerun (st.rerun)

2. *(!!!ЭКСПЕРИМЕНТАЛЬНО!!!)* Возможность использования временного каталога и как общего каталога temp dir между контейнерами

   используйте docker-compose.yml.temp.example , создайте каталог tmp_data (или подмонтируйте реальный)

   и раскоментиркуйте в .env
   ```bash
   TMP_DATA_DIR=/app/tmp_data
   ```
   т.к. с ver.0.5 проксирование через Nginx (location /proxy-download/, обязательно указание resolver = 10.89.2.1 Podman; 127.0.0.11 Docker) - загрузка исходного кода, логов. остальное через память.

   т.е если будет указан TMP_DATA_DIR, то скачивание по кнопкам будет через временный каталог.

   также можно использовать функцию source_download_action_tmp в таком случае Streamlit сам будет скачивать исходники, а Nginx раздавать их из общего каталога (location /downloads/).

3. *(!!!ЭКСПЕРИМЕНТАЛЬНО!!!)* Можно использовать Cookies для хранения токенов в браузере.

   Отключено т.к. компонент extra_streamlit_components.CookieManager() ведет себя непредсказуемо.

## Решение проблем

1. В случае падения при нехватке памяти, добавить ресурсов streamlit в docker-compose.yml

2. пока не решена проблема запуска podman compose в rootless режиме на Astra Linux 1.7.7.9

   сделан обход путем запуска через sudo podman compose

   Анамнез:

   в namespace контейнеров после запуска podman compose, нет доступности до внутреннего DNS 10.89.2.1, соответственно имена контейнеров не регистрируются в внутреннем DNS.

   Диагностика:
   ```bash
   $ podman unshare --rootless-netns
   root@:# systemd-run -q --scope --user /usr/lib/podman/aardvark-dns --config /run/user/1000/containers/networks/aardvark-dns -p 53 run
   Failed to start transient scope unit: Access denied
   ```

   Предположение: для Astra Linux 1.7.x проблема взаимодействия пакетов aardvark-dns / netavark в rootless podman, проблема плавающая, похожая проблема решалась в более свежих версиях пакетов.

   Предполагаемое решение: обновление пакетов aardvark-dns / netavark

   максимально доступные сейчас на Astra Linux 1.7.x:
   ```bash
   package: aardvark-dns_1.10.0~astra1+ci7+b1_amd64
   package: netavark_1.10.2.astra1+ci4_amd64
   ```
