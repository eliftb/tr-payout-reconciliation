#!/bin/bash
# Ödeme Kontrol başlatıcısı.
# Sunucu çalışmıyorsa başlatır, sonra tarayıcıyı açar.
# Zaten çalışıyorsa ikinci kez başlatmaz, sadece sayfayı açar.

cd "$(dirname "$(readlink -f "$0")")" || exit 1
PORT=8770
URL="http://127.0.0.1:$PORT"
LOG="data/sunucu.log"

hata() {
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --width=380 --title="Ödeme Kontrol" --text="$1" 2>/dev/null
  else
    echo "HATA: $1" >&2
  fi
  exit 1
}

# Port açık mı? (python3 ile, ek program gerektirmez)
acik() {
  python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

command -v python3 >/dev/null 2>&1 || hata "Python 3 bulunamadı.\nKurmak için terminalde:\nsudo apt install python3"

if ! acik; then
  mkdir -p data
  nohup python3 app.py >> "$LOG" 2>&1 &
  # Ayağa kalkmasını bekle (en fazla ~10 saniye)
  for _ in $(seq 1 40); do
    acik && break
    sleep 0.25
  done
  acik || hata "Program başlatılamadı.\nAyrıntı için şu dosyaya bakın:\n$(pwd)/$LOG"
fi

xdg-open "$URL" >/dev/null 2>&1 &
