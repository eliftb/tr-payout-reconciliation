import unittest

import reconcile
from helpers import correct_line, make_order, make_rule


def codes(result):
    return sorted(i["code"] for i in result["issues"])


def amount(result, code):
    return sum(i["amount"] for i in result["issues"] if i["code"] == code)


class SingleOrderTest(unittest.TestCase):
    """Her senaryo sözleşmeye uygun bir hakediş satırını tek noktadan bozar."""

    def setUp(self):
        self.rule = make_rule()
        self.order = make_order()                      # beklenen net 144,28

    def run_one(self, lines, orders=None, payout_total=None):
        orders = [self.order] if orders is None else orders
        return reconcile.reconcile_period(orders, lines, [self.rule], payout_total)

    def assert_fully_explained(self, res):
        self.assertAlmostEqual(res["summary"]["unexplained"], 0.0, places=2)

    def test_correct_payout_has_no_issues(self):
        res = self.run_one([correct_line(self.order, self.rule)])
        self.assertEqual(codes(res), [])
        self.assertEqual(res["summary"]["shortfall"], 0.0)

    def test_missing_from_payout(self):
        res = self.run_one([])
        self.assertEqual(codes(res), ["MISSING_FROM_PAYOUT"])
        self.assertAlmostEqual(amount(res, "MISSING_FROM_PAYOUT"), 144.28, places=2)

    def test_cancelled_order_missing_from_payout_is_fine(self):
        res = self.run_one([], orders=[make_order(status="cancelled")])
        self.assertEqual(codes(res), [])

    def test_rate_mismatch_is_the_only_cause(self):
        # %18 yerine %21: 180 x %21 = 37,80 ; KDV 7,56 ; net 137,80 -> eksik 6,48
        line = correct_line(self.order, self.rule, commission_charged=37.80,
                            commission_vat_charged=7.56, net_paid=137.80)
        res = self.run_one([line])
        # Aynı para ayrıca COMMISSION_OVERCHARGE ya da UNDERPAID diye sayılmamalı
        self.assertEqual(codes(res), ["RATE_MISMATCH"])
        self.assertAlmostEqual(amount(res, "RATE_MISMATCH"), 6.48, places=2)
        self.assertAlmostEqual(res["summary"]["shortfall"], 6.48, places=2)
        self.assert_fully_explained(res)

    def test_small_overcharge_at_correct_rate(self):
        # 33,20 / 180 = %18,44 -> oran eşiğinin (0,5 puan) altında, tutar fazla
        line = correct_line(self.order, self.rule, commission_charged=33.20,
                            commission_vat_charged=6.64, net_paid=143.32)
        res = self.run_one([line])
        self.assertEqual(codes(res), ["COMMISSION_OVERCHARGE"])
        self.assertAlmostEqual(amount(res, "COMMISSION_OVERCHARGE"), 0.96, places=2)
        self.assert_fully_explained(res)

    def test_commission_on_cancelled_order(self):
        order = make_order(status="cancelled")
        line = correct_line(order, self.rule, commission_charged=32.40,
                            commission_vat_charged=6.48, net_paid=-38.88)
        res = self.run_one([line], orders=[order])
        self.assertEqual(codes(res), ["CHARGED_ON_CANCELLED"])
        self.assertAlmostEqual(amount(res, "CHARGED_ON_CANCELLED"), 38.88, places=2)
        self.assert_fully_explained(res)

    def test_deduction_without_reason(self):
        line = correct_line(self.order, self.rule, other_deductions=25.0, net_paid=119.28)
        res = self.run_one([line])
        self.assertEqual(codes(res), ["UNKNOWN_DEDUCTION"])
        self.assert_fully_explained(res)

    def test_deduction_with_reason_is_still_an_unexplained_shortfall(self):
        # Gerekçe yazılı olması kesintiyi haklı kılmaz; sözleşmede yoksa eksik ödemedir
        line = correct_line(self.order, self.rule, other_deductions=25.0, net_paid=119.28,
                            line_note="Reklam bedeli")
        res = self.run_one([line])
        self.assertEqual(codes(res), ["UNDERPAID"])
        self.assertAlmostEqual(amount(res, "UNDERPAID"), 25.0, places=2)

    def test_platform_campaign_charged_to_restaurant(self):
        # Brüt 180 olmalı; platform kendi 10 TL indirimini düşüp 170 yazmış
        line = correct_line(self.order, self.rule, gross_reported=170.0, net_paid=134.28)
        res = self.run_one([line])
        self.assertEqual(codes(res), ["PLATFORM_DISCOUNT_CHARGED"])
        self.assertAlmostEqual(amount(res, "PLATFORM_DISCOUNT_CHARGED"), 10.0, places=2)
        self.assert_fully_explained(res)

    def test_line_without_pos_record(self):
        orphan = correct_line(make_order(platform_order_id="YS-999"), self.rule)
        res = self.run_one([correct_line(self.order, self.rule), orphan])
        self.assertEqual(codes(res), ["NOT_IN_POS"])

    def test_rounding_noise_is_ignored(self):
        line = correct_line(self.order, self.rule, net_paid=144.27)
        self.assertEqual(codes(self.run_one([line])), [])

    def test_order_without_rule(self):
        order = make_order(order_date="2025-06-01")
        res = self.run_one([correct_line(order, self.rule)], orders=[order])
        self.assertIn("NO_RULE", codes(res))


class PeriodTotalTest(unittest.TestCase):
    def setUp(self):
        self.rule = make_rule()
        self.orders = [make_order(platform_order_id="YS-%d" % i) for i in range(3)]
        self.lines = [correct_line(o, self.rule) for o in self.orders]
        self.line_sum = round(sum(l["net_paid"] for l in self.lines), 2)

    def run_total(self, payout_total, orders=None):
        return reconcile.reconcile_period(orders or self.orders, self.lines,
                                          [self.rule], payout_total)

    def test_bank_matches_statement(self):
        self.assertEqual(codes(self.run_total(self.line_sum)), [])

    def test_lump_sum_deduction(self):
        res = self.run_total(self.line_sum - 50.0)
        self.assertEqual(codes(res), ["PERIOD_TOTAL_MISMATCH"])
        self.assertAlmostEqual(amount(res, "PERIOD_TOTAL_MISMATCH"), -50.0, places=2)

    def test_sub_lira_difference_is_tolerated(self):
        self.assertEqual(codes(self.run_total(self.line_sum - 0.5)), [])

    def test_bank_check_counts_lines_of_orders_without_rule(self):
        # Kuralı eksik siparişin satırı da bankaya yatan paranın içinde.
        # NO_RULE uyarısı yeterli; ayrıca sahte bir "toplu kesinti" çıkmamalı.
        orders = list(self.orders)
        orders[0] = make_order(platform_order_id="YS-0", order_date="2025-06-01")
        self.assertEqual(codes(self.run_total(self.line_sum, orders=orders)), ["NO_RULE"])



if __name__ == "__main__":
    unittest.main()
