"""Uçtan uca: örnek aya bilerek yerleştirilen hataların tamamı, fazlası olmadan bulunmalı."""
import csv
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import importers as imp
import reconcile
from helpers import ROOT, SAMPLE, make_rule

# Örnek veri üreticisinin kullandığı sözleşme (make_sample.py)
SAMPLE_RULE = make_rule(commission_rate=0.18, commission_base="items_after_discount",
                        payment_processing_rate=0.0179, commission_vat_rate=0.20,
                        delivery_fee_to="platform")
# README'de yazan "bankaya geçen tutar"
BANK_TOTAL = 63155.16


def load(name, kind):
    with open(os.path.join(SAMPLE, name), "rb") as f:
        headers, rows = imp.read_table(f.read(), name)
    mapping = imp.guess_mapping(headers, kind)
    if kind == "pos_orders":
        return imp.build_orders(rows, mapping, "yemeksepeti")
    return imp.build_payout_lines(rows, mapping, "yemeksepeti")


def expected_findings():
    with open(os.path.join(SAMPLE, "beklenen_hatalar.csv"), encoding="utf-8-sig") as f:
        return {(r["Sipariş No"], r["Hata Kodu"], imp.to_float(r["Tutar"]))
                for r in csv.DictReader(f, delimiter=";")}


class SampleMonthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        orders, skipped_o = load("pos_siparisler_2026-08.csv", "pos_orders")
        lines, skipped_l = load("yemeksepeti_hakedis_2026-08.csv", "payout_lines")
        assert not skipped_o and not skipped_l
        cls.orders, cls.lines = orders, lines
        cls.result = reconcile.reconcile_period(orders, lines, [SAMPLE_RULE], BANK_TOTAL)

    def test_input_sizes(self):
        self.assertEqual(len(self.orders), 220)
        self.assertEqual(len(self.lines), 216)

    def test_bank_total_in_readme_matches_sample(self):
        planted_lump_sum = 1850.00
        self.assertAlmostEqual(sum(l["net_paid"] for l in self.lines) - planted_lump_sum,
                               BANK_TOTAL, places=2)

    def test_every_planted_error_found_with_amount_and_nothing_else(self):
        found = {(i["platform_order_id"], i["code"], i["amount"])
                 for i in self.result["issues"]}
        want = expected_findings()
        self.assertEqual(len(want), 30)
        self.assertEqual(found - want, set(), "fazladan bulgu (yanlış alarm)")
        self.assertEqual(want - found, set(), "kaçırılan hata")

    def test_whole_shortfall_is_attributed(self):
        s = self.result["summary"]
        self.assertGreater(s["shortfall"], 0)
        self.assertAlmostEqual(s["explained"], s["shortfall"], places=2)
        self.assertAlmostEqual(s["unexplained"], 0.0, places=2)


class SampleGeneratorTest(unittest.TestCase):
    def test_committed_sample_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(ROOT, "make_sample.py"), tmp)
            subprocess.run([sys.executable, "make_sample.py"], cwd=tmp, check=True,
                           stdout=subprocess.DEVNULL)
            for name in sorted(os.listdir(SAMPLE)):
                with self.subTest(file=name):
                    self.assertTrue(filecmp.cmp(os.path.join(SAMPLE, name),
                                                os.path.join(tmp, "sample", name),
                                                shallow=False))


if __name__ == "__main__":
    unittest.main()
