# RBBC — PWA

Search for books within the RBBC environment and verify their availability at the chosen library.
Can be used as a Progressive Web-App on smartphones.

## Render Deploy (Free)

1. Visit [render.com](https://render.com) and sign up (free version)
2. **New → Web Service**
3. Connect it with the GitHub repo
4. Click on **Deploy**

### 2. Mobile-only version: PWA
**Android (Chrome):**
- Open the website on Chrome
- Click on the three dots → "Add to Homepage"

**iPhone (Safari):**
- Open the website on Safari
- Click on Share (□↑)
- "Add to Homepage"

---

## File structure
```
rbbc-pwa/
├── app.py              # Flask backend (curl + API)
├── requirements.txt    # Python requirements
├── render.yaml         # Render deploy configurations
└── static/
    ├── index.html      # PWA frontend
    ├── manifest.json   # PWA manifest (icon, colors, name)
    └── sw.js           # Service Worker 
```

## Note
- Render goes into "sleep mode" after 15 minutes of inactivity. It may then take up to 30-40 seconds for the server to wake up.
  To avoid so, you can use a free [UptimeRobot](https://uptimerobot.com) which checks in every 5 minutes, not allowing the server to "fall asleep".
