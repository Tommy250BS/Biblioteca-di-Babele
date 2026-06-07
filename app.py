#!/usr/bin/env python3
"""Backend Flask per RBBC PWA — ricerca per qualsiasi biblioteca della rete."""

import subprocess, re, time, os
from urllib.parse import quote_plus
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

BASE_URL    = "https://opac.provincia.brescia.it"
COOKIE_FILE = "/tmp/rbbc_session.txt"

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: it-IT,it;q=0.9",
    "-H", "Accept-Encoding: gzip, deflate, br",
]

def curl_get(url):
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

def cerca_titolo(titolo):
    url  = f"{BASE_URL}/opac/search?q={quote_plus(titolo)}"
    html = curl_get(url)
    if not html:
        return []
    pattern = r'href="opac/detail/view/test:catalog:(\d+)"[\s\S]{0,200}?title="([^"]{5,200})"'
    visti = {}
    for num, titolo_raw in re.findall(pattern, html):
        if num not in visti:
            t = strip_tags(titolo_raw)
            if t and not t.lower().startswith("vai a"):
                visti[num] = t
    return [
        {"titolo": tit, "url": f"{BASE_URL}/opac/detail/view/test:catalog:{num}"}
        for num, tit in list(visti.items())[:10]
    ]

def verifica_disponibilita(url, biblioteca):
    html = curl_get(url)
    if not html:
        return {"titolo": "—", "autore": "—", "copie": []}
    m = re.search(r'<h3[^>]*>\s*([\s\S]*?)\s*</h3>', html)
    titolo = strip_tags(m.group(1)) if m else "—"
    m = re.search(r'<h4[^>]*>\s*([\s\S]*?)\s*</h4>', html)
    autore = strip_tags(m.group(1)) if m else "—"
    copie = []
    for riga in re.findall(r'<tr[\s\S]*?</tr>', html, re.IGNORECASE):
        if not re.search(re.escape(biblioteca), strip_tags(riga), re.IGNORECASE):
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

@app.route("/api/search")
def api_search():
    q         = request.args.get("q", "").strip()
    biblioteca = request.args.get("biblioteca", "").strip().upper()
    if not q:
        return jsonify({"error": "Parametro q mancante"}), 400
    if not biblioteca:
        return jsonify({"error": "Parametro biblioteca mancante"}), 400

    risultati_base = cerca_titolo(q)
    if not risultati_base:
        return jsonify({"query": q, "biblioteca": biblioteca, "risultati": []})

    output = []
    for libro in risultati_base:
        time.sleep(0.5)
        det = verifica_disponibilita(libro["url"], biblioteca)
        titolo_r = det["titolo"] if det["titolo"] not in ("—","") else libro["titolo"]
        autore_r = det["autore"]
        if autore_r in ("—","") and " - " in titolo_r:
            parti = titolo_r.rsplit(" - ", 1)
            titolo_r, autore_r = parti[0].strip(), parti[1].strip()
        output.append({
            "titolo":        titolo_r,
            "autore":        autore_r,
            "url":           libro["url"],
            "copie_rezzato": det["copie"],
            "disponibile":   any(
                "scaffale" in c["stato"].lower() or "disponib" in c["stato"].lower()
                for c in det["copie"]
            ),
        })
    return jsonify({"query": q, "biblioteca": biblioteca, "risultati": output})

@app.route("/")
def index():
    return app.send_static_file("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
