# JARVIS vom Server sicher nach GitHub hochladen

Dauer: etwa 10 Minuten. Dein laufender JARVIS wird dabei **nicht** verändert,
gestoppt oder neu gestartet. Das Skript liest den JARVIS-Ordner nur.

## Was das Skript macht

1. Es sucht den Ordner, mit dem dein laufender JARVIS arbeitet.
2. Es legt ein **vollständiges Backup** an: `~/jarvis-backups/jarvis-backup-DATUM.tar.gz`.
   Das Backup enthält alles, auch Passwörter und Datenbanken, und **bleibt nur auf dem Server**.
3. Es baut eine **bereinigte Kopie** ohne `.env`, Passwörter, Schlüssel, Datenbank-Inhalte,
   Chats, Logs, private Daten und große Dateien.
4. Es prüft diese Kopie auf API-Schlüssel und Passwörter und ersetzt sie durch
   `REDACTED_BY_IMPORT`. Deine Originaldateien bleiben, wie sie sind.
5. Es zeigt dir, was hochgeladen wird, und fragt dich vorher.
6. Es lädt die Kopie in dein **privates** Repository `Razhwan03/-jarvis` hoch.
   Nichts wird überschrieben, es gibt keinen Force-Push.

## Schritt für Schritt

### 1. Am Server anmelden

Öffne die Konsole deines Servers. Das geht entweder über die Weboberfläche deines
Server-Anbieters (oft „Konsole“, „VNC“ oder „Terminal“ genannt) oder über das
Programm, mit dem du dich sonst am Server anmeldest.

Melde dich mit dem Benutzer an, unter dem JARVIS läuft.

### 2. Einen Befehl einfügen

**Wenn du eine Zeile wie `root@server:~#` oder `name@server:~$` siehst (Linux):**

```bash
curl -fsSLO https://raw.githubusercontent.com/Razhwan03/wirkstatt-website/refs/heads/claude/jarvis-mailbox-org-integration-68duut/tools/jarvis-export/jarvis_export.py && python3 jarvis_export.py
```

**Wenn du eine Zeile wie `C:\Users\...>` oder `PS C:\...>` siehst (Windows):**

```powershell
curl.exe -fsSLO https://raw.githubusercontent.com/Razhwan03/wirkstatt-website/refs/heads/claude/jarvis-mailbox-org-integration-68duut/tools/jarvis-export/jarvis_export.py; python jarvis_export.py
```

### 3. Den Fragen auf dem Bildschirm folgen

- **Ordner wählen:** Das Skript zeigt eine nummerierte Liste. Nimm den Eintrag mit
  „laufender Prozess“ oder „systemd-Dienst“. Gib die Nummer ein und drücke Enter.
- **GitHub-Freigabe (nur beim ersten Mal):** Das Skript zeigt einen Link und eine
  lange Zeile, die mit `ssh-ed25519` beginnt.
  1. Öffne den Link im Browser (du musst bei GitHub angemeldet sein).
  2. Bei **Title** schreibst du: `JARVIS Server`
  3. Bei **Key** fügst du die lange Zeile ein.
  4. Setze den Haken bei **Allow write access**.
  5. Klicke auf **Add key**.
  6. Zurück in der Konsole drückst du Enter.

  Dieser Schlüssel gilt **nur** für das Repository `-jarvis`, für nichts anderes.
- **Bestätigung:** Lies die Liste. Wenn sie gut aussieht, tippe `ja` und drücke Enter.

### 4. Fertig

Am Ende steht **FERTIG**. Schreib mir dann einfach: **„Upload ist fertig“**.

## Wenn etwas nicht klappt

| Meldung | Was du tun musst |
|---|---|
| `Das Programm 'git' fehlt` | Linux: `sudo apt-get install -y git openssh-client` eingeben, danach den Befehl aus Schritt 2 noch einmal ausführen. Windows: „Git for Windows“ installieren. |
| `python3: command not found` | Probiere `python jarvis_export.py` |
| `Permission denied` bei Dateien | Den Befehl mit `sudo` davor ausführen: `sudo python3 jarvis_export.py` |
| `Nach der Bereinigung wurden noch Geheimnisse gefunden` | Nichts wurde hochgeladen. Schick mir die angezeigte Liste. Sie enthält nur Dateinamen, keine Passwörter. |
| Etwas anderes | Kopiere die letzten Zeilen und schick sie mir. Das Skript zeigt nie Passwörter an. |

Abbrechen kannst du jederzeit mit **Strg + C**. Dabei wird nichts hochgeladen.
