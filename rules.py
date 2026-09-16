"""Komisyon kural motoru: sözleşmeye göre bize NE ÖDENMESİ GEREKTİĞİNİ hesaplar.

Tasarım ilkesi: hesap asla tek bir sayı döndürmez. Her adımı ayrı satır
olarak döndürür ki platforma itiraz ederken "şu kalemi şöyle hesapladım"
diyebilesin. İtirazı kazandıran şey tutar değil, dökümdür.
"""
from datetime import date


def tl(x):
    """Parayı Türkçe biçimde yazar: 1234.5 -> '1.234,50'."""
    # Binlik ayracı nokta, ondalık virgül. Önce İngilizce biçimde üretip
    # iki ayracı takas ediyoruz.
    s = format(float(x), ",.2f")
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def r2(x):
    """Para yuvarlama. Kuruş farkları mutabakatta gürültü yapmasın diye tek noktadan."""
    return round(x + 0.0, 2)


def pick_rule(rules, platform, order_date):
    """Siparişin tarihinde geçerli olan kuralı seçer.

    Geçmiş ayı bugünün oranıyla denetlemek en sık yapılan hata; oran
    Mart'ta %15 iken Haziran'da %18 olduysa Mart siparişi %15 ile ölçülmeli.
    """
    best = None
    for r in rules:
        if r["platform"] != platform:
            continue
        if r["valid_from"] > order_date:
            continue
        if r["valid_to"] and r["valid_to"] < order_date:
            continue
        # Birden fazla eşleşirse en yeni başlayan kazanır
        if best is None or r["valid_from"] > best["valid_from"]:
            best = r
    return best


def commission_base_amount(order, rule):
    """Komisyonun hangi tutar üzerinden alınacağı.

    Burası platformlarla en çok kavga edilen yer: komisyonu indirim
    ÖNCESİ tutardan almak, indirimi ise bizden kesmek çifte zarardır.
    """
    items = order["items_subtotal"]
    base_kind = rule["commission_base"]

    if base_kind == "items_before_discount":
        return items
    if base_kind == "items_after_discount":
        # Sadece BİZİM finanse ettiğimiz indirim matrahı düşürür.
        # Platformun kendi kampanyası bizim cironuzu düşürmez.
        return items - order["discount_restaurant"]
    if base_kind == "items_plus_delivery":
        return items - order["discount_restaurant"] + order["delivery_fee"]
    if base_kind == "gross":
        return (items - order["discount_restaurant"] + order["delivery_fee"]
                + order["tip"])
    raise ValueError("Bilinmeyen komisyon matrahı: %s" % base_kind)


# Komisyon matrahının insan diline çevrilmiş hâli
BASE_ADI = {
    "items_after_discount": "indirim düşüldükten sonraki tutardan",
    "items_before_discount": "indirim düşülmeden önceki tutardan",
    "items_plus_delivery": "teslimat ücreti dahil tutardan",
    "gross": "her şey dahil toplam tutardan",
}


def expected_for_order(order, rule):
    """Tek sipariş için beklenen net ödemeyi ve tam dökümünü üretir.

    Döküm satırları (etiket, tutar, açıklama, tür) dörtlüsüdür. 'tür'
    arayüzün satırı nasıl göstereceğini söyler:
      ""      normal para kalemi
      "info"  bilgi satırı (para hareketi değil, hesabın dayanağı)
      "total" sonuç satırı

    Metinler bilerek sade tutulmuştur: bu dökümü okuyacak kişi
    muhasebeci değil, işletme sahibi.

    Dönen 'net': platformun ödemesi gereken tutar.
      pozitif -> platform size borçlu
      negatif -> siz platforma borçlusunuz (kapıda ödemede parayı siz
                 aldınız, komisyonu onlar sizden tahsil eder)
    """
    lines = []
    status = order["status"]
    method = order["payment_method"]

    # --- İptal / iade: ne ciro var ne de komisyon doğar ---
    if status in ("cancelled", "refunded"):
        durum = "iptal edilmiş" if status == "cancelled" else "iade edilmiş"
        lines.append(("Bu sipariş %s" % durum, 0.0,
                      "İptal veya iade olan siparişten ne para alınır ne komisyon ödenir",
                      "info"))
        lines.append(("Size ödenmesi gereken", 0.0, "", "total"))
        return {"net": 0.0, "lines": lines, "commission_total": 0.0,
                "our_revenue": 0.0, "rule_id": rule["id"] if rule else None}

    # --- 1. Sizin cironuz ---
    items = order["items_subtotal"]
    lines.append(("Sipariş tutarı", r2(items), "Kendi kayıtlarınızdan", ""))

    revenue = items

    if order["discount_restaurant"]:
        revenue -= order["discount_restaurant"]
        lines.append(("Sizin verdiğiniz indirim", r2(-order["discount_restaurant"]),
                      "Kampanyayı siz finanse ettiniz, cironuzdan düşer", ""))

    if order["discount_platform"]:
        lines.append(("Platformun verdiği indirim", 0.0,
                      "%s TL indirimi platform karşılıyor — sizin cironuzu "
                      "düşürmemeli" % tl(order["discount_platform"]), "info"))

    if rule["delivery_fee_to"] == "restaurant" and order["delivery_fee"]:
        revenue += order["delivery_fee"]
        lines.append(("Teslimat ücreti", r2(order["delivery_fee"]),
                      "Sözleşmeye göre teslimat ücreti size ait", ""))
    elif order["delivery_fee"]:
        lines.append(("Teslimat ücreti", 0.0,
                      "%s TL teslimat ücreti platforma ait — size ödenmez"
                      % tl(order["delivery_fee"]), "info"))

    if order["tip"]:
        revenue += order["tip"]
        lines.append(("Bahşiş", r2(order["tip"]),
                      "Bahşişten komisyon alınmamalı", ""))

    our_revenue = r2(revenue)

    # --- 2. Komisyon ---
    base = r2(commission_base_amount(order, rule))
    commission = r2(base * rule["commission_rate"])
    lines.append(("Komisyon %s TL üzerinden hesaplanır" % tl(base),
                  0.0,
                  "Sözleşmeye göre komisyon %s alınıyor"
                  % BASE_ADI.get(rule["commission_base"], rule["commission_base"]),
                  "info"))
    lines.append(("Komisyon (%%%s)" % ("%.2f" % (rule["commission_rate"] * 100)).replace(".", ","),
                  r2(-commission), "", ""))

    extra = 0.0
    if rule["fixed_fee_per_order"]:
        extra += rule["fixed_fee_per_order"]
        lines.append(("Sipariş başı sabit ücret", r2(-rule["fixed_fee_per_order"]), "", ""))
    if rule["service_fee_per_order"]:
        extra += rule["service_fee_per_order"]
        lines.append(("Hizmet bedeli", r2(-rule["service_fee_per_order"]), "", ""))

    commission_total = r2(commission + extra)

    # --- 3. Komisyon KDV'si ---
    com_vat = r2(commission_total * rule["commission_vat_rate"])
    if com_vat:
        lines.append(("Komisyonun KDV'si (%%%.0f)" % (rule["commission_vat_rate"] * 100),
                      r2(-com_vat),
                      "Bu KDV'yi beyannamede indirebilirsiniz, ama şimdi cebinizden çıkar",
                      ""))

    # --- 4. Online ödeme işlem ücreti ---
    processing = 0.0
    if method == "online" and rule["payment_processing_rate"]:
        collected = r2(items - order["discount_restaurant"] - order["discount_platform"]
                       + order["delivery_fee"] + order["tip"])
        processing = r2(collected * rule["payment_processing_rate"])
        lines.append(("Kart komisyonu (%%%s)"
                      % ("%.2f" % (rule["payment_processing_rate"] * 100)).replace(".", ","),
                      r2(-processing),
                      "Müşteriden tahsil edilen %s TL üzerinden"
                      % tl(collected), ""))

    # --- 5. Net ---
    if method in ("cash", "card_on_delivery"):
        # Parayı kapıda siz tahsil ettiniz. Platform size ciro ödemez;
        # sadece komisyonunu sizden alacaklıdır -> beklenen net negatif.
        net = r2(-(commission_total + com_vat))
        lines.append(("Parayı kapıda siz aldınız", r2(-our_revenue),
                      "Tahsilatı siz yaptığınız için platform ciroyu ödemez, "
                      "sadece komisyonunu sizden ister", ""))
        lines.append(("Platforma ödemeniz gereken", abs(net),
                      "Bu siparişte para almazsınız, aksine komisyon ödersiniz", "total"))
    else:
        net = r2(our_revenue - commission_total - com_vat - processing)
        lines.append(("Size ödenmesi gereken", net, "", "total"))

    return {"net": net, "lines": lines, "commission_total": commission_total,
            "commission_vat": com_vat, "processing_fee": processing,
            "our_revenue": our_revenue, "commission_base": base,
            "rule_id": rule["id"]}


def effective_rate(order, expected):
    """Fiilen uygulanan komisyon oranı — sözleşmeyle kıyaslamak için."""
    base = expected.get("commission_base") or 0
    if not base:
        return None
    return expected["commission_total"] / base
