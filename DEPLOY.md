# Как выложить СОКРАТ на сервер

Результат: бот работает круглосуточно, YandexGPT отвечает, у мини-приложения есть HTTPS-адрес
вида `https://51-250-10-20.sslip.io`.

## Шаг 1. Создать сервер в Yandex Cloud

1. Откройте [console.yandex.cloud](https://console.yandex.cloud), выберите свой каталог.
2. **Compute Cloud → Виртуальные машины → Создать ВМ.**
3. Настройки (остальное оставьте по умолчанию):
   - **Образ:** Ubuntu 24.04 LTS
   - **Вычислительные ресурсы:** 2 vCPU, гарантированная доля 20%, 2 ГБ RAM
   - **Диск:** 15 ГБ HDD
   - **Сеть → Публичный адрес:** Автоматически
   - **Доступ:** логин `sokrat`, SSH-ключ (см. ниже)
4. Нажмите **Создать ВМ** и дождитесь статуса Running. Запишите **публичный IPv4**.
5. Сделайте адрес постоянным: **VPC → IP-адреса →** у адреса машины **⋮ → Сделать статическим**.
   Иначе после перезагрузки адрес сменится и ссылка на приложение сломается.

**SSH-ключ.** В PowerShell на своём компьютере:

```bash
ssh-keygen -t ed25519
```

Нажмите Enter на все вопросы. Затем выведите публичный ключ и вставьте его целиком в поле «SSH-ключ»:

```bash
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

## Шаг 2. Подключиться к серверу

В PowerShell (вместо `IP` — адрес из шага 1):

```bash
ssh sokrat@IP
```

На вопрос `Are you sure you want to continue connecting` ответьте `yes`.

## Шаг 3. Установить Docker и скачать проект

Выполните на сервере по очереди:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
```

```bash
echo '{"registry-mirrors": ["https://mirror.gcr.io"]}' | sudo tee /etc/docker/daemon.json && sudo systemctl restart docker
```

```bash
git clone https://github.com/ВАШ_ЛОГИН/sokrat.git && cd sokrat
```

## Шаг 4. Заполнить настройки

```bash
cp .env.example .env && nano .env
```

Заполните:
- `BOT_TOKEN`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` — как в `.env` на вашем компьютере
- `DEV_MODE=0`
- `DOMAIN=` — IP с дефисами вместо точек и `.sslip.io` в конце. Например, для IP `51.250.10.20`:
  `DOMAIN=51-250-10-20.sslip.io`

Сохранить: `Ctrl+O`, `Enter`, выйти: `Ctrl+X`.

## Шаг 5. Запустить

> ⚠️ Сначала **остановите сервер на своём компьютере** (`Ctrl+C`). Если бот запущен в двух местах
> с одним токеном, они будут «перехватывать» сообщения друг у друга.

```bash
sudo docker compose up -d --build
```

Первый запуск занимает 2–4 минуты. Проверка: откройте в браузере `https://ВАШ_DOMAIN/health`,
должно быть `{"ok":true,"bot":true,"ai":true,...}`. Напишите боту в MAX `/start`.

## Шаг 6. Подключить мини-приложение к боту

Отправьте организаторам адрес `https://ВАШ_DOMAIN` с просьбой указать его как ссылку
на мини-приложение для бота `ideya_fiks_198_bot`.

## Полезные команды на сервере

| Что | Команда |
|---|---|
| Логи | `sudo docker compose logs -f app` |
| Обновить код после изменений | `git pull && sudo docker compose up -d --build` |
| Перезапустить | `sudo docker compose restart` |
| Остановить | `sudo docker compose down` |
