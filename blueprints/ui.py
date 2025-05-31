from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, session, current_app
)
from datetime import datetime, date, timedelta
import json # unitprice_dict_data をJSONとして渡すために必要

# サービスモジュールから必要な関数をインポート
from data_services import get_cached_personid_data, get_cached_workprocess_data
from airtable_service import (
    create_airtable_record,
    get_airtable_records_for_month,
    delete_airtable_record,
    get_airtable_record_details,
    update_airtable_record_fields
)
# 作成したフォームクラスをインポート
from forms import WorkLogForm


# UI用 Blueprint を作成
ui_bp = Blueprint(
    'ui_bp', __name__,
    template_folder='../templates',
    static_folder='../static'
)

# -------------------------------
# Flask のルート (入力フォーム) - "/"
@ui_bp.route("/", methods=["GET", "POST"])
def index():
    form = WorkLogForm(request.form if request.method == 'POST' else None)

    # --- SelectFieldの選択肢を動的に設定 ---
    personid_dict_data, _ = get_cached_personid_data() # personid_list_data はバリデーションでは直接使わない
    form.personid.choices = [("", "PersonIDを選択してください")] + \
                            [(str(pid), f"{pid} - {pname}") for pid, pname in personid_dict_data.items()]

    workprocess_list_data, unitprice_dict_data = get_cached_workprocess_data()
    form.workprocess.choices = [("", "行程名を選択してください")] + \
                               [(wp, wp) for wp in workprocess_list_data]
    # --- 選択肢設定ここまで ---

    if form.validate_on_submit(): # POSTリクエストで、かつバリデーション成功の場合
        selected_personid = form.personid.data
        workcd = form.workcd.data
        workname = form.workname.data         # JavaScriptで設定された品名
        bookname_val = form.bookname_hidden.data # JavaScriptで設定された書名
        workprocess = form.workprocess.data
        workoutput_str = form.workoutput.data # StringFieldなので文字列
        workday_date = form.workday.data       # DateFieldなのでPythonのdateオブジェクト

        try:
            workoutput_val = int(workoutput_str) # Regexpバリデータで形式チェック済みのはず
        except ValueError:
            current_app.logger.error(f"UI index POST - WorkOutputの整数変換に失敗(バリデータ後): {workoutput_str}")
            flash("数量の形式が不正です。", "error")
            # formオブジェクトにはエラー情報と入力値が保持されている
            return render_template("index.html", form=form, unitprice_dict_json=json.dumps(unitprice_dict_data))

        # 品番コードが入力されていて、品名が選択されていない場合の追加サーバーサイドバリデーション (任意)
        if workcd and not workname:
            # WTFormsのフィールドに直接エラーを追加できる
            form.workname.errors.append("品番コードを入力した場合、品名も選択してください。")
            # flash("品番コードを入力した場合は、品名も選択してください。", "warning") # こちらでも可
            # このエラーがある場合、下の if not form.errors: でキャッチされる

        if not form.errors: # WTFormsのバリデーションエラー + 上記カスタムエラーがなければ
            unitprice = unitprice_dict_data.get(workprocess, 0.0)
            workday_str = workday_date.strftime('%Y-%m-%d')

            current_app.logger.info(f"UI index POST (WTForm) - Airtable送信準備: PersonID={selected_personid}")
            status_code, response_text, new_record_id = create_airtable_record(
                selected_personid, workcd, workname, bookname_val, workoutput_val, workprocess, unitprice, workday_str
            )

            flash(response_text, "success" if status_code == 200 and new_record_id else "error")
            session['selected_personid'] = selected_personid
            session['workday'] = workday_str # 次回フォーム表示時のデフォルト作業日として保存

            if status_code == 200 and new_record_id:
                session['new_record_id'] = new_record_id
                return redirect(url_for(".records", year=workday_date.year, month=workday_date.month))
            else:
                # 送信失敗時、エラーメッセージはflashで表示されるので、ここではフォームを再表示
                # formオブジェクトにはエラー発生前の入力値が保持されている
                return render_template("index.html", form=form, unitprice_dict_json=json.dumps(unitprice_dict_data))
        # else: フォームにエラーがある場合は、このブロックの外側で再度フォームがレンダリングされる

    # GETリクエストまたはPOSTでバリデーション失敗時の処理
    # (form.validate_on_submit() が False だった場合、ここに来る)
    if request.method == 'GET':
        # GETリクエストの場合、セッションから前回値をフォームに設定
        form.personid.data = session.get('selected_personid')
        session_workday_str = session.get('workday')
        if session_workday_str:
            try:
                form.workday.data = date.fromisoformat(session_workday_str)
            except (ValueError, TypeError): # 不正な形式やNoneの場合
                current_app.logger.warning(f"セッションの作業日'{session_workday_str}'のパースに失敗。デフォルト値を使用。")
                form.workday.data = date.today() - timedelta(days=30)
        else:
            form.workday.data = date.today() - timedelta(days=30) # デフォルト
        
        # 他のフィールド(workcd, workoutputなど)はGET時には空で良い。
        # もしエラーで戻ってきた場合(POSTでバリデーション失敗)、
        # formオブジェクトは既にユーザーの入力値を保持しているので、ここで再設定は不要。

    # 最終的にテンプレートをレンダリング
    # GETリクエスト、またはPOSTでバリデーションエラーがあった場合にここに来る
    # formオブジェクトにはエラーメッセージや入力値が含まれている
    return render_template("index.html", form=form, unitprice_dict_json=json.dumps(unitprice_dict_data))


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
                current_app.logger.info(f"UI records - PersonIDがURLパラメータから設定されました: {personid_from_param}")
            else:
                current_app.logger.warning(f"UI records - 無効なPersonIDがURLパラメータで指定されました: {personid_from_param}")
                flash("⚠ 無効なPersonIDが指定されました。", "warning")
                return redirect(url_for(".index"))
        except ValueError:
            current_app.logger.warning(f"UI records - PersonIDの形式が無効です (URLパラメータ): {personid_from_param}")
            flash("⚠ PersonIDの形式が無効です。", "warning")
            return redirect(url_for(".index"))
        
        redirect_url = url_for('.records', year=year, month=month) if year is not None and month is not None else url_for('.records')
        return redirect(redirect_url)

    selected_personid = session.get("selected_personid")
    if not selected_personid:
        current_app.logger.info("UI records - PersonIDが未選択のためindexへリダイレクトします。")
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
            date(year, month, 1)
        except ValueError:
            current_app.logger.warning(f"UI records - 無効な年月が指定されました: year={year}, month={month}")
            flash("⚠ 無効な年月が指定されました。デフォルトの月を表示します。", "warning")
            base_date = default_display_date
            year = base_date.year
            month = base_date.month
    
    session['current_display_year'] = year
    session['current_display_month'] = month
    display_month_str = f"{year}年{month}月"
    current_app.logger.info(f"UI records - 表示対象月: {display_month_str}, PersonID: {selected_personid}")

    records_data = get_airtable_records_for_month(selected_personid, year, month)

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
            if work_output_value:
                try:
                    workoutput_total += float(work_output_value)
                except ValueError:
                    current_app.logger.info(f"UI records - '分給'のWorkOutput集計時、float変換失敗: '{work_output_value}'")

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
        personid_dict=personid_dict_data_for_template, # 辞書を渡す
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
        current_app.logger.warning("UI delete_record - PersonIDが選択されていません。")
        flash("❌ PersonIDが選択されていません。操作を続行できません。", "error")
        return redirect(url_for(".index"))

    success, message = delete_airtable_record(selected_personid, record_id)
    flash(message, "success" if success else "error")

    try:
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
    except (TypeError, ValueError):
        current_app.logger.warning("UI delete_record - formから年月の取得に失敗。セッション値を使用します。")
        year = session.get("current_display_year", date.today().year)
        month = session.get("current_display_month", date.today().month)
    
    return redirect(url_for(".records", year=year, month=month))


# ✅ レコードの修正ページ
@ui_bp.route("/edit_record/<record_id>", methods=["GET", "POST"])
def edit_record(record_id):
    selected_personid = session.get("selected_personid")
    if not selected_personid:
        current_app.logger.warning("UI edit_record - PersonIDが選択されていません。")
        flash("❌ PersonIDが選択されていません。操作を続行できません。", "error")
        return redirect(url_for(".index"))

    # GET時の戻り先年月取得 (現在の表示年月を優先)
    original_year = session.get('current_display_year', date.today().year)
    original_month = session.get('current_display_month', date.today().month)
    # URLパラメータがあればそれで上書き (文字列なので注意)
    year_from_args = request.args.get('year')
    month_from_args = request.args.get('month')
    if year_from_args:
        try: original_year = int(year_from_args)
        except ValueError: pass
    if month_from_args:
        try: original_month = int(month_from_args)
        except ValueError: pass


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
            record_data_for_render, error_msg = get_airtable_record_details(selected_personid, record_id)
            if error_msg or record_data_for_render is None:
                flash(error_msg or "❌ レコード情報の再取得に失敗しました。", "error")
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
            flash(f"{message} 更新内容：{detail}", "success")
            session['edited_record_id'] = record_id
        else:
            flash(message, "error")

        try:
            dt = datetime.strptime(new_day, "%Y-%m-%d")
            return redirect(url_for(".records", year=dt.year, month=dt.month))
        except ValueError:
            current_app.logger.warning(f"UI edit_record POST - 更新後の日付形式が無効なため元の年月へリダイレクト: {new_day}")
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