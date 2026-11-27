#!/usr/bin/env python3
"""Legge il dominio aggiornato dal canale Telegram pubblico e riscrive la pagina di redirect.

Uso: python3 aggiorna.py   (lanciato ogni 10 minuti da GitHub Actions)

Codici di uscita:
  0 = tutto ok (anche se Telegram e' momentaneamente irraggiungibile)
  1 = problema da guardare (messaggio non trovato, formato cambiato, errore HTTP):
      GitHub ti manda un'email e il redirect resta sull'ultimo dominio valido.
"""
import html as html_lib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

CANALE = "Streaming_community_sito"
FONTE = f"https://t.me/s/{CANALE}"   # anteprima web pubblica del canale (nessun login)
PAGINA = Path("index.html")
STATO = Path("stato.json")

# Dentro il messaggio "Dominio Aggiornato" cerco il dominio che segue "Nuovo:".
# La riga "Bloccati" usa la forma con [.] e quindi non viene mai presa.
PATTERN_MESSAGGIO = re.compile(r'data-post="([^"/]+)/(\d+)"')
PATTERN_NUOVO = re.compile(
    r"Nuovo\s*:?\s*(?:https?://)?(streamingcommunityz\.[a-z]{2,10})\b", re.IGNORECASE
)
PATTERN_DOMINIO = re.compile(r"^streamingcommunityz\.[a-z]{2,10}$")

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


def trova_ultimo_dominio(pagina):
    """Restituisce (id_messaggio, dominio) dell'annuncio piu' recente, oppure None."""
    segnaposti = list(PATTERN_MESSAGGIO.finditer(pagina))
    candidati = []
    for i, m in enumerate(segnaposti):
        if m.group(1).lower() != CANALE.lower():
            continue
        fine = segnaposti[i + 1].start() if i + 1 < len(segnaposti) else len(pagina)
        blocco = pagina[m.end():fine]
        testo = html_lib.unescape(re.sub(r"<[^>]+>", " ", blocco))
        testo = re.sub(r"\s+", " ", testo)
        if "dominio aggiornato" not in testo.lower():
            continue
        trovato = PATTERN_NUOVO.search(testo)
        if trovato:
            candidati.append((int(m.group(2)), trovato.group(1).lower()))
    if not candidati:
        return None
    candidati.sort()
    return candidati[-1]


def scrivi_output(**valori):
    """Passa i risultati al workflow (serve per l'avviso via email)."""
    percorso = os.environ.get("GITHUB_OUTPUT")
    if not percorso:
        return
    with open(percorso, "a", encoding="utf-8") as f:
        for chiave, valore in valori.items():
            f.write(f"{chiave}={valore}\n")


def main():
    # 1) Scarico l'anteprima pubblica del canale
    try:
        pagina = scarica(FONTE)
    except urllib.error.HTTPError as e:
        print(f"ERRORE: Telegram ha risposto con HTTP {e.code}")
        scrivi_output(cambiato="false", vecchio="", nuovo="")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"Telegram momentaneamente irraggiungibile ({e}). Riprovo al prossimo giro.")
        scrivi_output(cambiato="false", vecchio="", nuovo="")
        return 0

    # 2) Cerco l'annuncio piu' recente e il dominio dopo "Nuovo:"
    trovato = trova_ultimo_dominio(pagina)
    if trovato is None:
        print("ERRORE: nessun messaggio 'Dominio Aggiornato' con un dominio valido.")
        print("Non modifico nulla: controlla a mano il canale.")
        scrivi_output(cambiato="false", vecchio="", nuovo="")
        return 1
    id_messaggio, dominio = trovato
    if not PATTERN_DOMINIO.match(dominio):
        print(f"ERRORE: dominio con formato non valido: {dominio}")
        scrivi_output(cambiato="false", vecchio="", nuovo="")
        return 1

    # 3) Confronto con l'ultimo dominio applicato
    stato = json.loads(STATO.read_text(encoding="utf-8")) if STATO.exists() else {}
    vecchio = stato.get("dominio", "")

    if id_messaggio < stato.get("messaggio", 0):
        print("Il messaggio trovato e' piu' vecchio dell'ultimo applicato: lo ignoro.")
        scrivi_output(cambiato="false", vecchio=vecchio, nuovo=vecchio)
        return 0

    oggi = date.today()
    cambiato = vecchio != dominio

    if cambiato or not PAGINA.exists():
        PAGINA.write_text(TEMPLATE.replace("__DOMINIO__", dominio), encoding="utf-8")
        print(f"Redirect aggiornato: {vecchio or '(nessuno)'} -> {dominio} (messaggio {id_messaggio})")
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
            "messaggio": id_messaggio,
            "ultimo_controllo": oggi.isoformat(),
            "storico": storico[-MAX_STORICO:],
        }
        STATO.write_text(
            json.dumps(stato, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    scrivi_output(
        cambiato="true" if cambiato else "false", vecchio=vecchio, nuovo=dominio
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
