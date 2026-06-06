#!/usr/bin/env python3
"""
Cerca libri nell'OPAC RBBC e verifica disponibilità a Rezzato.

Uso:
    python cerca_libri_rezzato.py "La luna e i falò" "1984"
    python cerca_libri_rezzato.py --file lista.txt
    python cerca_libri_rezzato.py --debug "La luna e i falò"

Requisiti: Python 3.8+, curl
"""

import subprocess, sys, re, argparse, time
from urllib.parse import quote_plus

BASE_URL   = "https://opac.provincia.brescia.it"
BIBLIOTECA = "REZZATO"
RITARDO    = 1.5

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: it-IT,it;q=0.9",
    "-H", "Accept-Encoding: gzip, deflate, br",
]

COOKIE_FILE = "/tmp/rbbc_session.txt"

# ── curl ──────────────────────────────────────────────────────────────────────

def curl_get(url, verbose=False):
    if verbose:
        print(f"  → GET {url}", file=sys.stderr)
    cmd = (["curl", "-s", "-L", "--compressed", "--max-time", "25",
            "--cookie-jar", COOKIE_FILE, "--cookie", COOKIE_FILE]
           + HEADERS + [url])
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout

def strip_tags(h):
    t = re.sub(r'<[^>]+>', ' ', h)
    for a, b in [('&amp;','&'),('&nbsp;',' '),('&lt;','<'),
                 ('&gt;','>'),('&#39;',"'"),('&quot;','"')]:
        t = t.replace(a, b)
    return re.sub(r'\s+', ' ', t).strip()

# ── Ricerca ───────────────────────────────────────────────────────────────────

def cerca_titolo(titolo, verbose=False):
    """Cerca il titolo con ?q= e restituisce lista di {titolo, autore, url}."""
    url  = f"{BASE_URL}/opac/search?q={quote_plus(titolo)}"
    html = curl_get(url, verbose=verbose)
    if not html:
        return []

    # Regex confermato funzionante dalla diagnosi:
    # href="opac/detail/view/test:catalog:1835473" title="La luna e i falò - Cesare Pavese">
    # [\s\S]{0,200}? attraversa anche newline dentro il tag
    pattern = r'href="opac/detail/view/test:catalog:(\d+)"[\s\S]{0,200}?title="([^"]{5,200})"'
    matches = re.findall(pattern, html)

    # Deduplica mantenendo ordine; scarta titoli di navigazione ("Vai a ...")
    visti = {}
    for num, titolo_raw in matches:
        if num not in visti:
            t = strip_tags(titolo_raw)
            if t and not t.lower().startswith("vai a"):
                visti[num] = t

    if verbose:
        print(f"  [ricerca] {len(visti)} risultati trovati", file=sys.stderr)

    return [
        {"titolo": tit, "autore": "—",
         "url": f"{BASE_URL}/opac/detail/view/test:catalog:{num}"}
        for num, tit in list(visti.items())[:10]
    ]

# ── Verifica disponibilità a Rezzato ─────────────────────────────────────────

def verifica_disponibilita(url, verbose=False):
    """
    Apre la pagina di dettaglio e cerca le righe della tabella copie
    relative a REZZATO.
    Struttura colonne: Biblioteca|Collocazione|Inventario|Stato|Prestabilità|Rientra
    """
    html = curl_get(url, verbose=verbose)
    if not html:
        return {"titolo": "—", "autore": "—", "copie": []}

    m = re.search(r'<h3[^>]*>\s*([\s\S]*?)\s*</h3>', html)
    titolo = strip_tags(m.group(1)) if m else "—"
    m = re.search(r'<h4[^>]*>\s*([\s\S]*?)\s*</h4>', html)
    autore = strip_tags(m.group(1)) if m else "—"

    copie = []
    for riga in re.findall(r'<tr[\s\S]*?</tr>', html, re.IGNORECASE):
        if not re.search(r'\bREZZATO\b', strip_tags(riga), re.IGNORECASE):
            continue
        celle = [strip_tags(c)
                 for c in re.findall(r'<td[\s\S]*?</td>', riga, re.IGNORECASE)
                 if strip_tags(c)]
        copie.append({
            "collocazione": celle[1] if len(celle) > 1 else "—",
            "inventario":   celle[2] if len(celle) > 2 else "—",
            "stato":        celle[3] if len(celle) > 3 else "—",
            "rientra":      celle[5] if len(celle) > 5 else "",
        })
    return {"titolo": titolo, "autore": autore, "copie": copie}

# ── Colori ────────────────────────────────────────────────────────────────────

V="\033[92m"; R="\033[91m"; Y="\033[93m"; B="\033[1m"; D="\033[2m"; X="\033[0m"

def colora(stato):
    s = stato.lower()
    if "scaffale" in s or "disponib" in s: return f"{V}{stato}{X}"
    if "prestito" in s:                    return f"{R}{stato}{X}"
    return f"{Y}{stato}{X}"

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Cerca libri OPAC RBBC – disponibilità a Rezzato")
    ap.add_argument("titoli", nargs="*")
    ap.add_argument("--file", "-f", metavar="FILE",
                    help="File .txt con un titolo per riga (# = commento)")
    ap.add_argument("--debug", "-d", action="store_true",
                    help="Mostra URL chiamati e conteggi")
    args = ap.parse_args()

    titoli = list(args.titoli)
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                titoli += [r.strip() for r in f
                           if r.strip() and not r.startswith("#")]
        except FileNotFoundError:
            sys.exit(f"ERRORE: file '{args.file}' non trovato.")
    if not titoli:
        ap.print_help()
        print('\nEsempio:  python cerca_libri_rezzato.py "La luna e i falò"')
        sys.exit(0)

    print(f"\n{B}OPAC — Rete Bibliotecaria Bresciana e Cremonese{X}")
    print(f"Biblioteca: {B}{BIBLIOTECA}{X} | Titoli: {len(titoli)}\n")

    # Cookie di sessione
    curl_get(BASE_URL + "/", verbose=args.debug)
    time.sleep(0.5)

    riepilogo = []

    for titolo_cercato in titoli:
        print(f"{'─'*62}")
        print(f"{B}🔍 «{titolo_cercato}»{X}")

        time.sleep(RITARDO)
        risultati = cerca_titolo(titolo_cercato, verbose=args.debug)

        if not risultati:
            print(f"  {R}Nessun risultato nel catalogo RBBC.{X}")
            riepilogo.append((titolo_cercato, False))
            continue

        trovato = False
        for i, libro in enumerate(risultati, 1):
            time.sleep(RITARDO)
            det = verifica_disponibilita(libro["url"], verbose=args.debug)

            # Titolo e autore dalla pagina di dettaglio se disponibili,
            # altrimenti da quelli estratti dalla ricerca
            titolo_r = det["titolo"] if det["titolo"] not in ("—", "") else libro["titolo"]
            autore_r = det["autore"]

            print(f"\n  [{i}] {B}{titolo_r}{X}")
            if autore_r and autore_r != "—":
                print(f"       {D}{autore_r}{X}")
            print(f"       {D}{libro['url']}{X}")

            copie = det.get("copie", [])
            if not copie:
                print(f"       {R}✗ Nessuna copia a Rezzato{X}")
            else:
                trovato = True
                print(f"       {V}✓ Copie a Rezzato:{X}")
                for c in copie:
                    riga = (f"         • {c['collocazione']}"
                            f"  [{c['inventario']}]  {colora(c['stato'])}")
                    if c["rientra"]:
                        riga += f"  {D}(rientra: {c['rientra']}){X}"
                    print(riga)

        riepilogo.append((titolo_cercato, trovato))

    print(f"\n{'═'*62}")
    print(f"{B}RIEPILOGO{X}")
    for tc, trovato in riepilogo:
        ic = f"{V}✓" if trovato else f"{R}✗"
        print(f"  {ic} {tc}{X}")
    print()

if __name__ == "__main__":
    main()
