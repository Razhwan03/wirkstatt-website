# Wirkstatt — Webseite

Fertige, geprüfte Webseite für das Webdesign-Geschäft. Reines HTML/CSS/JS,
keine Abhängigkeiten, keine externen Schriftarten oder Tracking-Skripte.

## Was noch fehlt, bevor die Seite live geht

Nichts mehr. Name, Anschrift, Kleinunternehmer-Angabe, E-Mail und Telefon
stehen überall korrekt drin. Die Seite ist inhaltlich fertig zum
Veröffentlichen.

Falls später eine eigene geschäftliche E-Mail-Adresse dazukommt (z. B.
`kontakt@wirkstatt.de` nach Kauf der Domain), einfach in den drei Dateien
`index.html`, `impressum.html` und `datenschutz.html` nach
`razw.dler@icloud.com` suchen und ersetzen.

Suche im Ordner nach `[` um alle Stellen auf einen Blick zu finden:

```bash
grep -rn "\[" --include="*.html" .
```

## Seiten und Funktionen

- `index.html` — Startseite mit Hero, Mehrwert, Leistungen, Ablauf,
  Beispielprojekten, Warum-wir und Kontakt
- `impressum.html`, `datenschutz.html` — Pflichtangaben
- `demos/` — drei selbst gestaltete Beispielprojekte (Café, Handwerk,
  Beratung), klar als Demo gekennzeichnet, kein echter Kunde
- `assets/` — Stylesheet, Skript, Favicon
- `robots.txt` — erlaubt Suchmaschinen die Startseite und Rechtsseiten,
  schließt die Demo-Unterseiten aus

## Veröffentlichen (kostenlos, ohne eigenen Server)

Empfehlung: **GitHub Pages**. Kostenlos, zuverlässig, mit echter HTTPS-Adresse,
und später jederzeit auf eine eigene Domain umstellbar. Das muss über einen
eigenen GitHub-Account laufen, den nur du anlegen kannst, nicht ich. So geht's
ganz ohne Kommandozeile:

1. Auf [github.com](https://github.com) einen kostenlosen Account anlegen
   (falls noch keiner vorhanden ist).
2. Oben rechts auf **+** → **New repository** klicken. Name z. B.
   `wirkstatt-website`, Häkchen bei **Public**, dann **Create repository**.
3. Auf der neuen, leeren Repo-Seite auf **uploading an existing file**
   klicken und den kompletten Inhalt dieses Ordners hineinziehen (alle
   Dateien und die Unterordner `assets` und `demos`). Unten **Commit
   changes** klicken.
4. Im Repo auf **Settings** → **Pages**. Bei **Branch** `main` und als
   Ordner `/ (root)` auswählen, **Save** klicken.
5. Nach ein bis zwei Minuten zeigt dieselbe Seite die fertige Adresse an,
   etwa `https://dein-name.github.io/wirkstatt-website/`. Das ist die
   öffentliche URL für Revolut und für Kunden.

Wenn du lieber über das Terminal auf diesem Server arbeitest: leg das Repo
wie oben beschrieben über die Webseite an, dann in einem Terminal (mit
deinem eigenen GitHub-Login, nicht meinem Zugriff):

```bash
cd /opt/maaker/workspace/website
git init
git add -A
git commit -m "Erste Version der Wirkstatt-Webseite"
git branch -M main
git remote add origin https://github.com/DEIN-BENUTZERNAME/wirkstatt-website.git
git push -u origin main
```

Git fragt dabei nach deinem GitHub-Login (Benutzername + ein bei GitHub
selbst erzeugtes Zugangs-Token, kein normales Passwort mehr). Das trägst du
selbst ein, das sehe ich nicht.

## Eigene Domain (später, kostenpflichtig)

Eine `.de`-Domain wie `wirkstatt.de` kostet bei üblichen Anbietern grob
8–15 € im Jahr. Das ist eine reine Kosten-Grössenordnung zur Einordnung,
keine Buchung. Sobald du eine eigene Domain willst, prüfe ich eine konkrete
Domain samt Preis beim Anbieter und lege sie dir vor, bevor irgendetwas
gebucht wird. GitHub Pages funktioniert danach mit der eigenen Domain genauso
weiter, nur die Adresse ändert sich.

## Spätere Erweiterungen

Die Struktur ist bewusst so angelegt, dass Folgendes später ergänzt werden
kann, ohne alles neu zu bauen: echte Kundenreferenzen anstelle der Demo-
Projekte, eine Preisübersicht, eine Terminbuchung, ein Angebotsformular,
ein Blog-Bereich und eigene KI-Dienstleistungen als weitere Karte im
Leistungen-Bereich.
