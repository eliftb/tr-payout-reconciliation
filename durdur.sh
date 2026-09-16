#!/bin/bash
# Ödeme Kontrol sunucusunu durdurur.
if command -v fuser >/dev/null 2>&1 && fuser -k 8770/tcp 2>/dev/null; then
  echo "Durduruldu."
else
  echo "Zaten çalışmıyordu."
fi
