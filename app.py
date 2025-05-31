import os
import logging
from flask import Flask

# データサービスモジュールから初期ロード用関数をインポート
from data_services import (
    load_personid_data,
    load_workcord_data,
    load_workprocess_data
)

# Blueprint をインポート
from blueprints.api import api_bp
from blueprints.ui import ui_bp

def create_app(config_object=None): # config_objectは将来的な設定拡張用（今回は未使用）
    """Flaskアプリケーションインスタンスを生成して設定するファクトリ関数"""
    
    app = Flask(__name__, instance_relative_config=True) # instance_relative_config=True は将来的にinstanceフォルダから設定を読み込む場合に便利

    # --- 設定の読み込み ---
    # app.config.from_object(config_object or 'your_app.default_config_module') # 設定モジュールから読み込む場合
    # app.config.from_pyfile('application.cfg', silent=True) # instanceフォルダの設定ファイルから読み込む場合
    
    # SECRET_KEY の設定 (環境変数から)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a_very_strong_default_secret_key_for_dev_only_CHANGE_ME_IN_FACTORY")
    if app.secret_key == "a_very_strong_default_secret_key_for_dev_only_CHANGE_ME_IN_FACTORY" and not app.debug:
        # 本番モードでデフォルトキーが使われている場合は警告（またはエラー）
        app.logger.critical("本番環境でデフォルトのSECRET_KEYが使用されています！必ず変更してください。")


    # --- ロギング設定 ---
    for handler in app.logger.handlers[:]: # 既存のハンドラをクリア
        app.logger.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(module)s:%(lineno)d]'
    )
    stream_handler.setFormatter(formatter)
    app.logger.addHandler(stream_handler)

    if os.environ.get('FLASK_DEBUG') == '1' or app.config.get('DEBUG'):
        app.debug = True # Flaskのデバッグモードを有効化
        app.logger.setLevel(logging.DEBUG)
        stream_handler.setLevel(logging.DEBUG)
    else:
        app.debug = False
        app.logger.setLevel(logging.INFO)
        stream_handler.setLevel(logging.INFO)
    
    app.logger.info("アプリケーションのロギングが初期化されました (in create_app)。")
    app.logger.info(f"FLASK_DEBUG: {os.environ.get('FLASK_DEBUG')}, app.debug: {app.debug} (in create_app)")


    # --- Blueprint の登録 ---
    app.register_blueprint(api_bp)
    app.register_blueprint(ui_bp)
    app.logger.info("Blueprints が登録されました (in create_app)。")

    # --- ここに他のFlask拡張機能の初期化などを追加できます ---
    # 例: db.init_app(app), mail.init_app(app)

    return app

# --- アプリケーションインスタンスの作成 ---
# Gunicorn や Waitress が `app:app` という形で参照できるように、
# モジュールレベルで app インスタンスを作成します。
app = create_app()

# --- アプリケーション起動時の初期処理 (データキャッシュなど) ---
# この部分は、メインプロセスでのみ実行されるように制御します。
# (Flask開発サーバーのリロード時や、Gunicornの複数ワーカー環境を考慮)
# 実際の初期化は、CLIコマンドやアプリケーションコンテキストを利用した方がより堅牢ですが、
# ここではシンプルな形を示します。
if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and not app.debug: # 本番環境（Gunicorn/Waitress）やFlask CLIで起動した場合
    with app.app_context(): # アプリケーションコンテキスト内で実行
        app.logger.info("メインプロセスでのみ初期データロードを実行します (in app.py global scope)。")
        try:
            load_personid_data()
            load_workcord_data()
            load_workprocess_data()
            app.logger.info("初期データキャッシュが完了しました (in app.py global scope)。")
        except Exception as e:
            app.logger.critical(f"初期データロードに失敗しました: {e}", exc_info=True)
elif app.debug and os.environ.get("WERKZEUG_RUN_MAIN") == "true": # Flask開発サーバー（werkzeugリローダーのメインプロセス）
    with app.app_context():
        app.logger.info("Flask開発サーバー（メインプロセス）で初期データロードを実行します。")
        try:
            load_personid_data()
            load_workcord_data()
            load_workprocess_data()
            app.logger.info("初期データキャッシュが完了しました (Flask開発サーバー)。")
        except Exception as e:
            app.logger.critical(f"初期データロードに失敗しました (Flask開発サーバー): {e}", exc_info=True)


# --- サーバー起動 (ローカル開発時) ---
if __name__ == "__main__":
    # 開発時には create_app() を直接呼び出す代わりに、上で作成された app インスタンスを使用
    # 初期データロードは既に app インスタンス作成後に行われている想定
    
    # FLASK_DEBUGが設定されていない場合、ここで明示的にapp.debugをTrueにすることも検討
    # if os.environ.get('FLASK_ENV') == 'development':
    #    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    # else:
    # 本番環境で `python app.py` を直接実行する場合は Waitress を使う
    from waitress import serve
    port = int(os.environ.get("PORT", 10000))
    app.logger.info(f"Waitressサーバをポート {port} で起動します (from if __name__ == '__main__')...")
    serve(app, host="0.0.0.0", port=port)