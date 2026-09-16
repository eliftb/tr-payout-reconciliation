import unittest

import rules
from helpers import make_order, make_rule


class PickRuleTest(unittest.TestCase):
    RULES = [
        make_rule(id=1, valid_from="2026-01-01", commission_rate=0.15),
        make_rule(id=2, valid_from="2026-06-01", commission_rate=0.18),
        make_rule(id=3, valid_from="2025-01-01", valid_to="2025-12-31", commission_rate=0.10),
        make_rule(id=4, platform="trendyol", valid_from="2026-01-01", commission_rate=0.20),
    ]

    def pick(self, platform, day):
        r = rules.pick_rule(self.RULES, platform, day)
        return r["id"] if r else None

    def test_past_order_uses_rate_valid_at_order_date(self):
        # Oran Haziran'da değişti; Mart siparişi eski oranla ölçülmeli
        self.assertEqual(self.pick("yemeksepeti", "2026-03-15"), 1)

    def test_newest_start_wins_from_its_first_day(self):
        self.assertEqual(self.pick("yemeksepeti", "2026-05-31"), 1)
        self.assertEqual(self.pick("yemeksepeti", "2026-06-01"), 2)

    def test_valid_to_is_inclusive(self):
        self.assertEqual(self.pick("yemeksepeti", "2025-12-31"), 3)

    def test_no_rule_before_first_start(self):
        self.assertIsNone(self.pick("yemeksepeti", "2024-12-31"))

    def test_rules_do_not_leak_across_platforms(self):
        self.assertEqual(self.pick("trendyol", "2026-07-01"), 4)
        self.assertIsNone(self.pick("getir", "2026-07-01"))


class CommissionBaseTest(unittest.TestCase):
    def test_each_base_kind(self):
        o = make_order()
        cases = {
            "items_before_discount": 200.0,
            "items_after_discount": 180.0,   # sadece restoranın indirimi düşer
            "items_plus_delivery": 195.0,
            "gross": 202.0,
        }
        for kind, want in cases.items():
            with self.subTest(kind=kind):
                got = rules.commission_base_amount(o, make_rule(commission_base=kind))
                self.assertAlmostEqual(got, want, places=2)

    def test_unknown_base_is_an_error_not_a_silent_zero(self):
        with self.assertRaises(ValueError):
            rules.commission_base_amount(make_order(), make_rule(commission_base="net"))


class ExpectedForOrderTest(unittest.TestCase):
    def test_online_order_hand_computed(self):
        exp = rules.expected_for_order(make_order(), make_rule())
        self.assertAlmostEqual(exp["our_revenue"], 187.00, places=2)
        self.assertAlmostEqual(exp["commission_base"], 180.00, places=2)
        self.assertAlmostEqual(exp["commission_total"], 32.40, places=2)
        self.assertAlmostEqual(exp["commission_vat"], 6.48, places=2)
        self.assertAlmostEqual(exp["processing_fee"], 3.84, places=2)
        self.assertAlmostEqual(exp["net"], 144.28, places=2)

    def test_platform_discount_does_not_reduce_restaurant_revenue(self):
        with_disc = rules.expected_for_order(make_order(discount_platform=50.0), make_rule())
        without = rules.expected_for_order(make_order(discount_platform=0.0), make_rule())
        self.assertEqual(with_disc["our_revenue"], without["our_revenue"])
        self.assertEqual(with_disc["commission_total"], without["commission_total"])

    def test_cash_order_restaurant_owes_commission(self):
        # Kapıda ödemede parayı restoran aldı: platform ciro ödemez,
        # komisyon + KDV'sini alacaklıdır. İşlem ücreti yok.
        exp = rules.expected_for_order(make_order(payment_method="cash"), make_rule())
        self.assertAlmostEqual(exp["net"], -38.88, places=2)
        self.assertEqual(exp["processing_fee"], 0.0)

    def test_cancelled_and_refunded_orders_expect_nothing(self):
        for status in ("cancelled", "refunded"):
            with self.subTest(status=status):
                exp = rules.expected_for_order(make_order(status=status), make_rule())
                self.assertEqual(exp["net"], 0.0)
                self.assertEqual(exp["commission_total"], 0.0)

    def test_delivery_fee_kept_by_restaurant(self):
        exp = rules.expected_for_order(make_order(), make_rule(delivery_fee_to="restaurant"))
        self.assertAlmostEqual(exp["net"], 159.28, places=2)

    def test_fixed_fee_is_part_of_commission_and_its_vat(self):
        exp = rules.expected_for_order(make_order(), make_rule(fixed_fee_per_order=2.50))
        self.assertAlmostEqual(exp["commission_total"], 34.90, places=2)
        self.assertAlmostEqual(exp["commission_vat"], 6.98, places=2)
        self.assertAlmostEqual(exp["net"], 141.28, places=2)

    def test_breakdown_ends_with_total_equal_to_net(self):
        exp = rules.expected_for_order(make_order(), make_rule())
        label, amount, _note, kind = exp["lines"][-1]
        self.assertEqual(kind, "total")
        self.assertAlmostEqual(amount, exp["net"], places=2)


class TurkishMoneyFormatTest(unittest.TestCase):
    def test_tl(self):
        self.assertEqual(rules.tl(1234.5), "1.234,50")
        self.assertEqual(rules.tl(-0.5), "-0,50")
        self.assertEqual(rules.tl(1000000), "1.000.000,00")


if __name__ == "__main__":
    unittest.main()
