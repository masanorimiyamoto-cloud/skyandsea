# blueprints/ui.py
from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, session, current_app
)
from datetime import datetime, date, timedelta
import json # Pythonの辞書をJSON文字列としてテンプレートに渡す場合

# サービスモジュールから必要な関数をインポート
# data_services.py, airtable_service.py, forms.py はプロジェクトルートにあると仮定
from data_services import get_cached_personid_data, get_cached_workprocess_data
from airtable_service import (
    create_airtable_record,
    get_airtable_records_for_month,
    delete_airtable_record,
    get_airtable_record_details,
    update_airtable_record_fields
)
# from forms import WorkLogForm # Flask-WTF を導入する際にコメントを外します

# UI用 Blueprint を作成
# template_folder と static_folder は、メインアプリケーションのフォルダを参照するように指定
ui_bp = Blueprint(
    'ui_bp', __name__,
    template_folder='../templates',  # プロジェクトルートの templates フォルダ
    static_folder='../static'      # プロジェクトルートの static フォルダ
)

# -------------------------------
# Flask のルート (入力フォーム) - "/"
@ui_bp.route("/", methods=["GET", "POST"])
def index():
    # --- データ読み込み (GET/POST共通) ---
    # get_cached_workcord_data() # WorkCordデータはAPI経由なのでここでは不要
    personid_dict_data, personid_list_data = get_cached_personid_data()
    workprocess_list_data, unitprice_dict_data = get_cached_workprocess_data()
    # error_wp は get_workprocess_data() の返り値の一部でしたが、
    # get_cached_workprocess_data() はエラーを直接返さないため、ここでは扱いません。
    # data_services 内のロガーでエラーは記録されます。

    if request.method == "POST":
        selected_personid = request.form.get("personid", "").strip()
        workcd = request.form.get("workcd", "").strip()
        workoutput = request.form.get("workoutput", "").strip() or "0"
        workprocess = request.form.get("workprocess", "").strip()
        workday = request.form.get("workday", "").strip()
        selected_option = request.form.get("workname", "").strip() # JSからはworknameのみが送られてくる想定
        bookname_from_hidden = request.form.get("bookname", "").strip() # 元のコードでは 'bookname' で受け取っていた

        workname, bookname = "", ""
        workoutput_val = 0
        error_occurred = False

        if not selected_personid or not selected_personid.isdigit() or int(selected_personid) not in personid_list_data:
            flash("⚠ 有効な PersonID を選択してください！", "error")
            error_occurred = True
        
        if workcd and not workcd.isdigit():
            flash("⚠ WorkCD は数値で入力してください！", "error")
            error_occurred = True
            
        try:
            workoutput_val = int(workoutput)
        except ValueError:
            flash("⚠ 数量は数値を入力してください！", "error")
            error_occurred = True
            workoutput_val = 0 # エラー時のフォールバック
        
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
            flash("⚠ WorkCDを入力した場合は品名も選択してください！", "error")
            error_occurred = True
        elif selected_option:
            # JavaScript側で worknameSelect の option の value には workname のみが設定される想定
            workname = selected_option
            # bookname は hidden フィールドから取得
            bookname = bookname_from_hidden
        
        if error_occurred:
            current_app.logger.warning(f"UI index POST - 入力エラー: PersonID={selected_personid}, WorkCD={workcd}")
            # エラー時も入力値を保持してフォームを再表示
            # この部分は Flask-WTF 導入時に form オブジェクトを使う形に変わります
            return render_template("index.html",
                                   personid_list=personid_list_data,
                                   personid_dict=personid_dict_data,
                                   selected_personid=selected_personid,
                                   workprocess_list=workprocess_list_data,
                                   unitprice_dict_json=json.dumps(unitprice_dict_data), # JS用
                                   workday=workday,
                                   workcd=workcd,
                                   workoutput=workoutput, # 文字列のまま渡す
                                   workprocess_selected=workprocess, # workprocessだと予約語と衝突の可能性
                                   selected_workname_option=selected_option, # 元の値を保持
                                   bookname_hidden=bookname # hiddenフィールドの値も保持
                                   )

        unitprice = unitprice_dict_data.get(workprocess, 0.0) # floatで取得

        current_app.logger.info(f"UI index POST - Airtableへの送信準備: PersonID={selected_personid}, WorkCD={workcd or 'N/A'}")
        status_code, response_text, new_record_id = create_airtable_record(
            selected_personid, workcd, workname, bookname, workoutput_val, workprocess, unitprice, workday
        )

        flash(response_text, "success" if status_code == 200 and new_record_id else "error")
        session['selected_personid'] = selected_personid
        session['workday'] = workday

        if status_code == 200 and new_record_id:
            session['new_record_id'] = new_record_id
            try:
                workday_dt = datetime.strptime(workday, "%Y-%m-%d")
                # Blueprint内のルートを参照する場合は先頭にドット '.' をつける
                return redirect(url_for(".records", year=workday_dt.year, month=workday_dt.month))
            except ValueError: 
                current_app.logger.warning(f"UI index POST - workdayのパースに失敗 ({workday})。recordsのデフォルト表示へ。")
                return redirect(url_for(".records")) 
        else:
            # 送信失敗時も入力値を保持してindex.htmlを再表示
            return render_template("index.html",
                                   personid_list=personid_list_data,
                                   personid_dict=personid_dict_data,
                                   selected_personid=selected_personid,
                                   workprocess_list=workprocess_list_data,
                                   unitprice_dict_json=json.dumps(unitprice_dict_data),
                                   workday=workday,
                                   workcd=workcd,
                                   workoutput=workoutput,
                                   workprocess_selected=workprocess,
                                   selected_workname_option=selected_option,
                                   bookname_hidden=bookname
                                   )

    # GET リクエスト
    selected_personid_session = session.get('selected_personid', "")
    session_workday = session.get('workday')

    if session_workday:
        try: # セッションの作業日が正しい形式か確認
            datetime.strptime(session_workday, "%Y-%m-%d")
            workday_default = session_workday
        except ValueError:
            workday_default = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
            session['workday'] = workday_default # 不正な形式なら更新
    else:
        workday_default = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    # フォームの初期値を設定（POSTエラーで戻ってきた場合も考慮）
    # Flask-WTF未導入なので、手動で値を渡す
    return render_template("index.html",
                           workprocess_list=workprocess_list_data,
                           personid_list=personid_list_data, # PersonIDのリストも渡す
                           personid_dict=personid_dict_data,
                           selected_personid=selected_personid_session, 
                           unitprice_dict_json=json.dumps(unitprice_dict_data), # JS用
                           workday=request.form.get('workday', workday_default), # エラー時はフォームの値を優先
                           workcd=request.form.get('workcd', ""),
                           workoutput=request.form.get('workoutput', ""),
                           workprocess_selected=request.form.get('workprocess', ""),
                           selected_workname_option=request.form.get('workname', ""),
                           bookname_hidden=request.form.get('bookname', ""), # 元のコードでは 'bookname'
                           unitprice="" # 単価はJSで設定される
                           )


# 🆕 **一覧表示のルート (前月・次月機能対応)**
@ui_bp.route("/records")
@ui_bp.route("/records/<int:year>/<int:month>")
def records(year=None, month=None):
    personid_from_param = request.args.get("personid")
    if personid_from_param:
        _, personid_list_for_check = get_cached_personid_data() 
        try:
            if int(personid_from_param) in personid_list_for_check:
                session['selected_personid'] = personid_from_param
            else:
                flash("⚠ 無効なPersonIDが指定されました。", "warning")
                return redirect(url_for(".index")) # Blueprint内のindexへ
        except ValueError:
            flash("⚠ PersonIDの形式が無効です。", "warning")
            return redirect(url_for(".index"))

        redirect_url = url_for('.records', year=year, month=month) if year is not None and month is not None else url_for('.records')
        return redirect(redirect_url)

    selected_personid = session.get("selected_personid")
    if not selected_personid:
        flash("👤 PersonIDを選択してください。", "info")
        return redirect(url_for(".index"))

    today = date.today()
    default_display_date = today - timedelta(days=30)

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
            flash("⚠ 無効な年月が指定されました。デフォルトの月を表示します。", "warning")
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
    
    session['current_display_year'] = year
    session['current_display_month'] = month

    display_month_str = f"{year}年{month}月"
    # airtable_serviceの関数を使用
    records_data = get_airtable_records_for_month(selected_personid, year, month) 
    if records_data is None: # get_airtable_records_for_monthがエラー時にNoneを返す場合(現状は空リスト)
        flash("⚠ レコードの取得中にエラーが発生しました。", "error")
        records_data = []


    total_amount = 0
    for record_item in records_data:
        try:
            unit_price_str = str(record_item.get("UnitPrice", "0")).strip()
            unit_price = float(unit_price_str) if unit_price_str and unit_price_str != "不明" else 0.0
            work_output_str = str(record_item.get("WorkOutput", "0")).strip()
            work_output = int(work_output_str) if work_output_str else 0
            record_item["subtotal"] = unit_price * work_output
        except ValueError:
            current_app.logger.warning(f"UI records - subtotal計算エラー: UnitPrice='{record_item.get('UnitPrice')}', WorkOutput='{record_item.get('WorkOutput')}'")
            record_item["subtotal"] = 0
        total_amount += record_item["subtotal"]

    unique_workdays = set(r["WorkDay"] for r in records_data if r.get("WorkDay") != "9999-12-31")
    workdays_count = len(unique_workdays)
    
    workoutput_total = 0
    for r_item in records_data:
        if "分給" in r_item.get("WorkProcess", ""):
            work_output_value = str(r_item.get("WorkOutput", "0")).strip()
            if work_output_value and work_output_value.replace('.', '', 1).isdigit():
                try:
                    workoutput_total += float(work_output_value)
                except ValueError:
                    current_app.logger.warning(f"UI records - '分給'のWorkOutput集計時、float変換失敗（isdigitチェック後）: '{work_output_value}'")
            elif work_output_value:
                current_app.logger.info(f"UI records - WorkOutput '{work_output_value}' は '分給' の集計対象外の形式です。")

    first_day_of_current_month = date(year, month, 1)
    prev_month_date = first_day_of_current_month - timedelta(days=1)
    prev_year, prev_month = prev_month_date.year, prev_month_date.month

    next_month_date = (first_day_of_current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    next_year, next_month = next_month_date.year, next_month_date.month
    
    new_record_id_from_session = session.pop('new_record_id', None)
    edited_record_id_from_session = session.pop('edited_record_id', None)

    personid_dict_data_for_template, _ = get_cached_personid_data()

    return render_template(
        "records.html",
        records=records_data,
        personid=selected_personid,
        personid_dict=personid_dict_data_for_template,
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


# ✅ レコードの削除
@ui_bp.route("/delete_record/<record_id>", methods=["POST"])
def delete_record(record_id):
    selected_personid = session.get("selected_personid")
    if not selected_personid:
        flash("❌ PersonIDが選択されていません。操作を続行できません。", "error")
        return redirect(url_for(".index")) # Blueprint内のindexへ

    success, message = delete_airtable_record(selected_personid, record_id) # airtable_service を使用
    flash(message, "success" if success else "error")

    try:
        year  = int(request.form.get("year"))
        month = int(request.form.get("month"))
    except (TypeError, ValueError):
        year  = session.get("current_display_year", date.today().year)
        month = session.get("current_display_month", date.today().month)
    
    return redirect(url_for(".records", year=year, month=month)) # Blueprint内のrecordsへ


# ✅ レコードの修正ページ
@ui_bp.route("/edit_record/<record_id>", methods=["GET", "POST"])
def edit_record(record_id):
    selected_personid = session.get("selected_personid")
    if not selected_personid:
        flash("❌ PersonIDが選択されていません。操作を続行できません。", "error")
        return redirect(url_for(".index")) # Blueprint内のindexへ

    # GET時の戻り先年月取得 (現在の表示年月を優先)
    original_year = session.get('current_display_year', date.today().year)
    original_month = session.get('current_display_month', date.today().month)
    # URLパラメータがあればそれで上書き (文字列なので注意)
    year_from_args = request.args.get('year')
    month_from_args = request.args.get('month')
    if year_from_args:
        try: original_year = int(year_from_args)
        except ValueError: current_app.logger.warning(f"edit_record - 不正なyearパラメータ: {year_from_args}")
    if month_from_args:
        try: original_month = int(month_from_args)
        except ValueError: current_app.logger.warning(f"edit_record - 不正なmonthパラメータ: {month_from_args}")


    if request.method == "POST":
        orig_day = request.form.get("original_WorkDay", "")
        orig_output_str = request.form.get("original_WorkOutput", "")
        new_day = request.form.get("WorkDay", "")
        new_output_str = request.form.get("WorkOutput", "")

        try:
            new_output_val = int(new_output_str)
        except ValueError:
            current_app.logger.error(f"UI edit_record POST - WorkOutputの変換に失敗: {new_output_str}")
            flash("❌ 作業量は数値で入力してください。", "error")
            # エラー時も編集対象のレコードデータを再取得してフォーム表示
            record_data_for_render, error_get_msg = get_airtable_record_details(selected_personid, record_id)
            if error_get_msg or record_data_for_render is None:
                flash(error_get_msg or "❌ レコード情報の再取得に失敗しました。", "error")
                # エラー時は元の表示月へリダイレクト
                return redirect(url_for(".records", year=original_year, month=original_month))
            return render_template(
                "edit_record.html", record=record_data_for_render, record_id=record_id,
                original_year=original_year, original_month=original_month
            )

        updated_fields = { "WorkDay": new_day, "WorkOutput": new_output_val }
        
        success, message = update_airtable_record_fields(selected_personid, record_id, updated_fields)

        if success:
            changes = []
            if orig_day != new_day: changes.append(f"作業日：{orig_day}→{new_day}")
            if str(orig_output_str) != str(new_output_str): changes.append(f"作業量：{orig_output_str}→{new_output_str}")
            detail = "、".join(changes) if changes else "（変更なし）"
            flash(f"{message} 更新内容：{detail}", "success") # messageは "✅ レコードを更新しました！"
            session['edited_record_id'] = record_id
        else:
            flash(message, "error") # messageは "❌ 更新に失敗しました..."

        try:
            dt = datetime.strptime(new_day, "%Y-%m-%d")
            return redirect(url_for(".records", year=dt.year, month=dt.month))
        except ValueError:
            current_app.logger.warning(f"UI edit_record POST - 更新後の日付形式が無効 ({new_day})。元の年月へリダイレクト。")
            return redirect(url_for(".records", year=original_year, month=original_month))

    # GET リクエスト時
    record_data, error_message = get_airtable_record_details(selected_personid, record_id)
    if error_message or record_data is None:
        flash(error_message or "❌ レコード取得に失敗しました。", "error")
        return redirect(url_for(".records", year=original_year, month=original_month))

    return render_template(
        "edit_record.html",
        record=record_data,
        record_id=record_id,
        original_year=original_year,
        original_month=original_month
    )