import io
import unittest
from datetime import date, datetime

import importers as imp


class ToFloatTest(unittest.TestCase):
    def test_formats(self):
        cases = [
            ("1.234,56", 1234.56),       # TR
            ("1,234.56", 1234.56),       # EN
            ("12,5 TL", 12.5),
            ("₺ 99,90", 99.90),
            ("-15,00", -15.0),
            ("300", 300.0),
            (7, 7.0),
            (2.5, 2.5),
            ("", 0.0),
            (None, 0.0),
            ("-", 0.0),
            ("abc", 0.0),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(imp.to_float(raw), want, places=2)


class ToDateTest(unittest.TestCase):
    def test_formats(self):
        cases = [
            ("04.08.2026", "2026-08-04"),
            ("04/08/2026", "2026-08-04"),
            ("04.08.26", "2026-08-04"),
            ("2026-08-04", "2026-08-04"),
            ("2026-08-04 13:45:00", "2026-08-04"),
            ("2026-08-04T13:45:00", "2026-08-04"),
            (datetime(2026, 8, 4, 13, 45), "2026-08-04"),
            (date(2026, 8, 4), "2026-08-04"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(imp.to_date(raw), want)

    def test_empty(self):
        self.assertIsNone(imp.to_date(""))
        self.assertIsNone(imp.to_date(None))


class NormalizeTest(unittest.TestCase):
    def test_dotted_capital_i_does_not_split_words(self):
        # "İ".lower() -> "i" + U+0307; temizlenirken kelime bölünmemeli
        self.assertEqual(imp._norm("Restoran İndirimi"), "restoran indirimi")
        self.assertEqual(imp._norm("SİPARİŞ NO"), "siparis no")

    def test_status(self):
        cases = [
            ("İptal Edildi", "cancelled"),   # düz .lower() ile kaçan durum
            ("İPTAL", "cancelled"),
            ("Cancelled", "cancelled"),
            ("Reddedildi", "cancelled"),
            ("İade Edildi", "refunded"),
            ("Teslim Edildi", "delivered"),
            ("TESLİM EDİLDİ", "delivered"),
            ("", "delivered"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(imp.norm_status(raw), want)

    def test_payment(self):
        cases = [
            ("Kapıda Nakit", "cash"),
            ("Kapıda Kredi Kartı", "card_on_delivery"),
            ("Online Kredi Kartı", "online"),
            ("Cash", "cash"),
            ("", "online"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(imp.norm_payment(raw), want)


class GuessMappingTest(unittest.TestCase):
    def test_sample_pos_headers(self):
        headers = ["Sipariş No", "Sipariş Tarihi", "Ürün Tutarı", "Teslimat Ücreti",
                   "Restoran İndirimi", "Platform İndirimi", "Bahşiş", "Ödeme Tipi", "Durum"]
        self.assertEqual(imp.guess_mapping(headers, "pos_orders"), {
            "platform_order_id": "Sipariş No",
            "order_date": "Sipariş Tarihi",
            "items_subtotal": "Ürün Tutarı",
            "delivery_fee": "Teslimat Ücreti",
            "discount_restaurant": "Restoran İndirimi",
            "discount_platform": "Platform İndirimi",
            "tip": "Bahşiş",
            "payment_method": "Ödeme Tipi",
            "status": "Durum",
        })

    def test_sample_payout_headers(self):
        headers = ["Sipariş No", "Tarih", "Brüt Tutar", "Komisyon", "Komisyon KDV",
                   "Diğer Kesinti", "Net Ödeme", "Açıklama"]
        self.assertEqual(imp.guess_mapping(headers, "payout_lines"), {
            "platform_order_id": "Sipariş No",
            "order_date": "Tarih",
            "gross_reported": "Brüt Tutar",
            "commission_charged": "Komisyon",
            "commission_vat_charged": "Komisyon KDV",
            "other_deductions": "Diğer Kesinti",
            "net_paid": "Net Ödeme",
            "line_note": "Açıklama",
        })

    def test_tip_does_not_capture_payment_type_column(self):
        # 'tip' (bahşiş) terimi 'Ödeme Tipi' içinde alt dize olarak geçer
        m = imp.guess_mapping(["Sipariş No", "Ödeme Tipi"], "pos_orders")
        self.assertNotIn("tip", m)
        self.assertEqual(m["payment_method"], "Ödeme Tipi")

    def test_weak_match_does_not_steal_exact_match(self):
        # 'indirim' hem restoran hem platform indirimine benzer; tam eşleşmeler kazanmalı
        m = imp.guess_mapping(["Platform İndirimi", "Restoran İndirimi"], "pos_orders")
        self.assertEqual(m["discount_platform"], "Platform İndirimi")
        self.assertEqual(m["discount_restaurant"], "Restoran İndirimi")


class ReadTableTest(unittest.TestCase):
    def test_cp1254_semicolon_csv(self):
        data = "Sipariş No;Ürün Tutarı\nYS-1;1.234,56\n".encode("cp1254")
        headers, rows = imp.read_table(data, "pos.csv")
        self.assertEqual(headers, ["Sipariş No", "Ürün Tutarı"])
        self.assertEqual(rows, [{"Sipariş No": "YS-1", "Ürün Tutarı": "1.234,56"}])

    def test_utf8_bom_comma_csv(self):
        data = "﻿order id,subtotal\nA1,12.50\nA2,3.00\n".encode("utf-8")
        headers, rows = imp.read_table(data, "export.csv")
        self.assertEqual(headers, ["order id", "subtotal"])
        self.assertEqual(len(rows), 2)

    @unittest.skipUnless(imp.HAVE_XLSX, "openpyxl kurulu değil")
    def test_xlsx_skips_decoration_rows(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([None, None])                       # üstte boş satır
        ws.append(["Sipariş No", "Tarih"])
        ws.append(["YS-1", datetime(2026, 8, 4)])
        ws.append([None, None])                       # arada boş satır
        ws.append(["YS-2", datetime(2026, 8, 5)])
        buf = io.BytesIO()
        wb.save(buf)
        headers, rows = imp.read_table(buf.getvalue(), "rapor.xlsx")
        self.assertEqual(headers, ["Sipariş No", "Tarih"])
        self.assertEqual([r["Sipariş No"] for r in rows], ["YS-1", "YS-2"])
        self.assertEqual(imp.to_date(rows[0]["Tarih"]), "2026-08-04")


class BuildRecordsTest(unittest.TestCase):
    def test_rows_without_order_id_or_date_are_reported_not_dropped_silently(self):
        mapping = {"platform_order_id": "No", "order_date": "Tarih", "items_subtotal": "Tutar"}
        rows = [
            {"No": "YS-1", "Tarih": "01.08.2026", "Tutar": "100,00"},
            {"No": "", "Tarih": "01.08.2026", "Tutar": "50,00"},
            {"No": "YS-3", "Tarih": "", "Tutar": "70,00"},
        ]
        out, skipped = imp.build_orders(rows, mapping, "yemeksepeti")
        self.assertEqual([o["platform_order_id"] for o in out], ["YS-1"])
        self.assertEqual([line for line, _ in skipped], [3, 4])   # başlık = satır 1

    def test_payout_deductions_are_stored_positive(self):
        # Bazı raporlar kesintileri eksi yazar; motor pozitif bekler
        mapping = {"platform_order_id": "No", "commission_charged": "Komisyon",
                   "commission_vat_charged": "KDV", "other_deductions": "Kesinti",
                   "net_paid": "Net"}
        rows = [{"No": "YS-1", "Komisyon": "-32,40", "KDV": "-6,48",
                 "Kesinti": "-5,00", "Net": "144,28"}]
        out, _ = imp.build_payout_lines(rows, mapping, "yemeksepeti")
        self.assertEqual((out[0]["commission_charged"], out[0]["commission_vat_charged"],
                          out[0]["other_deductions"]), (32.40, 6.48, 5.00))


if __name__ == "__main__":
    unittest.main()
