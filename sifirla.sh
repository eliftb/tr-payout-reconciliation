#!/bin/bash
# Tüm veriyi siler: siparişler, hakediş raporları ve komisyon kuralları.
cd "$(dirname "$0")" || exit 1
read -r -p "TÜM veri silinecek (siparişler, hakedişler, komisyon kuralları). Emin misin? [e/H] " a
case "$a" in
  [eE]) rm -f data/hakedis.db data/hakedis.db-wal data/hakedis.db-shm
        python3 db.py && echo "Sıfırlandı. Komisyon kurallarını yeniden girmen gerekiyor." ;;
  *)    echo "İptal edildi." ;;
esac
