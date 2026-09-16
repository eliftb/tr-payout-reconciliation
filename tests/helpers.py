"""Testlerde ortak kullanılan sipariş, kural ve hakediş satırı üreticileri."""
import os

import rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "sample")


def make_rule(**kw):
    r = {
        "id": 1, "platform": "yemeksepeti",
        "valid_from": "2026-01-01", "valid_to": None,
        "commission_rate": 0.18, "commission_base": "items_after_discount",
        "fixed_fee_per_order": 0.0, "service_fee_per_order": 0.0,
        "payment_processing_rate": 0.02, "commission_vat_rate": 0.20,
        "delivery_fee_to": "platform", "notes": "",
    }
    r.update(kw)
    return r


def make_order(**kw):
    # Elle hesaplanan referans sipariş (rules testlerindeki rakamlar buna göre):
    #   ciro      = 200 - 20 + 7 (bahşiş)          = 187,00
    #   matrah    = 200 - 20                       = 180,00
    #   komisyon  = 180 x %18                      =  32,40
    #   KDV       = 32,40 x %20                    =   6,48
    #   tahsilat  = 200 - 20 - 10 + 15 + 7         = 192,00
    #   kart ücr. = 192 x %2                       =   3,84
    #   net       = 187 - 32,40 - 6,48 - 3,84      = 144,28
    o = {
        "platform": "yemeksepeti", "platform_order_id": "YS-1",
        "order_date": "2026-08-10",
        "items_subtotal": 200.0, "discount_restaurant": 20.0,
        "discount_platform": 10.0, "delivery_fee": 15.0, "tip": 7.0,
        "payment_method": "online", "status": "delivered",
    }
    o.update(kw)
    return o


def correct_line(order, rule, **kw):
    """Platformun sözleşmeye uygun hesaplasaydı yazacağı hakediş satırı."""
    exp = rules.expected_for_order(order, rule)
    line = {
        "platform": order["platform"],
        "platform_order_id": order["platform_order_id"],
        "order_date": order["order_date"],
        "gross_reported": round(order["items_subtotal"] - order["discount_restaurant"], 2),
        "commission_charged": exp["commission_total"],
        "commission_vat_charged": exp.get("commission_vat", 0.0),
        "other_deductions": 0.0,
        "net_paid": exp["net"],
        "line_note": "",
    }
    line.update(kw)
    return line
