"""HTTP API entegrasyon testi: gerçek sunucu, geçici veritabanı, örnek dosyalar."""
import http.client
import json
import os
import tempfile
import threading
import unittest
import uuid
from http.server import HTTPServer

import app
import db
from helpers import SAMPLE
from test_sample_regression import BANK_TOTAL, expected_findings


def multipart(fields, filename, content):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, k, v)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
                  'Content-Type: text/csv\r\n\r\n' % (boundary, filename)).encode()
                 + content + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=%s" % boundary


class ParseMultipartTest(unittest.TestCase):
    def test_fields_and_file(self):
        body, ctype = multipart({"kind": "payout_lines"}, "rapor.csv", b"a;b\r\n1;2")
        fields, files = app.parse_multipart(body, ctype)
        self.assertEqual(fields, {"kind": "payout_lines"})
        self.assertEqual(files["file"], ("rapor.csv", b"a;b\r\n1;2"))

    def test_missing_boundary(self):
        self.assertEqual(app.parse_multipart(b"x", "multipart/form-data"), ({}, {}))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._orig_db = db.DB_PATH
        db.DB_PATH = os.path.join(cls.tmp.name, "test.db")
        db.init()
        cls.srv = HTTPServer(("127.0.0.1", 0), app.Handler)
        app.Handler.log_message = lambda *a: None
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        db.DB_PATH = cls._orig_db
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers = {"Content-Type": "application/json"}
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r.getheader("Content-Type", ""), data

    def upload(self, kind, filename, **commit_extra):
        with open(os.path.join(SAMPLE, filename), "rb") as f:
            body, ctype = multipart({"kind": kind}, filename, f.read())
        status, _, data = self.request("POST", "/api/upload/preview", body,
                                       {"Content-Type": ctype})
        self.assertEqual(status, 200, data)
        preview = json.loads(data)
        commit = {"token": preview["token"], "platform": "yemeksepeti",
                  "mapping": preview["mapping"]}
        commit.update(commit_extra)
        status, _, data = self.request("POST", "/api/upload/commit", commit)
        self.assertEqual(status, 200, data)
        return json.loads(data)

    def test_full_flow_on_sample_month(self):
        status, _, _ = self.request("POST", "/api/rules", {
            "platform": "yemeksepeti", "valid_from": "2026-01-01",
            "commission_rate": 0.18, "commission_base": "items_after_discount",
            "payment_processing_rate": 0.0179, "commission_vat_rate": 0.20,
            "delivery_fee_to": "platform"})
        self.assertEqual(status, 200)

        pos = self.upload("pos_orders", "pos_siparisler_2026-08.csv")
        self.assertEqual((pos["imported"], pos["skipped_count"]), (220, 0))
        pay = self.upload("payout_lines", "yemeksepeti_hakedis_2026-08.csv",
                          total_paid=BANK_TOTAL, statement_ref="HAK-2026-08")
        self.assertEqual((pay["imported"], pay["skipped_count"]), (216, 0))

        q = "?platform=yemeksepeti&start=2026-08-01&end=2026-08-31"
        status, _, data = self.request("GET", "/api/reconcile" + q)
        self.assertEqual(status, 200)
        found = {(i["platform_order_id"], i["code"])
                 for i in json.loads(data)["issues"]}
        self.assertEqual(found, expected_findings())

        # İtiraz listesi: Excel için BOM, başlık + 30 satır
        status, ctype, data = self.request("GET", "/api/export" + q)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", ctype)
        text = data.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))
        self.assertEqual(len(text.strip().splitlines()), 31)

        # Aynı dosyayı tekrar yüklemek siparişleri çoğaltmamalı
        again = self.upload("pos_orders", "pos_siparisler_2026-08.csv")
        self.assertEqual(again["imported"], 220)
        _, _, data = self.request("GET", "/api/state")
        self.assertEqual(json.loads(data)["order_total"], 220)

    def test_static_path_traversal_is_blocked(self):
        for path in ("/static/..%2fapp.py", "/static/../app.py", "/static/..%2f..%2fetc%2fpasswd"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertEqual(status, 404)

    def test_commit_requires_order_id_mapping(self):
        with open(os.path.join(SAMPLE, "pos_siparisler_2026-08.csv"), "rb") as f:
            body, ctype = multipart({"kind": "pos_orders"}, "pos.csv", f.read())
        _, _, data = self.request("POST", "/api/upload/preview", body, {"Content-Type": ctype})
        token = json.loads(data)["token"]
        status, _, _ = self.request("POST", "/api/upload/commit",
                                    {"token": token, "platform": "yemeksepeti", "mapping": {}})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
