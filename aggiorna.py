#!/usr/bin/env python3
"""Legge il dominio aggiornato dal blog e riscrive la pagina di redirect.

Uso: python3 aggiorna.py   (lanciato ogni 30 minuti da GitHub Actions)

Codici di uscita:
  0 = tutto ok (anche se il blog e' momentaneamente irraggiungibile)
  1 = problema da guardare (pagina cambiata, piu' domini, errore HTTP):
      GitHub ti manda un'email e il redirect resta sull'ultimo dominio valido.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

FONTE = "https://www.giardiniblog.it/streamingcommunity-nuovo-link/"
PAGINA = Path("index.html")
STATO = Path("stato.json")

# Accetta solo domini della forma streaming-community.xxx / streamingcommunityz.xxx
PATTERN_URL = re.compile(
    r"https?://(?:www\.)?(streaming-?community[a-z]*\.[a-z]{2,10})", re.IGNORECASE
)
PATTERN_DOMINIO = re.compile(r"^streaming-?community[a-z]*\.[a-z]{2,10}$")

GIORNI_HEARTBEAT = 7   # ogni quanti giorni aggiornare la data di controllo
MAX_STORICO = 20       # quante modifiche di dominio ricordare

TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="referrer" content="no-referrer">
<meta http-equiv="refresh" content="0; url=https://__DOMINIO__/">
<title>Reindirizzamento...</title>
<style>
  body { font-family: system-ui, sans-serif; text-align: center; margin-top: 20vh; }
  @media (prefers-color-scheme: dark) { body { background: #111; color: #eee; } a { color: #8ab4f8; } }
</style>
<script>location.replace("https://__DOMINIO__/");</script>
</head>
<body>
<p>Reindirizzamento in corso...</p>
<p><a href="https://__DOMINIO__/">Clicca qui</a> se non parte da solo.</p>
</body>
</html>
"""


def scarica(url):
    richiesta = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9",
        },
    )
    with urllib.request.urlopen(richiesta, timeout=30) as risposta:
        return risposta.read().decode("utf-8", errors="replace")


def main():
    # 1) Scarico la pagina del blog
    try:
        html = scarica(FONTE)
    except urllib.error.HTTPError as e:
        print(f"ERRORE: il blog ha risposto con HTTP {e.code}")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"Blog momentaneamente irraggiungibile ({e}). Riprovo al prossimo giro.")
        return 0

    # 2) Cerco il dominio: deve essercene esattamente uno, nel formato atteso
    trovati = {m.group(1).lower() for m in PATTERN_URL.finditer(html)}
    if len(trovati) != 1:
        print(f"ERRORE: attesi 1 dominio, trovati {len(trovati)}: {sorted(trovati)}")
        print("Non modifico nulla: controlla a mano la pagina del blog.")
        return 1
    dominio = next(iter(trovati))
    if not PATTERN_DOMINIO.match(dominio):
        print(f"ERRORE: dominio con formato non valido: {dominio}")
        return 1

    # 3) Confronto con l'ultimo dominio applicato
    stato = json.loads(STATO.read_text(encoding="utf-8")) if STATO.exists() else {}
    oggi = date.today()
    cambiato = stato.get("dominio") != dominio

    if cambiato or not PAGINA.exists():
        PAGINA.write_text(TEMPLATE.replace("__DOMINIO__", dominio), encoding="utf-8")
        print(f"Redirect aggiornato: {stato.get('dominio')} -> {dominio}")
    else:
        print(f"Nessun cambio, dominio attuale: {dominio}")

    # 4) Aggiorno lo stato (registro modifiche + "battito" settimanale per
    #    evitare che GitHub disattivi l'automazione dopo 60 giorni di inattivita')
    ultimo = date.fromisoformat(stato.get("ultimo_controllo", "2000-01-01"))
    if cambiato or (oggi - ultimo).days >= GIORNI_HEARTBEAT:
        storico = stato.get("storico", [])
        if cambiato:
            storico.append({"data": oggi.isoformat(), "dominio": dominio})
        stato = {
            "dominio": dominio,
            "ultimo_controllo": oggi.isoformat(),
            "storico": storico[-MAX_STORICO:],
        }
        STATO.write_text(
            json.dumps(stato, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
