# La Biblioteca di Babele

A Progressive Web App for exploring and searching the **RBBC** catalog (Rete Bibliotecaria Bresciana e Cremonese — the shared library network of the Brescia and Cremona provinces, Italy).

Search for a title across the RBBC catalog and instantly check whether a copy is available at your chosen library, where it's shelved, and when it's due back if currently on loan. Beyond simple lookup, the app turns reading into a small journey through world literature, with the following sections:

- **Alexandria** — the core search tool. Look up a title, see all matching editions, and check real-time availability (on the shelf, on loan, due-back date) at the library you've selected.
- **Atlante** — an interactive world map linking countries to the authors and works that originated there, encouraging exploration beyond familiar shelves.
- **Lapides Miliarii** — the great classics of world literature presented as star constellations grouped by era (Antiquity, Middle Ages, Renaissance, etc.). Marking a book as read lights up its star; completing a constellation unlocks an era badge.
- **Pantheon** — a badge and achievement gallery tracking searches performed, countries explored, constellations completed, and other reading milestones.
- **Profile** — personal reading history, saved/read books, library preference, and account settings (including a dark mode toggle).

Users can browse and search without an account, picking a library directly. Creating an account additionally enables saving "read" books, tracking search history, syncing badges and progress across devices, and building a personal reading map.

The app is installable on smartphones as a Progressive Web App (PWA), so it behaves like a native app — home-screen icon, full-screen launch, offline-friendly shell — without going through an app store.

## Render Deploy (Free)

1. Visit [render.com](https://render.com/) and sign up (free version)
2. New → Web Service
3. Connect it with the GitHub repo
4. Click on Deploy

## Mobile-only version: PWA

**Android (Chrome):**
- Open the website on Chrome
- Click on the three dots → "Add to Homepage"

**iPhone (Safari):**
- Open the website on Safari
- Click on Share (□↑)
- "Add to Homepage"

## File structure

```
biblioteca-di-babele/
├── app.py              # Flask backend (curl + API)
├── requirements.txt    # Python requirements
├── render.yaml         # Render deploy configurations
└── static/
    ├── icon-192.png
    ├── icon-512.png
    ├── index.html      # PWA frontend
    ├── manifest.json   # PWA manifest (icon, colors, name)
    └── sw.js           # Service Worker
```

## Note

Render goes into "sleep mode" after 15 minutes of inactivity. It may then take up to 30-40 seconds for the server to wake up. To avoid this, you can use a free [UptimeRobot](https://uptimerobot.com/) account which pings the server every 5 minutes, preventing it from "falling asleep".
