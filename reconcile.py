"""Mutabakat motoru: POS gerçeği ile platform hakedişini sipariş bazında
karşılaştırır, farkı bulur ve SEBEBİNİ sınıflandırır.

Sadece "eksik ödediler" demek işe yaramaz; platform "hangi siparişte,
neden?" diye sorar. Bu modül her farka bir kod ve gerekçe üretir.
"""
import rules
from rules import r2, tl

# Kuruş yuvarlamasından doğan gürültüyü elemek için eşik.
TOLERANCE = 0.02

# Fark kodları: kod -> (başlık, ciddiyet, açıklama)
ISSUES = {
    "MISSING_FROM_PAYOUT": (
        "Hiç ödenmemiş", "high",
        "Bu siparişi teslim ettiniz ama platform ödeme raporuna hiç koymamış. "
        "Parası hiç yatmamış."),
    "NOT_IN_POS": (
        "Sizde kaydı yok", "medium",
        "Platform bu siparişin parasını yatırmış ama sizin kayıtlarınızda böyle "
        "bir sipariş yok. Kasaya girilmemiş olabilir."),
    "UNDERPAID": (
        "Sebebi bulunamayan eksik", "high",
        "Eksik ödenmiş ama sebebini tespit edemedik. Genelde bir sütunun "
        "eşlenmemiş olmasından olur."),
    "OVERPAID": (
        "Fazla ödenmiş", "low",
        "Hakkınızdan fazla ödenmiş. Platform bunu sonradan geri isteyebilir, "
        "haberiniz olsun."),
    "COMMISSION_OVERCHARGE": (
        "Fazla komisyon kesilmiş", "high",
        "Komisyon oranı doğru ama kesilen tutar olması gerekenden yüksek."),
    "RATE_MISMATCH": (
        "Anlaşmadan yüksek komisyon almışlar", "high",
        "Sözleşmede yazan orandan daha yüksek komisyon uygulanmış."),
    "PLATFORM_DISCOUNT_CHARGED": (
        "Kendi kampanyalarını size ödetmişler", "high",
        "İndirimi platform başlattı, parasını platform karşılamalıydı; "
        "ama sizin cironuzdan düşülmüş."),
    "CHARGED_ON_CANCELLED": (
        "İptal siparişten komisyon almışlar", "high",
        "Sipariş iptal edilmiş ya da iade olmuş. İptal olan siparişten "
        "komisyon alınmaması gerekir."),
    "UNKNOWN_DEDUCTION": (
        "Sebebi yazılmamış kesinti", "high",
        "Paranızdan kesinti yapılmış ama raporda hiçbir gerekçe yazmıyor."),
    "DUPLICATE_LINE": (
        "Aynı sipariş iki kez yazılmış", "medium",
        "Bu sipariş ödeme raporunda birden fazla kez görünüyor."),
    "PERIOD_TOTAL_MISMATCH": (
        "Toplu kesinti", "high",
        "Raporda sipariş sipariş yazan tutarların toplamı ile hesabınıza geçen "
        "para farklı. Aradaki fark hiçbir siparişte görünmüyor."),
    "NO_RULE": (
        "Komisyon bilgisi eksik", "medium",
        "Bu tarih için komisyon oranı girilmemiş, hesap yapılamadı. "
        "Ayarlar bölümünden ekleyin."),
}


def _issue(code, amount, detail, order_id, platform, order_date=None):
    title, severity, desc = ISSUES[code]
    return {
        "code": code, "title": title, "severity": severity,
        "description": desc, "detail": detail,
        "amount": r2(amount), "platform_order_id": order_id,
        "platform": platform, "order_date": order_date,
    }


def reconcile_period(orders, payout_lines, rule_rows, payout_total=None):
    """Bir dönemin mutabakatını yapar.

    orders       : POS siparişleri (dict listesi)
    payout_lines : hakediş raporu satırları (dict listesi)
    rule_rows    : komisyon kuralları
    payout_total : bankaya fiilen geçen tutar (varsa dönem kontrolü yapılır)
    """
    # Hakediş satırlarını sipariş no'ya göre grupla (mükerrer yakalamak için liste)
    by_id = {}
    for pl in payout_lines:
        by_id.setdefault(str(pl["platform_order_id"]).strip(), []).append(pl)

    results = []
    issues = []
    seen = set()

    total_expected = 0.0
    total_paid_lines = 0.0

    for o in orders:
        oid = str(o["platform_order_id"]).strip()
        seen.add(oid)
        plines = by_id.get(oid, [])

        rule = rules.pick_rule(rule_rows, o["platform"], o["order_date"])
        if rule is None:
            issues.append(_issue("NO_RULE", 0,
                                 "%s için %s tarihinde geçerli kural yok"
                                 % (o["platform"], o["order_date"]),
                                 oid, o["platform"], o["order_date"]))
            continue

        exp = rules.expected_for_order(o, rule)
        expected_net = exp["net"]
        total_expected += expected_net

        # --- Hakedişte hiç yok mu? ---
        if not plines:
            if o["status"] == "delivered" and abs(expected_net) > TOLERANCE:
                issues.append(_issue("MISSING_FROM_PAYOUT", expected_net,
                                     "Teslim edildi, size ödenmesi gereken %s TL, ödeme raporunda yok"
                                     % tl(expected_net), oid, o["platform"], o["order_date"]))
            results.append(_row(o, exp, None, expected_net, None, "missing"))
            continue

        if len(plines) > 1:
            issues.append(_issue("DUPLICATE_LINE", 0,
                                 "%d satır bulundu" % len(plines),
                                 oid, o["platform"], o["order_date"]))

        # Mükerrer varsa toplamını tek gerçek kabul et
        paid = r2(sum(p["net_paid"] for p in plines))
        com_charged = r2(sum(p["commission_charged"] for p in plines))
        com_vat_charged = r2(sum(p["commission_vat_charged"] for p in plines))
        other_ded = r2(sum(p["other_deductions"] for p in plines))
        gross_reported = r2(sum(p["gross_reported"] for p in plines))
        total_paid_lines += paid

        diff = r2(paid - expected_net)

        # Bu siparişe ait teşhisler önce ayrı toplanır. Amaç: eksik ödenen
        # her lirayı TEK bir sebebe bağlamak. Aynı parayı hem "iptalde
        # komisyon" hem "eksik ödeme" diye iki kez listelersek itiraz
        # tutarı şişer ve platform haklı olarak listeyi reddeder.
        local = []
        cancelled = o["status"] in ("cancelled", "refunded")

        # --- İptal siparişten komisyon kesilmiş mi? ---
        if cancelled and com_charged > TOLERANCE:
            local.append(_issue("CHARGED_ON_CANCELLED", com_charged + com_vat_charged,
                                "Sipariş %s ama %s TL komisyon + %s TL KDV kesilmiş"
                                % ("iptal edilmiş" if o["status"] == "cancelled" else "iade edilmiş",
                                   tl(com_charged), tl(com_vat_charged)),
                                oid, o["platform"], o["order_date"]))

        # --- Komisyon fazla mı, fazlaysa sebebi oran mı? ---
        # Önce oran sapmasına bakılır: "kesinti fazla" demek platformu
        # ikna etmez, "oranı %18 yerine %21 uygulamışsınız" eder.
        expected_com = exp["commission_total"]
        overcharge = r2(com_charged - expected_com)
        base = exp.get("commission_base") or 0
        rate_flagged = False

        if base > 0 and com_charged > 0:
            # Sabit ücretler düşülüp saf oran kıyaslanır
            pure = (com_charged - rule["fixed_fee_per_order"]
                    - rule["service_fee_per_order"]) / base
            if pure - rule["commission_rate"] > 0.005:
                rate_flagged = True
                gap_amt = r2((pure - rule["commission_rate"]) * base)
                local.append(_issue(
                    "RATE_MISMATCH", r2(gap_amt * (1 + rule["commission_vat_rate"])),
                    "Uygulanan %%%s, sözleşmede yazan %%%s — %s TL üzerinden %s TL fazla komisyon"
                    % (tl(pure * 100), tl(rule["commission_rate"] * 100), tl(base), tl(gap_amt)),
                    oid, o["platform"], o["order_date"]))

        if not rate_flagged and not cancelled and overcharge > TOLERANCE:
            local.append(_issue("COMMISSION_OVERCHARGE",
                                r2(overcharge * (1 + rule["commission_vat_rate"])),
                                "Kesilen %s TL, olması gereken %s TL"
                                % (tl(com_charged), tl(expected_com)),
                                oid, o["platform"], o["order_date"]))

        # --- Platform kampanyası bizden mi kesilmiş? ---
        if o["discount_platform"] > TOLERANCE and gross_reported > 0:
            expected_gross = r2(o["items_subtotal"] - o["discount_restaurant"])
            if expected_gross - gross_reported >= o["discount_platform"] - TOLERANCE:
                local.append(_issue(
                    "PLATFORM_DISCOUNT_CHARGED", o["discount_platform"],
                    "Sipariş tutarı %s TL olmalıydı, raporda %s TL yazıyor — aradaki fark platformun kampanyası"
                    % (tl(expected_gross), tl(gross_reported)),
                    oid, o["platform"], o["order_date"]))

        # --- Açıklamasız kesinti ---
        if other_ded > TOLERANCE and not (plines[0].get("line_note") or "").strip():
            local.append(_issue("UNKNOWN_DEDUCTION", other_ded,
                                "%s TL kesilmiş, sebebi yazılmamış" % tl(other_ded),
                                oid, o["platform"], o["order_date"]))

        # --- Kalan fark ---
        # Eksiğin teşhislerle açıklanan kısmı düşülür; geriye kalan varsa
        # "sebebi belirlenemeyen eksik ödeme" olarak ayrıca yazılır.
        shortfall = r2(-diff) if diff < 0 else 0.0
        explained = r2(sum(i["amount"] for i in local))
        residual = r2(shortfall - explained)

        if residual > TOLERANCE:
            detail = ("Ödenmesi gereken %s TL, ödenen %s TL" % (tl(expected_net), tl(paid)))
            if explained > TOLERANCE:
                detail += (" — %s TL'si diğer kalemlerle açıklanıyor, "
                           "kalan %s TL'nin sebebi bulunamadı"
                           % (tl(explained), tl(residual)))
            local.append(_issue("UNDERPAID", residual, detail,
                                oid, o["platform"], o["order_date"]))
        elif diff > TOLERANCE:
            local.append(_issue("OVERPAID", diff,
                                "Ödenmesi gereken %s TL, ödenen %s TL"
                                % (tl(expected_net), tl(paid)),
                                oid, o["platform"], o["order_date"]))

        issues.extend(local)

        status = "ok" if abs(diff) <= TOLERANCE else ("under" if diff < 0 else "over")
        results.append(_row(o, exp, paid, expected_net, diff, status))

    # --- Hakedişte olup POS'ta olmayanlar ---
    for oid, plines in by_id.items():
        if oid in seen:
            continue
        paid = r2(sum(p["net_paid"] for p in plines))
        total_paid_lines += paid
        issues.append(_issue("NOT_IN_POS", paid,
                             "Platform %s TL ödemiş ama sizde bu siparişin kaydı yok" % tl(paid),
                             oid, plines[0]["platform"], plines[0].get("order_date")))
        results.append({
            "platform_order_id": oid, "platform": plines[0]["platform"],
            "order_date": plines[0].get("order_date"), "status": "orphan",
            "order_status": "-", "payment_method": "-",
            "items_subtotal": 0, "our_revenue": 0, "commission_expected": 0,
            "expected_net": 0, "paid_net": paid, "diff": paid, "lines": [],
        })

    # --- Dönem toplamı kontrolü ---
    if payout_total is not None:
        gap = r2(payout_total - total_paid_lines)
        if abs(gap) > 1.0:
            issues.append(_issue("PERIOD_TOTAL_MISMATCH", gap,
                                 "Raporda yazan toplam %s TL, hesabınıza geçen %s TL"
                                 % (tl(total_paid_lines), tl(payout_total)),
                                 "-", orders[0]["platform"] if orders else "-"))

    # Asıl soru "bankaya ne geçti": hakediş satırlarının toplamı ile
    # hesaba yatan tutar da ayrıca farklı olabiliyor, o fark buraya dahildir.
    bank_gap = r2(payout_total - total_expected) if payout_total is not None else None

    # --- Denetim kimliği ---
    # Açıklamaların toplamı, satır düzeyindeki farka eşit olmalı.
    # Eşit çıkıyorsa eksiğin tamamı bir sebebe bağlanmış demektir; bu
    # rakam itiraz listesinin savunulabilirliğinin ölçüsüdür.
    PLUS = ("MISSING_FROM_PAYOUT", "UNDERPAID", "RATE_MISMATCH",
            "COMMISSION_OVERCHARGE", "CHARGED_ON_CANCELLED",
            "PLATFORM_DISCOUNT_CHARGED", "UNKNOWN_DEDUCTION")
    MINUS = ("NOT_IN_POS", "OVERPAID")
    explained = r2(sum(i["amount"] for i in issues if i["code"] in PLUS)
                   - sum(i["amount"] for i in issues if i["code"] in MINUS))
    shortfall = r2(-(total_paid_lines - total_expected))
    unexplained = r2(shortfall - explained)

    summary = {
        "order_count": len(orders),
        "shortfall": shortfall,
        "explained": explained,
        "unexplained": unexplained,
        "line_count": len(payout_lines),
        "total_expected": r2(total_expected),
        "total_paid": r2(total_paid_lines),
        "total_diff": r2(total_paid_lines - total_expected),
        "bank_gap": bank_gap,
        "underpaid_total": r2(sum(i["amount"] for i in issues
                                  if i["code"] in ("UNDERPAID", "MISSING_FROM_PAYOUT"))),
        "overcharge_total": r2(sum(i["amount"] for i in issues
                                   if i["code"] in ("COMMISSION_OVERCHARGE", "RATE_MISMATCH",
                                                    "CHARGED_ON_CANCELLED",
                                                    "PLATFORM_DISCOUNT_CHARGED",
                                                    "UNKNOWN_DEDUCTION"))),
        "issue_count": len(issues),
        "bank_total": payout_total,
        # Teşhis dökümü: kod bazında adet ve tutar. Bu kalemler birbirinin
        # içine geçebildiği için TOPLANMAZ; asıl rakam bank_gap'tir.
        "by_code": _by_code(issues),
    }
    return {"rows": results, "issues": issues, "summary": summary}


def _by_code(issues):
    """Sorun kodlarına göre adet ve tutar dökümü."""
    agg = {}
    for i in issues:
        a = agg.setdefault(i["code"], {"code": i["code"], "title": i["title"],
                                       "severity": i["severity"], "count": 0, "amount": 0.0})
        a["count"] += 1
        a["amount"] = r2(a["amount"] + i["amount"])
    return sorted(agg.values(), key=lambda x: -abs(x["amount"]))


def _row(o, exp, paid, expected_net, diff, status):
    return {
        "platform_order_id": str(o["platform_order_id"]).strip(),
        "platform": o["platform"],
        "order_date": o["order_date"],
        "order_status": o["status"],
        "payment_method": o["payment_method"],
        "items_subtotal": r2(o["items_subtotal"]),
        "our_revenue": exp["our_revenue"],
        "commission_expected": exp["commission_total"],
        "expected_net": r2(expected_net),
        "paid_net": paid,
        "diff": diff,
        "status": status,
        "lines": exp["lines"],
    }
