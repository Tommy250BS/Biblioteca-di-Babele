# Biblioteca Aeterna

[Description needed]

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
