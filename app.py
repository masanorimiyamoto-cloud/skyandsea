from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session, current_app
import requests
# import gspread # data_services.py へ移動
import json
import os
import time # time は session['workday'] のデフォルト値生成には直接使われていないが、他の部分で必要なら残す
# from oauth2client.service_account import ServiceAccountCredentials # data_services.py へ移動
from datetime import datetime, date, timedelta
import logging # logging モジュールをインポート

# data_services から必要なものをインポート
from data_services import (
    get_cached_personid_data,
    # get_cached_workcord_data, # API Blueprint で使用
    get_cached_workprocess_data,
    # アプリ起動時にキャッシュをウォームアップしたい場合はロード関数もインポート
    load_personid_data,
    load_workcord_data,
    load_workprocess_data
)

# Blueprints から api_bp をインポート
from blueprints.api import api_bp

app = Flask(__name__)
# 環境変数からSECRET_KEYを読み込む (例: Renderの環境変数で設定)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a_strong_default_secret_key_for_dev_only")


# ===== ロギング設定 =====
# 既存のハンドラをクリア (Flaskがデフォルトで追加するハンドラとの重複や意図しない動作を避けるため)
for handler in app.logger.handlers[:]:
    app.logger.removeHandler(handler)

stream_handler = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(module)s:%(lineno)d]'
)
stream_handler.setFormatter(formatter)
app.logger.addHandler(stream_handler)

if os.environ.get('FLASK_DEBUG') == '1': # 環境変数 FLASK_DEBUG で制御
    app.debug = True
    app.logger.setLevel(logging.DEBUG)
    stream_handler.setLevel(logging.DEBUG)
else:
    app.debug = False
    app.logger.setLevel(logging.INFO)
    stream_handler.setLevel(logging.INFO)

app.logger.info("アプリケーションのロギングが初期化されました。")
app.logger.info(f"FLASK_DEBUG: {os.environ.get('FLASK_DEBUG')}, app.debug: {app.debug}")
# ===== ロギング設定ここまで =====


# ==== Airtable 設定 (送信先用) ====
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID_BookSKY") # 環境変数名を確認してください

if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
    app.logger.critical("Airtableの環境変数 (AIRTABLE_TOKEN, AIRTABLE_BASE_ID_BookSKY) が設定されていません。")
    # ここでアプリケーションを停止させるか、エラーページを表示するなどの処理が必要

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

# Blueprint を登録
app.register_blueprint(api_bp)


# -------------------------------
# Airtable へのデータ送信
def send_record_to_destination(dest_url, workcord, workname, bookname, workoutput, workprocess, unitprice, workday):
    data = {
        "fields": {
            "WorkCord": int(workcord) if workcord else 0, # workcordが空なら0として扱うなど
            "WorkName": str(workname),
            "BookName": str(bookname),
            "WorkOutput": int(workoutput),
            "WorkProcess": str(workprocess),
            "UnitPrice": float(unitprice),
            "WorkDay": workday
        }
    }
    try:
        response = requests.post(dest_url, headers=HEADERS, json=data, timeout=10)
        response.raise_for_status()  # HTTPエラーがあれば例外を発生させる
        resp_json = response.json()
        new_id = resp_json.get("id")
        app.logger.info(f"Airtableへのデータ送信成功: {dest_url}, ID: {new_id}")
        return response.status_code, "✅ Airtable にデータを送信しました！", new_id
    except requests.exceptions.HTTPError as http_err:
        app.logger.error(f"Airtable送信エラー (HTTPError): {http_err.response.status_code} {http_err.response.text} - URL: {dest_url} - Data: {data}")
        return http_err.response.status_code, f"⚠ 送信エラー (HTTP {http_err.response.status_code}): {http_err.response.json().get('error', {}).get('message', '詳細不明')}", None
    except requests.RequestException as e:
        app.logger.error(f"Airtable送信エラー (RequestException): {str(e)} - URL: {dest_url} - Data: {data}", exc_info=True)
        return None, f"⚠ 送信エラー: {str(e)}", None


# ✅ 一覧のデータ取得 (指定された年月のデータを取得するように変更)
def get_selected_month_records(target_year, target_month):
    selected_personid = session.get("selected_personid")
    if not selected_personid:
        app.logger.warning("get_selected_month_records - PersonIDが選択されていません。")
        return []

    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID: # Airtable設定チェック
        app.logger.error("get_selected_month_records - Airtable設定が不完全です。")
        flash("⚠ Airtableの設定が不完全なため、データを取得できません。", "error")
        return []

    try:
        params = {"filterByFormula": f"AND(YEAR({{WorkDay}})={target_year}, MONTH({{WorkDay}})={target_month})"}
        table_name = f"TablePersonID_{selected_personid}"
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_name}"
        
        app.logger.info(f"Airtableからデータを取得開始: URL={url}, Params={params}")
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json().get("records", [])
        app.logger.info(f"Airtableから {len(data)} 件のレコードを取得しました。")

        records_list = [
            {
                "id": record["id"],
                "WorkDay": record["fields"].get("WorkDay", "9999-12-31"),
                "WorkCD": record["fields"].get("WorkCord", "不明"),
                "WorkName": record["fields"].get("WorkName", "不明"),
                "WorkProcess": record["fields"].get("WorkProcess", "不明"),
                "UnitPrice": record["fields"].get("UnitPrice", "不明"), # 文字列として取得される場合も考慮
                "WorkOutput": record["fields"].get("WorkOutput", "0"),
            }
            for record in data
        ]
        records_list.sort(key=lambda x: x["WorkDay"])
        return records_list

    except requests.exceptions.HTTPError as http_err:
        app.logger.error(f"Airtableデータ取得エラー (HTTPError): {http_err.response.status_code} {http_err.response.text} - URL: {url}")
        flash(f"⚠ Airtableからのデータ取得中にエラーが発生しました (HTTP {http_err.response.status_code})。", "error")
        return []
    except requests.RequestException as e:
        app.logger.error(f"Airtableデータ取得エラー (RequestException): {str(e)} - URL: {url}", exc_info=True)
        flash(f"⚠ Airtableからのデータ取得中にエラーが発生しました: {e}", "error")
        return []
    except Exception as e:
        app.logger.error(f"予期せぬエラー (get_selected_month_records): {e}", exc_info=True)
        flash("⚠ データ取得中に予期せぬエラーが発生しました。", "error")
        return []


# ✅ レコードの削除
@app.route("/delete_record/<record_id>", methods=["POST"])
def delete_record(record_id):
    selected_personid = session.get("selected_personid")
    if not selected_personid:
        app.logger.warning("delete_record - PersonIDが選択されていません。")
        flash("❌ PersonIDが選択されていません。操作を続行できません。", "error")
        return redirect(url_for("index")) # indexにリダイレクト、または適切なエラーページへ

    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID: # Airtable設定チェック
        app.logger.error("delete_record - Airtable設定が不完全です。")
        flash("⚠ Airtableの設定が不完全なため、レコードを削除できません。", "error")
        return redirect(url_for("records", year=session.get("current_display_year"), month=session.get("current_display_month")))


    try:
        table_name = f"TablePersonID_{selected_personid}"
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_name}/{record_id}"
        app.logger.info(f"Airtableレコード削除開始: URL={url}")
        resp = requests.delete(url, headers=HEADERS)
        resp.raise_for_status()
        app.logger.info(f"Airtableレコード削除成功: ID={record_id}")
        flash("✅ レコードを削除しました！", "success")
    except requests.exceptions.HTTPError as http_err:
        app.logger.error(f"Airtableレコード削除エラー (HTTPError): {http_err.response.status_code} {http_err.response.text} - URL: {url}")
        flash(f"❌ 削除に失敗しました (HTTP {http_err.response.status_code})。", "error")
    except requests.RequestException as e:
        app.logger.error(f"Airtableレコード削除エラー (RequestException): {str(e)} - URL: {url}", exc_info=True)
        flash(f"❌ 削除に失敗しました: {e}", "error")

    try:
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
    except (TypeError, ValueError):
        app.logger.warning("delete_record - formから年月の取得に失敗。セッション値を使用します。")
        year = session.get("current_display_year", date.today().year)
        month = session.get("current_display_month", date.today().month)
    
    return redirect(url_for("records", year=year, month=month))


# ✅ レコードの修正ページ
@app.route("/edit_record/<record_id>", methods=["GET", "POST"])
def edit_record(record_id):
    selected_personid = session.get("selected_personid")
    if not selected_personid:
        app.logger.warning("edit_record - PersonIDが選択されていません。")
        flash("❌ PersonIDが選択されていません。操作を続行できません。", "error")
        return redirect(url_for("index"))

    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID: # Airtable設定チェック
        app.logger.error("edit_record - Airtable設定が不完全です。")
        flash("⚠ Airtableの設定が不完全なため、レコードを編集できません。", "error")
        return redirect(url_for("records", year=session.get("current_display_year"), month=session.get("current_display_month")))

    table_name = f"TablePersonID_{selected_personid}"
    record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_name}/{record_id}"

    original_year = request.args.get('year', session.get('current_display_year', str(date.today().year)))
    original_month = request.args.get('month', session.get('current_display_month', str(date.today().month)))

    if request.method == "POST":
        orig_day = request.form.get("original_WorkDay", "")
        orig_output_str = request.form.get("original_WorkOutput", "") # 文字列として取得
        new_day = request.form.get("WorkDay", "")
        new_output_str = request.form.get("WorkOutput", "") # 文字列として取得

        try:
            new_output_val = int(new_output_str) # 整数に変換
        except ValueError:
            app.logger.error(f"edit_record - WorkOutputの変換に失敗: {new_output_str}")
            flash("❌ 作業量は数値で入力してください。", "error")
            # GETリクエスト相当の処理でフォームを再表示 (編集対象のレコードデータを再度取得)
            try:
                resp_get = requests.get(record_url, headers=HEADERS)
                resp_get.raise_for_status()
                record_data_for_render = resp_get.json().get("fields", {})
            except Exception as e_get:
                app.logger.error(f"edit_record POST (ValueError時) - レコード再取得エラー: {e_get}", exc_info=True)
                flash(f"❌ レコード情報の再取得に失敗しました: {e_get}", "error")
                return redirect(url_for("records", year=original_year, month=original_month))
            
            return render_template(
                "edit_record.html",
                record=record_data_for_render, # 再取得したデータ
                record_id=record_id,
                original_year=original_year,
                original_month=original_month
            )


        updated_fields = {
            "WorkDay": new_day,
            "WorkOutput": new_output_val # 変換後の整数
        }
        try:
            app.logger.info(f"Airtableレコード更新開始: URL={record_url}, Data={updated_fields}")
            resp = requests.patch(record_url, headers=HEADERS, json={"fields": updated_fields})
            resp.raise_for_status()
            app.logger.info(f"Airtableレコード更新成功: ID={record_id}")

            changes = []
            if orig_day != new_day:
                changes.append(f"作業日：{orig_day}→{new_day}")
            if str(orig_output_str) != str(new_output_str): # 文字列比較で変更を確認
                changes.append(f"作業量：{orig_output_str}→{new_output_str}")
            
            detail = "、".join(changes) if changes else "（変更なし）"
            flash(f"✅ レコードを更新しました！ 更新内容：{detail}", "success")
            session['edited_record_id'] = record_id

        except requests.exceptions.HTTPError as http_err:
            app.logger.error(f"Airtableレコード更新エラー (HTTPError): {http_err.response.status_code} {http_err.response.text} - URL: {record_url}")
            err_detail = http_err.response.json().get('error', {}).get('message', '詳細不明') if http_err.response else str(http_err)
            flash(f"❌ 更新に失敗しました (HTTP {http_err.response.status_code}): {err_detail}", "error")
        except requests.RequestException as e:
            app.logger.error(f"Airtableレコード更新エラー (RequestException): {str(e)} - URL: {record_url}", exc_info=True)
            flash(f"❌ 更新に失敗しました: {e}", "error")

        try:
            dt = datetime.strptime(new_day, "%Y-%m-%d")
            return redirect(url_for("records", year=dt.year, month=dt.month))
        except ValueError:
            app.logger.warning(f"edit_record - 更新後の日付形式が無効なためデフォルトへリダイレクト: {new_day}")
            return redirect(url_for("records"))

    # GET リクエスト時
    try:
        app.logger.info(f"Airtableレコード編集フォーム用データ取得開始: URL={record_url}")
        resp = requests.get(record_url, headers=HEADERS)
        resp.raise_for_status()
        record_data = resp.json().get("fields", {})
        app.logger.info(f"Airtableレコード編集フォーム用データ取得成功: ID={record_id}")
    except Exception as e:
        app.logger.error(f"Airtableレコード取得エラー (GET edit_record): {e} - URL: {record_url}", exc_info=True)
        flash(f"❌ レコード取得に失敗しました: {e}", "error")
        return redirect(url_for("records", year=original_year, month=original_month))

    return render_template(
        "edit_record.html",
        record=record_data,
        record_id=record_id,
        original_year=original_year,
        original_month=original_month
    )


# 🆕 **一覧表示のルート (前月・次月機能対応)**
@app.route("/records")
@app.route("/records/<int:year>/<int:month>")
def records(year=None, month=None):
    personid_from_param = request.args.get("personid")
    if personid_from_param:
        _, personid_list_for_check = get_cached_personid_data()
        try:
            if int(personid_from_param) in personid_list_for_check:
                session['selected_personid'] = personid_from_param
                app.logger.info(f"records - PersonIDがURLパラメータから設定されました: {personid_from_param}")
            else:
                app.logger.warning(f"records - 無効なPersonIDがURLパラメータで指定されました: {personid_from_param}")
                flash("⚠ 無効なPersonIDが指定されました。", "warning")
                return redirect(url_for("index"))
        except ValueError:
            app.logger.warning(f"records - PersonIDの形式が無効です (URLパラメータ): {personid_from_param}")
            flash("⚠ PersonIDの形式が無効です。", "warning")
            return redirect(url_for("index"))
        
        redirect_url = url_for('records', year=year, month=month) if year is not None and month is not None else url_for('records')
        return redirect(redirect_url)

    selected_personid = session.get("selected_personid")
    if not selected_personid:
        app.logger.info("records - PersonIDが未選択のためindexへリダイレクトします。")
        flash("👤 PersonIDを選択してください。", "info")
        return redirect(url_for("index"))

    today = date.today()
    default_display_date = today - timedelta(days=30) # 約1ヶ月前

    if year is None or month is None:
        selected_workday_from_session = session.get("workday")
        if selected_workday_from_session:
            try:
                base_date = datetime.strptime(selected_workday_from_session, "%Y-%m-%d").date()
            except ValueError:
                base_date = default_display_date
        else:
            base_date = default_display_date
        year = base_date.year
        month = base_date.month
    else:
        try:
            date(year, month, 1) # 有効な年月かチェック
        except ValueError:
            app.logger.warning(f"records - 無効な年月が指定されました: year={year}, month={month}")
            flash("⚠ 無効な年月が指定されました。デフォルトの月を表示します。", "warning")
            base_date = default_display_date # デフォルトに戻す
            year = base_date.year
            month = base_date.month
    
    session['current_display_year'] = year
    session['current_display_month'] = month
    display_month_str = f"{year}年{month}月"
    app.logger.info(f"records - 表示対象月: {display_month_str}, PersonID: {selected_personid}")

    records_data = get_selected_month_records(year, month)

    total_amount = 0
    for record_item in records_data:
        try:
            unit_price_str = str(record_item.get("UnitPrice", "0")).strip()
            unit_price = float(unit_price_str) if unit_price_str and unit_price_str != "不明" else 0.0
            work_output = int(record_item.get("WorkOutput", 0))
            record_item["subtotal"] = unit_price * work_output
        except ValueError:
            app.logger.warning(f"records - subtotal計算エラー: UnitPrice='{record_item.get('UnitPrice')}', WorkOutput='{record_item.get('WorkOutput')}'")
            record_item["subtotal"] = 0
        total_amount += record_item["subtotal"]

    unique_workdays = set(r["WorkDay"] for r in records_data if r.get("WorkDay") != "9999-12-31") # WorkDayが有効なもののみ
    workdays_count = len(unique_workdays)
    
    workoutput_total = 0
    for r_item in records_data:
        if "分給" in r_item.get("WorkProcess", ""):
            work_output_value = str(r_item.get("WorkOutput", "0")).strip()
            if work_output_value:
                try:
                    workoutput_total += float(work_output_value)
                except ValueError:
                    app.logger.info(f"records - '分給'のWorkOutput集計時、float変換失敗: '{work_output_value}'")

    first_day_of_current_month = date(year, month, 1)
    prev_month_date = first_day_of_current_month - timedelta(days=1)
    prev_year, prev_month = prev_month_date.year, prev_month_date.month

    next_month_date = (first_day_of_current_month.replace(day=28) + timedelta(days=4)).replace(day=1) # 次の月の1日を安全に取得
    next_year, next_month = next_month_date.year, next_month_date.month
    
    new_record_id_from_session = session.pop('new_record_id', None)
    edited_record_id_from_session = session.pop('edited_record_id', None)

    personid_dict, _ = get_cached_personid_data()

    return render_template(
        "records.html",
        records=records_data,
        personid=selected_personid,
        personid_dict=personid_dict,
        display_month=display_month_str,
        total_amount=total_amount,
        workdays_count=workdays_count,
        workoutput_total=workoutput_total,
        current_year=year,
        current_month=month,
        new_record_id=new_record_id_from_session,
        edited_record_id=edited_record_id_from_session,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month
    )


# -------------------------------
# Flask のルート (入力フォーム)
@app.route("/", methods=["GET", "POST"])
def index():
    # フォーム表示に必要なデータをロード
    personid_dict_data, personid_list_data = get_cached_personid_data()
    workprocess_list_data, unitprice_dict_data = get_cached_workprocess_data()
    # workcordデータはAPI経由で取得するため、ここではロード不要 (get_cached_workcord_data() は呼ばない)

    if request.method == "POST":
        selected_personid = request.form.get("personid", "").strip()
        workcd = request.form.get("workcd", "").strip()
        workoutput_str = request.form.get("workoutput", "").strip() or "0"
        workprocess = request.form.get("workprocess", "").strip()
        workday = request.form.get("workday", "").strip()
        selected_option = request.form.get("workname", "").strip() # "WorkName||BookName" または WorkName のみ

        workname, bookname = "", ""
        error_occurred = False

        if not selected_personid or not selected_personid.isdigit() or int(selected_personid) not in personid_list_data:
            flash("⚠ 有効な PersonID を選択してください！", "error")
            error_occurred = True
        
        if workcd and not workcd.isdigit():
            flash("⚠ WorkCD は数値で入力してください！", "error")
            error_occurred = True
            
        try:
            workoutput_val = int(workoutput_str)
        except ValueError:
            flash("⚠ 数量は数値を入力してください！", "error")
            error_occurred = True
            workoutput_val = 0 # エラー時は0など安全な値にフォールバック
        
        if not workprocess or not workday:
            flash("⚠ 行程と作業日は入力してください！", "error")
            error_occurred = True
        else:
            try:
                datetime.strptime(workday, "%Y-%m-%d")
            except ValueError:
                flash("⚠ 作業日はYYYY-MM-DDの形式で入力してください！", "error")
                error_occurred = True

        if not selected_option and workcd:
            flash("⚠ WorkCD を入力した場合は WorkName/BookName も選択してください！", "error")
            error_occurred = True
        elif selected_option:
            if "||" in selected_option:
                workname, bookname = selected_option.split("||", 1)
            else:
                workname = selected_option
                bookname = request.form.get("bookname_hidden", "").strip() # hiddenフィールドから取得

        if error_occurred:
            app.logger.warning(f"index POST - 入力エラー: {selected_personid}, {workcd}, {workoutput_str}, {workprocess}, {workday}, {selected_option}")
            # エラー時も入力値を保持してフォームを再表示
            return render_template("index.html",
                                   personid_list=personid_list_data,
                                   personid_dict=personid_dict_data,
                                   selected_personid=selected_personid,
                                   workprocess_list=workprocess_list_data,
                                   workday=workday,
                                   workcd=workcd,
                                   workoutput=workoutput_str, # 元の文字列を返す
                                   workprocess_selected=workprocess, # 選択された値を保持
                                   selected_workname_option=selected_option,
                                   bookname_hidden=bookname # hiddenの値も保持
                                   )

        if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID: # Airtable設定チェック
            app.logger.error("index POST - Airtable設定が不完全です。")
            flash("⚠ Airtableの設定が不完全なため、データを送信できません。", "error")
            return redirect(url_for("index"))


        dest_table = f"TablePersonID_{selected_personid}"
        dest_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{dest_table}"
        unitprice = unitprice_dict_data.get(workprocess, 0.0) # floatで取得

        app.logger.info(f"index POST - Airtableへの送信準備: PersonID={selected_personid}, WorkCD={workcd or 'N/A'}")
        status_code, response_text, new_record_id = send_record_to_destination(
            dest_url, workcd, workname, bookname, workoutput_val, workprocess, unitprice, workday
        )

        flash(response_text, "success" if status_code == 200 else "error")
        session['selected_personid'] = selected_personid
        session['workday'] = workday # 次回フォーム表示時のデフォルト作業日として保存

        if status_code == 200 and new_record_id:
            session['new_record_id'] = new_record_id
            try:
                workday_dt = datetime.strptime(workday, "%Y-%m-%d")
                return redirect(url_for("records", year=workday_dt.year, month=workday_dt.month))
            except ValueError:
                app.logger.warning(f"index POST - workdayのパースに失敗 ({workday})。recordsのデフォルト表示へ。")
                return redirect(url_for("records"))
        else:
            # 送信失敗時も入力値を保持してフォームを再表示
            return render_template("index.html",
                                   personid_list=personid_list_data,
                                   personid_dict=personid_dict_data,
                                   selected_personid=selected_personid,
                                   workprocess_list=workprocess_list_data,
                                   workday=workday,
                                   workcd=workcd,
                                   workoutput=workoutput_str,
                                   workprocess_selected=workprocess,
                                   selected_workname_option=selected_option,
                                   bookname_hidden=bookname
                                   )

    # GET リクエスト
    selected_personid_session = session.get('selected_personid', "")
    # セッションに前回入力した作業日があればそれを、なければ約1ヶ月前の日付をデフォルトにする
    session_workday = session.get('workday')
    if session_workday:
        try:
            datetime.strptime(session_workday, "%Y-%m-%d") # 形式チェック
            workday_default = session_workday
        except ValueError:
            workday_default = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
            session['workday'] = workday_default # 不正な形式なら更新
    else:
        workday_default = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    return render_template("index.html",
                           workprocess_list=workprocess_list_data,
                           personid_list=personid_list_data,
                           personid_dict=personid_dict_data,
                           selected_personid=selected_personid_session,
                           workday=workday_default,
                           workcd="",
                           workoutput="",
                           workprocess_selected="", # 初期値は空
                           selected_workname_option="",
                           bookname_hidden=""
                           )


if __name__ == "__main__":
    # アプリケーション起動時に必要なキャッシュを事前にロード（ウォームアップ）
    app.logger.info("アプリケーション起動: 初期データキャッシュを開始します...")
    try:
        load_personid_data()
        load_workcord_data()
        load_workprocess_data()
        app.logger.info("初期データキャッシュが完了しました。")
    except Exception as e:
        app.logger.critical(f"アプリケーション起動時の初期データロードに失敗しました: {e}", exc_info=True)
        # ここで処理を中断するかどうかを決定
        # exit(1) # 例えばエラーで終了させる

    from waitress import serve
    port = int(os.environ.get("PORT", 10000))
    app.logger.info(f"サーバをポート {port} で起動します...")
    serve(app, host="0.0.0.0", port=port)