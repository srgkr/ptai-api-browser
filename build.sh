#!/bin/bash
set -e

GENERATE_REQ=false
DOCKERFILE_NAME="Dockerfile"

# Перебираем все переданные аргументы
for arg in "$@"; do
    case $arg in
        --requirements)
            GENERATE_REQ=true
            ;;
        --github)
            DOCKERFILE_NAME="Dockerfile-github"
            ;;
        *)
            echo "Неизвестный аргумент: $arg"
            echo "Использование: ./build.sh [--requirements] [--github]"
            exit 1
            ;;
    esac
done


if command -v podman &> /dev/null; then
    echo "Используем Podman"
    CONTAINER_RUN="sudo podman run"
    # обход для Astra Linux 1.7.x с проблемой запуска DNS aardvark-dns / netavark в rootless podman, образ в хранилище root чтобы запускать через sudo podman compose
    CONTAINER_BUILD="sudo podman build"
    ENGINE_NAME="Podman"
    #package: aardvark-dns_1.10.0~astra1+ci7+b1_amd64
    #package: netavark_1.10.2.astra1+ci4_amd64
elif command -v docker &> /dev/null; then
    echo "Используем Docker"
    CONTAINER_RUN="docker run"
    CONTAINER_BUILD="docker build"
    ENGINE_NAME="Docker"
else
    echo "Не найден: podman, docker"
    exit 1
fi

if [ ! -f VERSION ]; then
    echo "0.0.0" > VERSION
fi
APP_VERSION=$(cat VERSION | tr -d '\r\n')
echo "Версия $APP_VERSION"

KEY_FILE="./nginx/certs/server.key"
CRT_FILE="./nginx/certs/server.crt"

if [ ! -f "$KEY_FILE" ] || [ ! -f "$CRT_FILE" ]; then
    echo "Генерация сертификатов: запуск"
    mkdir -p ./nginx/certs
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
      -keyout "$KEY_FILE" \
      -out "$CRT_FILE" \
      -subj "/C=RU/ST=Moscow/L=Moscow/O=LocalCompany/CN=localhost/CN=ptai-api-browser"
else
echo "Генерация сертификатов: пропуск"
fi

if [ "$GENERATE_REQ" = true ]; then
    echo "Генерируем requirements.txt"
    $CONTAINER_RUN --rm \
        -v ".:/app:z" \
        -w /app \
        python:3.12-slim \
        sh -c "pip install --quiet pipreqs && pipreqs . --force --ignore venv,.venv"
else
    echo "Для принудительного обновления requirements.txt запустить: ./build.sh --requirements)"
fi

mkdir -p ./tmp_data

echo "Генерируем образ"
$CONTAINER_BUILD \
    -f $DOCKERFILE_NAME \
    -t ptai-api-browser:$APP_VERSION \
    -t ptai-api-browser:latest .

if [ "$ENGINE_NAME" = "Podman" ]; then
    echo "  sudo podman compose up -d"
else
    echo "  docker compose up -d"
fi
