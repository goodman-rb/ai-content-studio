# 🔧 Настройка автопубликации через N8N v1.118+

Подробное руководство по настройке автоматической публикации постов в VK и Telegram **БЕЗ генерации изображений**.

**Актуально для N8N версии 1.118.1 и выше**

---

## 📋 Оглавление

1. [Что такое N8N](#что-такое-n8n)
2. [Установка N8N локально](#установка-n8n-локально)
3. [Получение API токенов](#получение-api-токенов)
4. [Настройка Credentials в N8N](#настройка-credentials-в-n8n)
5. [Создание Workflow](#создание-workflow)
6. [Тестирование](#тестирование)
7. [Запуск в продакшн](#запуск-в-продакшн)
8. [Решение проблем](#решение-проблем)

---

## 🤔 Что такое N8N

**N8N** — это платформа автоматизации с открытым исходным кодом (аналог Zapier/Make).

**Зачем нужен для AI Content Studio:**

- ✅ Автоматическая публикация постов по расписанию
- ✅ Публикация в VK и Telegram одновременно
- ✅ Обновление статуса в Google Sheets

**Архитектура (упрощённая, без картинок):**

```
┌─────────────────┐
│  N8N Workflow   │ ← Запускается каждый час
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ Google Sheets           │ ← Читает Content_Plan
│ Get row(s): Status=Ready│    где время <= сейчас
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ Loop Over Items         │ ← Обрабатывает посты
└────────┬────────────────┘  по одному
         │
         ├─────────────────┐
         ▼                 ▼
┌──────────────┐   ┌──────────────┐
│  Telegram    │   │  VK API      │ ← Публикация
│  sendMessage │   │  wall.post   │    только текста
└──────────────┘   └──────────────┘
         │                 │
         └────────┬────────┘
                  ▼
         ┌─────────────────────┐
         │ Google Sheets       │ ← Обновление
         │ Update row          │    Status → Published
         └─────────────────────┘
                  ▼
         ┌─────────────────────┐
         │ Merge               │ ← Возврат в цикл
         └─────────────────────┘
                  ▼
         Loop Over Items (следующий пост)
```

---

## 🐳 Установка N8N локально

### Через Docker Compose (Рекомендуется)

**Шаг 1: Создай файл docker-compose-n8n.yml**

В корне проекта `ai-content-studio/`:

```yaml
version: '3.8'

services:
  n8n:
    image: docker.n8n.io/n8nio/n8n
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      # Security
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=MySecurePass123

      # Webhook URL (важно для OAuth!)
      - WEBHOOK_URL=http://localhost:5678

      # Settings
      - N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
      - DB_SQLITE_POOL_SIZE=5
      - N8N_RUNNERS_ENABLED=true
      - N8N_BLOCK_ENV_ACCESS_IN_NODE=false
      - N8N_GIT_NODE_DISABLE_BARE_REPOS=true
      - N8N_DIAGNOSTICS_ENABLED=false

      # Localization
      - TZ=Europe/Moscow
      - GENERIC_TIMEZONE=Europe/Moscow

    volumes:
      - n8n_data:/home/node/.n8n

volumes:
  n8n_data:
```

**Шаг 2: Запуск**

```bash
docker-compose -f docker-compose-n8n.yml up -d
```

**Шаг 3: Открой N8N**

```
http://localhost:5678
```

**Первый вход:**

- Email: твой email
- Пароль: минимум 8 символов
- Имя: твоё имя

---

## 🔑 Получение API токенов

### 1. Google Sheets API (OAuth 2.0)

N8N v1.118+ использует **OAuth 2.0** для Google Sheets.

#### Шаг 1: Создай проект в Google Cloud

1. Перейди: https://console.cloud.google.com/
2. **Создать проект**
3. Название: `AI Content Studio`
4. **Создать**

#### Шаг 2: Включи Google Sheets API

1. **APIs & Services** → **Library**
2. Найди **Google Sheets API**
3. Нажми **Enable**

#### Шаг 3: Настрой OAuth Consent Screen

1. **APIs & Services** → **OAuth consent screen**
2. **User Type:**
   - ✅ **External** (для обычного Gmail)
   - Или **Internal** (если у тебя Google Workspace)
3. **Create**

**Заполни форму:**

- **App name:** `AI Content Studio`
- **User support email:** твой Gmail
- **Developer contact information:** твой Gmail
- **Save and Continue**

**Scopes:** 

- Пропусти (оставь пустым)
- **Save and Continue**

**Test users (ВАЖНО!):**

1. **Add Users**
2. Введи свой Gmail (которым будешь авторизоваться)
3. **Add**
4. **Save and Continue**

#### Шаг 4: Создай OAuth Client ID

1. **APIs & Services** → **Credentials**

2. **Create Credentials** → **OAuth client ID**

3. **Application type:** **Web application**

4. **Name:** `N8N Google Sheets`

5. **Authorized redirect URIs** → **Add URI:**
   
   ```
   http://localhost:5678/rest/oauth2-credential/callback
   ```

6. **Create**

#### Шаг 5: Скопируй учётные данные

Появится окно:

- **Client ID:** `123456789-abc...xyz.apps.googleusercontent.com`
- **Client Secret:** `GOCSPX-abc...xyz`

**Скопируй оба!** Они понадобятся в N8N.

#### Шаг 6: Дай доступ к таблице

В Google Sheets:

1. Открой свою таблицу AI Content Studio
2. **Share** (Настройки доступа)
3. Добавь свой Gmail (тот, что в Test users)
4. Права: **Editor** (Редактор)

---

### 2. VK API Token и Group ID

#### Шаг 1: Найди ID своей группы

**Способ A: Из URL**

URL группы: `https://vk.com/club123456789`

**ID группы:** `123456789` (число после `club`)

**Способ B: Через настройки**

1. Открой группу в VK
2. **Управление** → **Настройки**
3. Внизу страницы: **ID сообщества:** `123456789`

**Важно:** 

- Для получения токена используй: `123456789` (без минуса)
- Для публикации используй: `-123456789` (с минусом!)

#### Шаг 2: Получи токен сообщества

1. Открой группу в VK
2. **Управление** → **Работа с API**
3. **Ключи доступа** → **Создать ключ**

**Права токена (выбери):**

- ✅ **Управление сообществом** (позволяет постить на стену)
- ✅ **Фотографии** (если будешь добавлять картинки позже)
4. **Создать**
5. Скопируй токен

**Формат токена:**

```
vk1.a.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

⚠️ **Важно:** Токен показывается только один раз! Сохрани его.

**Если потерял токен:**

- Создай новый ключ (старый автоматически отключится)

---

### 3. Telegram Bot Token и Chat ID

#### Шаг 1: Создай бота

1. Найди в Telegram: **@BotFather**
2. Отправь: `/newbot`
3. Введи имя: `Салон Шарм Bot`
4. Введи username: `sharm_salon_bot` (должен заканчиваться на `_bot`)
5. Скопируй токен

**Формат токена:**

```
1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-1234567
```

#### Шаг 2: Добавь бота в канал

1. Открой свой канал/группу в Telegram
2. **⋮** (три точки) → **Manage Channel**
3. **Administrators** → **Add Administrator**
4. Найди своего бота → Добавь
5. Права: **Post Messages** (Публикация сообщений)

#### Шаг 3: Получи Chat ID

**Способ A: Через @userinfobot**

1. Перешли любое сообщение из канала в @userinfobot
2. Бот пришлёт информацию
3. Скопируй `Id` (будет начинаться с `-100`)

**Способ B: Через API**

1. Отправь тестовое сообщение в свой канал

2. Открой в браузере:
   
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
   
   (Замени `YOUR_BOT_TOKEN` на токен бота)

3. Найди `"chat":{"id":-100XXXXXXXXX}`

**Формат Chat ID:**

- Публичный канал: `@channel_username` или `-100XXXXXXXXX`
- Приватный канал: `-100XXXXXXXXX`
- Группа: `-XXXXXXXXX`

---

## 🔧 Настройка Credentials в N8N

### 1. Google Sheets OAuth2 API

**В N8N:**

1. **Settings** (шестерёнка внизу слева) → **Credentials**
2. **Add Credential** → Найди **Google Sheets OAuth2 API**

**Заполни:**

- **Credential Name:** `Google Sheets OAuth`
- **Client ID:** вставь из Google Console
- **Client Secret:** вставь из Google Console

**Нажми "Sign in with Google":**

1. Откроется окно Google
2. Выбери свой аккаунт (тот, что добавил в Test users)
3. ⚠️ Предупреждение "This app isn't verified"
   - **Advanced** → **Go to AI Content Studio (unsafe)**
4. Разреши доступ к Google Sheets
5. Вернёшься в N8N: "Authentication successful"

**Save**

---

### 2. Telegram API

**В N8N:**

1. **Add Credential** → **Telegram API**
2. **Access Token:** вставь токен бота
3. **Save**

---

## 🛠️ Создание Workflow

### Шаг 1: Создай новый Workflow

1. **Workflows** → **Add workflow**
2. Имя: `Auto Publish to VK and Telegram`
3. **Save**

---

### Нода 1: Schedule Trigger

**Назначение:** Запуск workflow каждый час

1. Добавь **Schedule Trigger** на холст
2. **Trigger Interval:** `Hours`
3. **Hours Between Triggers:** `1`
4. **Test step** → должна сработать ✅

---

### Нода 2: Google Sheets (Get row(s))

**Назначение:** Читает посты со статусом Ready

1. Добавь **Google Sheets**
2. **Credential:** выбери `Google Sheets OAuth`
3. **Resource:** `Sheet`
4. **Operation:** `Get row(s)`
5. **Document:** выбери свою таблицу из списка
6. **Sheet:** `Content_Plan`

**Filters (фильтры):**

1. Нажми **Add Filter**
2. **Column:** `Status`
3. **Operator:** `=` (равно)
4. **Value:** `Ready`

**Test step** → должны загрузиться посты со статусом Ready

---

### Нода 3: Code (Filter by Time)

**Назначение:** Оставляет только посты, где время публикации ≤ сейчас

1. Добавь **Code**
2. **Mode:** `Run Once for All Items`
3. **JavaScript:**

```javascript
const now = new Date();
const readyItems = [];

// Проходим по всем постам
for (const item of $input.all()) {
  try {
    // Парсим дату публикации
    const publishTime = new Date(item.json.Publish_Time);

    // Если время пришло (с запасом 1 час)
    if (publishTime <= now) {
      readyItems.push(item);
    }
  } catch (error) {
    console.log(`Error parsing date for item ${item.json.ID}:`, error);
  }
}

// Если нет постов готовых к публикации
if (readyItems.length === 0) {
  console.log('No posts ready for publication at this time');
  return [];
}

console.log(`Found ${readyItems.length} post(s) ready for publication`);
return readyItems;
```

4. Соедини с Google Sheets
5. **Test step**

---

### Нода 4: Loop Over Items

**Назначение:** Обрабатывает посты по одному в цикле

1. Добавь **Loop Over Items**
2. **Batch Size:** `1`
3. Соедини с Code (Filter by Time)

**Важно:** У Loop Over Items два выхода:

- **loop** — основной, идёт на следующую ноду (Telegram)
- **done** — не используется, оставь пустым

---

### Нода 5: Telegram (Send Message)

**Назначение:** Публикация текста в Telegram

1. Добавь **Telegram**
2. **Credential:** выбери Telegram API
3. **Resource:** `Message`
4. **Operation:** `Send Message`

**Настройки:**

- **Chat ID:** вставь свой Chat ID (например: `-100123456789`)

- **Text:** 
  
  ```
  {{ $json.TG_Text }}
  ```
5. Соедини с **Loop Over Items** (выход `loop`)
6. **Test step** → должно отправиться сообщение в Telegram!

---

### Нода 6: HTTP Request (VK - Post to Wall)

**Назначение:** Публикация текста в VK

1. Добавь **HTTP Request**
2. **Method:** `POST`
3. **URL:** `https://api.vk.com/method/wall.post`

**Authentication:** `None` (параметры передаём через Query)

**Send Query Parameters:** включи (зелёный переключатель)

**Query Parameters (нажми "Add Parameter" 4 раза):**

**Параметр 1:**

- **Name:** `access_token`
- **Value:** `ВАШ_VK_TOKEN` (вставь токен из VK)

**Параметр 2:**

- **Name:** `v`
- **Value:** `5.131`

**Параметр 3:**

- **Name:** `owner_id`
- **Value:** `-123456789` (твой ID группы **С МИНУСОМ!**)

**Параметр 4:**

- **Name:** `message`

- **Value:** 
  
  ```
  {{ $json.VK_Text }}
  ```
4. Соедини с Telegram
5. **Test step** → должен появиться пост в VK!

---

### Нода 7: Google Sheets (Update row)

**Назначение:** Обновляет статус на Published

1. Добавь **Google Sheets**
2. **Credential:** `Google Sheets OAuth`
3. **Resource:** `Sheet`
4. **Operation:** `Update row`

**Настройки:**

- **Document:** твоя таблица

- **Sheet:** `Content_Plan`

- **Column to Match On:** `ID`

- **Value to Match On:** 
  
  ```
  {{ $json.ID }}
  ```

**Values to Update:**

1. Нажми **Add Field to Update**

2. **Column:** `Status`

3. **Value:** `Published`

4. Соедини с HTTP Request (VK)

5. **Test step** → статус должен измениться на Published!

---

### Нода 8: Merge (Loop Continue)

**Назначение:** Возвращает управление в Loop для обработки следующего поста

1. Добавь **Merge**
2. **Mode:** `Append`
3. **Input 1:** соедини с Google Sheets (Update row)
4. **Output:** соедини обратно с **Loop Over Items** (на вход)

---

## 🔗 **Итоговая схема подключения:**

```
Schedule Trigger
    ↓
Google Sheets (Get row(s))
    ↓
Code (Filter by Time)
    ↓
Loop Over Items
    │
    ├─ loop ──→ Telegram (Send Message)
    │               ↓
    │           HTTP Request (VK - Post to Wall)
    │               ↓
    │           Google Sheets (Update row)
    │               ↓
    │           Merge ───┐
    │                    │
    └─ done (пусто)      │
                         │
Loop Over Items ←────────┘
(возврат для следующего поста)
```

**Важно:**

- От **Loop Over Items** используй выход **`loop`** (не `done`)
- **Merge** замыкает цикл обратно на вход Loop Over Items

---

## 🧪 Тестирование

### Тест 1: Один пост вручную

**Подготовка:**

1. В Google Sheets создай тестовый пост:
   - **Status:** `Ready`
   - **Publish_Time:** текущее время минус 10 минут
   - **VK_Text:** `Тестовый пост для VK`
   - **TG_Text:** `Тестовый пост для Telegram`

**Выполнение:**

1. В N8N нажми **Execute Workflow** (справа вверху)
2. Следи за выполнением каждой ноды (они станут зелёными ✅)

**Проверка:**

- ✅ Пост появился в Telegram
- ✅ Пост появился в VK
- ✅ Status в Google Sheets = `Published`

---

### Тест 2: Два поста (проверка цикла)

**Подготовка:**

1. Создай **2 поста** со статусом Ready
2. Оба с временем публикации в прошлом

**Выполнение:**

1. **Execute Workflow**
2. Workflow должен обработать оба поста по очереди

**Проверка:**

- ✅ Оба поста опубликованы в VK
- ✅ Оба поста опубликованы в Telegram
- ✅ Оба Status = Published

---

### Тест 3: Автоматический запуск

**Подготовка:**

1. **Activate workflow** (переключатель вверху справа)
2. Создай пост с временем публикации **+1 час** от сейчас

**Выполнение:**

1. Подожди 1 час
2. Workflow должен запуститься автоматически (по Schedule Trigger)

**Проверка:**

- ✅ Пост опубликован автоматически
- ✅ В **Executions** (история) есть успешный запуск

---

## 🚀 Запуск в продакшн

### Активация Workflow

1. **Переключатель "Active"** (вверху справа) → включи (зелёный)
2. Workflow теперь работает 24/7
3. Проверяет посты каждый час

### Мониторинг

**В N8N:**

- **Executions** (слева) → история запусков
- Зелёный ✅ — успешно
- Красный ❌ — ошибка
- Серый — пропущено (нет постов)

**В Google Sheets:**

- Проверяй колонку Status
- Ready → Published означает успешную публикацию

### Уведомления об ошибках (опционально)

**Добавь Error Workflow:**

1. В настройках workflow → **Error Trigger**

2. Добавь Telegram ноду

3. Отправляй себе уведомление:
   
   ```
   ❌ Ошибка автопубликации!
   
   Пост ID: {{ $json.ID }}
   Ошибка: {{ $json.error?.message }}
   Время: {{ $now }}
   ```

---

## 🐛 Решение проблем

### Ошибка: "This app isn't verified" (Google OAuth)

**Причина:** Приложение не прошло верификацию Google

**Решение:**

1. Это нормально для локального использования
2. Нажми **Advanced** → **Go to AI Content Studio (unsafe)**
3. Разреши доступ

---

### Ошибка: "Invalid access_token" (VK)

**Причины и решения:**

**1. Неправильный токен:**

- Проверь что скопировал полностью
- Токен должен начинаться с `vk1.a.`

**2. Токен не сообщества:**

- Нужен токен **сообщества**, а не пользователя
- Создай в **Управление → Работа с API**

**3. Недостаточно прав:**

- Токен должен иметь право **"Управление"**
- Пересоздай токен с правильными правами

---

### Ошибка: "Permission to perform this action is denied" (VK)

**Причина:** Неправильный owner_id

**Решение:**

- Owner_id должен быть **С МИНУСОМ**: `-123456789`
- Для публикации от имени группы всегда минус!

---

### Ошибка: "Chat not found" (Telegram)

**Причины и решения:**

**1. Неправильный Chat ID:**

- Для приватных каналов: `-100XXXXXXXXX`
- Для публичных: `@channel_username` или `-100XXXXXXXXX`

**2. Бот не добавлен в канал:**

- Добавь бота как администратора
- Права: **Post Messages**

**3. Бот не активирован:**

- Отправь боту `/start` в личные сообщения

---

### Ошибка: "Permission denied" (Google Sheets)

**Решение:**

1. Проверь что таблица расшарена на твой Gmail
2. Gmail должен совпадать с Test users
3. Переавторизуйся: удали credential → создай заново

---

### Workflow не запускается по расписанию

**Решение:**

**1. Проверь активацию:**

- Переключатель **Active** должен быть зелёным

**2. Проверь Schedule Trigger:**

- Интервал установлен правильно (1 hour)

**3. Проверь часовой пояс:**

- Docker Compose: `TZ=Europe/Moscow`
- Перезапусти контейнер

**4. Проверь логи:**

```bash
docker logs n8n
```

---

### Посты дублируются

**Причина:** Workflow запустился дважды до обновления статуса

**Решение:**

**1. Увеличь интервал:**

- Schedule Trigger → 2 hours вместо 1

**2. Добавь блокировку:**

```javascript
// В начале Code (Filter by Time)
const lastRun = await this.helpers.getWorkflowStaticData('global');
const now = Date.now();

// Блокировка на 30 минут
if (lastRun.timestamp && (now - lastRun.timestamp) < 1800000) {
  console.log('Workflow ran recently, skipping');
  return [];
}

lastRun.timestamp = now;
```

---

## 📊 Полезные команды Docker

### Просмотр логов N8N:

```bash
docker logs n8n -f
```

### Перезапуск N8N:

```bash
docker-compose -f docker-compose-n8n.yml restart
```

### Остановка N8N:

```bash
docker-compose -f docker-compose-n8n.yml down
```

### Запуск N8N:

```bash
docker-compose -f docker-compose-n8n.yml up -d
```

### Обновление N8N:

```bash
docker-compose -f docker-compose-n8n.yml pull
docker-compose -f docker-compose-n8n.yml up -d
```

---

## ✅ Финальный чеклист

- [ ] N8N установлен и запущен (Docker Compose)
- [ ] Google OAuth Client ID создан
- [ ] Test users добавлен (свой Gmail)
- [ ] VK токен получен (с правом "Управление")
- [ ] VK Group ID определён (с минусом для owner_id)
- [ ] Telegram бот создан
- [ ] Telegram бот добавлен в канал как админ
- [ ] Telegram Chat ID получен
- [ ] Google Sheets OAuth настроен в N8N
- [ ] Telegram API настроен в N8N
- [ ] Все 8 нод созданы и соединены правильно
- [ ] Тестовый пост успешно опубликован
- [ ] Цикл работает (проверено на 2 постах)
- [ ] Workflow активирован
- [ ] Автозапуск по расписанию работает

---

## 🎯 Итоговая структура Workflow

**8 нод:**

1. ✅ Schedule Trigger (каждый час)
2. ✅ Google Sheets - Get row(s) (Status = Ready)
3. ✅ Code - Filter by Time
4. ✅ Loop Over Items (Batch Size = 1)
5. ✅ Telegram - Send Message
6. ✅ HTTP Request - VK Post to Wall
7. ✅ Google Sheets - Update row (Status → Published)
8. ✅ Merge (возврат в Loop)

**Поток данных:**

```
Trigger → Sheets → Filter → Loop → Telegram → VK → Update → Merge → Loop
                             ↑                                      ↓
                             └──────────────────────────────────────┘
```

---

**Автопубликация настроена и работает! 🎉**

Теперь AI Content Studio полностью автоматизирован:

1. ✅ Создание постов через Streamlit
2. ✅ Планирование в Google Sheets
3. ✅ Автоматическая публикация через N8N


