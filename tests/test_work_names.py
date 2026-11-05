import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


# 実際の認証情報を読み込まず、外部通信は各テストでモックする。
with patch.dict(os.environ, {
    "SERVICE_ACCOUNT_FILE": str(Path(__file__).with_name("missing-credentials.json")),
    "AIRTABLE_TOKEN": "test-token",
    "AIRTABLE_BASE_ID_BookSKY": "test-base",
    "FLASK_SECRET_KEY": "test-secret",
}):
    import airtable_service
    from app import app

import airtable_cache


class WorkNameFlowTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in_personid"] = 99
            session["logged_in_personname"] = "テスト利用者"
        airtable_cache._cache.clear()
        self.addCleanup(airtable_cache._cache.clear)
        # 個別のモックが漏れても実サービスへ接続しない。
        guard = patch("requests.sessions.Session.request", side_effect=AssertionError("External HTTP is disabled"))
        guard.start()
        self.addCleanup(guard.stop)

    @staticmethod
    def response(payload, status=200):
        response = Mock(status_code=status)
        response.json.return_value = payload
        return response

    def test_candidates_clean_exact_and_prefix_matches_without_changing_master(self):
        master = {
            "123": [{"workname": "商品A #管理メモ", "bookname": "書名A"}],
            "1234": [{"workname": "商品B#メモ#追記", "bookname": "書名B"}],
            "999": [{"workname": "別の商品#非表示", "bookname": "書名C"}],
        }
        with patch("blueprints.api.get_cached_workcord_data", return_value=master):
            response = self.client.get("/api/get_worknames?workcd=123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["worknames"], [
            {"code": "123", "workname": "商品A", "bookname": "書名A"},
            {"code": "1234", "workname": "商品B", "bookname": "書名B"},
        ])
        self.assertEqual(master["123"][0]["workname"], "商品A #管理メモ")

    def test_form_sends_clean_name_and_keeps_names_starting_with_hash(self):
        form = {
            "workcd": "1234", "workname": "商品A #管理メモ",
            "bookname_hidden": "書名A", "workoutput": "5",
            "workprocess": "工程A", "workday": "2026-11-03",
        }
        with patch("blueprints.ui.get_cached_workprocess_data", return_value=(["工程A"], {"工程A": 2.5})), \
             patch("blueprints.ui.create_airtable_record", return_value=(201, "送信完了", "recNew")) as create:
            response = self.client.post("/", data=form)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith("/records/2026/11"))
            create.assert_called_once_with("99", "1234", "商品A", "書名A", 5, "工程A", 2.5, "2026-11-03")

            create.reset_mock()
            form["workname"] = " #A12 商品C#追記 "
            response = self.client.post("/", data=form)
            self.assertEqual(response.status_code, 302)
            create.assert_called_once_with("99", "1234", "#A12 商品C#追記", "書名A", 5, "工程A", 2.5, "2026-11-03")

    def test_names_starting_with_hash_are_shown_in_full(self):
        from work_names import normalize_workname
        self.assertEqual(normalize_workname("#A12 商品"), "#A12 商品")
        self.assertEqual(normalize_workname("  #A12#メモ "), "#A12#メモ")
        self.assertEqual(normalize_workname("商品A #管理メモ"), "商品A")
        self.assertEqual(normalize_workname(None), "")

    def test_create_saves_clean_name_in_airtable_and_month_cache(self):
        key = airtable_cache.month_key("99", 2026, 11)
        airtable_cache.cache_set(key, [], 60)
        with patch.object(airtable_service.requests, "post", return_value=self.response({"id": "recNew"}, 201)) as post:
            status, _, record_id = airtable_service.create_airtable_record(
                "99", "1234", " 商品A #管理メモ#追記 ", "書名A", 5, "工程A", 2.5, "2026-11-03"
            )
        self.assertEqual((status, record_id), (201, "recNew"))
        fields = post.call_args.kwargs["json"]["fields"]
        self.assertEqual(fields["WorkName"], "商品A")
        self.assertEqual(fields["BookName"], "書名A")
        self.assertEqual(airtable_cache.cache_get(key)[0]["WorkName"], "商品A")

    def test_existing_record_is_clean_in_list_cache_and_edit_without_writes(self):
        fields = {
            "WorkName": "既存商品 #古い管理メモ", "WorkCord": 1234,
            "WorkDay": "2026-11-03", "WorkProcess": "工程A",
            "UnitPrice": 2.5, "WorkOutput": 5,
        }
        responses = [
            self.response({"records": [{"id": "recOld", "fields": fields}]}),
            self.response({"fields": fields}),
        ]
        with patch.object(airtable_service.requests, "get", side_effect=responses) as get, \
             patch("blueprints.ui.get_cached_personid_data", return_value=({99: {"name": "テスト利用者"}}, [99])):
            for url in ("/records/2026/11", "/records/2026/11", "/edit_record/recOld?year=2026&month=11"):
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertIn("既存商品", html)
                    self.assertNotIn("古い管理メモ", html)
            self.assertEqual(get.call_count, 2)
        cached = airtable_cache.cache_get(airtable_cache.month_key("99", 2026, 11))
        self.assertEqual(cached[0]["WorkName"], "既存商品")

    def test_update_cleans_name_without_mutating_callers_fields(self):
        original = {"WorkName": "商品A#管理メモ", "WorkOutput": 5}
        with patch.object(airtable_service.requests, "patch", return_value=self.response({})) as update:
            success, _ = airtable_service.update_airtable_record_fields("99", "recOld", original)
        self.assertTrue(success)
        self.assertEqual(update.call_args.kwargs["json"]["fields"], {"WorkName": "商品A", "WorkOutput": 5})
        self.assertEqual(original["WorkName"], "商品A#管理メモ")


if __name__ == "__main__":
    unittest.main()
