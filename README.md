# RBBC Rezzato — PWA

Cerca libri nel catalogo RBBC e verifica la disponibilità alla Biblioteca di Rezzato.
Installabile come app sul telefono (PWA).

## Deploy su Render (gratuito)

### 1. Carica su GitHub
```bash
git init
git add .
git commit -m "primo commit"
# Crea un repo su github.com e poi:
git remote add origin https://github.com/TUO_USERNAME/rbbc-rezzato.git
git push -u origin main
```

### 2. Crea il servizio su Render
1. Vai su [render.com](https://render.com) e registrati (gratis)
2. **New → Web Service**
3. Collega il tuo repo GitHub
4. Render rileva automaticamente `render.yaml` e configura tutto
5. Clicca **Deploy** — in 2-3 minuti il sito è online

### 3. Installa sul telefono (PWA)
**Android (Chrome):**
- Apri l'URL del sito in Chrome
- Tocca i 3 puntini → "Aggiungi a schermata Home"

**iPhone (Safari):**
- Apri l'URL in Safari
- Tocca il pulsante Condividi (□↑)
- "Aggiungi a schermata Home"

---

## Struttura file
```
rbbc-pwa/
├── app.py              # Backend Flask (logica curl + API)
├── requirements.txt    # Dipendenze Python
├── render.yaml         # Configurazione deploy Render
└── static/
    ├── index.html      # Frontend PWA
    ├── manifest.json   # Manifest PWA (icona, colori, nome)
    └── sw.js           # Service Worker (cache offline)
```

## Note
- Il piano gratuito di Render mette il servizio in "sleep" dopo 15 min di inattività.
  La prima ricerca dopo una pausa può richiedere 20-30 secondi per il risveglio.
- Per tenerlo sempre sveglio (opzionale): usa [UptimeRobot](https://uptimerobot.com)
  con un ping ogni 10 minuti sull'URL del tuo sito.
