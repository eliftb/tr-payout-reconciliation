#!/usr/bin/env python3
"""Hakediş Mutabakat Paneli — yerel web sunucusu.

Harici web çatısı kullanılmaz: makinede çalışır, veri dışarı çıkmaz,
kurulum gerektirmez. python3 app.py -> http://127.0.0.1:8770
"""
import json
import os
import re
import sqlite3
import sys
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

import db
import rules as rules_mod
import reconcile as rec
import importers as imp

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")

# Yüklenen dosyanın ayrıştırılmış hali: önizleme ile onay arasında burada bekler.
UPLOAD_CACHE = {}


# ------------------------------------------------------------------
# multipart/form-data ayrıştırma (stdlib cgi modülü 3.13'te kaldırıldı)
# ------------------------------------------------------------------
def parse_multipart(body, content_type):
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        return {}, {}
    boundary = ("--" + m.group(1)).encode()
    fields, files = {}, {}
    for part in body.split(boundary):
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_head, data = part.split(b"\r\n\r\n", 1)
        data = data.rstrip(b"\r\n")
        head = raw_head.decode("utf-8", "replace")
        name_m = re.search(r'name="([^"]*)"', head)
        if not name_m:
            continue
        name = name_m.group(1)
        fn_m = re.search(r'filename="([^"]*)"', head)
        if fn_m and fn_m.group(1):
            files[name] = (fn_m.group(1), data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


# ------------------------------------------------------------------
# Veri erişimi
# ------------------------------------------------------------------
def get_rules(conn, platform=None):
    if platform:
        cur = conn.execute("SELECT * FROM commission_rules WHERE platform=? ORDER BY valid_from", (platform,))
    else:
        cur = conn.execute("SELECT * FROM commission_rules ORDER BY platform, valid_from")
    return db.rows_to_dicts(cur.fetchall())


def get_orders(conn, platform, start, end):
    q = "SELECT * FROM orders WHERE order_date>=? AND order_date<=?"
    p = [start, end]
    if platform and platform != "all":
        q += " AND platform=?"
        p.append(platform)
    return db.rows_to_dicts(conn.execute(q + " ORDER BY order_date, platform_order_id", p).fetchall())


def get_payout_lines(conn, platform, start, end):
    q = ("SELECT pl.* FROM payout_lines pl JOIN payouts p ON p.id=pl.payout_id "
         "WHERE p.period_end>=? AND p.period_start<=?")
    p = [start, end]
    if platform and platform != "all":
        q += " AND pl.platform=?"
        p.append(platform)
    return db.rows_to_dicts(conn.execute(q, p).fetchall())


def get_bank_total(conn, platform, start, end):
    q = ("SELECT SUM(total_paid) t FROM payouts WHERE period_end>=? AND period_start<=? "
         "AND total_paid<>0")
    p = [start, end]
    if platform and platform != "all":
        q += " AND platform=?"
        p.append(platform)
    row = conn.execute(q, p).fetchone()
    return row["t"] if row and row["t"] else None


def run_reconcile(conn, platform, start, end):
    orders = get_orders(conn, platform, start, end)
    lines = get_payout_lines(conn, platform, start, end)
    rule_rows = get_rules(conn)
    bank = get_bank_total(conn, platform, start, end)
    out = rec.reconcile_period(orders, lines, rule_rows, bank)

    # Açık itirazları sonuca iliştir
    open_d = {}
    for d in db.rows_to_dicts(conn.execute("SELECT * FROM disputes").fetchall()):
        open_d[(d["platform"], d["platform_order_id"], d["issue_code"])] = d
    for i in out["issues"]:
        d = open_d.get((i["platform"], i["platform_order_id"], i["code"]))
        i["dispute_status"] = d["status"] if d else None
    return out


# ------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "HakedisPanel"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- yardımcılar --
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self):
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    # -- GET --
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if u.path.startswith("/static/"):
                return self._serve_static(u.path[len("/static/"):])
            if u.path == "/api/state":
                return self._api_state()
            if u.path == "/api/rules":
                with db.connect() as c:
                    return self._send(200, get_rules(c))
            if u.path == "/api/reconcile":
                return self._api_reconcile(q)
            if u.path == "/api/export":
                return self._api_export(q)
            if u.path.startswith("/api/order/"):
                return self._api_order(u.path)
            self._send(404, {"error": "bulunamadı"})
        except Exception as e:
            import traceback; traceback.print_exc()
            self._send(500, {"error": str(e)})

    # -- POST --
    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/upload/preview":
                return self._api_preview()
            if u.path == "/api/upload/commit":
                return self._api_commit()
            if u.path == "/api/rules":
                return self._api_rule_save()
            if u.path == "/api/payout/total":
                return self._api_payout_total()
            if u.path == "/api/dispute":
                return self._api_dispute()
            self._send(404, {"error": "bulunamadı"})
        except Exception as e:
            import traceback; traceback.print_exc()
            self._send(500, {"error": str(e)})

    def do_DELETE(self):
        u = urlparse(self.path)
        try:
            m = re.match(r"^/api/rules/(\d+)$", u.path)
            if m:
                with db.connect() as c:
                    c.execute("DELETE FROM commission_rules WHERE id=?", (int(m.group(1)),))
                    c.commit()
                return self._send(200, {"ok": True})
            m = re.match(r"^/api/data/(orders|payouts)$", u.path)
            if m:
                with db.connect() as c:
                    if m.group(1) == "orders":
                        c.execute("DELETE FROM orders")
                    else:
                        c.execute("DELETE FROM payouts")
                    c.commit()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "bulunamadı"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    # -- statik --
    def _serve_static(self, rel):
        rel = unquote(rel).lstrip("/")
        path = os.path.normpath(os.path.join(STATIC, rel))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._send(404, "bulunamadı", "text/plain; charset=utf-8")
        ctype = ("text/html; charset=utf-8" if path.endswith(".html")
                 else "text/css; charset=utf-8" if path.endswith(".css")
                 else "application/javascript; charset=utf-8" if path.endswith(".js")
                 else "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # -- API --
    def _api_state(self):
        with db.connect() as c:
            stats = c.execute(
                "SELECT platform, COUNT(*) n, MIN(order_date) mn, MAX(order_date) mx "
                "FROM orders GROUP BY platform").fetchall()
            pay = c.execute(
                "SELECT platform, COUNT(*) n, MIN(period_start) mn, MAX(period_end) mx, "
                "SUM(total_paid) tot FROM payouts GROUP BY platform").fetchall()
            self._send(200, {
                "orders": db.rows_to_dicts(stats),
                "payouts": db.rows_to_dicts(pay),
                "rules": get_rules(c),
                "order_total": c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"],
                "line_total": c.execute("SELECT COUNT(*) n FROM payout_lines").fetchone()["n"],
            })

    def _api_preview(self):
        fields, files = parse_multipart(self._body(), self.headers.get("Content-Type", ""))
        if "file" not in files:
            return self._send(400, {"error": "Dosya bulunamadı"})
        fname, data = files["file"]
        kind = fields.get("kind", "pos_orders")
        headers, rows = imp.read_table(data, fname)
        if not rows:
            return self._send(400, {"error": "Dosyada veri satırı yok"})
        token = uuid.uuid4().hex
        UPLOAD_CACHE[token] = {"headers": headers, "rows": rows,
                               "filename": fname, "kind": kind}
        self._send(200, {
            "token": token, "filename": fname, "kind": kind,
            "headers": headers, "row_count": len(rows),
            "mapping": imp.guess_mapping(headers, kind),
            "sample": [{k: ("" if v is None else str(v)) for k, v in r.items()}
                       for r in rows[:5]],
            "fields": (list(imp.POS_SYNONYMS.keys()) if kind == "pos_orders"
                       else list(imp.PAYOUT_SYNONYMS.keys())),
        })

    def _api_commit(self):
        p = self._json_body()
        cached = UPLOAD_CACHE.get(p.get("token"))
        if not cached:
            return self._send(400, {"error": "Yükleme oturumu bulunamadı, dosyayı tekrar seçin"})
        platform = p.get("platform")
        mapping = p.get("mapping") or {}
        if not platform:
            return self._send(400, {"error": "Platform seçilmedi"})
        if not mapping.get("platform_order_id"):
            return self._send(400, {"error": "Sipariş No sütunu eşlenmeli — eşleme anahtarı budur"})

        conn = db.connect()
        if cached["kind"] == "pos_orders":
            recs, skipped = imp.build_orders(cached["rows"], mapping, platform, cached["filename"])
            ins = upd = 0
            for r in recs:
                cur = conn.execute(
                    "INSERT INTO orders (platform,platform_order_id,order_date,items_subtotal,"
                    "delivery_fee,discount_restaurant,discount_platform,tip,payment_method,"
                    "status,source_file) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(platform,platform_order_id) DO UPDATE SET "
                    "order_date=excluded.order_date, items_subtotal=excluded.items_subtotal,"
                    "delivery_fee=excluded.delivery_fee,"
                    "discount_restaurant=excluded.discount_restaurant,"
                    "discount_platform=excluded.discount_platform, tip=excluded.tip,"
                    "payment_method=excluded.payment_method, status=excluded.status,"
                    "source_file=excluded.source_file",
                    (r["platform"], r["platform_order_id"], r["order_date"], r["items_subtotal"],
                     r["delivery_fee"], r["discount_restaurant"], r["discount_platform"],
                     r["tip"], r["payment_method"], r["status"], r["source_file"]))
                if cur.rowcount == 1:
                    ins += 1
                else:
                    upd += 1
            conn.commit()
            result = {"ok": True, "kind": "pos_orders", "imported": len(recs),
                      "inserted": ins, "updated": upd, "skipped": skipped[:20],
                      "skipped_count": len(skipped)}
        else:
            recs, skipped = imp.build_payout_lines(cached["rows"], mapping, platform)
            dates = sorted(r["order_date"] for r in recs if r["order_date"])
            ps = p.get("period_start") or (dates[0] if dates else "1970-01-01")
            pe = p.get("period_end") or (dates[-1] if dates else "2100-01-01")
            ref = p.get("statement_ref") or cached["filename"]
            total = float(p.get("total_paid") or 0)
            conn.execute("DELETE FROM payouts WHERE platform=? AND statement_ref=?", (platform, ref))
            cur = conn.execute(
                "INSERT INTO payouts (platform,period_start,period_end,statement_ref,"
                "total_paid,source_file) VALUES (?,?,?,?,?,?)",
                (platform, ps, pe, ref, total, cached["filename"]))
            pid = cur.lastrowid
            for r in recs:
                conn.execute(
                    "INSERT INTO payout_lines (payout_id,platform,platform_order_id,order_date,"
                    "gross_reported,commission_charged,commission_vat_charged,other_deductions,"
                    "net_paid,line_note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, r["platform"], r["platform_order_id"], r["order_date"],
                     r["gross_reported"], r["commission_charged"], r["commission_vat_charged"],
                     r["other_deductions"], r["net_paid"], r["line_note"]))
            conn.commit()
            result = {"ok": True, "kind": "payout_lines", "imported": len(recs),
                      "period_start": ps, "period_end": pe, "payout_id": pid,
                      "skipped": skipped[:20], "skipped_count": len(skipped)}
        conn.close()
        UPLOAD_CACHE.pop(p["token"], None)
        self._send(200, result)

    def _api_rule_save(self):
        p = self._json_body()
        conn = db.connect()
        vals = (p["platform"], p["valid_from"], p.get("valid_to") or None,
                float(p["commission_rate"]), p.get("commission_base", "items_after_discount"),
                float(p.get("fixed_fee_per_order") or 0),
                float(p.get("payment_processing_rate") or 0),
                float(p.get("commission_vat_rate") or 0.20),
                p.get("delivery_fee_to", "platform"),
                float(p.get("service_fee_per_order") or 0), p.get("notes") or "")
        if p.get("id"):
            conn.execute(
                "UPDATE commission_rules SET platform=?,valid_from=?,valid_to=?,"
                "commission_rate=?,commission_base=?,fixed_fee_per_order=?,"
                "payment_processing_rate=?,commission_vat_rate=?,delivery_fee_to=?,"
                "service_fee_per_order=?,notes=? WHERE id=?", vals + (int(p["id"]),))
        else:
            conn.execute(
                "INSERT INTO commission_rules (platform,valid_from,valid_to,commission_rate,"
                "commission_base,fixed_fee_per_order,payment_processing_rate,"
                "commission_vat_rate,delivery_fee_to,service_fee_per_order,notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", vals)
        conn.commit(); conn.close()
        self._send(200, {"ok": True})

    def _api_payout_total(self):
        p = self._json_body()
        conn = db.connect()
        conn.execute("UPDATE payouts SET total_paid=? WHERE id=?",
                     (float(p["total_paid"]), int(p["payout_id"])))
        conn.commit(); conn.close()
        self._send(200, {"ok": True})

    def _api_dispute(self):
        p = self._json_body()
        conn = db.connect()
        conn.execute(
            "INSERT INTO disputes (platform,platform_order_id,amount,issue_code,status,note) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(platform,platform_order_id,issue_code) "
            "DO UPDATE SET status=excluded.status, note=excluded.note, "
            "resolved_at=CASE WHEN excluded.status IN ('accepted','rejected','recovered') "
            "THEN datetime('now') ELSE NULL END",
            (p["platform"], p["platform_order_id"], float(p.get("amount") or 0),
             p["issue_code"], p.get("status", "open"), p.get("note", "")))
        conn.commit(); conn.close()
        self._send(200, {"ok": True})

    def _api_reconcile(self, q):
        platform = (q.get("platform") or ["all"])[0]
        start = (q.get("start") or ["1970-01-01"])[0]
        end = (q.get("end") or ["2100-01-01"])[0]
        with db.connect() as c:
            self._send(200, run_reconcile(c, platform, start, end))

    def _api_order(self, path):
        m = re.match(r"^/api/order/([^/]+)/(.+)$", path)
        if not m:
            return self._send(404, {"error": "bulunamadı"})
        platform, oid = unquote(m.group(1)), unquote(m.group(2))
        conn = db.connect()
        o = conn.execute("SELECT * FROM orders WHERE platform=? AND platform_order_id=?",
                         (platform, oid)).fetchone()
        lines = db.rows_to_dicts(conn.execute(
            "SELECT * FROM payout_lines WHERE platform=? AND platform_order_id=?",
            (platform, oid)).fetchall())
        if not o:
            conn.close()
            return self._send(200, {"order": None, "payout_lines": lines,
                                    "breakdown": [], "expected": None})
        o = dict(o)
        rule = rules_mod.pick_rule(get_rules(conn), platform, o["order_date"])
        conn.close()
        if not rule:
            return self._send(200, {"order": o, "payout_lines": lines,
                                    "breakdown": [], "expected": None,
                                    "error": "Bu tarih için komisyon kuralı yok"})
        exp = rules_mod.expected_for_order(o, rule)
        self._send(200, {"order": o, "payout_lines": lines, "rule": rule,
                         "expected": exp["net"],
                         "breakdown": [{"label": a, "amount": b, "note": c, "kind": d}
                                       for a, b, c, d in exp["lines"]]})

    def _api_export(self, q):
        platform = (q.get("platform") or ["all"])[0]
        start = (q.get("start") or ["1970-01-01"])[0]
        end = (q.get("end") or ["2100-01-01"])[0]
        with db.connect() as c:
            out = run_reconcile(c, platform, start, end)
        import io as _io, csv as _csv
        buf = _io.StringIO()
        w = _csv.writer(buf, delimiter=";")
        w.writerow(["Platform", "Sipariş No", "Tarih", "Sorun", "Tutar (TL)", "Açıklama", "Durum"])
        for i in sorted(out["issues"], key=lambda x: -x["amount"]):
            w.writerow([i["platform"], i["platform_order_id"], i["order_date"] or "",
                        i["title"], ("%.2f" % i["amount"]).replace(".", ","),
                        i["detail"], i.get("dispute_status") or "açık"])
        body = "﻿" + buf.getvalue()   # BOM: Excel Türkçe karakterleri doğru açsın
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="itiraz_listesi_%s_%s.csv"' % (start, end))
        b = body.encode("utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def main():
    db.init()
    port = int(os.environ.get("PORT", "8770"))
    srv = HTTPServer(("127.0.0.1", port), Handler)
    print("\n  Hakediş Mutabakat Paneli")
    print("  http://127.0.0.1:%d\n" % port)
    print("  Veritabanı: %s" % db.DB_PATH)
    print("  Durdurmak için Ctrl+C\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Kapatıldı.")


if __name__ == "__main__":
    main()
