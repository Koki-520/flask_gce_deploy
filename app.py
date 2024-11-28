# app.py

from flask import Flask, request, jsonify
import os
import pandas as pd
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
from dotenv import load_dotenv
import uuid

# 既存のスクリプトのインポート
from form_automator import (
    verify_columns, load_input_mappings, save_input_mapping,
    extract_form_data, generate_form_input, handle_recaptcha,
    fill_form, click_submit_button, check_submission_status,
    check_form_submission_success, add_result, summarize_results,
    save_results_to_json, save_results_to_csv, detect_captcha,
    scroll_into_view, fill_input_field, find_and_click_submit,
    submit_contact_form, find_contact_info, process_company
)

app = Flask(__name__)

# ログの設定
logging.basicConfig(
    filename="app.log",
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 環境変数の読み込み
load_dotenv()

# OpenAI APIキーの設定
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OpenAI APIキーが設定されていません。")

# Anticaptcha APIキーの設定
anticaptcha_api_key = os.getenv("ANTICAPTCHA_API_KEY")
if not anticaptcha_api_key:
    raise ValueError("Anticaptcha APIキーが設定されていません。")

# ユーザーIDの設定
USER_ID = os.getenv("USER_ID")
if not USER_ID:
    raise ValueError("ユーザーIDが設定されていません。")


@app.route('/submit_forms', methods=['POST'])
def submit_forms():
    """
    CSVファイルをアップロードし、フォーム送信を実行するエンドポイント。
    """
    if 'file' not in request.files:
        return jsonify({"error": "CSVファイルがアップロードされていません。"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "選択されたファイルがありません。"}), 400

    if not file.filename.endswith('.csv'):
        return jsonify({"error": "CSVファイルのみがサポートされています。"}), 400

    try:
        df = pd.read_csv(file)
    except Exception as e:
        return jsonify({"error": f"CSVファイルの読み込みに失敗しました: {str(e)}"}), 400

    # 必要なカラムが存在するか確認
    required_columns = ['企業名', '住所', 'サイトURL', 'お問い合わせ内容']
    if not verify_columns(df, required_columns):
        return jsonify({"error": "必要なカラムが不足しています。CSVファイルを確認してください。"}), 400

    input_mapping_csv_path = 'input_mapping.csv'

    # 既存のマッピング情報をロード
    existing_mappings = load_input_mappings(input_mapping_csv_path)
    logging.info(f"既存のマッピング情報が {len(existing_mappings)} 企業からロードされました。")

    # 並列処理の設定
    max_workers = min(4, os.cpu_count() or 1)
    logging.info(f"並列処理のワーカー数: {max_workers}")

    results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                process_company,
                row,
                existing_mappings,
                input_mapping_csv_path,
                anticaptcha_api_key
            )
            for index, row in df.iterrows()
        ]

        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logging.error(f"並列処理中にエラーが発生しました: {e}")
                results.append({
                    "日時": time.strftime("%Y/%m/%d %H:%M", time.localtime()),
                    "お問い合わせURL": "N/A",
                    "入力項目": "",
                    "入力した内容": "",
                    "status": "error",
                    "status_message": f"並列処理中にエラーが発生しました: {e}",
                    "check_message": ""
                })

    # 結果の集計
    summary = summarize_results(results)

    # 結果の保存
    save_results_to_json(results)
    save_results_to_csv(results)

    return jsonify({
        "summary": summary,
        "details": results
    }), 200


@app.route('/')
def index():
    return "Flask API for Form Submission. Use /submit_forms to submit CSV files."


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
