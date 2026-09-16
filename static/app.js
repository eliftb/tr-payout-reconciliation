"use strict";

/* =================================================================
   Ödeme Kontrol — panel arayüzü
   Tasarım ilkesi: kullanıcı muhasebeci değil. Ekranda her zaman tek
   bir "şimdi ne yapmalıyım" olmalı ve rakamlar okunmak için
   yakınlaşmayı gerektirmemeli.
   ================================================================= */

const $ = (s) => document.querySelector(s);
const el = (t, c, txt) => { const e = document.createElement(t);
  if (c) e.className = c; if (txt !== undefined) e.textContent = txt; return e; };
const esc = (s) => String(s === null || s === undefined ? "" : s)
  .replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                 '"': "&quot;", "'": "&#39;" }[c]));

const nf = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
const money = (n) => (n === null || n === undefined) ? "—" : nf.format(n) + " TL";
const moneyAbs = (n) => money(Math.abs(n || 0));
const signed = (n) => (n === null || n === undefined) ? "—"
  : (n > 0 ? "+" : "") + nf.format(n) + " TL";

const PLATFORMS = { yemeksepeti: "Yemeksepeti", trendyol: "Trendyol Yemek",
                    getir: "Getir Yemek", ubereats: "Uber Eats", migros: "Migros Yemek" };
const plabel = (p) => PLATFORMS[p] || p;
const AYLAR = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
               "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"];
const monthLabel = (ym) => { const [y, m] = ym.split("-"); return AYLAR[+m - 1] + " " + y; };
const lastDay = (ym) => { const [y, m] = ym.split("-").map(Number);
  return `${ym}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`; };

const DURUM = { ok: "Doğru", under: "Eksik", over: "Fazla",
                missing: "Ödenmemiş", orphan: "Sizde yok" };
const ODEME = { online: "Online", cash: "Kapıda nakit", card_on_delivery: "Kapıda kart" };
const SIPARIS_DURUM = { delivered: "Teslim", cancelled: "İptal", refunded: "İade" };

async function api(path, opts) {
  const r = await fetch(path, opts);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || ("Sunucu hatası " + r.status));
  return data;
}

let STATE = null, RESULT = null;
let SEL = { platform: "", month: "" };   // seçili platform + ay
let reasonFilter = null;

/* ---------------- sekmeler ---------------- */
function showTab(name) {
  const btn = document.querySelector(`nav button[data-tab="${name}"]`);
  if (!btn) return showTab("sonuc");
  document.querySelectorAll("nav button").forEach((x) => x.classList.remove("on"));
  document.querySelectorAll("section").forEach((x) => x.classList.remove("on"));
  btn.classList.add("on");
  $("#tab-" + name).classList.add("on");
  window.scrollTo(0, 0);
  if (name === "yukle") renderUpload();
  if (name === "ayarlar") renderSettings();
  if (name === "sonuc") renderResult();
}
document.querySelectorAll("nav button").forEach((b) => {
  b.onclick = () => { location.hash = b.dataset.tab; };
});
window.addEventListener("hashchange", () => showTab(location.hash.slice(1) || "sonuc"));

$("#modalClose").onclick = () => $("#modal").classList.remove("on");
$("#modal").onclick = (e) => { if (e.target === $("#modal")) $("#modal").classList.remove("on"); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#modal").classList.remove("on");
});
function openModal(title, node) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = ""; $("#modalBody").appendChild(node);
  $("#modal").classList.add("on");
}

/* ---------------- veri durumu ---------------- */
async function loadState() {
  STATE = await api("/api/state");
  // Veride hangi platformlar ve aylar var?
  STATE._platforms = [...new Set([...(STATE.orders || []).map((o) => o.platform),
                                  ...(STATE.rules || []).map((r) => r.platform)])].sort();
  const months = new Set();
  (STATE.orders || []).forEach((o) => {
    if (!o.mn || !o.mx) return;
    let [y, m] = o.mn.split("-").map(Number);
    const [ey, em] = o.mx.split("-").map(Number);
    let guard = 0;
    while ((y < ey || (y === ey && m <= em)) && guard++ < 120) {
      months.add(`${y}-${String(m).padStart(2, "0")}`);
      m++; if (m > 12) { m = 1; y++; }
    }
  });
  STATE._months = [...months].sort().reverse();
  if (!SEL.platform && STATE._platforms.length) SEL.platform = STATE._platforms[0];
  if (!SEL.month && STATE._months.length) SEL.month = STATE._months[0];
  return STATE;
}

const hasRules = () => STATE && STATE.rules && STATE.rules.length > 0;
const hasOrders = () => STATE && STATE.order_total > 0;
const hasPayouts = () => STATE && STATE.line_total > 0;
const isReady = () => hasRules() && hasOrders() && hasPayouts();

async function runReconcile() {
  if (!SEL.month) return;
  RESULT = await api(`/api/reconcile?platform=${encodeURIComponent(SEL.platform || "all")}` +
                     `&start=${SEL.month}-01&end=${lastDay(SEL.month)}`);
}

/* =================================================================
   SONUÇ
   ================================================================= */
async function renderResult() {
  const box = $("#sonucBody");
  if (!isReady()) return renderOnboarding(box);

  box.innerHTML = '<div class="empty"><span class="spin"></span><p>Hesaplanıyor…</p></div>';
  try { await runReconcile(); }
  catch (e) { box.innerHTML = `<div class="note err">Hesaplanamadı: ${esc(e.message)}</div>`; return; }

  box.innerHTML = "";
  box.appendChild(periodPicker());

  const s = RESULT.summary;
  if (!s.order_count) {
    box.appendChild(Object.assign(el("div", "note warn"),
      { innerHTML: `<b>${esc(monthLabel(SEL.month))}</b> için sipariş bulunamadı. ` +
                   `Yukarıdan başka bir ay seçin.` }));
    return;
  }

  // ---- büyük cevap ----
  const gap = (s.bank_gap !== null && s.bank_gap !== undefined) ? s.bank_gap : s.total_diff;
  const eksik = gap < -0.5;
  const v = el("div", "verdict " + (eksik ? "bad" : "good"));
  v.appendChild(el("div", "when",
    `${monthLabel(SEL.month)} · ${SEL.platform === "all" ? "Tüm platformlar" : plabel(SEL.platform)}`));
  v.appendChild(el("div", "amount num", eksik ? moneyAbs(gap) : "Sorun yok"));
  v.appendChild(el("div", "said", eksik
    ? "size eksik ödenmiş görünüyor"
    : "Ödemeler anlaşmayla uyumlu."));

  const facts = el("div", "facts");
  const fact = (k, val) => { const f = el("div", "fact");
    f.appendChild(el("div", "k", k)); f.appendChild(el("div", "v num", val)); return f; };
  facts.appendChild(fact("Gelmesi gereken", money(s.total_expected)));
  facts.appendChild(fact(s.bank_total !== null ? "Hesabınıza geçen" : "Raporda yazan",
                         money(s.bank_total !== null ? s.bank_total : s.total_paid)));
  facts.appendChild(fact("İncelenen sipariş", nf0.format(s.order_count)));
  v.appendChild(facts);
  box.appendChild(v);

  if (!eksik) return;

  // ---- indirme ----
  const dl = el("div", "row");
  dl.style.marginBottom = "26px";
  const b1 = el("button", "big-btn", "İtiraz listesini indir");
  b1.onclick = () => { window.location =
    `/api/export?platform=${encodeURIComponent(SEL.platform || "all")}` +
    `&start=${SEL.month}-01&end=${lastDay(SEL.month)}`; };
  const b2 = el("button", "big-btn ghost", "Siparişleri tek tek gör");
  b2.onclick = () => showOrdersTable();
  dl.appendChild(b1); dl.appendChild(b2);
  box.appendChild(dl);

  const dlNote = el("p");
  dlNote.style.cssText = "color:var(--muted);font-size:16px;margin:-16px 0 26px";
  dlNote.textContent = "İndirilen dosya Excel'de açılır. Platformun müşteri " +
    "temsilcisine bu listeyi gönderebilirsiniz.";
  box.appendChild(dlNote);

  // ---- sebepler ----
  const h = el("h2", null, "Bu para nereye gitti?");
  h.style.cssText = "font-size:24px;margin-bottom:6px";
  box.appendChild(h);
  const sub = el("p");
  sub.style.cssText = "color:var(--muted);font-size:16.5px;margin-bottom:18px";
  sub.textContent = "Her kutuya tıklayarak o siparişleri görebilirsiniz. " +
    "Gri kutular sizin lehinize olan kalemlerdir, alacağınız değildir.";
  box.appendChild(sub);

  // Bu iki kalem kayıp DEĞİL: platformun size fazladan yatırdığı paradır.
  // Kırmızı gösterip alacak gibi sunmak yanlış beklenti yaratır.
  const LEHTE = ["NOT_IN_POS", "OVERPAID"];

  const grid = el("div", "reasons");
  (s.by_code || []).forEach((c) => {
    const lehte = LEHTE.includes(c.code);
    const d = el("button", "reason " + (lehte || c.severity === "low" ? "low" : ""));
    d.appendChild(el("div", "amt num", moneyAbs(c.amount)));
    d.appendChild(el("div", "ttl", lehte ? c.title + " (sizin lehinize)" : c.title));
    const info = (RESULT.issues.find((i) => i.code === c.code) || {}).description || "";
    d.appendChild(el("div", "dsc", info));
    d.appendChild(el("div", "cnt", c.code === "PERIOD_TOTAL_MISMATCH"
      ? "Tüm dönem için" : `${c.count} sipariş`));
    d.onclick = () => showOrdersTable(c.code);
    grid.appendChild(d);
  });
  box.appendChild(grid);

  // ---- güven notu ----
  if (s.shortfall > 0.02) {
    const okAll = Math.abs(s.unexplained) < 0.5;
    const n = el("div", "note " + (okAll ? "ok" : "warn"));
    n.innerHTML = okAll
      ? "Eksik ödenen paranın <b>tamamının</b> sebebi tespit edildi. Listeyi " +
        "gönül rahatlığıyla platforma iletebilirsiniz."
      : `Eksiğin <b>${esc(money(s.unexplained))}</b> kadarının sebebini bulamadık. ` +
        `Genelde dosya yüklerken bir sütunun eşleşmemiş olmasından olur — ` +
        `Dosya Yükle bölümünden tekrar deneyin.`;
    box.appendChild(n);
  }
}

function periodPicker() {
  const p = el("div", "panel");
  p.style.cssText = "padding:18px 22px;margin-bottom:22px";
  const r = el("div", "row");

  if (STATE._platforms.length > 1) {
    const w = el("div", "fldwrap");
    w.appendChild(el("label", "fld", "Platform"));
    const sel = el("select");
    const oa = el("option", null, "Tüm platformlar"); oa.value = "all"; sel.appendChild(oa);
    STATE._platforms.forEach((pl) => {
      const o = el("option", null, plabel(pl)); o.value = pl; sel.appendChild(o);
    });
    sel.value = SEL.platform || "all";
    sel.onchange = () => { SEL.platform = sel.value; renderResult(); };
    w.appendChild(sel); r.appendChild(w);
  }

  const w2 = el("div", "fldwrap");
  w2.appendChild(el("label", "fld", "Hangi ay?"));
  const ms = el("select");
  STATE._months.forEach((m) => {
    const o = el("option", null, monthLabel(m)); o.value = m; ms.appendChild(o);
  });
  ms.value = SEL.month;
  ms.onchange = () => { SEL.month = ms.value; renderResult(); };
  w2.appendChild(ms); r.appendChild(w2);

  p.appendChild(r);
  return p;
}

/* ---------------- ilk kurulum ---------------- */
function renderOnboarding(box) {
  box.innerHTML = "";
  const p = el("div", "panel");
  p.appendChild(el("h2", null, "Hoş geldiniz"));
  const lead = el("p", "lead");
  lead.textContent = "Bu program, yemek platformlarının size ödemesi gereken parayı " +
    "hesaplar ve gerçekte ödedikleriyle karşılaştırır. Başlamak için üç adım var.";
  p.appendChild(lead);

  const steps = el("div", "steps");
  const mk = (n, title, desc, done, btnText, go) => {
    const d = el("div", "stepitem " + (done ? "done" : ""));
    d.appendChild(el("div", "stepnum", done ? "✓" : String(n)));
    const b = el("div", "stepbody");
    b.appendChild(el("h3", null, title));
    b.appendChild(el("p", null, desc));
    if (!done && btnText) {
      const a = el("div", "act");
      const btn = el("button", "big-btn", btnText);
      btn.onclick = go; a.appendChild(btn); b.appendChild(a);
    }
    d.appendChild(b);
    return d;
  };

  const r = hasRules(), o = hasOrders(), y = hasPayouts();
  steps.appendChild(mk(1, "Komisyon oranınızı girin",
    r ? `${STATE.rules.length} kural kayıtlı.`
      : "Platformla anlaştığınız komisyon yüzdesi. Sözleşmenizde yazıyor.",
    r, "Oranı gir", () => { location.hash = "ayarlar"; }));
  steps.appendChild(mk(2, "Sipariş listenizi yükleyin",
    o ? `${nf0.format(STATE.order_total)} sipariş yüklü.`
      : "Kendi kasa/POS sisteminizden aldığınız sipariş dökümü. Excel veya CSV.",
    o, "Dosya yükle", () => { location.hash = "yukle"; }));
  steps.appendChild(mk(3, "Platformun ödeme raporunu yükleyin",
    y ? `${nf0.format(STATE.line_total)} satır yüklü.`
      : "Platformun panelinden indirdiğiniz hakediş/ödeme raporu.",
    y, "Dosya yükle", () => { location.hash = "yukle"; }));
  p.appendChild(steps);
  box.appendChild(p);
}

/* =================================================================
   SİPARİŞ TABLOSU (pencerede)
   ================================================================= */
function showOrdersTable(code) {
  reasonFilter = code || null;
  const box = el("div");

  let rows = RESULT.rows.slice();
  let title = "Tüm siparişler";

  if (code) {
    const ids = new Set(RESULT.issues.filter((i) => i.code === code)
      .map((i) => i.platform_order_id));
    const info = RESULT.issues.find((i) => i.code === code);
    title = info ? info.title : "Siparişler";
    if (code === "PERIOD_TOTAL_MISMATCH") {
      const d = el("div");
      const n = el("div", "note warn");
      n.innerHTML = `<b>${esc(info.detail)}</b><br><br>${esc(info.description)}`;
      d.appendChild(n);
      const tip = el("p");
      tip.style.cssText = "font-size:16px;color:var(--muted)";
      tip.textContent = "Bu kesinti tek bir siparişe ait değil, tüm döneme " +
        "toplu olarak uygulanmış. Platformdan yazılı gerekçe isteyin.";
      d.appendChild(tip);
      return openModal(title, d);
    }
    rows = rows.filter((r) => ids.has(r.platform_order_id));
    const desc = el("p");
    desc.style.cssText = "font-size:16.5px;color:var(--ink2);margin-bottom:16px";
    desc.textContent = info ? info.description : "";
    box.appendChild(desc);
  } else {
    rows = rows.filter((r) => r.status !== "ok");
    const desc = el("p");
    desc.style.cssText = "font-size:16.5px;color:var(--ink2);margin-bottom:16px";
    desc.textContent = "Farklı çıkan siparişler. Detayını görmek için bir satıra tıklayın.";
    box.appendChild(desc);
  }

  if (!rows.length) {
    box.appendChild(el("div", "note ok", "Bu grupta sipariş yok."));
    return openModal(title, box);
  }

  const w = el("div", "tablewrap");
  const t = el("table");
  t.innerHTML = `<thead><tr>
    <th>Sipariş No</th><th>Tarih</th>
    <th class="r">Gelmeliydi</th><th class="r">Geldi</th><th class="r">Fark</th>
    </tr></thead>`;
  const tb = el("tbody");
  rows.sort((a, b) => (a.diff || 0) - (b.diff || 0));
  rows.slice(0, 500).forEach((r) => {
    const tr = el("tr", "clickable");
    tr.innerHTML =
      `<td><b>${esc(r.platform_order_id)}</b></td>
       <td>${esc(r.order_date || "—")}</td>
       <td class="r num">${money(r.expected_net)}</td>
       <td class="r num">${r.paid_net === null ? "—" : money(r.paid_net)}</td>
       <td class="r num ${r.diff < -0.02 ? "neg" : ""}">${r.diff === null ? "—" : signed(r.diff)}</td>`;
    tr.onclick = () => showOrder(r.platform, r.platform_order_id);
    tb.appendChild(tr);
  });
  t.appendChild(tb); w.appendChild(t); box.appendChild(w);
  if (rows.length > 500) {
    box.appendChild(el("p", null, `${rows.length} siparişin ilk 500'ü gösteriliyor.`));
  }
  openModal(`${title} · ${rows.length} sipariş`, box);
}

/* ---------------- tek sipariş dökümü ---------------- */
async function showOrder(platform, oid) {
  const box = el("div");
  box.innerHTML = '<div class="empty"><span class="spin"></span></div>';
  openModal("Sipariş " + oid, box);
  let d;
  try { d = await api(`/api/order/${encodeURIComponent(platform)}/${encodeURIComponent(oid)}`); }
  catch (e) { box.innerHTML = `<div class="note err">${esc(e.message)}</div>`; return; }
  box.innerHTML = "";

  if (!d.order) {
    box.appendChild(el("div", "note err",
      "Bu sipariş sizin kayıtlarınızda yok. Platform parasını yatırmış ama " +
      "kasanıza girilmemiş görünüyor."));
  }
  if (d.error) box.appendChild(el("div", "note warn", d.error));

  if (d.breakdown && d.breakdown.length) {
    const h = el("h3", null, "Size ne ödenmeliydi?");
    h.style.cssText = "font-size:19px;margin-bottom:12px";
    box.appendChild(h);
    const t = el("table", "bd");
    d.breakdown.forEach((b) => {
      // "info" satırları para hareketi değil, hesabın dayanağıdır:
      // tutar sütununda rakam göstermek yanıltıcı olur.
      const info = b.kind === "info";
      const tr = el("tr", b.kind === "total" ? "total" : (info ? "muted" : ""));
      tr.innerHTML =
        `<td>${esc(b.label)}${b.note ? `<span class="sub">${esc(b.note)}</span>` : ""}</td>
         <td class="r num ${!info && b.amount < 0 ? "neg" : ""}">${
           info ? "" : (b.kind === "total" ? money(b.amount) : signed(b.amount))}</td>`;
      t.appendChild(tr);
    });
    box.appendChild(t);
  }

  const h2 = el("h3", null, "Platform ne ödedi?");
  h2.style.cssText = "font-size:19px;margin:30px 0 12px";
  box.appendChild(h2);

  if (!d.payout_lines.length) {
    box.appendChild(el("div", "note err",
      "Bu sipariş platformun ödeme raporunda hiç yok. Parası hiç yatmamış."));
  } else {
    const t2 = el("table", "bd");
    let paid = 0;
    d.payout_lines.forEach((p) => {
      paid += p.net_paid;
      t2.innerHTML +=
        `<tr><td>Sipariş tutarı</td><td class="r num">${money(p.gross_reported)}</td></tr>
         <tr><td>Aldıkları komisyon</td><td class="r num neg">${signed(-p.commission_charged)}</td></tr>
         <tr><td>Komisyon KDV'si</td><td class="r num neg">${signed(-p.commission_vat_charged)}</td></tr>
         ${p.other_deductions ? `<tr><td>Diğer kesinti<span class="sub">${esc(p.line_note || "gerekçe yazılmamış")}</span></td><td class="r num neg">${signed(-p.other_deductions)}</td></tr>` : ""}
         <tr class="total"><td>Ödedikleri</td><td class="r num">${money(p.net_paid)}</td></tr>`;
    });
    box.appendChild(t2);

    if (d.expected !== null && d.expected !== undefined) {
      const diff = Math.round((paid - d.expected) * 100) / 100;
      const n = el("div", "note " + (diff < -0.02 ? "err" : diff > 0.02 ? "warn" : "ok"));
      n.innerHTML = diff < -0.02
        ? `Bu siparişte <b>${esc(moneyAbs(diff))} eksik</b> ödenmiş.`
        : diff > 0.02 ? `Bu siparişte ${esc(moneyAbs(diff))} fazla ödenmiş.`
        : "Bu siparişte sorun yok.";
      box.appendChild(n);
    }
  }
}

/* =================================================================
   DOSYA YÜKLEME
   ================================================================= */
const ALAN_ADI = {
  platform_order_id: "Sipariş numarası", order_date: "Sipariş tarihi",
  items_subtotal: "Sipariş tutarı", delivery_fee: "Teslimat ücreti",
  discount_restaurant: "Sizin verdiğiniz indirim",
  discount_platform: "Platformun verdiği indirim",
  tip: "Bahşiş", payment_method: "Ödeme şekli", status: "Sipariş durumu",
  gross_reported: "Sipariş tutarı", commission_charged: "Aldıkları komisyon",
  commission_vat_charged: "Komisyon KDV'si", other_deductions: "Diğer kesinti",
  net_paid: "Ödedikleri tutar", line_note: "Açıklama",
};
const ALAN_IPUCU = {
  discount_restaurant: "Kampanyayı siz finanse ettiyseniz",
  discount_platform: "Kampanyayı platform finanse ettiyse",
  payment_method: "Online mı, kapıda mı ödenmiş",
  status: "Teslim edildi / iptal edildi",
};
const ZORUNLU = { pos_orders: ["platform_order_id", "order_date", "items_subtotal"],
                  payout_lines: ["platform_order_id", "net_paid"] };
let PREVIEW = null;

function renderUpload() {
  const box = $("#yukleBody"); box.innerHTML = "";

  // Durum özeti
  const st = el("div", "panel");
  st.appendChild(el("h2", null, "Nerede kaldık?"));
  const steps = el("div", "steps");
  const line = (done, title, desc) => {
    const d = el("div", "stepitem " + (done ? "done" : ""));
    d.appendChild(el("div", "stepnum", done ? "✓" : "!"));
    const b = el("div", "stepbody");
    b.appendChild(el("h3", null, title));
    b.appendChild(el("p", null, desc));
    d.appendChild(b); return d;
  };
  steps.appendChild(line(hasRules(), "Komisyon oranı",
    hasRules() ? `${STATE.rules.length} kural kayıtlı` : "Henüz girilmedi — Ayarlar bölümünden ekleyin"));
  steps.appendChild(line(hasOrders(), "Sipariş listeniz",
    hasOrders() ? `${nf0.format(STATE.order_total)} sipariş yüklü` : "Henüz yüklenmedi"));
  steps.appendChild(line(hasPayouts(), "Platformun ödeme raporu",
    hasPayouts() ? `${nf0.format(STATE.line_total)} satır yüklü` : "Henüz yüklenmedi"));
  st.appendChild(steps);
  box.appendChild(st);

  // Yükleme
  const p = el("div", "panel");
  p.appendChild(el("h2", null, "Dosya yükle"));
  const lead = el("p", "lead");
  lead.textContent = "Önce ne yüklediğinizi seçin, sonra dosyayı sürükleyin ya da tıklayıp bulun. " +
    "Dosyalarınız bu bilgisayardan çıkmaz.";
  p.appendChild(lead);

  const r1 = el("div", "row");
  const w1 = el("div", "fldwrap");
  w1.appendChild(el("label", "fld", "Bu dosya ne?"));
  const kind = el("select");
  [["pos_orders", "Kendi sipariş listem"],
   ["payout_lines", "Platformun ödeme raporu"]]
    .forEach(([v, t]) => { const o = el("option", null, t); o.value = v; kind.appendChild(o); });
  w1.appendChild(kind); r1.appendChild(w1);

  const w2 = el("div", "fldwrap");
  w2.appendChild(el("label", "fld", "Hangi platform?"));
  const plat = el("select");
  Object.entries(PLATFORMS).forEach(([v, t]) => {
    const o = el("option", null, t); o.value = v; plat.appendChild(o);
  });
  w2.appendChild(plat); r1.appendChild(w2);
  p.appendChild(r1);

  const drop = el("label", "drop");
  drop.style.marginTop = "20px";
  drop.innerHTML = `<div class="ico">📄</div>
    <div class="t">Dosyayı buraya sürükleyin</div>
    <div class="s">ya da tıklayıp bilgisayarınızdan seçin · Excel (.xlsx) veya CSV</div>`;
  const file = el("input"); file.type = "file"; file.accept = ".csv,.xlsx,.xlsm,.txt";
  drop.appendChild(file);
  p.appendChild(drop);
  const area = el("div"); p.appendChild(area);
  box.appendChild(p);

  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) { file.files = e.dataTransfer.files; handle(); }
  });
  file.onchange = handle;

  async function handle() {
    if (!file.files.length) return;
    drop.classList.add("filled");
    drop.querySelector(".t").textContent = file.files[0].name;
    drop.querySelector(".s").textContent = "okunuyor…";
    area.innerHTML = '<div class="empty"><span class="spin"></span></div>';
    const fd = new FormData();
    fd.append("file", file.files[0]); fd.append("kind", kind.value);
    try {
      PREVIEW = await api("/api/upload/preview", { method: "POST", body: fd });
      drop.querySelector(".s").textContent =
        `${nf0.format(PREVIEW.row_count)} satır okundu`;
      renderMapping(area, plat.value, kind.value);
    } catch (e) {
      drop.classList.remove("filled");
      drop.querySelector(".s").textContent = "tekrar deneyin";
      area.innerHTML = `<div class="note err">${esc(e.message)}</div>`;
    }
  }
}

function renderMapping(container, platform, kind) {
  container.innerHTML = "";
  const p = PREVIEW;
  const wrap = el("div");
  wrap.style.marginTop = "26px";

  const h = el("h2", null, "Sütunları eşleştirin");
  h.style.cssText = "font-size:22px;margin-bottom:6px";
  wrap.appendChild(h);
  const lead = el("p", "lead");
  lead.innerHTML = "Dosyanızdaki sütunları tanımaya çalıştık. <b>Yanlış olan varsa " +
    "düzeltin.</b> Boş bırakılan bilgi sıfır kabul edilir ve sonuç yanlış çıkar.";
  wrap.appendChild(lead);

  const zorunlu = ZORUNLU[kind];
  const grid = el("div", "maps");
  const selects = {};
  // Zorunlular üstte
  const sorted = p.fields.slice().sort((a, b) =>
    (zorunlu.includes(b) ? 1 : 0) - (zorunlu.includes(a) ? 1 : 0));
  sorted.forEach((fld) => {
    const item = el("div", "mapitem");
    const lab = el("label");
    lab.innerHTML = esc(ALAN_ADI[fld] || fld) +
      (zorunlu.includes(fld) ? ' <span class="req">*</span>' : "");
    item.appendChild(lab);
    const sel = el("select");
    const o0 = el("option", null, "— dosyamda yok —"); o0.value = ""; sel.appendChild(o0);
    p.headers.forEach((hd) => {
      if (!hd) return;
      const o = el("option", null, hd); o.value = hd; sel.appendChild(o);
    });
    sel.value = p.mapping[fld] || "";
    const mark = () => item.classList.toggle("miss", !sel.value && zorunlu.includes(fld));
    mark(); sel.onchange = mark;
    selects[fld] = sel;
    item.appendChild(sel);
    if (ALAN_IPUCU[fld]) {
      item.appendChild(el("div", "help", ALAN_IPUCU[fld]));
    }
    grid.appendChild(item);
  });
  wrap.appendChild(grid);

  // Önizleme (katlanmış)
  const det = el("details");
  const sum = el("summary", null, "Dosyamın ilk satırlarını göster");
  det.appendChild(sum);
  const inner = el("div", "inner");
  const w = el("div", "tablewrap"); w.style.maxHeight = "260px";
  const t = el("table");
  t.innerHTML = "<thead><tr>" + p.headers.map((hd) => `<th>${esc(hd)}</th>`).join("") + "</tr></thead>";
  const tb = el("tbody");
  p.sample.forEach((rw) => {
    tb.innerHTML += "<tr>" + p.headers.map((hd) => `<td>${esc(rw[hd])}</td>`).join("") + "</tr>";
  });
  t.appendChild(tb); w.appendChild(t); inner.appendChild(w); det.appendChild(inner);
  wrap.appendChild(det);

  // Hakediş ek bilgileri
  let bankIn = null, refIn = null;
  if (kind === "payout_lines") {
    const d2 = el("div");
    d2.style.marginTop = "26px";
    const h2 = el("h2", null, "Bankaya ne kadar geçti?");
    h2.style.cssText = "font-size:22px;margin-bottom:6px";
    d2.appendChild(h2);
    const l2 = el("p", "lead");
    l2.innerHTML = "Bu ay için hesabınıza <b>gerçekte yatan</b> tutarı yazın. " +
      "Raporda yazan toplamla banka hesabınıza geçen para çoğu zaman farklı olur — " +
      "aradaki fark en çok para kaybedilen yerdir. Bilmiyorsanız boş bırakabilirsiniz.";
    d2.appendChild(l2);
    const r2 = el("div", "row");
    const mk = (lbl, type, ph, help) => {
      const f = el("div", "fldwrap");
      f.appendChild(el("label", "fld", lbl));
      const i = el("input"); i.type = type; if (ph) i.placeholder = ph;
      if (type === "number") i.step = "0.01";
      f.appendChild(i);
      if (help) f.appendChild(el("div", "help", help));
      r2.appendChild(f); return i;
    };
    bankIn = mk("Hesabınıza geçen tutar (TL)", "number", "örnek: 63155,16",
                "Banka ekstrenizdeki tutar");
    refIn = mk("Dekont / hakediş no", "text", "örnek: HAK-2026-08",
               "İsteğe bağlı, hatırlamanız için");
    d2.appendChild(r2);
    wrap.appendChild(d2);
  }

  const act = el("div", "row");
  act.style.marginTop = "28px";
  const btn = el("button", "big-btn", "Kaydet");
  const msg = el("div");
  msg.style.fontSize = "16.5px";
  act.appendChild(btn); act.appendChild(msg);
  wrap.appendChild(act);
  container.appendChild(wrap);

  btn.onclick = async () => {
    const mapping = {};
    Object.entries(selects).forEach(([k, v]) => { if (v.value) mapping[k] = v.value; });
    const miss = zorunlu.filter((f) => !mapping[f]);
    if (miss.length) {
      msg.innerHTML = `<span style="color:var(--bad)"><b>Şunlar eksik:</b> ` +
        miss.map((f) => esc(ALAN_ADI[f])).join(", ") + "</span>";
      return;
    }
    btn.disabled = true; msg.innerHTML = '<span class="spin"></span>';
    try {
      const body = { token: p.token, platform, mapping };
      if (kind === "payout_lines") {
        body.statement_ref = refIn.value;
        body.total_paid = parseFloat(String(bankIn.value).replace(",", ".")) || 0;
      }
      const res = await api("/api/upload/commit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
      await loadState();
      const ok = el("div", "note ok");
      ok.innerHTML = `<b>${nf0.format(res.imported)} satır kaydedildi.</b>` +
        (res.skipped_count ? ` ${res.skipped_count} satır okunamadığı için atlandı.` : "");
      container.innerHTML = ""; container.appendChild(ok);
      if (isReady()) {
        const go = el("button", "big-btn", "Sonucu gör");
        go.onclick = () => { location.hash = "sonuc"; };
        container.appendChild(go);
      } else {
        container.appendChild(el("p", null, hasPayouts() && !hasOrders()
          ? "Şimdi kendi sipariş listenizi de yükleyin."
          : "Şimdi platformun ödeme raporunu da yükleyin."));
      }
      renderUploadStatusOnly();
    } catch (e) {
      msg.innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
    } finally { btn.disabled = false; }
  };
}

// Kaydettikten sonra üstteki durum kutusunu tazele (formu bozmadan)
function renderUploadStatusOnly() {
  const first = $("#yukleBody").firstElementChild;
  if (!first) return;
  const steps = first.querySelectorAll(".stepitem");
  const vals = [[hasRules(), hasRules() ? `${STATE.rules.length} kural kayıtlı` : "Henüz girilmedi — Ayarlar bölümünden ekleyin"],
                [hasOrders(), hasOrders() ? `${nf0.format(STATE.order_total)} sipariş yüklü` : "Henüz yüklenmedi"],
                [hasPayouts(), hasPayouts() ? `${nf0.format(STATE.line_total)} satır yüklü` : "Henüz yüklenmedi"]];
  steps.forEach((s, i) => {
    s.classList.toggle("done", !!vals[i][0]);
    s.querySelector(".stepnum").textContent = vals[i][0] ? "✓" : "!";
    s.querySelector("p").textContent = vals[i][1];
  });
}

/* =================================================================
   AYARLAR — komisyon oranları
   ================================================================= */
const MATRAH = {
  items_after_discount: "İndirim düşüldükten sonraki tutardan",
  items_before_discount: "İndirim düşülmeden önceki tutardan",
  items_plus_delivery: "Teslimat ücreti de dahil tutardan",
  gross: "Her şey dahil toplam tutardan",
};

function renderSettings() {
  const box = $("#ayarlarBody"); box.innerHTML = "";

  const p = el("div", "panel");
  p.appendChild(el("h2", null, "Komisyon oranlarınız"));
  const lead = el("p", "lead");
  lead.innerHTML = "Program “size ne ödenmeliydi”yi <b>buradaki bilgilere göre</b> hesaplar. " +
    "Sözleşmenizde yazan oranı girin. Emin değilseniz platformun müşteri " +
    "temsilcisine sorun — yanlış oran, yanlış sonuç demektir.";
  p.appendChild(lead);

  const rules = (STATE && STATE.rules) || [];
  if (rules.length) {
    const w = el("div", "tablewrap"); w.style.maxHeight = "none";
    const t = el("table");
    t.innerHTML = `<thead><tr><th>Platform</th><th class="r">Komisyon</th>
      <th>Ne zamandan beri</th><th></th></tr></thead>`;
    const tb = el("tbody");
    rules.forEach((r) => {
      const tr = el("tr");
      tr.innerHTML =
        `<td><b>${esc(plabel(r.platform))}</b></td>
         <td class="r num"><b>%${nf.format(r.commission_rate * 100)}</b></td>
         <td>${esc(r.valid_from)}${r.valid_to ? " → " + esc(r.valid_to) : ""}</td>
         <td class="r"></td>`;
      const del = el("button", "big-btn ghost", "Sil");
      del.style.cssText = "padding:8px 16px;font-size:15px";
      del.onclick = async () => {
        if (!confirm("Bu oran silinsin mi? Kapsadığı dönemin hesabı yapılamaz hale gelir.")) return;
        await api("/api/rules/" + r.id, { method: "DELETE" });
        await loadState(); renderSettings();
      };
      tr.lastChild.appendChild(del);
      tb.appendChild(tr);
    });
    t.appendChild(tb); w.appendChild(t); p.appendChild(w);
  } else {
    p.appendChild(el("div", "note warn",
      "Henüz komisyon oranı girmediniz. Hesaplama yapılabilmesi için gerekli."));
  }
  box.appendChild(p);

  // --- ekleme formu ---
  const f = el("div", "panel");
  f.appendChild(el("h2", null, rules.length ? "Yeni oran ekle" : "Komisyon oranınızı girin"));
  const lead2 = el("p", "lead");
  lead2.textContent = "Çoğu kullanıcı için ilk üç kutuyu doldurmak yeterli.";
  f.appendChild(lead2);

  const inputs = {};
  const r1 = el("div", "row");
  const mk = (parent, key, label, type, opts, def, help) => {
    const w = el("div", "fldwrap");
    const lb = el("label", "fld"); lb.innerHTML = label; w.appendChild(lb);
    let i;
    if (opts) { i = el("select");
      opts.forEach(([v, t]) => { const o = el("option", null, t); o.value = v; i.appendChild(o); });
    } else { i = el("input"); i.type = type; if (type === "number") i.step = "0.01"; }
    if (def !== undefined) i.value = def;
    w.appendChild(i);
    if (help) w.appendChild(el("div", "help", help));
    inputs[key] = i; parent.appendChild(w); return i;
  };

  mk(r1, "platform", "Platform", null, Object.entries(PLATFORMS));
  mk(r1, "rate", "Komisyon oranı (%)", "number", null, "18", "Sözleşmenizde yazan yüzde");
  mk(r1, "from", "Ne zamandan beri geçerli?", "date", null, "",
     "Bu tarihten sonraki siparişlere uygulanır");
  f.appendChild(r1);

  // Gelişmiş
  const det = el("details");
  det.appendChild(el("summary", null, "Gelişmiş ayarlar (çoğu kullanıcı dokunmaz)"));
  const inner = el("div", "inner");
  const r2 = el("div", "row");
  mk(r2, "base", "Komisyon hangi tutardan alınıyor?", null, Object.entries(MATRAH), undefined,
     "Sözleşmede indirimli fiyattan mı, indirimsizden mi yazıyor");
  mk(r2, "vat", "Komisyon KDV oranı (%)", "number", null, "20",
     "Türkiye'de %20. Komisyon faturasının KDV'si.");
  inner.appendChild(r2);
  const r3 = el("div", "row");
  r3.style.marginTop = "16px";
  mk(r3, "proc", "Online ödeme işlem ücreti (%)", "number", null, "0",
     "Kartlı ödemelerde ayrıca kesiliyorsa");
  mk(r3, "fixed", "Sipariş başı sabit ücret (TL)", "number", null, "0",
     "Her siparişten sabit bir tutar kesiliyorsa");
  mk(r3, "delivery", "Teslimat ücreti kimin?", null,
     [["platform", "Platformun"], ["restaurant", "Bizim"]], undefined,
     "Teslimat bedelini kim alıyor");
  inner.appendChild(r3);
  det.appendChild(inner);
  f.appendChild(det);

  const act = el("div", "row"); act.style.marginTop = "26px";
  const btn = el("button", "big-btn", "Kaydet");
  const msg = el("div"); msg.style.fontSize = "16.5px";
  act.appendChild(btn); act.appendChild(msg); f.appendChild(act);
  box.appendChild(f);

  btn.onclick = async () => {
    if (!inputs.from.value) {
      msg.innerHTML = '<span style="color:var(--bad)">Başlangıç tarihi girin</span>'; return;
    }
    const rate = parseFloat(String(inputs.rate.value).replace(",", "."));
    if (!(rate > 0 && rate < 100)) {
      msg.innerHTML = '<span style="color:var(--bad)">Komisyon oranı 0 ile 100 arasında olmalı</span>';
      return;
    }
    btn.disabled = true;
    try {
      await api("/api/rules", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: inputs.platform.value,
          valid_from: inputs.from.value, valid_to: null,
          commission_rate: rate / 100,
          commission_base: inputs.base.value,
          fixed_fee_per_order: parseFloat(String(inputs.fixed.value).replace(",", ".")) || 0,
          payment_processing_rate:
            (parseFloat(String(inputs.proc.value).replace(",", ".")) || 0) / 100,
          commission_vat_rate:
            (parseFloat(String(inputs.vat.value).replace(",", ".")) || 0) / 100,
          delivery_fee_to: inputs.delivery.value,
          service_fee_per_order: 0,
        }) });
      await loadState(); renderSettings();
    } catch (e) {
      msg.innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
    } finally { btn.disabled = false; }
  };
}

/* ================================================================= */
(async function init() {
  try {
    await loadState();
    const h = location.hash.slice(1);
    if (h) showTab(h);
    else if (!isReady()) showTab(hasRules() ? "yukle" : "sonuc");
    else showTab("sonuc");
  } catch (e) {
    $("#sonucBody").innerHTML =
      `<div class="note err">Program yüklenemedi: ${esc(e.message)}</div>`;
  }
})();
