import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import os
import logging # 標準のloggingモジュールを使用

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)
# このロガーの基本的な設定 (app.py側の設定とは独立)
# 必要に応じて、より詳細な設定をここで行うこともできます。
# ここでは、少なくともエラーが見えるように基本的な設定をしておきます。
if not logger.hasHandlers(): # ハンドラが重複しないように
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO) # デフォルトレベル

# ✅ Google Sheets 設定
SERVICE_ACCOUNT_FILE = os.environ.get("SERVICE_ACCOUNT_FILE", "configGooglesheet.json")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "AirtableTest129")
WORKSHEET_NAME = "wsTableCD" # wsTableCD, WorkCord/WorkName/BookName
PERSONID_WORKSHEET_NAME = "wsPersonID" # PersonID/PersonName
WORKPROCESS_WORKSHEET_NAME = "wsWorkProcess" # WorkProcess/UnitPrice

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
    client = gspread.authorize(creds)
except Exception as e:
    logger.critical(f"Google Sheets クライアントの初期化に失敗しました: {e}", exc_info=True)
    # アプリケーションがこれ以上進めない場合、ここでエラーを発生させるか、
    # client が None であることを呼び出し元でチェックするようにする
    client = None # エラー発生時は client を None に

CACHE_TTL = 300  # 300秒 (5分間)

# ===== PersonID データ =====
PERSON_ID_DICT = {}
PERSON_ID_LIST = []
last_personid_load_time = 0

def load_personid_data():
    global PERSON_ID_DICT, PERSON_ID_LIST, last_personid_load_time
    if not client:
        logger.error("Google Sheets クライアントが初期化されていません。PersonIDデータをロードできません。")
        return
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(PERSONID_WORKSHEET_NAME)
        records = sheet.get_all_records()
        temp_dict = {}
        for row in records:
            pid = str(row.get("PersonID", "")).strip()
            pname = str(row.get("PersonName", "")).strip()
            if pid and pname:
                try:
                    pid_int = int(pid)
                    temp_dict[pid_int] = pname
                except ValueError:
                    logger.warning(f"PersonID '{pid}' を整数に変換できませんでした。スキップします。")
                    continue
        PERSON_ID_DICT = temp_dict
        PERSON_ID_LIST = list(PERSON_ID_DICT.keys())
        last_personid_load_time = time.time()
        logger.info(f"Google Sheets から {len(PERSON_ID_DICT)} 件の PersonID/PersonName レコードをロードしました！")
    except Exception as e:
        logger.error(f"Google Sheets の PersonID データ取得に失敗: {e}", exc_info=True)

def get_cached_personid_data():
    if not PERSON_ID_DICT or (time.time() - last_personid_load_time > CACHE_TTL):
        logger.info("PersonIDキャッシュが無効または期限切れです。再ロードします。")
        load_personid_data()
    return PERSON_ID_DICT, PERSON_ID_LIST

# ===== WorkCord/WorkName/BookName キャッシュ =====
workcord_dict = {}
last_workcord_load_time = 0

def load_workcord_data():
    global workcord_dict, last_workcord_load_time
    if not client:
        logger.error("Google Sheets クライアントが初期化されていません。WorkCordデータをロードできません。")
        return
    workcord_dict = {} # 毎回初期化
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(WORKSHEET_NAME)
        records = sheet.get_all_records()
        for row in records:
            workcord = str(row.get("WorkCord", "")).strip()
            workname = str(row.get("WorkName", "")).strip()
            bookname = str(row.get("BookName", "")).strip()
            if workcord and workname: # BookNameは空でも許容するかもしれないので条件から外す場合も
                if workcord not in workcord_dict:
                    workcord_dict[workcord] = []
                workcord_dict[workcord].append({"workname": workname, "bookname": bookname})
        total_records = sum(len(lst) for lst in workcord_dict.values())
        logger.info(f"Google Sheets から {total_records} 件の WorkCD/WorkName/BookName レコードをロードしました！")
        last_workcord_load_time = time.time()
    except Exception as e:
        logger.error(f"Google Sheets の WorkCordデータ取得に失敗: {e}", exc_info=True)

def get_cached_workcord_data():
    if not workcord_dict or (time.time() - last_workcord_load_time > CACHE_TTL):
        logger.info("WorkCordキャッシュが無効または期限切れです。再ロードします。")
        load_workcord_data()
    return workcord_dict

# ===== WorkProcess/UnitPrice データ =====
workprocess_list_cache = []
unitprice_dict_cache = {}
last_workprocess_load_time = 0

def load_workprocess_data():
    global workprocess_list_cache, unitprice_dict_cache, last_workprocess_load_time
    if not client:
        logger.error("Google Sheets クライアントが初期化されていません。WorkProcessデータをロードできません。")
        return
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(WORKPROCESS_WORKSHEET_NAME)
        records = sheet.get_all_records()
        temp_list = []
        temp_dict = {}
        for row in records:
            wp = str(row.get("WorkProcess", "")).strip()
            up_str = str(row.get("UnitPrice", "0")).strip() # 文字列として取得
            if wp:
                temp_list.append(wp)
                try:
                    # UnitPriceをfloatに変換しようと試みる
                    up = float(up_str)
                except ValueError:
                    logger.warning(f"WorkProcess '{wp}' の UnitPrice '{up_str}' をfloatに変換できませんでした。0として扱います。")
                    up = 0.0 # エラーの場合は0または他のデフォルト値
                temp_dict[wp] = up
        workprocess_list_cache = temp_list
        unitprice_dict_cache = temp_dict
        last_workprocess_load_time = time.time()
        logger.info(f"Google Sheets から {len(workprocess_list_cache)} 件の WorkProcess/UnitPrice レコードをロードしました！")
    except Exception as e:
        logger.error(f"Google Sheets の WorkProcessデータ取得に失敗: {e}", exc_info=True)

def get_cached_workprocess_data():
    if not workprocess_list_cache or (time.time() - last_workprocess_load_time > CACHE_TTL):
        logger.info("WorkProcessキャッシュが無効または期限切れです。再ロードします。")
        load_workprocess_data()
    return workprocess_list_cache, unitprice_dict_cache