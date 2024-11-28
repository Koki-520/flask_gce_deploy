# form_automator.py

import os
import csv
import json
import re
import time
import random
import logging
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from seleniumwire import webdriver  # Selenium Wireを使用
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    ElementNotInteractableException,
)
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import openai
from dotenv import load_dotenv
from python_anticaptcha import (
    AnticaptchaClient,
    NoCaptchaTaskProxylessTask,
    AnticaptchaException,
)
from selenium.webdriver.chrome.options import Options
from fake_useragent import UserAgent
from openai import OpenAI
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial

# -----------------------------
# 1. 環境設定
# -----------------------------

# 環境変数の読み込み（.envファイルを使用する場合）
load_dotenv()

# OpenAI APIキーの設定
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError(
        "OpenAI APIキーが設定されていません。環境変数 'OPENAI_API_KEY' を設定してください。"
    )

openai.api_key = openai_api_key

# Anticaptcha APIキーの設定
anticaptcha_api_key = os.getenv("ANTICAPTCHA_API_KEY")
if not anticaptcha_api_key:
    raise ValueError(
        "Anticaptcha APIキーが設定されていません。環境変数 'ANTICAPTCHA_API_KEY' を設定してください。"
    )

# ユーザーIDの設定（固定）
USER_ID = os.getenv("USER_ID")
if not USER_ID:
    raise ValueError(
        "ユーザーIDが設定されていません。環境変数 'USER_ID' を設定してください。"
    )

# -----------------------------
# 2. ログの設定
# -----------------------------

logging.basicConfig(
    filename="form_automator.log",
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# -----------------------------
# 3. フィールドのキーワードと選択肢
# -----------------------------

# フィールドのキーワード
FIELD_KEYWORDS = {
    "first_name": ["名", "First Name", "Given Name", "ファーストネーム", "first_name", "firstName"],
    "last_name": ["姓", "Last Name", "Family Name", "ラストネーム", "last_name", "lastName"],
    "email": ["メールアドレス", "Email", "Your Email", "email"],
    "inquiry_content": ["お問い合わせ本文", "Inquiry Content", "Content", "ご用件", "demand", "message"],
    "inquiry_type": ["お問い合わせの種類", "Inquiry Type", "Type of Inquiry", "ご質問の種類", "departmentId", "subject"]
}

# お問い合わせの種類の選択肢（必要に応じて拡張可能）
INQUIRY_TYPES = [
    "製品について", "サービスについて", "パートナーシップ", "その他",
    "About Product", "About Service", "Partnership", "Other",
    "カスタマーサポート", "Technical Support", "Billing", "Feedback",
    "広報・取材に関するお問い合せ",
    "IRに関するお問い合せ",
    "店舗開発に関するお問い合わせ",
    "採用・労務　人事等に関するお問い合わせ",
    "chocoZAPに関するお問い合わせ"
]

def verify_columns(df, required_columns):
    """
    DataFrameに必要なカラムが存在するかを確認します。

    :param df: pandas DataFrame
    :param required_columns: 必要なカラムのリスト
    :return: すべてのカラムが存在すればTrue、そうでなければFalse
    """
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        print(f"以下の必要なカラムが見つかりません: {missing_columns}")
        return False
    return True

# -----------------------------
# 4. ヘッダーマネージャクラス
# -----------------------------

class HeaderManager:
    def __init__(self):
        """
        ヘッドレスブラウザではない場合のブラウザプロファイル管理。
        """
        self.profiles = [
            # Windows / Chrome（最新）
            {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'browser': 'chrome',
                'version': '120',
                'platform': 'Windows',
                'mobile': False
            },
            # Windows / Chrome（1つ前のバージョン）
            {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'browser': 'chrome',
                'version': '119',
                'platform': 'Windows',
                'mobile': False
            },
            # Windows / Edge
            {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
                'browser': 'edge',
                'version': '120',
                'platform': 'Windows',
                'mobile': False
            },
            # Windows / Firefox
            {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
                'browser': 'firefox',
                'version': '123',
                'platform': 'Windows',
                'mobile': False
            },
            # macOS / Chrome
            {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'browser': 'chrome',
                'version': '120',
                'platform': 'macOS',
                'mobile': False
            },
            # macOS / Safari
            {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
                'browser': 'safari',
                'version': '17',
                'platform': 'macOS',
                'mobile': False
            },
            # macOS / Firefox
            {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0',
                'browser': 'firefox',
                'version': '123',
                'platform': 'macOS',
                'mobile': False
            },
            # Android / Chrome Mobile
            {
                'user_agent': 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                'browser': 'chrome',
                'version': '120',
                'platform': 'Android',
                'mobile': True
            },
            # iOS / Safari Mobile
            {
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
                'browser': 'safari',
                'version': '17',
                'platform': 'iOS',
                'mobile': True
            }
        ]

    def _select_browser_profile(self):
        return random.choice(self.profiles)

    def _generate_headers(self):
        """
        ブラウザプロファイルに基づいてヘッダーを生成
        """
        # 基本ヘッダー（共通）
        headers = {
            'User-Agent': self.browser_profile['user_agent'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

        # Chromium系のヘッダー
        if self.browser_profile['browser'] in ['chrome', 'edge']:
            headers.update({
                'Sec-Ch-Ua': f'"Not A(Brand";v="99", "Google Chrome";v="{self.browser_profile["version"]}"',
                'Sec-Ch-Ua-Mobile': '?1' if self.browser_profile['mobile'] else '?0',
                'Sec-Ch-Ua-Platform': f'"{self.browser_profile["platform"]}"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            })

        # モバイルの場合
        if self.browser_profile['mobile']:
            headers.update({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'  # モバイル向けにシンプル化
            })

        return headers

    def get_headers(self):
        """現在のヘッダーを返す"""
        self.browser_profile = self._select_browser_profile()
        return self._generate_headers()

# -----------------------------
# 5. ステルスドライバー設定クラス
# -----------------------------

class StealthDriver:
    def __init__(self):
        self.options = Options()

    def configure_stealth_settings(self):
        """Bot検知を回避するための各種設定を行う"""
        # ヘッドレスモードの設定
        self.options.add_argument('--headless=new')  # 新しいヘッドレスモード

        # ランダムなUser-Agentの設定
        ua = UserAgent()
        self.options.add_argument(f'user-agent={ua.random}')

        # 自動化の痕跡を隠す
        self.options.add_argument('--disable-blink-features=AutomationControlled')
        self.options.add_experimental_option('excludeSwitches', ['enable-automation'])
        self.options.add_experimental_option('useAutomationExtension', False)

        # 言語設定をランダムに
        languages = ['en-US', 'en-GB', 'ja-JP']
        self.options.add_argument(f'--lang={random.choice(languages)}')

        # その他の一般的なブラウザ設定
        self.options.add_argument('--disable-notifications')  # 通知を無効化
        self.options.add_argument('--disable-dev-shm-usage')  # 共有メモリの使用を無効化
        self.options.add_argument('--no-sandbox')  # サンドボックスを無効化

        # ウィンドウサイズをランダムに設定
        window_sizes = [
            (1366, 768),  # HD
            (1920, 1080),  # Full HD
            (1536, 864),  # HD+
            (1440, 900)   # WXGA+
        ]
        window_size = random.choice(window_sizes)
        self.options.add_argument(f'--window-size={window_size[0]},{window_size[1]}')

        return self.options

    def create_driver(self):
        """設定を適用したWebDriverを作成"""
        options = self.configure_stealth_settings()
        
        # Selenium Manager を使用せず、webdriver_manager を利用して chromedriver をインストール
        service = ChromeService(ChromeDriverManager().install())
        
        # Selenium Wire の WebDriver を使用
        driver = webdriver.Chrome(service=service, options=options)

        # JavaScriptを使用して追加の偽装
        driver.execute_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {
              get: () => [1, 2, 3, 4, 5]
            });
        """)

        return driver

    @staticmethod
    def random_sleep():
        """人間らしい待機時間を設定"""
        # ページ読み込み待機時間（2-5秒）
        base_delay = random.uniform(2, 5)
        # さらにミリ秒単位のノイズを追加
        noise = random.uniform(0, 0.5)
        time.sleep(base_delay + noise)

    @staticmethod
    def random_scroll(driver):
        """人間らしいスクロール動作を実行"""
        total_height = driver.execute_script("return document.body.scrollHeight")
        current_position = 0

        while current_position < total_height:
            # ランダムなスクロール量
            scroll_amount = random.randint(100, 300)
            current_position += scroll_amount

            # スムーズなスクロール
            driver.execute_script(
                f"window.scrollTo({{top: {current_position}, behavior: 'smooth'}})"
            )

            # ランダムな待機（0.5-1.5秒）
            time.sleep(random.uniform(0.5, 1.5))

# -----------------------------
# 6. CSVファイルの読み込み・保存
# -----------------------------

def load_input_mappings(csv_file_path):
    """
    マッピングCSVファイルを読み込み、企業名ごとにマッピング情報を保持する辞書を返します。

    :param csv_file_path: マッピングCSVファイルのパス
    :return: 企業名をキー、フィールドマッピングを値とする辞書
    """
    mappings = {}
    if not os.path.exists(csv_file_path):
        return mappings

    with open(csv_file_path, mode='r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            company_name = row['company-name']  # 'company-name' に変更
            field_info = {
                'company-id': row['company-id'],  # 'company-id' を追加
                'type': row['type'],
                'name': row['name'],  # フィールド名
                'option': row.get('option', ''),
                'value': row['value'],
                'required': row.get('required', '').lower() == 'true',
                'max_length': row.get('max_length', ''),
                'placeholder': row.get('placeholder', '')
            }
            if company_name not in mappings:
                mappings[company_name] = []
            mappings[company_name].append(field_info)
    return mappings

def save_input_mapping(csv_file_path, generate_item, company_id, company_name):
    """
    生成されたマッピング情報をCSVファイルに保存します。企業名ごとに分けて保存します。

    :param csv_file_path: マッピングCSVファイルのパス
    :param generate_item: 生成されたマッピング情報のリスト
    :param company_id: 企業ID
    :param company_name: 企業名
    """
    print('マッピング情報を保存します')
    print(f'渡されたgenerate_item:{generate_item}')
    file_exists = os.path.isfile(csv_file_path)
    with open(csv_file_path, mode='a', encoding='utf-8', newline='') as csvfile:
        # 'id' を最初のフィールドとして追加
        fieldnames = ['id', 'company-name', 'company-id', 'type', 'name', 'option', 'value', 'required', 'max_length', 'placeholder']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        
        for field_info in generate_item:
            print()
            # 各フィールドの情報を取得
            field_type = field_info['type']  # デフォルトは 'text'
            field_name = field_info['name'] 
            option = field_info['option']  # 選択肢があれば取得（未選択オプション）
            value = field_info['value']  # 値を取得
            required = field_info.get('required', False) # 必須かどうか
            max_length = field_info.get('max_length', '') # 最大長
            placeholder = field_info.get('placeholder', '') # プレースホルダー
            
            writer.writerow({
                'id': USER_ID,  # 固定のユーザーIDを設定
                'company-name': company_name,  # 'company-name' に変更
                'company-id': company_id,      # 'company-id' に変更
                'type': field_type,
                'name': field_name,
                'option': option,  # 未選択オプションを格納
                'value': value,
                'required': str(required),  # booleanをstring型に変換
                'max_length': str(max_length) if max_length else '',
                'placeholder': placeholder if placeholder else ''
            })

# -----------------------------
# 7. フォームの要素を抽出
# -----------------------------

def extract_form_data(driver):
    form_data = {}
    form_html = ""

    try:
        # フォーム全体を取得
        form = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "form"))
        )
        form_html = form.get_attribute("outerHTML")

        # BeautifulSoupを使用してフォーム内の要素を解析
        soup = BeautifulSoup(form_html, 'html.parser')

        # テキスト、メール、電話番号入力フィールドの処理
        input_fields = soup.find_all('input', {'type': ['text', 'email', 'tel']})
        for input_field in input_fields:
            name = input_field.get('name')
            input_type = input_field.get('type')
            required = input_field.get('aria-required') == "true"
            max_length = input_field.get('maxlength')
            placeholder = input_field.get('placeholder')

            if name:
                form_data[name] = {
                    "type": input_type,
                    "required": required,
                    "max_length": max_length,
                    "placeholder": placeholder
                }

        # セレクトボックスの処理
        select_elements = soup.find_all('select')
        for select_element in select_elements:
            name = select_element.get('name')
            required = select_element.get('aria-required') == "true"
            options = [option.text.strip() for option in select_element.find_all('option') if option.text.strip()]
            if name:
                form_data[name] = {
                    "type": "select",
                    "required": required,
                    "options": options
                }

        # ラジオボタンの処理
        radio_groups = {}
        radio_buttons = soup.find_all('input', {'type': 'radio'})
        for radio in radio_buttons:
            name = radio.get('name')
            value = radio.get('value')
            required = radio.get('aria-required') == "true"

            if name:
                if name not in radio_groups:
                    radio_groups[name] = {
                        "type": "radio",
                        "required": required,
                        "options": []
                    }
                radio_groups[name]["options"].append(value)
        form_data.update(radio_groups)

        # チェックボックスの処理
        checkboxes = soup.find_all('input', {'type': 'checkbox'})
        for checkbox in checkboxes:
            name = checkbox.get('name')
            value = checkbox.get('value')
            required = checkbox.get('aria-required') == "true"

            # 同意系のチェックボックスを特定
            if name and ('agree' in name.lower() or 'consent' in name.lower() or '同意' in name):
                form_data[name] = {
                    "type": "checkbox",
                    "required": required,
                    "value": value,
                    "purpose": "agreement"
                }
            else:
                form_data[name] = {
                    "type": "checkbox",
                    "required": required,
                    "value": value
                }

        # テキストエリアの処理
        textareas = soup.find_all('textarea')
        for textarea in textareas:
            name = textarea.get('name')
            # CAPTCHA関連のフィールドを特定
            if name and ('captcha' in name.lower() or 'g-recaptcha-response' in name.lower()):
                form_data[name] = {
                    "type": "captcha",
                    "required": True
                }
                continue
            required = textarea.get('aria-required') == "true"
            if name:
                form_data[name] = {
                    "type": "textarea",
                    "required": required
                }

        print("抽出されたフォームデータ:", json.dumps(form_data, indent=2, ensure_ascii=False))
        return form_data, form_html

    except NoSuchElementException:
        print("ページにフォームが見つかりませんでした。")
        # ページの全HTMLを出力
        full_page_html = driver.page_source
        with open("full_page.html", "w", encoding='utf-8') as f:
            f.write(full_page_html)
        print("ページの全HTMLを 'full_page.html' として保存しました。フォームの構造を確認してください。")
        return form_data, form_html
    except TimeoutException:
        print("フォームのロードにタイムアウトしました。")
        return form_data, form_html

# -----------------------------
# 8. 入力データの生成
# -----------------------------

def generate_form_input(form_data, existing_mappings, company_name, inquiry_content=None):
    """
    企業名に基づいてマッピング情報を取得または生成し、フォーム入力データを生成します。

    :param form_data: フォームのフィールドデータ
    :param existing_mappings: 企業名をキーとした既存のマッピング情報
    :param company_name: 現在処理中の企業名
    :param inquiry_content: お問い合わせ内容
    :return: 生成された入力データ、フィールドのソース、生成ステータス、生成アイテム
    """
    generated_input = {}
    field_sources = {}
    generate_item = []
    generate_status = ""
    # g-recaptcha-response フィールドを削除
    if "g-recaptcha-response" in form_data:
        del form_data["g-recaptcha-response"]
        print('g-recaptcha-response フィールドを削除しました。')

    # 既存のマッピングが存在する場合、それを使用
    if company_name in existing_mappings:
        print(f"既存のマッピング情報を企業 '{company_name}' からロードします。")
        for field_info in existing_mappings[company_name]:
            field_name = field_info['name']
            generated_input[field_name] = field_info['value']
            field_sources[field_name] = "CSVからのマッピング"
        generate_status = "input_from_existing_mapping"
        print("既存の入力値:", generated_input)
        # 既存企業の場合、generate_itemを空リストに設定
        return generated_input, field_sources, generate_status, generate_item

    # 既存のマッピングがない場合、新規に生成
    # inquiry_contentが指定されている場合、それを生成入力に追加
    if inquiry_content:
        generated_input['inquiry_content'] = inquiry_content
        field_sources['inquiry_content'] = "CSVからの入力"  # 必要に応じて調整
        print(f"フィールド 'inquiry_content' にCSVからの値を設定しました: {inquiry_content}")

    # AIに必要なデータを全フィールドから生成（inquiry_contentを除外）
    ai_input_needed = {field_name: field_info for field_name, field_info in form_data.items() if field_name != 'inquiry_content'}

    # AIによる入力生成が必要な場合
    if ai_input_needed:
        # プロンプトの構築
        prompt = (
            "あなたは株式会社なんでも屋の営業担当者として、自社のサービスを売り込むためにお問い合わせフォームに情報を入力しています。以下のフォーム情報に基づいて、適切な入力値を生成してください。\n\n"
            + json.dumps(ai_input_needed, indent=2, ensure_ascii=False) +
            "\n\n特に次の点に注意してください:\n"
            "- CAPTCHAフィールドは無視してください。\n"
            "- 同意系のチェックボックスには、適切にチェックを入れてください。\n"
            "- お問い合わせの種類を選択する項目がある場合：\n"
            "  * 'その他' または類似の選択肢があれば、それを選んでください。\n"
            "  * 'その他' がない場合は、最も適切な選択肢を選んでください。サービス検討中、採用、取材関連は避けてください。\n"
            "- お客様について聞かれた場合：\n"
            "  * '導入検討中のお客様' や 'その他' などの選択肢を選んでください。\n"
            "  * 当社サービスをご利用中のお客様、就活生、投資家などの選択肢は避けてください。\n"
            "- 問い合わせ内容には以下をそのまま使用してください：\n"
            f"  『{inquiry_content}』\n"
            "上記のフォーム情報に基づいて、各項目に対する適切な入力値をフラットなJSON形式で提供してください。各キーはフィールド名であり、各値はそのフィールドに入力する文字列です。"
        )

        print("送信するプロンプト:\n", prompt)

        # OpenAI クライアントの初期化
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # 変更しないでください

        try:
            # AIにリクエストを送信
            response = client.chat.completions.create(  # 変更しないでください
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "あなたは株式会社なんでも屋の営業担当者として行動する、有能なAIアシスタントです。自社のサービスを売り込むために、フォームの入力を適切に行うことが求められています。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1000
            )

            answer = response.choices[0].message.content
            print("ChatGPTの応答:\n", answer)

            # 応答からJSONを抽出
            json_match = re.search(r'\{[\s\S]*\}', answer)
            if json_match:
                json_str = json_match.group(0)
                try:
                    ai_generated_input = json.loads(json_str)
                    for field_name, value in ai_generated_input.items():
                        if field_name in generated_input:
                            continue  # 既に設定済みのフィールドはスキップ
                        generated_input[field_name] = value
                        field_type = form_data[field_name]['type']
                        option_selected = value
                        all_options = form_data[field_name].get('options', [])
                        # 未選択オプションを計算
                        not_selected_options = [opt for opt in all_options if opt != option_selected]
                        option = ', '.join(not_selected_options) if not_selected_options else ''
                        required = form_data[field_name].get('required', False)
                        max_length = form_data[field_name].get('max_length')
                        placeholder = form_data[field_name].get('placeholder')

                        generate_item.append({
                            "type": field_type,
                            "name": field_name,
                            "option": option,  # 未選択オプションを格納
                            "value": value,
                            "required": required,
                            "max_length": max_length,
                            "placeholder": placeholder
                        })

                        print(f"フィールド '{field_name}' の値を生成し、CSVに保存しました。 未選択オプション: {option}")
                    generate_status = "all_input_from_ai"
                    print("生成された入力値:", generated_input)
                    return generated_input, field_sources, generate_status, generate_item
                except json.JSONDecodeError:
                    print("エラー: 生成された内容が有効なJSONではありません。")
                    return None, field_sources, "input_generation_failed", None
            else:
                print("エラー: JSONブロックが見つかりませんでした。")
                return None, field_sources, "input_generation_failed", None
        except Exception as e:
            print(f"入力値の生成中にエラーが発生しました: {e}")
            return None, field_sources, "input_generation_failed", None
    else:
        print("生成された入力値:", generated_input)
        # 何も生成していないためNone
        return generated_input, field_sources, "all_fill_from_csv", None

# -----------------------------
# 9. reCAPTCHAの処理
# -----------------------------

def handle_recaptcha(driver, anticaptcha_api_key):
    try:
        # reCAPTCHA hidden inputを探す
        recaptcha_response = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.NAME, 'g-recaptcha-response'))
        )
        
        if recaptcha_response:
            # reCAPTCHA iframeを探す
            try:
                recaptcha_iframe = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[src^="https://www.google.com/recaptcha/api2/anchor"]'))
                )
                
                # ページのURLとサイトキーを取得
                url = driver.current_url
                # サイトキーを取得するためにiframeのsrc属性を解析
                src = recaptcha_iframe.get_attribute('src')
                site_key_match = re.search(r'k=([a-zA-Z0-9_-]+)', src)
                if site_key_match:
                    site_key = site_key_match.group(1)
                else:
                    print("サイトキーを取得できませんでした。")
                    return False, "サイトキーの取得に失敗しました。"

                # AnticaptchaClientを使用してreCAPTCHAを解決
                client = AnticaptchaClient(anticaptcha_api_key)
                task = NoCaptchaTaskProxylessTask(url, site_key)
                job = client.createTask(task)
                job.join()
                solution = job.get_solution_response()
                print("CAPTCHA解決済み:", solution)

                # 解決したCAPTCHAをフォームに挿入
                driver.execute_script(f'document.getElementsByName("g-recaptcha-response")[0].value="{solution}";')
                print("CAPTCHAソリューションをフォームに挿入しました。")
                return True, "reCAPTCHAが解決され、ソリューションが挿入されました。"
            except TimeoutException:
                print("reCAPTCHAの iframe が見つかりませんでした。非表示の可能性があります。")
                return True, "reCAPTCHAの iframe が見つかりませんでした。非表示の可能性があります。"
        else:
            print("reCAPTCHAはありません。")
            return True, "reCAPTCHAはありません。"
    except TimeoutException:
        print("reCAPTCHAはありません。")
        return True, "reCAPTCHAはありません。"
    except AnticaptchaException as e:
        print(f"Anticaptchaエラー: {e}")
        if e.error_code == 'ERROR_ZERO_BALANCE':
            # 資金不足の通知処理をここに追加
            print("Anticaptchaの残高が不足しています。")
        return False, f"Anticaptchaエラー: {e}"
    except Exception as e:
        print(f"reCAPTCHAの確認中にエラーが発生しました: {e}")
        return False, f"reCAPTCHAの確認中にエラーが発生しました: {e}"

# -----------------------------
# 10. フォームに入力
# -----------------------------

def fill_form(driver, form_data, generated_input, field_sources, anticaptcha_api_key):
    try:
        if generated_input:
            for field_name, field_value in generated_input.items():
                if field_name not in form_data:
                    print(f"フィールド '{field_name}' はフォームに存在しません。スキップします。")
                    continue

                field_type = form_data[field_name]['type']

                if field_type in ['text', 'email', 'tel']:
                    try:
                        element = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.NAME, field_name))
                        )
                        element.clear()
                        element.send_keys(field_value)
                        print(f"フィールド '{field_name}' に値を入力しました。 (ソース: {field_sources.get(field_name, '不明')})")
                    except TimeoutException:
                        print(f"フィールド '{field_name}' が見つかりませんでした。")

                elif field_type == 'select':
                    try:
                        select = Select(WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.NAME, field_name))
                        ))
                        select.select_by_visible_text(field_value)
                        print(f"セレクトボックス '{field_name}' に値を選択しました。 (ソース: {field_sources.get(field_name, '不明')})")
                    except TimeoutException:
                        print(f"セレクトボックス '{field_name}' が見つかりませんでした。")

                elif field_type == 'radio':
                    try:
                        radio = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, f"//input[@type='radio'][@name='{field_name}'][@value='{field_value}']"))
                        )
                        radio.click()
                        print(f"ラジオボタン '{field_name}' に値を選択しました。 (ソース: {field_sources.get(field_name, '不明')})")
                    except TimeoutException:
                        print(f"ラジオボタン '{field_name}' の値 '{field_value}' が見つかりませんでした。")

                elif field_type == 'checkbox':
                    try:
                        checkbox = driver.find_element(By.XPATH, f"//input[@type='checkbox'][@name='{field_name}']")
                        if form_data[field_name].get('purpose') == 'agreement':
                            if not checkbox.is_selected():
                                checkbox.click()  # 同意系チェックボックスにチェックを入れる
                                print(f"同意系チェックボックス '{field_name}' を選択しました。 (ソース: {field_sources.get(field_name, '不明')})")
                        else:
                            if isinstance(field_value, bool):
                                if field_value and not checkbox.is_selected():
                                    checkbox.click()
                                    print(f"チェックボックス '{field_name}' を選択しました。 (ソース: {field_sources.get(field_name, '不明')})")
                                elif not field_value and checkbox.is_selected():
                                    checkbox.click()
                                    print(f"チェックボックス '{field_name}' の選択を解除しました。 (ソース: {field_sources.get(field_name, '不明')})")
                            else:
                                # 値が文字列の場合（チェックボックスの値に基づく）
                                if field_value and not checkbox.is_selected():
                                    checkbox.click()
                                    print(f"チェックボックス '{field_name}' を選択しました。 (ソース: {field_sources.get(field_name, '不明')})")
                                elif not field_value and checkbox.is_selected():
                                    checkbox.click()
                                    print(f"チェックボックス '{field_name}' の選択を解除しました。 (ソース: {field_sources.get(field_name, '不明')})")
                    except NoSuchElementException:
                        print(f"チェックボックス '{field_name}' が見つかりませんでした。")

                elif field_type == 'textarea':
                    try:
                        textarea = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.NAME, field_name))
                        )
                        textarea.clear()
                        textarea.send_keys(field_value)
                        print(f"テキストエリア '{field_name}' に値を入力しました。 (ソース: {field_sources.get(field_name, '不明')})")
                    except TimeoutException:
                        print(f"テキストエリア '{field_name}' が見つかりませんでした。")

                elif field_type == 'captcha':
                    # CAPTCHAフィールドは無視します。後でhandle_recaptchaで処理します。
                    print(f"CAPTCHAフィールド '{field_name}' を検出しました。")
                    continue
                
                else:
                    print(f"未対応のフィールドタイプ '{field_type}' です: {field_name}")

        else:
            print("生成された入力データがありません。")
        
        # reCAPTCHAの処理を追加
        captcha_result, captcha_message = handle_recaptcha(driver, anticaptcha_api_key)
        return captcha_result, captcha_message
    except TimeoutError:
        print("タイムアウトしました。")
