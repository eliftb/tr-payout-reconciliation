# Ödeme Kontrol

*[English](README.md) · Türkçe*

Yemek platformlarının (Yemeksepeti, Trendyol Yemek, Getir Yemek…) size
ödemesi **gereken** parayı hesaplar, **gerçekte ödediklerini** karşılaştırır,
aradaki farkı ve sebebini gösterir.

Her şey kendi bilgisayarınızda çalışır. Verileriniz dışarı çıkmaz,
internet gerekmez.

---

## Nasıl açılır

Masaüstündeki **Ödeme Kontrol** simgesine çift tıklayın. Program açılır ve
tarayıcıda kendiliğinden görüntülenir.

İlk çift tıklamada Ubuntu "Güvenilmeyen uygulama" diye sorabilir —
**Başlat / Trust and Launch** deyin, bir daha sormaz.

Zaten açıkken tekrar tıklarsanız ikinci kopya açılmaz, sadece sayfa
yeniden gösterilir.

### Kapatmak
Sadece tarayıcı sekmesini kapatmak programı kapatmaz, arkada çalışmaya
devam eder (bilgisayarınızı yavaşlatmaz). Tamamen durdurmak isterseniz
`Ödeme Kontrol dosyaları` klasöründeki `durdur.sh` dosyasına çift tıklayın.

Bilgisayarı kapatıp açtığınızda program durur; masaüstü simgesine tekrar
tıklamanız yeterlidir.

### Terminalden açmak isterseniz
```bash
cd ~/hakedis
python3 app.py
```
Sonra tarayıcıdan **http://127.0.0.1:8770**

---

## Üç bölüm var

### Sonuç
Ayı seçersiniz, program size o ay ne kadar eksik ödendiğini söyler.

- **İtiraz listesini indir** — Excel dosyası olarak iner, platformun
  müşteri temsilcisine gönderebilirsiniz.
- **Siparişleri tek tek gör** — hangi siparişte ne kadar fark olduğunu
  gösterir. Bir siparişe tıklayınca hesabın **satır satır dökümü** açılır:
  sipariş tutarından başlayıp her kesintiyi sebebiyle gösterir.

İtiraz ederken kullanacağınız ekran bu dökümdür. "Eksik ödediniz" demek
platformu ikna etmez; "şu kalemi şöyle hesapladım" demek eder.

### Dosya Yükle
İki dosya yüklersiniz:

1. **Kendi sipariş listeniz** — kasa/POS sisteminizden aldığınız döküm
2. **Platformun ödeme raporu** — platformun panelinden indirdiğiniz
   hakediş/ödeme raporu

Excel (.xlsx) veya CSV olur. Sütunları program tanımaya çalışır, siz
onaylarsınız.

> Ödeme raporunu yüklerken **hesabınıza gerçekte geçen tutarı** da yazın.
> Raporda yazan toplamla bankaya yatan para çoğu zaman farklı olur ve
> aradaki fark hiçbir siparişte görünmez — en çok para orada kaybolur.

### Ayarlar
Komisyon oranınızı girersiniz. Program "size ne ödenmeliydi"yi buradan
hesaplar.

Çoğu kişi için üç kutu yeterli: platform, komisyon yüzdesi, başlangıç
tarihi. Gerisi "Gelişmiş ayarlar" içinde ve varsayılanları Türkiye için
doğru ayarlı.

> Oranınız sonradan değiştiyse eskisini silmeyin, yenisini ekleyin.
> Program hangi siparişe hangi oranın uygulanacağını tarihe bakarak bulur.
> Mart siparişini bugünün oranıyla ölçmek yanlış sonuç verir.

---

## Program neleri yakalar

| Bulgu | Ne olmuş |
|---|---|
| Hiç ödenmemiş | Teslim ettiğiniz sipariş rapora hiç girmemiş |
| Anlaşmadan yüksek komisyon almışlar | Sözleşmedekinden yüksek oran uygulanmış |
| Fazla komisyon kesilmiş | Oran doğru ama tutar fazla |
| İptal siparişten komisyon almışlar | İptal olan siparişten komisyon alınmış |
| Kendi kampanyalarını size ödetmişler | Platformun indirimi sizin cironuzdan düşülmüş |
| Sebebi yazılmamış kesinti | Kesinti var ama gerekçe yok |
| Toplu kesinti | Rapor toplamı ile bankaya geçen para farklı |
| Sizde kaydı yok | Platform ödemiş ama sizde sipariş yok (lehinize) |
| Fazla ödenmiş | Hakkınızdan fazla ödenmiş (lehinize, geri isteyebilirler) |

Eksik ödenen her lira **tek bir sebebe** bağlanır. Aynı para iki kalemde
sayılmaz — yoksa itiraz tutarı şişer ve platform listeyi haklı olarak
reddeder. Sonuç ekranındaki yeşil şerit "eksiğin tamamının sebebi
tespit edildi" diyorsa liste savunulabilir demektir.

---

## Kapıda ödeme neden eksi görünüyor?

Kapıda nakit/kartla ödenen siparişte parayı siz tahsil ettiniz. Platform
size ciro ödemez, sadece komisyonunu sizden alacaklıdır. Bu yüzden o
siparişte "size ödenmesi gereken" eksi çıkar. Hata değil.

---

## Örnek veriler

`sample/` klasöründe bilerek hata yerleştirilmiş örnek bir ay var
(Ağustos 2026, Yemeksepeti, 220 sipariş). Programın bulması gereken 30
hata `sample/beklenen_hatalar.csv` dosyasında yazılı. Denemek için:

1. **Ayarlar** → platform `yemeksepeti`, komisyon oranı %18, başlangıç
   tarihi Ağustos 2026'dan önce herhangi bir gün. *Gelişmiş ayarlar*
   içinde: komisyon *indirim düşüldükten sonraki tutardan*, online ödeme
   işlem ücreti %1,79
2. **Dosya Yükle** → `pos_siparisler_2026-08.csv` kendi sipariş listeniz,
   `yemeksepeti_hakedis_2026-08.csv` platform raporu; bankaya geçen tutar
   `63155,16`
3. **Sonuç** → Ağustos 2026

Denedikten sonra kendi verinizle temiz başlamak için:

```bash
cd ~/hakedis
./sifirla.sh
```

Komisyon oranları da silinir, yeniden girmeniz gerekir.

---

## Yedekleme

Bütün veriniz tek bir dosyada: `~/hakedis/data/hakedis.db`
Bu dosyayı kopyalamanız yedek almak için yeterlidir.

---

## Teknik notlar

| Dosya | Görevi |
|---|---|
| `app.py` | Web sunucusu ve API |
| `db.py` | Veritabanı şeması (SQLite) |
| `rules.py` | Komisyon hesap motoru — "ne ödenmeliydi" |
| `reconcile.py` | Karşılaştırma ve fark sınıflandırma |
| `importers.py` | Excel/CSV okuma, sütun tanıma |
| `static/` | Arayüz |
| `sample/` | Örnek veri üreticisi (`make_sample.py`) |

Python 3 ve `openpyxl` dışında bağımlılık yok.

### Henüz yapılmadı
- Trendyol/Getir rapor formatları için hazır sütun eşlemeleri
  (`import_profiles` tablosu şemada var, arayüzü yok)
- İtiraz takibi: açık / gönderildi / kabul / tahsil edildi
  (`disputes` tablosu ve API hazır, arayüzü yok)
- Aylar arası karşılaştırma
