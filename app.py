#!/usr/bin/env python3
"""
RBBC PWA — backend Flask con account utente, sessioni e storico ricerche.
DB: PostgreSQL
Auth: bcrypt + flask-login, cookie di sessione firmato
"""

import subprocess, re, os, time, unicodedata, tempfile, concurrent.futures
from urllib.parse import quote_plus
from flask import Flask, request, jsonify, g, session
from flask_cors import CORS
from psycopg.rows import dict_row
import bcrypt
import psycopg

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "cambia-questa-chiave-in-produzione")
CORS(app, supports_credentials=True)

BASE_URL    = "https://opac.provincia.brescia.it"  # mantenuto per compatibilità: coincide con RETI['rbbc']['base_url']

# ── RETI BIBLIOTECARIE ────────────────────────────────────────────────────
# Tutte e quattro girano sullo stesso software OPAC (DiscoveryNG), quindi lo
# stesso motore di scraping (curl_get + regex) funziona su tutte cambiando
# solo l'URL base. Per attivare una nuova rete basta aggiungerla qui: non
# serve toccare cerca_titolo/verifica_disponibilita/get_biblioteche.
#
# Tutte e quattro le reti girano sul software OPAC DiscoveryNG, ma non tutte
# espongono l'elenco biblioteche sullo stesso percorso: RBBC, Comasca e
# Bergamasca usano il percorso standard "/library/"; Mantovana invece ha una
# struttura del sito personalizzata e l'elenco vive su
# "/la-rete-delle-biblioteche/" (verificato manualmente: "/library/" su quel
# dominio non esiste/non è collegato dalla nav del sito). "lib_path" permette
# di configurare questo per singola rete senza toccare get_biblioteche().
#
# Ogni istanza DiscoveryNG ha anche un proprio "codename" di catalogo negli
# URL dei risultati di ricerca (es. "opac/detail/view/<codename>:catalog:123").
# Non è "test" per tutte le reti come si era assunto inizialmente: RBBC usa
# "test", Como usa "como", Mantova usa "mn" (tutti verificati dal vivo tramite
# i log di cerca_titolo). Per Bergamasca non è ancora stato verificato, dato
# che la rete è irraggiungibile dal server (blocco a livello di connessione,
# vedi /api/debug/rete-check): resta "test" come placeholder finché il
# problema di rete non è risolto e si può fare un test reale.
RETI = {
    "rbbc": {
        "label": "Rete Bibliotecaria Bresciana e Cremonese",
        "short": "RBBC",
        "base_url": "https://opac.provincia.brescia.it",
        "lib_path": "/library/",
        "catalog_code": "test",
    },
    "comasca": {
        "label": "Rete Bibliotecaria della Provincia di Como",
        "short": "Comasca",
        "base_url": "https://opac.provincia.como.it",
        "lib_path": "/library/",
        "catalog_code": "como",
    },
    "mantovana": {
        "label": "Rete Bibliotecaria Mantovana",
        "short": "Mantovana",
        "base_url": "https://opac.provincia.mantova.it",
        "lib_path": "/la-rete-delle-biblioteche/",
        "catalog_code": "mn",
    },
    "bergamasca": {
        "label": "Rete Bibliotecaria Bergamasca",
        "short": "Bergamasca",
        "base_url": "https://opacbg.provincia.brescia.it",
        "lib_path": "/library/",
        "catalog_code": "test",  # placeholder, da verificare quando la rete sarà raggiungibile
    },
}
RETE_DEFAULT = "rbbc"


# ── ELENCO STATICO COMASCA ──────────────────────────────────────────────
# Per Comasca lo scraping live di "/library/" usa lo schema corretto
# (href="...libpage/id/N">Nome</a>", verificato manualmente sul sito), quindi
# in teoria funzionerebbe; se in produzione risulta comunque vuoto è quasi
# certamente un problema di rete/timeout verso quell'host, non di parsing.
# Come mitigazione immediata (e per eliminare una dipendenza di rete in più)
# usiamo un elenco statico, sullo stesso modello di BIBS in index.html per
# RBBC. Va aggiornato manualmente se la composizione della rete cambia.
BIBLIOTECHE_COMASCA = [
    "Albavilla", "Albese con Cassano", "Albiolo", "Alzate Brianza",
    "Appiano Gentile", "Asso", "Bassone Casa circondariale", "Bene Lario",
    "Beregazzo con F.", "Biblioteca Liceo Classico e Scientifico \"A. Volta\"",
    "Biblioteca Liceo Scientifico G. Galilei", "Binago", "Bizzarone", "Blevio",
    "Bregnano", "Brenna", "Brienno", "Brunate", "Bulgarograsso", "Cadorago",
    "Cagno", "Cantù", "Capiago Intimiano", "Carate Urio", "Carlazzo",
    "Caslino d'Erba", "Casnate con Bernate", "Cassina Rizzardi", "Cavallasca",
    "Centro Prov. Catalog.", "Cermenate", "Cernobbio", "Cirimido",
    "Colverde - Drezzo", "Colverde - Gironico", "Colverde - Parè", "Como",
    "Como Locker", "Como Musei civici", "Corrido", "Cucciago", "Dizzasco",
    "Dongo", "Faloppio", "Fenegrò", "Figino Serenza", "Fino Mornasco",
    "Fondazione Ratti", "Grandate", "Grandola ed Uniti",
    "Gravedona ed Uniti. IC Don Roberto Malgesini", "Griante", "Guanzate",
    "ITIS Magistri Cumacini", "Laglio", "Laino", "Lenno", "Lezzeno",
    "Limido Comasco", "Lipomo", "Lomazzo", "Luisago", "Lurago Marinone",
    "Lurate Caccivio", "Mariano Comense", "Menaggio", "Moltrasio",
    "Montano Lucino", "Mozzate", "Novedrate", "Olgiate Comasco",
    "Oltrona San Mamette", "Ossuccio", "Pianello", "Pigra", "Plesio",
    "Ponte Lambro", "Porlezza", "Pusiano", "Rodero", "Ronago", "Rovellasca",
    "S. Bartolomeo", "S. Fedele CMLI", "San Fermo della Battaglia",
    "San Siro", "Società Archeologica Comense", "Solbiate", "Tavernerio",
    "Uggiate Trevano", "Università Terza Età", "Valmorea", "Valsolda",
    "Veniano", "Vertemate con M.", "Villa Guardia", "Zelbio",
]

def rete_valida(rete):
    """Restituisce l'id rete se valido, altrimenti la rete di default.
    Centralizza la validazione così nessun endpoint rischia di costruire
    un base_url da input utente non controllato."""
    return rete if rete in RETI else RETE_DEFAULT
# Nota: non esiste più un cookie-jar condiviso a livello di modulo (era
# CURL_COOKIE = "/tmp/rbbc_opac.txt"). curl_get() ora crea un cookie-jar
# temporaneo per ciascuna chiamata, necessario per poter eseguire più
# richieste in parallelo senza race condition sullo stesso file.

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
                ALTER TABLE utenti ADD COLUMN IF NOT EXISTS obiettivo_annuale INTEGER NOT NULL DEFAULT 0;
            """)

            # Multi-rete: ogni utente/ricerca/lettura è ora legata a una rete
            # bibliotecaria specifica (rbbc, comasca, ...). Default 'rbbc' per
            # non rompere i dati già esistenti (che erano tutti su RBBC).
            cur.execute("""
                ALTER TABLE utenti ADD COLUMN IF NOT EXISTS rete VARCHAR(32) NOT NULL DEFAULT 'rbbc';
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
                ALTER TABLE ricerche ADD COLUMN IF NOT EXISTS rete VARCHAR(32) NOT NULL DEFAULT 'rbbc';
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
                    letto BOOLEAN NOT NULL DEFAULT FALSE,
                    salvato_il TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (utente_id, url_opac)
                );
            """)
            cur.execute("""
                ALTER TABLE salvati ADD COLUMN IF NOT EXISTS rete VARCHAR(32) NOT NULL DEFAULT 'rbbc';
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS letti (
                    id SERIAL PRIMARY KEY,
                    utente_id INTEGER NOT NULL REFERENCES utenti(id),
                    titolo TEXT NOT NULL,
                    autore TEXT NOT NULL DEFAULT '',
                    url_opac TEXT NOT NULL,
                    biblioteca TEXT NOT NULL,
                    letto_il TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (utente_id, url_opac)
                );
            """)
            cur.execute("""
                ALTER TABLE letti ADD COLUMN IF NOT EXISTS rete VARCHAR(32) NOT NULL DEFAULT 'rbbc';
            """)

            # Migrazione: aggiunge la colonna 'letto' se il DB esisteva già
            cur.execute("""
                ALTER TABLE salvati ADD COLUMN IF NOT EXISTS letto BOOLEAN NOT NULL DEFAULT FALSE;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS badge (
                    id SERIAL PRIMARY KEY,
                    utente_id INTEGER NOT NULL REFERENCES utenti(id),
                    badge_id VARCHAR(64) NOT NULL,
                    sbloccato_il TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (utente_id, badge_id)
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

def curl_get(url, timeout=12):
    # Cookie jar TEMPORANEO per singola chiamata (non più CURL_COOKIE
    # condiviso): con l'introduzione delle richieste in parallelo
    # (vedi ThreadPoolExecutor in /api/search), più curl in corsa
    # contemporaneamente sullo stesso file di cookie causerebbero
    # corruzione/race condition. Un file temporaneo per chiamata elimina
    # il problema; viene rimosso subito dopo l'uso. Timeout ridotto
    # rispetto a prima (25s → 12s di default) perché ora le richieste
    # corrono in parallelo, quindi non serve più "risparmiare" un'unica
    # chiamata lunga: è meglio fallire presto su una singola fonte
    # piuttosto che bloccare tutto il worker.
    fd, cookie_path = tempfile.mkstemp(prefix="rbbc_ck_", dir="/tmp")
    os.close(fd)
    cmd = (["curl", "-s", "-L", "--compressed", "--max-time", str(timeout),
            "--cookie-jar", cookie_path, "--cookie", cookie_path]
           + HEADERS + [url])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout + 5)
        return r.stdout
    except subprocess.TimeoutExpired:
        return ""
    finally:
        try:
            os.remove(cookie_path)
        except OSError:
            pass

def strip_tags(h):
    t = re.sub(r'<[^>]+>', ' ', h)
    for a, b in [('&amp;','&'),('&nbsp;',' '),('&lt;','<'),
                 ('&gt;','>'),('&#39;',"'"),('&quot;','"')]:
        t = t.replace(a, b)
    return re.sub(r'\s+', ' ', t).strip()

def _norm(s):
    """Normalizza per confronto: minuscolo, senza accenti."""
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.lower().strip()

def _estrai_risultati(html):
    """Estrae (numero_notizia, titolo) dai risultati di una pagina OPAC.
    NOTA: non più chiamata da nessuna parte (rimossa la logica duplicata,
    ora vive in cerca_titolo() con catalog_code dinamico). Tenuta solo se
    servisse un'estrazione "grezza" senza il resto della logica di
    cerca_titolo — altrimenti da rimuovere."""
    pattern = r'href="opac/detail/view/test:catalog:(\d+)"[\s\S]{0,200}?title="([^"]{5,200})"'
    visti = {}
    for num, raw in re.findall(pattern, html):
        if num not in visti:
            t = strip_tags(raw)
            if t and not t.lower().startswith("vai a"):
                visti[num] = t
    return visti

def cerca_titolo(titolo, base_url=BASE_URL, rows=10, rete_debug=None, catalog_code="test"):
    url  = f"{base_url}/opac/search?q={quote_plus(titolo)}&rows={rows}"
    html = curl_get(url)
    if not html:
        if rete_debug:
            app.logger.warning("cerca_titolo(%s): nessuna risposta da %s", rete_debug, url)
        return []
    pattern = (r'href="opac/detail/view/' + re.escape(catalog_code)
               + r':catalog:(\d+)"[\s\S]{0,200}?title="([^"]{5,200})"')
    visti = {}
    for num, raw in re.findall(pattern, html):
        if num not in visti:
            t = strip_tags(raw)
            if t and not t.lower().startswith("vai a"):
                visti[num] = t
    if not visti and rete_debug:
        # Il regex usa il codename di catalogo configurato in RETI[...]["catalog_code"]
        # (es. "test" per RBBC, "como" per Comasca). Se una rete non ancora
        # verificata usa un codename diverso, il link non combacia anche con
        # risposta HTML perfettamente valida. Cerchiamo il primo "detail/view"
        # nel corpo per vedere il codename reale usato da questa rete.
        idx = html.find("detail/view")
        contesto = html[max(0, idx - 100):idx + 150] if idx != -1 else None
        app.logger.warning(
            "cerca_titolo(%s): risposta da %s (%d caratteri), 0 risultati estratti con catalog_code=%r — "
            "'detail/view' %s, contesto: %r",
            rete_debug, url, len(html), catalog_code,
            "presente" if idx != -1 else "ASSENTE",
            contesto
        )
    return [{"titolo": tit, "url": f"{base_url}/opac/detail/view/{catalog_code}:catalog:{num}"}
            for num, tit in list(visti.items())[:rows]]

# ── ELENCO BIBLIOTECHE (dinamico, per rete) ────────────────────────────────
# Ogni rete DiscoveryNG espone una pagina /library/ con l'elenco dei punti
# di servizio, come link "<a href=".../libpage/id/N">Nome</a>". Invece di
# tenere elenchi statici da aggiornare a mano per ogni rete (rischio di
# errori/dimenticanze), li leggiamo da qui e li teniamo in cache in memoria
# per non ri-scaricare la pagina ad ogni richiesta.
_LIB_CACHE = {}          # rete -> (timestamp, [nomi ordinati])
_LIB_CACHE_TTL = 24 * 3600  # 24 ore: l'elenco cambia raramente

def _estrai_biblioteche(html):
    # Alcune reti (es. Mantovana) avvolgono il nome in un tag interno, es.
    # <a href="libpage/id/2" ...><span property="name">Nome</span></a>,
    # altre (es. Como) lo mettono come testo diretto dentro <a>...</a>.
    # Per essere robusti su entrambi i casi catturiamo tutto il contenuto tra
    # <a ...> e </a> e lo ripuliamo con strip_tags(), invece di richiedere
    # che sia testo puro subito dopo il '>' di apertura (fragile: si rompe
    # non appena c'è un tag annidato, come successo con Mantovana).
    pattern = r'href="[^"]*?libpage/id/\d+"[^>]*>([\s\S]{0,300}?)</a>'
    visti, nomi = set(), []
    for raw in re.findall(pattern, html):
        nome = strip_tags(raw)
        if nome and nome not in visti:
            visti.add(nome)
            nomi.append(nome)
    nomi.sort(key=_norm)
    return nomi

def get_biblioteche(rete):
    # Comasca: elenco statico, nessuna dipendenza di rete (vedi BIBLIOTECHE_COMASCA).
    if rete == "comasca":
        return BIBLIOTECHE_COMASCA

    now = time.time()
    cached = _LIB_CACHE.get(rete)
    if cached and (now - cached[0]) < _LIB_CACHE_TTL:
        return cached[1]
    base_url = RETI[rete]["base_url"]
    lib_path = RETI[rete].get("lib_path", "/library/")
    url = f"{base_url}{lib_path}"
    html = curl_get(url, timeout=15)

    # Logging esplicito: senza questo, un fallimento qui è indistinguibile
    # dall'esterno tra "il sito non ha risposto" e "il sito ha risposto ma
    # l'HTML non combacia col regex di parsing" — due problemi con soluzioni
    # completamente diverse (rete/firewall vs. lib_path/regex da correggere).
    if not html:
        app.logger.warning(
            "get_biblioteche(%s): nessuna risposta da %s (timeout, DNS o blocco di rete)",
            rete, url
        )
    nomi = _estrai_biblioteche(html) if html else []
    if html and not nomi:
        # Il primo tentativo mostrava i primi 500 caratteri della pagina, che
        # sono sempre e solo l'<head> — inutile per capire perché il regex
        # non cattura i link, che stanno più in basso nel corpo. Ora
        # mostriamo il contesto reale attorno al primo "libpage/id" trovato,
        # cioè esattamente il markup che il regex deve interpretare.
        idx = html.find("libpage/id")
        if idx == -1:
            contesto = None
        else:
            contesto = html[max(0, idx - 150):idx + 150]
        app.logger.warning(
            "get_biblioteche(%s): risposta da %s (%d caratteri), 0 biblioteche estratte — "
            "contesto attorno al primo 'libpage/id': %r",
            rete, url, len(html), contesto
        )

    if nomi:
        _LIB_CACHE[rete] = (now, nomi)
        return nomi
    if cached:
        # Il sito non ha risposto bene: meglio restituire la cache scaduta
        # (anche se non freschissima) che una lista vuota all'utente.
        return cached[1]
    return []

def verifica_disponibilita(url, biblioteca):
    html = curl_get(url)
    if not html:
        return {"titolo": "—", "autore": "—", "copie": []}
    m = re.search(r'<h3[^>]*>\s*([\s\S]*?)\s*</h3>', html)
    titolo = strip_tags(m.group(1)) if m else "—"
    autore = "—"
    for h4 in re.findall(r'<h4[^>]*>\s*([\s\S]*?)\s*</h4>', html):
        cand = strip_tags(h4)
        if cand and cand.lower() not in ("login", "aggiungi allo scaffale", "1984 - copie") and not cand.lower().endswith("- copie"):
            autore = cand
            break
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
    rete = rete_valida((d.get("rete") or "").strip())

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
                (email, nome, password, biblioteca, rete)
            VALUES
                (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (email, nome, pw_hash, biblioteca, rete)
        )

        uid = cur.fetchone()["id"]

        db.commit()

        session["uid"] = uid
        session.permanent = True

        return jsonify({
            "ok": True,
            "nome": nome,
            "biblioteca": biblioteca,
            "rete": rete,
            "obiettivo_annuale": 0
        })

    except Exception as e:
        db.rollback()

        if "duplicate key" in str(e).lower():
            return jsonify({"error": "Email già registrata"}), 409
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
    return jsonify({"ok": True, "nome": u["nome"], "biblioteca": u["biblioteca"],
                     "rete": u.get("rete") or RETE_DEFAULT,
                     "obiettivo_annuale": u.get("obiettivo_annuale", 0) or 0})

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
        "rete":        u.get("rete") or RETE_DEFAULT,
        "obiettivo_annuale": u.get("obiettivo_annuale", 0) or 0,
    })

@app.route("/api/auth/aggiorna", methods=["POST"])
@login_richiesto
def aggiorna_profilo():
    u = utente_corrente()
    d = request.get_json() or {}
    biblioteca = (d.get("biblioteca") or "").strip()
    nome       = (d.get("nome") or "").strip()
    # rete è opzionale nella richiesta: se non passata, resta quella attuale
    # dell'utente (così una semplice modifica del nome non la tocca).
    rete = (d.get("rete") or "").strip()
    rete = rete_valida(rete) if rete else (u.get("rete") or RETE_DEFAULT)
    if not biblioteca or not nome:
        return jsonify({"error": "Campi mancanti"}), 400
    get_db().execute("UPDATE utenti SET nome=%s, biblioteca=%s, rete=%s WHERE id=%s",
                     (nome, biblioteca, rete, u["id"]))
    get_db().commit()
    return jsonify({"ok": True, "nome": nome, "biblioteca": biblioteca, "rete": rete})

@app.route("/api/obiettivo", methods=["POST"])
@login_richiesto
def imposta_obiettivo():
    u = utente_corrente()
    d = request.get_json() or {}
    try:
        obiettivo = int(d.get("obiettivo", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Valore non valido"}), 400
    if obiettivo < 0 or obiettivo > 9999:
        return jsonify({"error": "Valore non valido"}), 400
    get_db().execute("UPDATE utenti SET obiettivo_annuale=%s WHERE id=%s",
                     (obiettivo, u["id"]))
    get_db().commit()
    return jsonify({"ok": True, "obiettivo_annuale": obiettivo})

#  API Ricerca 

@app.route("/api/search")
def api_search():
    q          = request.args.get("q", "").strip()
    biblioteca = request.args.get("biblioteca", "").strip()
    rete       = rete_valida(request.args.get("rete", "").strip())
    base_url   = RETI[rete]["base_url"]
    if not q or not biblioteca:
        return jsonify({"error": "Parametri mancanti"}), 400

    try:
        risultati_base = cerca_titolo(q, base_url, rows=10, rete_debug=rete,
                                       catalog_code=RETI[rete].get("catalog_code", "test"))
        max_risultati = 10
        candidati = risultati_base[:max_risultati]

        # Le pagine di dettaglio di candidati diversi sono richieste
        # indipendenti tra loro: prima venivano scaricate una alla volta con
        # 0.5s di pausa fissa tra ciascuna (fino a 20 candidati = 10s di soli
        # sleep, oltre al tempo di rete). Ora corrono in parallelo con un
        # tetto di concorrenza per non sovraccaricare l'OPAC.
        dettagli = [None] * len(candidati)
        if candidati:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
                futures = {
                    ex.submit(verifica_disponibilita, c["url"], biblioteca): i
                    for i, c in enumerate(candidati)
                }
                for fut in concurrent.futures.as_completed(futures):
                    i = futures[fut]
                    try:
                        dettagli[i] = fut.result()
                    except Exception:
                        dettagli[i] = {"titolo": "—", "autore": "—", "copie": []}

        output = []
        for libro, det in zip(candidati, dettagli):
            if len(output) >= max_risultati:
                break
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
                "INSERT INTO ricerche (utente_id,query,biblioteca,rete,trovati,a_bib) VALUES (%s,%s,%s,%s,%s,%s)",
                (u["id"], q, biblioteca, rete, len(output), a_bib))
            get_db().commit()

        return jsonify({"query": q, "biblioteca": biblioteca, "rete": rete, "risultati": output})

    except Exception as e:
        # Log completo lato server (visibile nei log del processo/host) +
        # messaggio esplicito nella risposta, così un eventuale errore futuro
        # è diagnosticabile subito invece di apparire come un 500 generico.
        app.logger.exception("Errore in /api/search (q=%r)", q)
        return jsonify({"error": f"Errore interno: {e}"}), 500

#  API Debug rete (diagnostica temporanea)

@app.route("/api/debug/rete-check")
def debug_rete_check():
    """Testa la raggiungibilità di ogni host OPAC dal server e restituisce
    codice HTTP, tempo di risposta ed errore curl (se presente). Serve a
    distinguere in un colpo solo: blocco a livello di connessione (DNS,
    timeout, TLS, connection refused) da un 200 con contenuto inatteso.
    Endpoint diagnostico: rimuovere o proteggere una volta chiuso il debug."""
    risultati = {}
    for rete_id, info in RETI.items():
        base_url = info["base_url"]
        lib_path = info.get("lib_path", "/library/")
        url = f"{base_url}{lib_path}"
        cmd = (["curl", "-s", "-o", "/dev/null",
                "-w", "%{http_code}|%{time_total}|%{ssl_verify_result}|%{num_redirects}",
                "-L", "--max-time", "10"] + HEADERS + [url])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            parti = r.stdout.strip().split("|")
            risultati[rete_id] = {
                "url": url,
                "http_code": parti[0] if len(parti) > 0 else None,
                "tempo_sec": parti[1] if len(parti) > 1 else None,
                "ssl_verify_result": parti[2] if len(parti) > 2 else None,
                "redirect_count": parti[3] if len(parti) > 3 else None,
                "curl_returncode": r.returncode,
                "curl_stderr": r.stderr.strip()[:300] or None,
            }
        except subprocess.TimeoutExpired:
            risultati[rete_id] = {"url": url, "errore": "timeout (>15s) — nessuna risposta dal server curl stesso"}
        except Exception as e:
            risultati[rete_id] = {"url": url, "errore": str(e)}
    return jsonify(risultati)

#  API Reti e Biblioteche

@app.route("/api/reti")
def api_reti():
    return jsonify([
        {"id": k, "label": v["label"], "short": v["short"]}
        for k, v in RETI.items()
    ])

@app.route("/api/biblioteche")
def api_biblioteche():
    rete = rete_valida(request.args.get("rete", "").strip())
    return jsonify({"rete": rete, "biblioteche": get_biblioteche(rete)})

#  API Letti

@app.route("/api/letti", methods=["GET"])
@login_richiesto
def get_letti():
    u = utente_corrente()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM letti WHERE utente_id=%s ORDER BY letto_il DESC",
        (u["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/letti", methods=["POST"])
@login_richiesto
def aggiungi_letto():
    u = utente_corrente()
    d = request.get_json() or {}
    url_opac = (d.get("url_opac") or "").strip()
    if not url_opac:
        return jsonify({"error": "url_opac mancante"}), 400
    rete = rete_valida((d.get("rete") or "").strip())
    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO letti (utente_id, titolo, autore, url_opac, biblioteca, rete)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (utente_id, url_opac) DO NOTHING
            """,
            (u["id"], d.get("titolo",""), d.get("autore",""),
             url_opac, d.get("biblioteca",""), rete)
        )
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/api/letti/<path:url_opac>", methods=["DELETE"])
@login_richiesto
def rimuovi_letto(url_opac):
    u = utente_corrente()
    db = get_db()
    db.execute("DELETE FROM letti WHERE url_opac=%s AND utente_id=%s", (url_opac, u["id"]))
    db.commit()
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
        """SELECT lower(query) as query, COUNT(*) as n FROM ricerche
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

#  API Badge

@app.route("/api/badge/atlante-visit", methods=["POST"])
@login_richiesto
def atlante_visit():
    """Incrementa contatore visite Atlante e restituisce il totale."""
    u = utente_corrente()
    db = get_db()
    # Usa una riga speciale nella tabella badge per tracciare il contatore
    # Strategia: teniamo N righe badge_id='_atlante_1', '_atlante_2' ecc.
    count = db.execute(
        "SELECT COUNT(*) as n FROM badge WHERE utente_id=%s AND badge_id LIKE '_atlante_%'",
        (u["id"],)
    ).fetchone()["n"]
    new_count = count + 1
    db.execute(
        "INSERT INTO badge (utente_id, badge_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (u["id"], f"_atlante_{new_count}")
    )
    db.commit()
    return jsonify({"visite": new_count})

@app.route("/api/badge", methods=["GET"])
@login_richiesto
def get_badge():
    u = utente_corrente()
    rows = get_db().execute(
        "SELECT badge_id FROM badge WHERE utente_id=%s", (u["id"],)
    ).fetchall()
    return jsonify([r["badge_id"] for r in rows])

@app.route("/api/badge", methods=["POST"])
@login_richiesto
def aggiungi_badge():
    u = utente_corrente()
    d = request.get_json() or {}
    badge_id = (d.get("badge_id") or "").strip()
    if not badge_id:
        return jsonify({"error": "badge_id mancante"}), 400
    db = get_db()
    try:
        db.execute(
            "INSERT INTO badge (utente_id, badge_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (u["id"], badge_id)
        )
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/")
def index():
    return app.send_static_file("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
