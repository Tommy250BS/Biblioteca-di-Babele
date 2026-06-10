#!/usr/bin/env python3
"""
RBBC PWA — backend Flask con account utente, sessioni e storico ricerche.
DB: PostgreSQL
Auth: bcrypt + flask-login, cookie di sessione firmato
"""

import subprocess, re, time, os
from datetime import datetime
from urllib.parse import quote_plus
from flask import (Flask, request, jsonify, g,
                   session, redirect, url_for)
from flask_cors import CORS
from psycopg.rows import dict_row
from psycopg import errors
import bcrypt
import psycopg

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "cambia-questa-chiave-in-produzione")
CORS(app, supports_credentials=True)

BASE_URL    = "https://opac.provincia.brescia.it"
CURL_COOKIE = "/tmp/rbbc_opac.txt"

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: it-IT,it;q=0.9",
    "-H", "Accept-Encoding: gzip, deflate, br",
]

# Database

def get_db():
    if "db" not in g:
        g.db = psycopg.connect(
            os.environ["DATABASE_URL"],
            row_factory=dict_row
        )
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        with db.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS utenti (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    nome VARCHAR(255) NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    biblioteca VARCHAR(255) NOT NULL DEFAULT '',
                    creato_il TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS ricerche (
                    id SERIAL PRIMARY KEY,
                    utente_id INTEGER NOT NULL REFERENCES utenti(id),
                    query TEXT NOT NULL,
                    biblioteca TEXT NOT NULL,
                    trovati INTEGER NOT NULL DEFAULT 0,
                    a_bib INTEGER NOT NULL DEFAULT 0,
                    cercato_il TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS salvati (
                    id SERIAL PRIMARY KEY,
                    utente_id INTEGER NOT NULL REFERENCES utenti(id),
                    titolo TEXT NOT NULL,
                    autore TEXT NOT NULL DEFAULT '',
                    url_opac TEXT NOT NULL,
                    biblioteca TEXT NOT NULL,
                    disponibile BOOLEAN NOT NULL DEFAULT FALSE,
                    salvato_il TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (utente_id, url_opac)
                );
            """)

init_db()

#  Helpers auth 

def utente_corrente():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM utenti WHERE id=%s", (uid,)).fetchone()

def login_richiesto(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*a, **kw):
        if not utente_corrente():
            return jsonify({"error": "Non autenticato", "login_required": True}), 401
        return fn(*a, **kw)
    return wrapper

#  curl + OPAC 

def curl_get(url):
    cmd = (["curl", "-s", "-L", "--compressed", "--max-time", "25",
            "--cookie-jar", CURL_COOKIE, "--cookie", CURL_COOKIE]
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
    for num, raw in re.findall(pattern, html):
        if num not in visti:
            t = strip_tags(raw)
            if t and not t.lower().startswith("vai a"):
                visti[num] = t
    return [{"titolo": tit, "url": f"{BASE_URL}/opac/detail/view/test:catalog:{num}"}
            for num, tit in list(visti.items())[:10]]

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
        celle = [strip_tags(c) for c in
                 re.findall(r'<td[\s\S]*?</td>', riga, re.IGNORECASE) if strip_tags(c)]
        copie.append({
            "collocazione": celle[1] if len(celle) > 1 else "—",
            "inventario":   celle[2] if len(celle) > 2 else "—",
            "stato":        celle[3] if len(celle) > 3 else "—",
            "rientra":      celle[5] if len(celle) > 5 else "",
        })
    return {"titolo": titolo, "autore": autore, "copie": copie}

#  API Auth 

@app.route("/api/auth/registra", methods=["POST"])
def registra():
    d = request.get_json() or {}

    email = (d.get("email") or "").strip().lower()
    nome = (d.get("nome") or "").strip()
    password = d.get("password") or ""
    biblioteca = (d.get("biblioteca") or "").strip()

    if not email or not nome or not password or not biblioteca:
        return jsonify({"error": "Tutti i campi sono obbligatori"}), 400

    if len(password) < 6:
        return jsonify({"error": "La password deve avere almeno 6 caratteri"}), 400

    pw_hash = bcrypt.hashpw(
        password.encode(),
        bcrypt.gensalt()
    ).decode()

    db = get_db()

    try:
        cur = db.execute(
            """
            INSERT INTO utenti
                (email, nome, password, biblioteca)
            VALUES
                (%s, %s, %s, %s)
            RETURNING id
            """,
            (email, nome, pw_hash, biblioteca)
        )

        uid = cur.fetchone()["id"]

        db.commit()

        session["uid"] = uid
        session.permanent = True

        return jsonify({
            "ok": True,
            "nome": nome,
            "biblioteca": biblioteca
        })

    except Exception as e:
    db.rollback()

    if "duplicate key" in str(e).lower():
        return jsonify({"error": "Email già registrata"}), 409

     return jsonify({"error": str(e)}), 500

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.get_json() or {}
    email    = (d.get("email") or "").strip().lower()
    password = (d.get("password") or "")
    db = get_db()
    u = db.execute("SELECT * FROM utenti WHERE email=%s", (email,)).fetchone()
    if not u or not bcrypt.checkpw(password.encode(), u["password"].encode()):
        return jsonify({"error": "Email o password errati"}), 401
    session["uid"] = u["id"]
    session.permanent = True
    return jsonify({"ok": True, "nome": u["nome"], "biblioteca": u["biblioteca"]})

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/me")
def me():
    u = utente_corrente()
    if not u:
        return jsonify({"autenticato": False})
    return jsonify({
        "autenticato": True,
        "nome":        u["nome"],
        "email":       u["email"],
        "biblioteca":  u["biblioteca"],
    })

@app.route("/api/auth/aggiorna", methods=["POST"])
@login_richiesto
def aggiorna_profilo():
    u = utente_corrente()
    d = request.get_json() or {}
    biblioteca = (d.get("biblioteca") or "").strip()
    nome       = (d.get("nome") or "").strip()
    if not biblioteca or not nome:
        return jsonify({"error": "Campi mancanti"}), 400
    get_db().execute("UPDATE utenti SET nome=%s, biblioteca=%s WHERE id=%s",
                     (nome, biblioteca, u["id"]))
    get_db().commit()
    return jsonify({"ok": True, "nome": nome, "biblioteca": biblioteca})

#  API Ricerca 

@app.route("/api/search")
def api_search():
    q          = request.args.get("q", "").strip()
    biblioteca = request.args.get("biblioteca", "").strip()
    if not q or not biblioteca:
        return jsonify({"error": "Parametri mancanti"}), 400

    risultati_base = cerca_titolo(q)
    output = []
    for libro in risultati_base:
        time.sleep(0.5)
        det = verifica_disponibilita(libro["url"], biblioteca)
        titolo_r = det["titolo"] if det["titolo"] not in ("—","") else libro["titolo"]
        autore_r = det["autore"]
        if autore_r in ("—","") and " - " in titolo_r:
            parti = titolo_r.rsplit(" - ", 1)
            titolo_r, autore_r = parti[0].strip(), parti[1].strip()
        copie = det["copie"]
        output.append({
            "titolo":        titolo_r,
            "autore":        autore_r,
            "url":           libro["url"],
            "copie_rezzato": copie,
            "disponibile":   any(
                "scaffale" in c["stato"].lower() or "disponib" in c["stato"].lower()
                for c in copie),
        })

    # Salva ricerca se loggato
    u = utente_corrente()
    if u and output:
        a_bib = sum(1 for r in output if r["copie_rezzato"])
        get_db().execute(
            "INSERT INTO ricerche (utente_id,query,biblioteca,trovati,a_bib) VALUES (%s,%s,%s,%s,%s)",
            (u["id"], q, biblioteca, len(output), a_bib))
        get_db().commit()

    return jsonify({"query": q, "biblioteca": biblioteca, "risultati": output})

#  API Salvati 

@app.route("/api/salvati", methods=["GET"])
@login_richiesto
def get_salvati():
    u = utente_corrente()
    rows = get_db().execute(
        "SELECT * FROM salvati WHERE utente_id=%s ORDER BY salvato_il DESC",
        (u["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/salvati", methods=["POST"])
@login_richiesto
def aggiungi_salvato():
    u = utente_corrente()
    d = request.get_json() or {}

    try:
        get_db().execute(
            """
            INSERT INTO salvati
                (
                    utente_id,
                    titolo,
                    autore,
                    url_opac,
                    biblioteca,
                    disponibile
                )
            VALUES
                (%s, %s, %s, %s, %s, %s)

            ON CONFLICT (utente_id, url_opac)
            DO UPDATE SET
                titolo = EXCLUDED.titolo,
                autore = EXCLUDED.autore,
                biblioteca = EXCLUDED.biblioteca,
                disponibile = EXCLUDED.disponibile
            """,
            (
                u["id"],
                d.get("titolo", ""),
                d.get("autore", ""),
                d.get("url_opac", ""),
                d.get("biblioteca", ""),
                bool(d.get("disponibile")))),
            )
        )

        get_db().commit()

        return jsonify({"ok": True})

    except Exception as e:
        get_db().rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/api/salvati/<int:sid>", methods=["DELETE"])
@login_richiesto
def rimuovi_salvato(sid):
    u = utente_corrente()
    get_db().execute(
        "DELETE FROM salvati WHERE id=%s AND utente_id=%s", (sid, u["id"]))
    get_db().commit()
    return jsonify({"ok": True})

#  API Storico e statistiche personali 

@app.route("/api/storico")
@login_richiesto
def get_storico():
    u   = utente_corrente()
    db  = get_db()
    # Ultime 30 ricerche
    ricerche = db.execute(
        "SELECT * FROM ricerche WHERE utente_id=%s ORDER BY cercato_il DESC LIMIT 30",
        (u["id"],)).fetchall()
    # Query più frequenti (top 10)
    top_query = db.execute(
        """SELECT query, COUNT(*) as n FROM ricerche
           WHERE utente_id=%s GROUP BY lower(query) ORDER BY n DESC LIMIT 10""",
        (u["id"],)).fetchall()
    # Totali
    totali = db.execute(
        "SELECT COUNT(*) as tot, SUM(trovati) as libri FROM ricerche WHERE utente_id=%s",
        (u["id"],)).fetchone()
    return jsonify({
        "ricerche":   [dict(r) for r in ricerche],
        "top_query":  [dict(r) for r in top_query],
        "tot_ricerche": totali["tot"] or 0,
        "tot_libri":    totali["libri"] or 0,
    })

@app.route("/")
def index():
    return app.send_static_file("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
