"""Örnek veri üretir: POS sipariş dosyası + platform hakediş raporu.

Hakediş raporuna BİLEREK gerçek hayattaki hata tipleri yerleştirilir ki
sistemin bunları yakalayıp yakalamadığı doğrulanabilsin.
"""
import csv, os, random
from datetime import date, timedelta

random.seed(20260915)
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "sample")
os.makedirs(OUT, exist_ok=True)

PLATFORM = "yemeksepeti"
RATE, VAT, PROC = 0.18, 0.20, 0.0179
START = date(2026, 8, 1)
N = 220

def tr(x):
    return ("%.2f" % x).replace(".", ",")

orders, payout = [], []
# Yerleştirilen hataların kaydı — testte beklenen sonuç budur.
planted = []

for i in range(N):
    oid = "YS-%06d" % (480000 + i)
    d = START + timedelta(days=i % 30)
    items = round(random.uniform(120, 850), 2)
    delivery = random.choice([0.0, 0.0, 19.9, 29.9])
    disc_r = round(items * random.choice([0, 0, 0, 0.10]), 2)
    disc_p = round(items * random.choice([0, 0, 0, 0, 0.15]), 2)
    tip = random.choice([0.0, 0.0, 0.0, 10.0, 25.0])
    pay = random.choices(["online", "cash"], weights=[88, 12])[0]
    status = random.choices(["delivered", "cancelled"], weights=[96, 4])[0]

    orders.append({
        "Sipariş No": oid,
        "Sipariş Tarihi": d.strftime("%d.%m.%Y"),
        "Ürün Tutarı": tr(items),
        "Teslimat Ücreti": tr(delivery),
        "Restoran İndirimi": tr(disc_r),
        "Platform İndirimi": tr(disc_p),
        "Bahşiş": tr(tip),
        "Ödeme Tipi": "Kapıda Nakit" if pay == "cash" else "Online Kredi Kartı",
        "Durum": "İptal Edildi" if status == "cancelled" else "Teslim Edildi",
    })

    # --- Platformun DOĞRU hesaplaması ne olurdu ---
    base = round(items - disc_r, 2)
    com = round(base * RATE, 2)
    cvat = round(com * VAT, 2)
    collected = round(items - disc_r - disc_p + delivery + tip, 2)
    proc = round(collected * PROC, 2) if pay == "online" else 0.0
    revenue = round(items - disc_r + tip, 2)
    net = round(revenue - com - cvat - proc, 2) if pay == "online" else round(-(com + cvat), 2)
    other, note = 0.0, ""

    if status == "cancelled":
        com = cvat = proc = net = 0.0
        base = 0.0

    # --- BİLEREK yerleştirilen hatalar ---
    if status == "delivered":
        if i % 37 == 5:                      # 1) siparişi hakedişe hiç koymamak
            planted.append((oid, "MISSING_FROM_PAYOUT", net))
            continue
        if i % 29 == 3:                      # 2) komisyonu %18 yerine %21 almak
            com2 = round(base * 0.21, 2)
            cvat = round(com2 * VAT, 2)
            net = round(net - (com2 - com) * (1 + VAT), 2)
            planted.append((oid, "RATE_MISMATCH", round(com2 - com, 2)))
            com = com2
        if i % 41 == 7:                      # 3) açıklamasız kesinti
            other = round(random.uniform(15, 60), 2)
            net = round(net - other, 2)
            planted.append((oid, "UNKNOWN_DEDUCTION", other))
        if i % 53 == 11 and disc_p > 0:      # 4) platform kampanyasını bizden kesmek
            net = round(net - disc_p, 2)
            base = round(base - disc_p, 2)
            planted.append((oid, "PLATFORM_DISCOUNT_CHARGED", disc_p))
    else:
        if i % 3 == 0:                       # 5) iptal siparişten komisyon almak
            com = round((items - disc_r) * RATE, 2)
            cvat = round(com * VAT, 2)
            net = round(-(com + cvat), 2)
            planted.append((oid, "CHARGED_ON_CANCELLED", round(com + cvat, 2)))

    payout.append({
        "Sipariş No": oid,
        "Tarih": d.strftime("%d.%m.%Y"),
        "Brüt Tutar": tr(base),
        "Komisyon": tr(com),
        "Komisyon KDV": tr(cvat),
        "Diğer Kesinti": tr(other),
        "Net Ödeme": tr(net),
        "Açıklama": note,
    })

# 6) POS'ta olmayan bir sipariş hakedişte görünüyor
payout.append({"Sipariş No": "YS-999001", "Tarih": "15.08.2026", "Brüt Tutar": "300,00",
               "Komisyon": "54,00", "Komisyon KDV": "10,80", "Diğer Kesinti": "0,00",
               "Net Ödeme": "230,00", "Açıklama": ""})
planted.append(("YS-999001", "NOT_IN_POS", 230.00))

def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader(); w.writerows(rows)

write_csv(os.path.join(OUT, "pos_siparisler_2026-08.csv"), orders)
write_csv(os.path.join(OUT, "yemeksepeti_hakedis_2026-08.csv"), payout)

bank_total = sum(float(r["Net Ödeme"].replace(",", ".")) for r in payout)
# 7) Satır toplamı ile bankaya geçen arasında açıklanmamış toplu kesinti
bank_total = round(bank_total - 1850.00, 2)
planted.append(("-", "PERIOD_TOTAL_MISMATCH", -1850.00))

with open(os.path.join(OUT, "beklenen_hatalar.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["Sipariş No", "Hata Kodu", "Tutar"])
    for row in planted:
        w.writerow([row[0], row[1], tr(row[2])])

print("Örnek dosyalar: %s" % OUT)
print("  POS siparişleri      : %d satır" % len(orders))
print("  Hakediş satırları    : %d satır" % len(payout))
print("  Bankaya geçen tutar  : %s TL  <-- panele bu girilecek" % tr(bank_total))
print("  Yerleştirilen hata   : %d adet" % len(planted))
