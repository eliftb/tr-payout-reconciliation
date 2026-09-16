"""Veritabanı şeması ve temel erişim katmanı (SQLite, bağımlılıksız)."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hakedis.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ---------------------------------------------------------------
-- 1) POS siparişleri: BİZİM gerçeğimiz. Ne sattık, kim ne ödedi.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY,
    platform            TEXT    NOT NULL,          -- yemeksepeti | trendyol | getir
    platform_order_id   TEXT    NOT NULL,          -- platformun sipariş numarası (eşleme anahtarı)
    order_date          TEXT    NOT NULL,          -- ISO: YYYY-MM-DD
    items_subtotal      REAL    NOT NULL DEFAULT 0,-- ürün tutarı (KDV dahil, indirim öncesi)
    delivery_fee        REAL    NOT NULL DEFAULT 0,-- teslimat ücreti
    discount_restaurant REAL    NOT NULL DEFAULT 0,-- indirimin BİZİM finanse ettiğimiz kısmı
    discount_platform   REAL    NOT NULL DEFAULT 0,-- indirimin PLATFORMUN finanse ettiği kısmı
    tip                 REAL    NOT NULL DEFAULT 0,
    payment_method      TEXT    NOT NULL DEFAULT 'online', -- online | cash | card_on_delivery
    status              TEXT    NOT NULL DEFAULT 'delivered', -- delivered | cancelled | refunded
    source_file         TEXT,
    imported_at         TEXT    DEFAULT (datetime('now')),
    UNIQUE (platform, platform_order_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_platform ON orders(platform, order_date);

-- ---------------------------------------------------------------
-- 2) Komisyon kuralları: SÖZLEŞMEDE ne yazıyor.
--    Tarih aralıklı, çünkü oranlar zamanla değişir ve geçmiş ayı
--    bugünkü oranla denetlersen yanlış sonuç çıkar.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS commission_rules (
    id                    INTEGER PRIMARY KEY,
    platform              TEXT NOT NULL,
    valid_from            TEXT NOT NULL,   -- ISO tarih, dahil
    valid_to              TEXT,            -- ISO tarih, dahil; NULL = hâlâ geçerli
    commission_rate       REAL NOT NULL,   -- ör. 0.18 = %18
    commission_base       TEXT NOT NULL DEFAULT 'items_after_discount',
                          -- items_after_discount | items_before_discount | items_plus_delivery | gross
    fixed_fee_per_order   REAL NOT NULL DEFAULT 0,   -- sipariş başı sabit ücret (TL)
    payment_processing_rate REAL NOT NULL DEFAULT 0, -- online ödeme işlem komisyonu, ör. 0.0179
    commission_vat_rate   REAL NOT NULL DEFAULT 0.20,-- komisyon faturasının KDV'si (TR: %20)
    delivery_fee_to       TEXT NOT NULL DEFAULT 'platform', -- teslimat ücreti kime kalıyor
    service_fee_per_order REAL NOT NULL DEFAULT 0,
    notes                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_rules_platform ON commission_rules(platform, valid_from);

-- ---------------------------------------------------------------
-- 3) Hakediş dönemi: platformun "şu kadar ödedim" dediği belge.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payouts (
    id            INTEGER PRIMARY KEY,
    platform      TEXT NOT NULL,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    statement_ref TEXT,                      -- hakediş/dekont no
    total_paid    REAL NOT NULL DEFAULT 0,   -- BANKAYA geçen net tutar
    source_file   TEXT,
    imported_at   TEXT DEFAULT (datetime('now')),
    UNIQUE (platform, period_start, period_end, statement_ref)
);

-- ---------------------------------------------------------------
-- 4) Hakediş satırları: raporun sipariş bazlı dökümü.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payout_lines (
    id                INTEGER PRIMARY KEY,
    payout_id         INTEGER NOT NULL REFERENCES payouts(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    platform_order_id TEXT NOT NULL,
    order_date        TEXT,
    gross_reported    REAL NOT NULL DEFAULT 0,  -- platformun gördüğü brüt
    commission_charged REAL NOT NULL DEFAULT 0, -- kestiği komisyon (KDV hariç)
    commission_vat_charged REAL NOT NULL DEFAULT 0,
    other_deductions  REAL NOT NULL DEFAULT 0,  -- adı konmamış kesintiler
    net_paid          REAL NOT NULL DEFAULT 0,  -- bu sipariş için ödediği net
    line_note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_plines_order ON payout_lines(platform, platform_order_id);
CREATE INDEX IF NOT EXISTS idx_plines_payout ON payout_lines(payout_id);

-- ---------------------------------------------------------------
-- 5) İtiraz takibi: bulunan farkın akıbeti.
--    Fark bulmak yarısı; tahsil etmek diğer yarısı.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS disputes (
    id                INTEGER PRIMARY KEY,
    platform          TEXT NOT NULL,
    platform_order_id TEXT NOT NULL,
    amount            REAL NOT NULL,
    issue_code        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'open', -- open | submitted | accepted | rejected | recovered
    opened_at         TEXT DEFAULT (datetime('now')),
    resolved_at       TEXT,
    note              TEXT,
    UNIQUE (platform, platform_order_id, issue_code)
);

-- ---------------------------------------------------------------
-- 6) Sütun eşleme profilleri: POS/platform export başlıkları
--    firmadan firmaya değişir; bir kez eşle, sonra hatırla.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_profiles (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL,   -- pos_orders | payout_lines
    platform   TEXT,
    mapping_json TEXT NOT NULL, -- {"hedef_alan": "dosyadaki başlık"}
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init()
    print("Şema kuruldu:", DB_PATH)
