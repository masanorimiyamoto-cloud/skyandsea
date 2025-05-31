from flask import Flask
import os
import logging # logging モジュールをインポート

# データサービスモジュールから初期ロード用関数をインポート
from data_services import (
    load_personid_data,
    load_workcord_data,
    load_workprocess_data
)

# Blueprint をインポート
from blueprints.api import api_bp
from blueprints.ui import ui_bp # 新しく作成したUI Blueprint

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a_very_strong_default_secret_key_for_dev_only_CHANGE_ME")

# ===== ロギング設定 =====
for handler in app.logger.handlers[:]: # 既存のハンドラをクリア
    app.logger.removeHandler(handler)

stream_handler = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(module)s:%(lineno)d]'
)
stream_handler.setFormatter(formatter)
app.logger.addHandler(stream_handler)

if os.environ.get('FLASK_DEBUG') == '1':
    app.debug = True
    app.logger.setLevel(logging.DEBUG)
    stream_handler.setLevel(logging.DEBUG) # ハンドラのレベルも設定
else:
    app.debug = False
    app.logger.setLevel(logging.INFO)
    stream_handler.setLevel(logging.INFO) # ハンドラのレベルも設定

app.logger.info("アプリケーションのロギングが初期化されました。")
app.logger.info(f"FLASK_DEBUG: {os.environ.get('FLASK_DEBUG')}, app.debug: {app.debug}")
# ===== ロギング設定ここまで =====

# Airtable関連の設定や関数は airtable_service.py へ移動したので削除
# AIRTABLE_TOKEN = ...
# HEADERS = ...
# send_record_to_destination(), get_selected_month_records() なども削除

# Blueprint を登録
app.register_blueprint(api_bp)  # /api プレフィックスでAPIルートを登録
app.register_blueprint(ui_bp)   # UIルートを登録 (プレフィックスなしなので / などがそのまま使える)


if __name__ == "__main__":
    app.logger.info("アプリケーション起動: 初期データキャッシュを開始します...")
    try:
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true": # Flaskの開発サーバーでのリロード時に二重実行を防ぐ (本番では不要な場合も)
            app.logger.info("メインプロセスでのみ初期データロードを実行します。")
            load_personid_data()
            load_workcord_data()
            load_workprocess_data()
            app.logger.info("初期データキャッシュが完了しました。")
        else:
             app.logger.info("Flaskリローダープロセスなので初期データロードをスキップします。")
    except Exception as e:
        app.logger.critical(f"アプリケーション起動時の初期データロードに失敗しました: {e}", exc_info=True)
        # ここで処理を中断するかどうかを決定 (例: exit(1))

    from waitress import serve
    port = int(os.environ.get("PORT", 10000))
    app.logger.info(f"サーバをポート {port} で起動します...")
    serve(app, host="0.0.0.0", port=port)