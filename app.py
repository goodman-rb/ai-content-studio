import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timedelta
import httpx
import json
import time
import plotly.express as px

# --- НАСТРОЙКИ ---
SHEET_ID = "11POL8ft8ETDnI-Qhvdw0qSeP8OnPjVx55gzya1dTtEU"
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]
APPOINTMENT_URL = "https://salon1c.ru/widget-org/812445871"
MAX_REGENERATIONS = 3

# --- ИНИЦИАЛИЗАЦИЯ ---
st.set_page_config(layout="wide", page_title="🤖 AI-Контент Студия", page_icon="🤖")


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

@st.cache_resource
def get_credentials():
    """Получение credentials для Google API"""
    try:
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        return creds
    except FileNotFoundError:
        st.error("❌ Файл 'credentials.json' не найден.")
        st.stop()
    except Exception as e:
        st.error(f"❌ Ошибка при загрузке credentials: {e}")
        st.stop()


@st.cache_resource
def get_gspread_client():
    """Подключение к Google Sheets"""
    creds = get_credentials()
    return gspread.authorize(creds)


@st.cache_data(ttl=300)
def load_data_from_sheets(_client):
    """Загрузка данных из Google Sheets"""
    try:
        spreadsheet = _client.open_by_key(SHEET_ID)

        services_df = pd.DataFrame(spreadsheet.worksheet("Services").get_all_records())

        try:
            discounts_df = pd.DataFrame(spreadsheet.worksheet("Discounts").get_all_records())
        except gspread.WorksheetNotFound:
            discounts_df = pd.DataFrame(columns=['Name_for_UI', 'Description_for_AI', 'Applicable_Category'])

        try:
            general_info = {row['Key']: row['Value']
                            for row in spreadsheet.worksheet("General_Info").get_all_records()}
        except gspread.WorksheetNotFound:
            general_info = {
                'Tone_of_Voice': 'Профессионально и дружелюбно',
                'Blacklist_Words': '',
                'Address': 'Москва'
            }

        return services_df, discounts_df, general_info
    except Exception as e:
        st.error(f"❌ Ошибка при загрузке данных: {e}")
        st.stop()


@st.cache_data(ttl=300)
def load_prompts(_client):
    """Загрузка промптов из Google Sheets"""
    try:
        spreadsheet = _client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet("Prompts")
        data = worksheet.get_all_records()

        if not data:
            return pd.DataFrame(columns=['Prompt_ID', 'Prompt_Name', 'Prompt_Text', 'Active'])

        df = pd.DataFrame(data)
        return df
    except gspread.WorksheetNotFound:
        st.warning("⚠️ Лист 'Prompts' не найден. Создайте его для настройки промптов.")
        return pd.DataFrame(columns=['Prompt_ID', 'Prompt_Name', 'Prompt_Text', 'Active'])
    except Exception as e:
        st.error(f"❌ Ошибка загрузки промптов: {e}")
        return pd.DataFrame(columns=['Prompt_ID', 'Prompt_Name', 'Prompt_Text', 'Active'])


@st.cache_data(ttl=60)
def load_content_plan(_client):
    """Загрузка контент-плана"""
    try:
        spreadsheet = _client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet("Content_Plan")
        data = worksheet.get_all_records()

        if not data:
            return pd.DataFrame(
                columns=['ID', 'Publish_Time', 'Status', 'Post_Type', 'VK_Text', 'TG_Text', 'Image_Prompt',
                         'Created_At'])

        df = pd.DataFrame(data)
        return df
    except Exception as e:
        st.error(f"❌ Ошибка загрузки контент-плана: {e}")
        return pd.DataFrame()


def ensure_content_plan_sheet(client):
    """Проверка наличия листа Content_Plan"""
    try:
        spreadsheet = client.open_by_key(SHEET_ID)
        try:
            worksheet = spreadsheet.worksheet("Content_Plan")
            headers = worksheet.row_values(1)
            if not headers or len(headers) < 8:
                st.warning(
                    "⚠️ Проверьте структуру листа Content_Plan. Должны быть столбцы: ID, Publish_Time, Status, Post_Type, VK_Text, TG_Text, Image_Prompt, Created_At")
        except gspread.WorksheetNotFound:
            st.info("📋 Создаю лист Content_Plan...")
            worksheet = spreadsheet.add_worksheet(title="Content_Plan", rows="100", cols="8")
            worksheet.append_row([
                "ID", "Publish_Time", "Status", "Post_Type",
                "VK_Text", "TG_Text", "Image_Prompt", "Created_At"
            ])
            st.success("✅ Лист Content_Plan создан!")
    except Exception as e:
        st.error(f"❌ Ошибка при проверке Content_Plan: {e}")


def ensure_prompts_sheet(client):
    """Проверка наличия листа Prompts"""
    try:
        spreadsheet = client.open_by_key(SHEET_ID)
        try:
            worksheet = spreadsheet.worksheet("Prompts")
            headers = worksheet.row_values(1)
            if not headers or len(headers) < 4:
                st.warning("⚠️ Проверьте структуру листа Prompts")
        except gspread.WorksheetNotFound:
            st.info("📋 Создаю лист Prompts...")
            worksheet = spreadsheet.add_worksheet(title="Prompts", rows="50", cols="4")
            worksheet.append_row(["Prompt_ID", "Prompt_Name", "Prompt_Text", "Active"])

            # Добавляем промпты по умолчанию
            default_prompts = [
                ["system_base", "Системный промпт",
                 "Ты — SMM-маркетолог для элитной клиники косметологии 'Шарм'.\n\nTone-of-Voice: {tone_of_voice}\nАдрес: {address}\nЗапрещенные слова: {blacklist_words}\nЦелевая аудитория: {age} лет\n\nТвоя задача — написать тексты для поста в VK и Telegram.\n\nВАЖНО: ВСЕГДА заканчивай посты призывом к действию и ссылкой для записи: {appointment_url}\n\nВерни ответ ТОЛЬКО в формате JSON:\n{{\n  \"vk_post\": \"Подробный текст для VK с эмодзи и призывом к действию\",\n  \"tg_post\": \"Короткий емкий текст для Telegram с призывом\",\n  \"image_prompt\": \"Детальный промпт для генерации изображения на русском языке (максимум 500 символов, фотореалистичный стиль, без текста на изображении)\"\n}}",
                 "TRUE"],

                ["promo_post", "Рекламный пост",
                 "Задача: Рекламный пост\n\nУслуга: {service_name}\nОписание: {service_description}\nОборудование: {service_equipment}\nКлючевые слова: {service_keywords}\nАкция: {discount_text}\n{promo_code}\n\nСгенерируй тексты и промпт для изображения (косметология, процедура, атмосфера салона).",
                 "TRUE"],

                ["educational_post", "Познавательный пост",
                 "Задача: Познавательный пост\n\nТема: {theme}\n\nВажно: Сделай пост интересным для аудитории {age} лет.\nВ конце мягко пригласи на консультацию и добавь ссылку.\n\nДля image_prompt создай описание изображения связанного с темой (например: красивая кожа, косметология, натуральная красота, wellness, SPA-атмосфера).",
                 "TRUE"],

                ["analysis_prompt", "Анализ поста",
                 "Ты — эксперт по SMM для салонов красоты и косметологии.\nПроанализируй созданный пост и дай конкретные советы по улучшению.\n\nОцени по критериям (оценка от 1 до 10):\n1. headline_score - Привлекательность заголовка/первого предложения\n2. cta_score - Ясность и сила призыва к действию\n3. emotion_score - Эмоциональная вовлеченность\n4. emoji_score - Использование эмодзи (оптимально = 8-9, слишком много = 3-5)\n5. length_score - Оптимальность длины текста\n\nДай 3-4 КОНКРЕТНЫХ совета как улучшить пост.\nСоветы должны быть практичными и применимыми.\n\nВерни ответ ТОЛЬКО в формате JSON:\n{{\n  \"scores\": {{\n    \"headline\": 8,\n    \"cta\": 9,\n    \"emotion\": 7,\n    \"emoji\": 8,\n    \"length\": 9\n  }},\n  \"overall_score\": 8.2,\n  \"suggestions\": [\n    \"Конкретный совет 1\",\n    \"Конкретный совет 2\",\n    \"Конкретный совет 3\"\n  ],\n  \"summary\": \"Краткая общая оценка поста (1-2 предложения)\"\n}}",
                 "TRUE"],

                ["improvement_prompt", "Улучшение поста",
                 "ВАЖНО: Перепиши тексты постов с учетом следующих рекомендаций:\n\n{suggestions}\n\nСохрани общую структуру и ключевые элементы (промокод, призыв к действию, ссылку), но улучши тексты согласно советам выше.",
                 "TRUE"]
            ]

            for prompt in default_prompts:
                worksheet.append_row(prompt)

            st.success("✅ Лист Prompts создан с промптами по умолчанию!")
    except Exception as e:
        st.error(f"❌ Ошибка при проверке Prompts: {e}")


# Инициализация клиентов
client = get_gspread_client()
services_df, discounts_df, general_info = load_data_from_sheets(client)
ensure_content_plan_sheet(client)
ensure_prompts_sheet(client)

# Инициализация DeepSeek клиента
try:
    deepseek_client = httpx.Client(
        base_url="https://api.deepseek.com",
        headers={"Authorization": f"Bearer {st.secrets['DEEPSEEK_API_KEY']}"},
        timeout=60
    )
except KeyError as e:
    st.error(f"❌ Секрет не найден: {e}. Проверьте .streamlit/secrets.toml")
    st.stop()


# --- ФУНКЦИИ ГЕНЕРАЦИИ ---

def replace_variables(template, variables):
    """Замена переменных в промпте"""
    result = template
    for key, value in variables.items():
        placeholder = f"{{{key}}}"
        result = result.replace(placeholder, str(value))
    return result


def get_prompt_by_id(prompts_df, prompt_id):
    """Получение промпта по ID"""
    prompt_row = prompts_df[(prompts_df['Prompt_ID'] == prompt_id) & (prompts_df['Active'] == 'TRUE')]
    if prompt_row.empty:
        return None
    return prompt_row.iloc[0]['Prompt_Text']


def build_prompt(post_type, age, promo_code, service_info, discount_info, theme, prompts_df):
    """Сборка промпта для DeepSeek с использованием шаблонов из Sheets"""

    # Базовые переменные
    variables = {
        'tone_of_voice': general_info.get('Tone_of_Voice', 'Профессионально и дружелюбно'),
        'address': general_info.get('Address', 'Москва'),
        'blacklist_words': general_info.get('Blacklist_Words', ''),
        'age': age,
        'appointment_url': APPOINTMENT_URL,
        'promo_code': '',
        'service_name': '',
        'service_description': '',
        'service_equipment': '',
        'service_keywords': '',
        'discount_text': '',
        'theme': ''
    }

    # Обработка промокода
    if promo_code:
        variables[
            'promo_code'] = f"КРИТИЧЕСКИ ВАЖНО ПРО ПРОМОКОД:\n- В тексте ОБЯЗАТЕЛЬНО должен быть промокод: {promo_code}\n- Для VK: \"Используйте промокод {promo_code} при записи для получения скидки!\"\n- Для TG: \"💎 Промокод: {promo_code}\"\n- Промокод должен быть выделен и заметен в тексте"

    # Получаем системный промпт
    system_prompt_template = get_prompt_by_id(prompts_df, 'system_base')
    if not system_prompt_template:
        st.error("❌ Не найден системный промпт (system_base)")
        return None, None

    system_prompt = replace_variables(system_prompt_template, variables)

    # Получаем user промпт в зависимости от типа поста
    if post_type == "Рекламный":
        user_prompt_template = get_prompt_by_id(prompts_df, 'promo_post')
        if not user_prompt_template:
            st.error("❌ Не найден промпт для рекламного поста")
            return None, None

        # Заполняем переменные для рекламного поста
        variables['service_name'] = service_info['Name'] if service_info is not None else ''
        variables['service_description'] = service_info['Description_for_AI'] if service_info is not None else ''
        variables['service_equipment'] = service_info['Equipment_Used'] if service_info is not None else ''
        variables['service_keywords'] = service_info['Keywords_for_AI'] if service_info is not None else ''

        if discount_info is not None and discount_info['Name_for_UI'] != '(Нет акции)':
            variables['discount_text'] = discount_info['Description_for_AI']
        else:
            variables['discount_text'] = 'Нет акции'

        if not promo_code:
            variables['promo_code'] = "Промокода нет, не упоминай его"

    else:  # Познавательный
        user_prompt_template = get_prompt_by_id(prompts_df, 'educational_post')
        if not user_prompt_template:
            st.error("❌ Не найден промпт для познавательного поста")
            return None, None

        variables['theme'] = theme if theme else 'косметология и уход за кожей'

    user_prompt = replace_variables(user_prompt_template, variables)

    return system_prompt, user_prompt


def generate_text_content(system_prompt, user_prompt):
    """Генерация текста через DeepSeek"""
    try:
        response = deepseek_client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()
        content_json = response.json()['choices'][0]['message']['content']
        return json.loads(content_json)
    except Exception as e:
        st.error(f"❌ Ошибка DeepSeek: {e}")
        return None


def analyze_post(vk_text, tg_text, post_type, prompts_df):
    """Анализ поста через DeepSeek"""
    try:
        analysis_prompt_template = get_prompt_by_id(prompts_df, 'analysis_prompt')
        if not analysis_prompt_template:
            st.error("❌ Не найден промпт для анализа")
            return None

        analysis_prompt = f"""{analysis_prompt_template}

Тип поста: {post_type}

VK текст:
{vk_text}

Telegram текст:
{tg_text}
"""

        response = deepseek_client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": analysis_prompt}
                ],
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()

        analysis_json = response.json()['choices'][0]['message']['content']
        return json.loads(analysis_json)

    except Exception as e:
        st.error(f"❌ Ошибка анализа поста: {e}")
        return None


def improve_post_with_suggestions(vk_text, tg_text, suggestions, post_type, form_data, prompts_df):
    """Улучшение поста с учетом рекомендаций AI"""
    try:
        suggestions_text = "\n".join([f"- {s}" for s in suggestions])

        service_info_dict = form_data.get('service_info')
        service_info_obj = pd.Series(service_info_dict) if service_info_dict else None
        discount_info_dict = form_data.get('discount_info')
        discount_info_obj = pd.Series(discount_info_dict) if discount_info_dict else None

        # Базовый промпт
        system_prompt, user_prompt = build_prompt(
            form_data['Post_Type'],
            form_data['age'],
            form_data['promo_code'],
            service_info_obj,
            discount_info_obj,
            form_data['theme'],
            prompts_df
        )

        # Получаем промпт для улучшения
        improvement_template = get_prompt_by_id(prompts_df, 'improvement_prompt')
        if not improvement_template:
            st.error("❌ Не найден промпт для улучшения")
            return None

        improvement_instructions = replace_variables(improvement_template, {'suggestions': suggestions_text})

        improvement_instructions += f"""

Текущий VK пост:
{vk_text}

Текущий Telegram пост:
{tg_text}
"""

        user_prompt_improved = user_prompt + "\n\n" + improvement_instructions

        response = deepseek_client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt_improved}
                ],
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()

        improved_json = response.json()['choices'][0]['message']['content']
        return json.loads(improved_json)

    except Exception as e:
        st.error(f"❌ Ошибка улучшения поста: {e}")
        return None


# --- СТРАНИЦЫ ПРИЛОЖЕНИЯ ---

def page_create_post():
    """Страница создания поста"""
    st.title("🎨 Создать пост")

    # Загружаем промпты
    prompts_df = load_prompts(client)

    # Инициализация session state
    if 'generated_data' not in st.session_state:
        st.session_state.generated_data = None
    if 'form_data' not in st.session_state:
        st.session_state.form_data = {}
    if 'regeneration_count' not in st.session_state:
        st.session_state.regeneration_count = 0
    if 'analysis_result' not in st.session_state:
        st.session_state.analysis_result = None

    st.header("1️⃣ Настройка генерации")

    post_type = st.radio(
        "Тип поста:",
        ["Рекламный", "Познавательный"],
        horizontal=True,
        key="post_type_radio"
    )

    with st.form("generation_form"):
        col1, col2 = st.columns(2)

        with col1:
            if st.session_state.post_type_radio == "Рекламный":
                service_names = services_df['Name'].tolist()
                selected_service_name = st.selectbox("Выберите услугу:", service_names)
                service_info = services_df[services_df['Name'] == selected_service_name].iloc[0]
                theme_input = None
            else:
                selected_service_name = None
                service_info = None
                theme_input = st.text_input("Введите тему:", "Мифы о гиалуроновой кислоте")

            promo_code = st.text_input("Промокод (если есть):", placeholder="BEAUTY20", key="promo_code_input")

        with col2:
            if st.session_state.post_type_radio == "Рекламный" and service_info is not None:
                if not discounts_df.empty:
                    applicable_discounts = discounts_df[
                        (discounts_df['Applicable_Category'] == service_info['Category']) |
                        (discounts_df['Applicable_Category'] == '*')
                        ].copy()

                    discount_names = ['(Нет акции)'] + applicable_discounts['Name_for_UI'].tolist()
                else:
                    discount_names = ['(Нет акции)']

                selected_discount_name = st.selectbox(
                    "Выберите акцию:",
                    discount_names,
                    index=discount_names.index("(Нет акции)") if "(Нет акции)" in discount_names else 0
                )
                discount_info = applicable_discounts[
                    applicable_discounts['Name_for_UI'] == selected_discount_name
                    ].iloc[0] if selected_discount_name != '(Нет акции)' else None
            else:
                discount_info = None

            age_options = ["18-25", "25-40", "40+", "Все"]

            if st.session_state.post_type_radio == "Рекламный" and service_info is not None:
                default_age = service_info.get('Default_Age', 'Все')
                default_age = default_age if default_age in age_options else "Все"
            else:
                default_age = "Все"

            selected_age = st.selectbox(
                "Целевая аудитория:",
                age_options,
                index=age_options.index(default_age)
            )

        st.subheader("2️⃣ Изображение (опционально)")
        col_img1, col_img2 = st.columns(2)

        with col_img1:
            custom_image_url = st.text_input(
                "URL своей картинки:",
                placeholder="https://example.com/image.jpg",
                key="custom_image_url_input",
                help="Если нужно использовать готовое изображение"
            )

        with col_img2:
            custom_image_prompt = st.text_input(
                "Или свой промпт для картинки:",
                placeholder="Элегантный салон красоты, мягкое освещение...",
                key="custom_image_prompt_input",
                help="Будет использован вместо автоматически сгенерированного"
            )

        submit_button = st.form_submit_button("✨ Сгенерировать контент", width='stretch')

    # Обработка генерации
    if submit_button:
        post_type = st.session_state.post_type_radio
        theme = theme_input if post_type == "Познавательный" else None
        promo_code = st.session_state.promo_code_input

        st.session_state.form_data = {
            "Post_Type": post_type,
            "service_info": service_info.to_dict() if service_info is not None else None,
            "discount_info": discount_info.to_dict() if discount_info is not None else None,
            "theme": theme,
            "age": selected_age,
            "promo_code": promo_code,
            "custom_image_url": custom_image_url,
            "custom_image_prompt": custom_image_prompt
        }
        st.session_state.regeneration_count = 0

        with st.spinner("🎨 DeepSeek пишет тексты..."):
            system_prompt, user_prompt = build_prompt(
                post_type, selected_age, promo_code, service_info, discount_info, theme, prompts_df
            )

            if system_prompt and user_prompt:
                content_data = generate_text_content(system_prompt, user_prompt)

                if content_data:
                    # Применяем кастомные настройки изображения
                    if custom_image_url:
                        content_data['image_prompt'] = f"[URL картинки: {custom_image_url}]"
                    elif custom_image_prompt:
                        content_data['image_prompt'] = custom_image_prompt

                    st.session_state.generated_data = content_data
                    st.success("✅ Контент сгенерирован! Проверьте и сохраните ниже.")

    # Блок предпросмотра и регенерации
    if st.session_state.generated_data:
        st.header("3️⃣ Проверка и Регенерация")

        # Счетчик попыток
        col_counter, col_button = st.columns([1, 2])
        with col_counter:
            st.metric("Попыток регенерации", f"{st.session_state.regeneration_count}/{MAX_REGENERATIONS}")

        with col_button:
            can_regenerate = st.session_state.regeneration_count < MAX_REGENERATIONS

            if st.button("🔄 Регенерировать текст", disabled=not can_regenerate, width='stretch'):
                st.session_state.regeneration_count += 1
                form_data = st.session_state.form_data

                with st.spinner("🎨 Регенерирую тексты..."):
                    service_info_dict = form_data.get('service_info')
                    service_info_obj = pd.Series(service_info_dict) if service_info_dict else None
                    discount_info_dict = form_data.get('discount_info')
                    discount_info_obj = pd.Series(discount_info_dict) if discount_info_dict else None

                    system_prompt, user_prompt = build_prompt(
                        form_data['Post_Type'],
                        form_data['age'],
                        form_data['promo_code'],
                        service_info_obj,
                        discount_info_obj,
                        form_data['theme'],
                        prompts_df
                    )
                    new_content = generate_text_content(system_prompt, user_prompt)

                    if new_content:
                        # Сохраняем кастомные настройки изображения
                        if form_data.get('custom_image_url'):
                            new_content['image_prompt'] = f"[URL картинки: {form_data['custom_image_url']}]"
                        elif form_data.get('custom_image_prompt'):
                            new_content['image_prompt'] = form_data['custom_image_prompt']

                        st.session_state.generated_data = new_content
                        st.success("✅ Тексты обновлены!")
                        st.rerun()

        if not can_regenerate:
            st.warning(
                f"⚠️ Достигнут лимит попыток регенерации ({MAX_REGENERATIONS}). Создайте новый пост для новых попыток.")

        # НОВОЕ: Блок AI-советов
        st.divider()
        st.subheader("💡 AI-советы по улучшению")

        if st.button("🔍 Проанализировать пост", width='stretch'):
            with st.spinner("🤖 AI анализирует пост..."):
                data = st.session_state.generated_data
                analysis = analyze_post(
                    data.get('vk_post', ''),
                    data.get('tg_post', ''),
                    st.session_state.form_data.get('Post_Type', ''),
                    prompts_df
                )

                if analysis:
                    st.session_state.analysis_result = analysis
                    st.rerun()

        # Показываем результаты анализа если они есть
        if st.session_state.analysis_result:
            analysis = st.session_state.analysis_result

            # Общая оценка
            st.markdown(f"### 📊 Общая оценка: **{analysis['overall_score']}/10**")
            st.info(analysis.get('summary', ''))

            # Детальные оценки
            st.markdown("#### 📈 Детальные оценки:")
            scores = analysis['scores']

            col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)

            with col_s1:
                score_val = scores.get('headline', 0)
                st.metric("Заголовок", f"{score_val}/10")

            with col_s2:
                score_val = scores.get('cta', 0)
                st.metric("Призыв", f"{score_val}/10")

            with col_s3:
                score_val = scores.get('emotion', 0)
                st.metric("Эмоции", f"{score_val}/10")

            with col_s4:
                score_val = scores.get('emoji', 0)
                st.metric("Эмодзи", f"{score_val}/10")

            with col_s5:
                score_val = scores.get('length', 0)
                st.metric("Длина", f"{score_val}/10")

            # Редактируемые рекомендации
            st.markdown("#### 💡 Рекомендации по улучшению:")
            st.caption("✏️ Отредактируйте список ниже - уберите ненужные советы или добавьте свои")

            suggestions = analysis.get('suggestions', [])
            suggestions_text = "\n".join([f"- {s}" for s in suggestions])

            edited_suggestions = st.text_area(
                "Рекомендации (каждая с новой строки, начинается с '- '):",
                value=suggestions_text,
                height=150,
                key="edited_suggestions",
                help="Вы можете редактировать, удалять или добавлять рекомендации. Каждая должна начинаться с '- '"
            )

            # Кнопка применить улучшения - ПОСЛЕ рекомендаций
            st.divider()
            if st.button("✨ Применить улучшения", width='stretch', type="primary"):
                # Парсим отредактированные рекомендации
                edited_suggestions_list = [
                    line.strip().lstrip('- ').strip()
                    for line in edited_suggestions.split('\n')
                    if line.strip() and line.strip().startswith('-')
                ]

                if not edited_suggestions_list:
                    st.warning("⚠️ Добавьте хотя бы одну рекомендацию для улучшения")
                else:
                    with st.spinner("🎨 Улучшаю пост с учётом рекомендаций..."):
                        data = st.session_state.generated_data
                        improved_content = improve_post_with_suggestions(
                            data.get('vk_post', ''),
                            data.get('tg_post', ''),
                            edited_suggestions_list,
                            st.session_state.form_data.get('Post_Type', ''),
                            st.session_state.form_data,
                            prompts_df
                        )

                        if improved_content:
                            # Сохраняем кастомные настройки изображения
                            form_data = st.session_state.form_data
                            if form_data.get('custom_image_url'):
                                improved_content['image_prompt'] = f"[URL картинки: {form_data['custom_image_url']}]"
                            elif form_data.get('custom_image_prompt'):
                                improved_content['image_prompt'] = form_data['custom_image_prompt']

                            st.session_state.generated_data = improved_content
                            st.session_state.analysis_result = None  # Очищаем анализ
                            st.success("✅ Пост улучшен!")
                            st.rerun()

        st.divider()

        # Блок предпросмотра и планирования
        st.header("4️⃣ Планирование публикации")

        with st.form("planning_form"):
            col_date, col_time = st.columns(2)
            with col_date:
                publish_date = st.date_input("Дата публикации", value=datetime.now().date())
            with col_time:
                publish_time = st.time_input("Время публикации", value=datetime.now().time())

            st.divider()
            st.subheader("Предпросмотр контента")

            data = st.session_state.generated_data

            col_vk, col_tg = st.columns(2)
            with col_vk:
                st.subheader("📱 VK")
                vk_text_edited = st.text_area(
                    "Текст для VK:",
                    value=data.get('vk_post', ''),
                    height=250,
                    label_visibility="collapsed"
                )

            with col_tg:
                st.subheader("✈️ Telegram")
                tg_text_edited = st.text_area(
                    "Текст для Telegram:",
                    value=data.get('tg_post', ''),
                    height=250,
                    label_visibility="collapsed"
                )

            st.subheader("🎨 Промпт для изображения")
            image_prompt_edited = st.text_area(
                "Промпт:",
                value=data.get('image_prompt', ''),
                height=100,
                help="Этот промпт будет сохранён в таблицу и может использоваться для генерации изображения"
            )

            save_button = st.form_submit_button(
                "✅ Запланировать пост (Сохранить в Google Sheets)",
                width='stretch'
            )

        if save_button:
            try:
                with st.spinner("💾 Сохраняю в Google Sheets..."):
                    spreadsheet = client.open_by_key(SHEET_ID)
                    content_plan_sheet = spreadsheet.worksheet("Content_Plan")
                    form_data = st.session_state.form_data

                    # Генерация уникального ID
                    existing_ids = content_plan_sheet.col_values(1)[1:]
                    max_num = 0
                    for id_str in existing_ids:
                        if id_str.startswith('POST_'):
                            try:
                                num = int(id_str.split('_')[1])
                                max_num = max(max_num, num)
                            except:
                                pass

                    new_id = f"POST_{max_num + 1}"

                    publish_datetime = f"{publish_date} {publish_time}"

                    row_to_add = [
                        new_id,
                        publish_datetime,
                        "Ready",
                        form_data.get("Post_Type"),
                        vk_text_edited,
                        tg_text_edited,
                        image_prompt_edited,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ]

                    content_plan_sheet.append_row(row_to_add, value_input_option='USER_ENTERED')
                    load_content_plan.clear()

                    st.success(f"🎉 Пост {new_id} успешно запланирован на {publish_datetime}!")
                    st.balloons()

                    st.session_state.generated_data = None
                    st.session_state.form_data = {}
                    st.session_state.regeneration_count = 0
                    st.session_state.analysis_result = None

                    time.sleep(2)
                    st.rerun()

            except Exception as e:
                st.error(f"❌ Не удалось сохранить пост: {e}")


def page_dashboard():
    """Страница Dashboard со статистикой"""
    st.title("📊 Dashboard")

    df = load_content_plan(client)

    if df.empty:
        st.info("🔭 Контент-план пуст. Создайте первый пост!")
        return

    # Статистика
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Всего постов", len(df))

    with col2:
        ready_count = len(df[df['Status'] == 'Ready'])
        st.metric("Запланировано", ready_count)

    with col3:
        published_count = len(df[df['Status'] == 'Published'])
        st.metric("Опубликовано", published_count)

    with col4:
        promo_count = len(df[df['Post_Type'] == 'Рекламный'])
        st.metric("Рекламных", promo_count)

    st.divider()

    # Графики
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.subheader("📊 Типы постов")
        type_counts = df['Post_Type'].value_counts()
        fig_pie = px.pie(
            values=type_counts.values,
            names=type_counts.index,
            color_discrete_sequence=['#FF6B6B', '#4ECDC4']
        )
        st.plotly_chart(fig_pie, use_container_width=True, config={'displayModeBar': False})

    with col_chart2:
        st.subheader("📈 Статусы постов")
        status_counts = df['Status'].value_counts()
        fig_bar = px.bar(
            x=status_counts.index,
            y=status_counts.values,
            color=status_counts.index,
            color_discrete_sequence=['#95E1D3', '#F38181']
        )
        fig_bar.update_layout(showlegend=False, xaxis_title="", yaxis_title="Количество")
        st.plotly_chart(fig_bar, use_container_width=True, config={'displayModeBar': False})

    st.divider()

    # Ближайшие публикации
    st.subheader("📅 Ближайшие публикации (7 дней)")

    try:
        df['Publish_DateTime'] = pd.to_datetime(df['Publish_Time'], format='mixed', errors='coerce')
        # Отладка: выводим проблемные строки
        invalid_dates = df[df['Publish_DateTime'].isna()]['Publish_Time']
        if not invalid_dates.empty:
            st.sidebar.warning(f"⚠️ Не удалось распарсить даты: {invalid_dates.tolist()}")
        today = datetime.now()
        week_later = today + timedelta(days=7)

        # Убираем NaT (Not a Time) значения
        df_valid = df.dropna(subset=['Publish_DateTime'])

        upcoming = df_valid[
            (df_valid['Publish_DateTime'] >= today) &
            (df_valid['Publish_DateTime'] <= week_later) &
            (df_valid['Status'] == 'Ready')
            ].sort_values('Publish_DateTime')


        if upcoming.empty:
            st.info("🔭 Нет запланированных публикаций на ближайшие 7 дней")
        else:
            for _, row in upcoming.iterrows():
                col_time, col_type, col_preview = st.columns([1, 1, 3])

                with col_time:
                    st.write(f"🕐 **{row['Publish_DateTime'].strftime('%d.%m %H:%M')}**")

                with col_type:
                    post_type_emoji = "🎯" if row['Post_Type'] == 'Рекламный' else "📚"
                    st.write(f"{post_type_emoji} {row['Post_Type']}")

                with col_preview:
                    preview_text = row['VK_Text'][:100] + "..." if len(row['VK_Text']) > 100 else row['VK_Text']
                    st.write(preview_text)

                st.divider()

    except Exception as e:
        st.error(f"❌ Ошибка отображения ближайших публикаций: {e}")


def page_content_plan():
    """Страница контент-плана с редактированием и удалением"""
    st.title("📅 Контент-план")

    df = load_content_plan(client)

    if df.empty:
        st.info("🔭 Контент-план пуст. Создайте первый пост!")
        return

    # Фильтры
    col_filter1, col_filter2, col_filter3 = st.columns(3)

    with col_filter1:
        status_filter = st.selectbox(
            "Статус:",
            ["Все"] + list(df['Status'].unique()),
            key="status_filter"
        )

    with col_filter2:
        type_filter = st.selectbox(
            "Тип поста:",
            ["Все"] + list(df['Post_Type'].unique()),
            key="type_filter"
        )

    with col_filter3:
        sort_order = st.selectbox(
            "Сортировка:",
            ["По дате (новые)", "По дате (старые)"],
            key="sort_order"
        )

    # Применение фильтров
    filtered_df = df.copy()

    if status_filter != "Все":
        filtered_df = filtered_df[filtered_df['Status'] == status_filter]

    if type_filter != "Все":
        filtered_df = filtered_df[filtered_df['Post_Type'] == type_filter]

    # Сортировка
    try:
        filtered_df['Publish_DateTime'] = pd.to_datetime(filtered_df['Publish_Time'])
        ascending = sort_order == "По дате (старые)"
        filtered_df = filtered_df.sort_values('Publish_DateTime', ascending=ascending)
    except:
        pass

    st.divider()

    # Отображение постов
    if filtered_df.empty:
        st.info("🔍 Посты не найдены по заданным фильтрам")
        return

    for list_idx, (idx, row) in enumerate(filtered_df.iterrows()):
        with st.container():
            col_info, col_actions = st.columns([4, 1])

            with col_info:
                post_type_emoji = "🎯" if row['Post_Type'] == 'Рекламный' else "📚"
                status_emoji = "✅" if row['Status'] == 'Ready' else "🚀" if row['Status'] == 'Published' else "📝"

                st.markdown(f"### {status_emoji} {post_type_emoji} {row['Post_Type']} | {row['Publish_Time']}")
                st.caption(f"ID: {row['ID']}")

                with st.expander("📱 Посмотреть тексты"):
                    col_vk, col_tg = st.columns(2)
                    with col_vk:
                        st.markdown("**VK:**")
                        st.write(row['VK_Text'])
                    with col_tg:
                        st.markdown("**Telegram:**")
                        st.write(row['TG_Text'])

                    if row.get('Image_Prompt'):
                        st.markdown("**🎨 Промпт для изображения:**")
                        st.info(row['Image_Prompt'])

            with col_actions:
                if st.button("✏️ Редактировать", key=f"edit_{row['ID']}_{list_idx}"):
                    st.session_state.editing_post = row.to_dict()
                    st.rerun()

                if st.button("🗑️ Удалить", key=f"delete_{row['ID']}_{list_idx}"):
                    st.session_state.deleting_post = row['ID']
                    st.rerun()

            st.divider()

    # Диалог редактирования
    if 'editing_post' in st.session_state:
        edit_post_dialog(st.session_state.editing_post)

    # Диалог удаления
    if 'deleting_post' in st.session_state:
        delete_post_dialog(st.session_state.deleting_post)


def edit_post_dialog(post_data):
    """Диалог редактирования поста"""
    st.subheader(f"✏️ Редактирование поста {post_data['ID']}")

    with st.form("edit_post_form"):
        new_publish_time = st.text_input("Дата и время публикации:", value=post_data['Publish_Time'])
        new_status = st.selectbox("Статус:", ["Ready", "Published", "Draft"],
                                  index=["Ready", "Published", "Draft"].index(post_data['Status']) if post_data[
                                                                                                          'Status'] in [
                                                                                                          "Ready",
                                                                                                          "Published",
                                                                                                          "Draft"] else 0)
        new_vk_text = st.text_area("Текст VK:", value=post_data['VK_Text'], height=200)
        new_tg_text = st.text_area("Текст Telegram:", value=post_data['TG_Text'], height=200)
        new_image_prompt = st.text_area("Промпт для изображения:", value=post_data.get('Image_Prompt', ''), height=100)

        col_save, col_cancel = st.columns(2)

        with col_save:
            save_button = st.form_submit_button("💾 Сохранить изменения", width='stretch')

        with col_cancel:
            cancel_button = st.form_submit_button("❌ Отмена", width='stretch')

    if save_button:
        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            worksheet = spreadsheet.worksheet("Content_Plan")

            all_ids = worksheet.col_values(1)
            row_index = all_ids.index(post_data['ID']) + 1

            current_created_at = post_data.get('Created_At', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            updated_row = [
                post_data['ID'],
                new_publish_time,
                new_status,
                post_data['Post_Type'],
                new_vk_text,
                new_tg_text,
                new_image_prompt,
                current_created_at
            ]

            worksheet.update(f'A{row_index}:H{row_index}', [updated_row])
            load_content_plan.clear()

            st.success("✅ Пост обновлен!")
            del st.session_state.editing_post
            time.sleep(1)
            st.rerun()

        except Exception as e:
            st.error(f"❌ Ошибка обновления: {e}")

    if cancel_button:
        del st.session_state.editing_post
        st.rerun()


def delete_post_dialog(post_id):
    """Диалог подтверждения удаления"""
    st.warning(f"⚠️ Вы уверены, что хотите удалить пост {post_id}?")

    col_confirm, col_cancel = st.columns(2)

    with col_confirm:
        if st.button("🗑️ Да, удалить", key="confirm_delete"):
            try:
                spreadsheet = client.open_by_key(SHEET_ID)
                worksheet = spreadsheet.worksheet("Content_Plan")

                all_ids = worksheet.col_values(1)
                row_index = all_ids.index(post_id) + 1
                worksheet.delete_rows(row_index)
                load_content_plan.clear()

                st.success("✅ Пост удален!")
                del st.session_state.deleting_post
                time.sleep(1)
                st.rerun()

            except Exception as e:
                st.error(f"❌ Ошибка удаления: {e}")

    with col_cancel:
        if st.button("❌ Отмена", key="cancel_delete"):
            del st.session_state.deleting_post
            st.rerun()


def page_archive():
    """Страница архива/истории постов"""
    st.title("📜 Архив постов")

    load_content_plan.clear()  # Очищаем кэш
    df = load_content_plan(client)

    if df.empty:
        st.info("🔭 Архив пуст")
        return

    # Фильтры
    st.subheader("🔍 Фильтры")
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)

    with col_f1:
        try:
            df['Publish_DateTime'] = pd.to_datetime(df['Publish_Time'], errors='coerce')
            min_date = df['Publish_DateTime'].min().date()
            max_date = df['Publish_DateTime'].max().date()
        except:
            min_date = datetime.now().date() - timedelta(days=30)
            max_date = datetime.now().date()

        date_from = st.date_input("От:", value=min_date, key="archive_date_from")

    with col_f2:
        date_to = st.date_input("До:", value=max_date, key="archive_date_to")

    with col_f3:
        type_filter = st.selectbox(
            "Тип поста:",
            ["Все"] + list(df['Post_Type'].unique()),
            key="archive_type_filter"
        )

    with col_f4:
        status_filter = st.selectbox(
            "Статус:",
            ["Все"] + list(df['Status'].unique()),
            key="archive_status_filter"
        )

    # Применение фильтров
    filtered_df = df.copy()

    try:
        filtered_df['Publish_DateTime'] = pd.to_datetime(filtered_df['Publish_Time'], format='mixed', errors='coerce')
        filtered_df = filtered_df[
            (filtered_df['Publish_DateTime'].dt.date >= date_from) &
            (filtered_df['Publish_DateTime'].dt.date <= date_to)
            ]
    except:
        pass

    if type_filter != "Все":
        filtered_df = filtered_df[filtered_df['Post_Type'] == type_filter]

    if status_filter != "Все":
        filtered_df = filtered_df[filtered_df['Status'] == status_filter]

    st.divider()

    # Статистика по отфильтрованным данным
    if not filtered_df.empty:
        st.subheader("📊 Статистика за период")

        col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)

        with col_stat1:
            st.metric("Всего постов", len(filtered_df))

        with col_stat2:
            published = len(filtered_df[filtered_df['Status'] == 'Published'])
            st.metric("Опубликовано", published)

        with col_stat3:
            promo_posts = len(filtered_df[filtered_df['Post_Type'] == 'Рекламный'])
            st.metric("Рекламных", promo_posts)

        with col_stat4:
            edu_posts = len(filtered_df[filtered_df['Post_Type'] == 'Познавательный'])
            st.metric("Познавательных", edu_posts)

        st.divider()

    # Отображение постов
    if filtered_df.empty:
        st.info("🔍 Посты не найдены по заданным фильтрам")
        return

    st.subheader(f"📋 Найдено постов: {len(filtered_df)}")

    # Сортировка по дате (новые первые)
    try:
        filtered_df = filtered_df.sort_values('Publish_DateTime', ascending=False)
    except:
        pass

    # Отображение постов
    for list_idx, (idx, row) in enumerate(filtered_df.iterrows()):
        with st.expander(
                f"{row.get('Publish_Time', 'Нет даты')} | {row['Post_Type']} | {row['Status']}",
                expanded=False
        ):
            col_info, col_preview = st.columns([1, 2])

            with col_info:
                st.markdown(f"**ID:** {row['ID']}")
                st.markdown(f"**Тип:** {row['Post_Type']}")
                st.markdown(f"**Статус:** {row['Status']}")
                st.markdown(f"**Создан:** {row.get('Created_At', 'Н/Д')}")

            with col_preview:
                st.markdown("##### 📱 VK")
                st.text_area(
                    "VK текст",
                    value=row['VK_Text'],
                    height=150,
                    disabled=True,
                    key=f"archive_vk_{row['ID']}_{list_idx}",
                    label_visibility="collapsed"
                )

                st.markdown("##### ✈️ Telegram")
                st.text_area(
                    "TG текст",
                    value=row['TG_Text'],
                    height=150,
                    disabled=True,
                    key=f"archive_tg_{row['ID']}_{list_idx}",
                    label_visibility="collapsed"
                )

                if row.get('Image_Prompt'):
                    st.markdown("##### 🎨 Промпт для изображения")
                    st.info(row['Image_Prompt'])


def page_settings():
    """Страница настроек: редактор промптов + General Info"""
    st.title("⚙️ Настройки")

    tab1, tab2 = st.tabs(["📝 Промпты", "🎯 Общие настройки"])

    # Вкладка 1: Редактор промптов
    with tab1:
        st.subheader("Редактор промптов для AI")
        st.caption(
            "Настройте промпты для генерации контента. Используйте переменные для динамической подстановки данных.")

        prompts_df = load_prompts(client)

        if prompts_df.empty:
            st.warning("⚠️ Не удалось загрузить промпты. Проверьте лист 'Prompts' в Google Sheets.")
            return

        # Показываем доступные переменные
        with st.expander("📌 Доступные переменные для промптов"):
            st.markdown("""
            - `{tone_of_voice}` - Тон общения (из General_Info)
            - `{address}` - Адрес салона
            - `{blacklist_words}` - Запрещенные слова
            - `{age}` - Целевая аудитория
            - `{appointment_url}` - Ссылка на запись
            - `{promo_code}` - Промокод (если указан)
            - `{service_name}` - Название услуги
            - `{service_description}` - Описание услуги
            - `{service_equipment}` - Используемое оборудование
            - `{service_keywords}` - Ключевые слова услуги
            - `{discount_text}` - Описание акции
            - `{theme}` - Тема для познавательного поста
            - `{suggestions}` - Рекомендации AI (для improvement_prompt)
            """)

        st.divider()

        # Выбор промпта для редактирования
        active_prompts = prompts_df[prompts_df['Active'] == 'TRUE']

        if active_prompts.empty:
            st.info("ℹ️ Нет активных промптов для редактирования")
            return

        prompt_names = active_prompts['Prompt_Name'].tolist()
        prompt_ids = active_prompts['Prompt_ID'].tolist()

        selected_prompt_name = st.selectbox(
            "Выберите промпт для редактирования:",
            prompt_names,
            key="selected_prompt_for_edit"
        )

        selected_idx = prompt_names.index(selected_prompt_name)
        selected_prompt_id = prompt_ids[selected_idx]
        selected_prompt_row = active_prompts[active_prompts['Prompt_ID'] == selected_prompt_id].iloc[0]

        st.markdown(f"**ID:** `{selected_prompt_id}`")

        with st.form("edit_prompt_form"):
            new_prompt_text = st.text_area(
                "Текст промпта:",
                value=selected_prompt_row['Prompt_Text'],
                height=400,
                help="Используйте переменные в фигурных скобках, например: {service_name}"
            )

            col_save, col_reset = st.columns(2)

            with col_save:
                save_prompt_button = st.form_submit_button("💾 Сохранить изменения", width='stretch')

            with col_reset:
                reset_button = st.form_submit_button("🔄 Сбросить к исходному", width='stretch',
                                                     help="Восстановит промпт по умолчанию (если возможно)")

        if save_prompt_button:
            try:
                spreadsheet = client.open_by_key(SHEET_ID)
                worksheet = spreadsheet.worksheet("Prompts")

                # Находим строку по Prompt_ID
                all_ids = worksheet.col_values(1)
                row_index = all_ids.index(selected_prompt_id) + 1

                # Обновляем только Prompt_Text (колонка C)
                worksheet.update(f'C{row_index}', [[new_prompt_text]])

                load_prompts.clear()

                st.success(f"✅ Промпт '{selected_prompt_name}' успешно обновлен!")
                time.sleep(1)
                st.rerun()

            except Exception as e:
                st.error(f"❌ Ошибка сохранения промпта: {e}")

        if reset_button:
            st.info("ℹ️ Функция сброса к исходному промпту будет доступна в следующей версии")

    # Вкладка 2: Общие настройки
    with tab2:
        st.subheader("Общие настройки салона")
        st.caption("Эти параметры используются при генерации контента")

        try:
            spreadsheet = client.open_by_key(SHEET_ID)
            general_info_sheet = spreadsheet.worksheet("General_Info")
            general_info_data = general_info_sheet.get_all_records()

            # Преобразуем в словарь для удобства
            current_settings = {row['Key']: row['Value'] for row in general_info_data}

        except Exception as e:
            st.error(f"❌ Ошибка загрузки настроек: {e}")
            return

        with st.form("general_settings_form"):
            tone_of_voice = st.text_area(
                "Tone of Voice (стиль общения):",
                value=current_settings.get('Tone_of_Voice', 'Профессионально и дружелюбно'),
                height=100,
                help="Определяет стиль и тон общения в постах"
            )

            address = st.text_input(
                "Адрес салона:",
                value=current_settings.get('Address', 'Москва'),
                help="Будет использоваться в постах при необходимости"
            )

            blacklist_words = st.text_area(
                "Запрещенные слова (через запятую):",
                value=current_settings.get('Blacklist_Words', ''),
                height=100,
                help="Слова, которые AI должен избегать в текстах"
            )

            save_settings_button = st.form_submit_button("💾 Сохранить настройки", width='stretch')

        if save_settings_button:
            try:
                # Обновляем каждую настройку
                settings_to_update = {
                    'Tone_of_Voice': tone_of_voice,
                    'Address': address,
                    'Blacklist_Words': blacklist_words
                }

                all_keys = general_info_sheet.col_values(1)

                for key, value in settings_to_update.items():
                    if key in all_keys:
                        row_index = all_keys.index(key) + 1
                        general_info_sheet.update(f'B{row_index}', [[value]])
                    else:
                        # Если ключа нет, добавляем новую строку
                        general_info_sheet.append_row([key, value])

                load_data_from_sheets.clear()

                st.success("✅ Настройки успешно сохранены!")
                time.sleep(1)
                st.rerun()

            except Exception as e:
                st.error(f"❌ Ошибка сохранения настроек: {e}")

        st.divider()

        # Показываем превью Services и Discounts (read-only)
        st.subheader("📋 Справочники (только просмотр)")

        col_services, col_discounts = st.columns(2)

        with col_services:
            st.markdown("**Услуги:**")
            services_preview = services_df[['Name', 'Category']].head(10) if not services_df.empty else pd.DataFrame()
            st.dataframe(services_preview, width='stretch', hide_index=True)
            if len(services_df) > 10:
                st.caption(f"Показано 10 из {len(services_df)} услуг")

        with col_discounts:
            st.markdown("**Акции:**")
            discounts_preview = discounts_df[['Name_for_UI', 'Applicable_Category']].head(
                10) if not discounts_df.empty else pd.DataFrame()
            st.dataframe(discounts_preview, width='stretch', hide_index=True)
            if len(discounts_df) > 10:
                st.caption(f"Показано 10 из {len(discounts_df)} акций")

        st.info("💡 Для редактирования услуг и акций используйте Google Sheets напрямую")


# --- ГЛАВНОЕ МЕНЮ НАВИГАЦИИ ---

st.sidebar.title("🤖 AI-Контент Студия")
st.sidebar.markdown("### Салон красоты Шарм")
st.sidebar.divider()

page = st.sidebar.radio(
    "Навигация:",
    ["🎨 Создать пост", "📊 Dashboard", "📅 Контент-план", "📜 Архив", "⚙️ Настройки"],
    label_visibility="collapsed"
)

st.sidebar.divider()
st.sidebar.caption("v2.3 | DeepSeek + Prompts Editor")
st.sidebar.caption(
    "🔗 [Открыть Google Sheets](https://docs.google.com/spreadsheets/d/11POL8ft8ETDnI-Qhvdw0qSeP8OnPjVx55gzya1dTtEU)")

st.sidebar.divider()
# Добавим много пустых строк или прозрачных div'ов, чтобы "отжать" текст вниз
for _ in range(20):  # подберите число под ваш контент
    st.sidebar.write("")

st.sidebar.markdown(
    """
    <div style='color: blue; font-size: 14px;'>
        Разработано<br>
        Студия 'AI Bolit'
    </div>
    """,
    unsafe_allow_html=True
)

# Роутинг страниц
if page == "🎨 Создать пост":
    page_create_post()
elif page == "📊 Dashboard":
    page_dashboard()
elif page == "📅 Контент-план":
    page_content_plan()
elif page == "📜 Архив":
    page_archive()
elif page == "⚙️ Настройки":
    page_settings()