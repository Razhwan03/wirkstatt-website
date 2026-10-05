#!/usr/bin/env python3
"""
JARVIS-Export: sichert den bestehenden JARVIS-Stand auf dem Server und laedt
eine bereinigte Kopie (ohne Passwoerter, Schluessel, .env, Datenbanken,
private Daten) in das private GitHub-Repository hoch.

Sicherheitsregeln dieses Skripts:
  * Der JARVIS-Ordner wird NUR GELESEN. Es werden keine Dateien darin
    veraendert, keine Dienste gestoppt oder neu gestartet.
  * Bestehende Git-Remotes/Einstellungen des Projekts werden nicht angefasst.
    Hochgeladen wird aus einer separaten, bereinigten Arbeitskopie.
  * Kein Force-Push. Ist das Ziel-Repository nicht leer, wird in einen
    neuen Branch hochgeladen statt etwas zu ueberschreiben.
  * Gefundene Geheimnisse werden nie im Klartext angezeigt.
  * Die alte Git-Historie wird nicht hochgeladen (sie koennte alte
    Geheimnisse enthalten). Sie bleibt vollstaendig im lokalen Backup.

Nur Python-Standardbibliothek. Laeuft unter Linux und Windows (Python 3.7+).
Benoetigt zum Hochladen: git und ssh/ssh-keygen.
"""

import fnmatch
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

GITHUB_REPO = "Razhwan03/-jarvis"
# Port 443 funktioniert auch, wenn der Anbieter Port 22 sperrt.
REMOTE_URL = os.environ.get(
    "JARVIS_EXPORT_REMOTE", "ssh://git@ssh.github.com:443/" + GITHUB_REPO + ".git"
)
DEPLOY_KEY_URL = "https://github.com/" + GITHUB_REPO + "/settings/keys/new"

# Offizielle Host-Schluessel von GitHub (docs.github.com, "GitHub's SSH key
# fingerprints"). Verhindert, dass ein falscher Server untergeschoben wird.
GITHUB_HOST_KEYS = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl",
    "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=",
]

STAMP = time.strftime("%Y%m%d-%H%M%S")
HOME = Path.home()
WORK = HOME / "jarvis-export"
MAX_FILE_BYTES = 10 * 1024 * 1024
REDACTED = "REDACTED_BY_IMPORT"

# --------------------------------------------------------------------------
# Ausschlussregeln
# --------------------------------------------------------------------------

# Ordner, die komplett ausgelassen werden (Name, Kleinschreibung).
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", ".virtualenv",
    "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".cache", ".idea", ".vscode", "logs", "log", "backups", "backup",
    ".ssh", ".gnupg", "secrets", ".secrets", "credentials", "instance",
    "uploads", "recordings", "vectorstore", "vector_store", "qdrant_storage",
    "chroma", ".chroma", "chroma_db", "chromadb", "faiss_index", "wandb",
    "jarvis-export", "site-packages",
}
# Ordner, die nur im Backup fehlen (reproduzierbar, sehr gross).
BACKUP_SKIP_DIRS = {
    "__pycache__", ".venv", "venv", ".virtualenv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".cache",
    "site-packages", "jarvis-export",
}
# Ordner, in denen Daten-Dateien (keine Code-Dateien) als privat gelten.
DATA_DIRS = {
    "data", "memory", "memories", "chats", "chat", "chat_history",
    "conversations", "history", "inbox", "mail", "mails", "messages",
    "transcripts", "personal", "private", "user_data", "userdata", "storage",
    "exports", "downloads", "db", "database", "dumps", "media",
}
DATA_EXTS = {
    ".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".txt", ".md", ".xml",
    ".yaml", ".yml", ".html", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic",
}
# Dateien, die immer ausgelassen werden (Glob, Kleinschreibung).
SKIP_FILE_GLOBS = [
    ".env", ".env.*", "*.env", ".envrc",
    "*.pem", "*.key", "*.crt", "*.cer", "*.p12", "*.pfx", "*.jks",
    "*.keystore", "*.ppk", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    "*.kdbx", "*.gpg", "*.pgp", "*.asc", ".netrc", "_netrc", ".pgpass",
    ".htpasswd", ".npmrc", ".pypirc", ".git-credentials",
    "credentials*.json", "credential*.json", "client_secret*.json",
    "service_account*.json", "service-account*.json", "token*.json",
    "token*.pickle", "*cookies*", "*.session", "session*.json",
    "*.db", "*.sqlite", "*.sqlite3", "*.db3", "*.db-journal", "*.db-wal",
    "*.db-shm", "*-wal", "*-shm", "*.mdb", "*.accdb", "*.dump",
    "*.log", "*.log.*", "*.bak", "*.old", "*.orig", "*.swp", "*.swo",
    "*.tmp", "*~", "*.pid", "*.sock",
    "*.pickle", "*.pkl", "*.npy", "*.npz", "*.parquet", "*.faiss",
    "*.index", "*.ann", "*.hnsw",
    "*.eml", "*.mbox", "*.msg", "*.vcf", "*.ics", "*.pst", "*.ost",
    "*.wav", "*.mp3", "*.m4a", "*.ogg", "*.oga", "*.opus", "*.flac",
    "*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm",
    "*.gguf", "*.ggml", "*.safetensors", "*.pt", "*.pth", "*.onnx",
    "*.ckpt", "*.h5", "*.tflite", "*.bin",
    "*.zip", "*.tar", "*.tgz", "*.gz", "*.bz2", "*.xz", "*.7z", "*.rar",
    ".ds_store", "thumbs.db", "desktop.ini",
]
# Diese Vorlagen enthalten normalerweise keine echten Werte und bleiben.
KEEP_FILE_GLOBS = [
    ".env.example", ".env.sample", ".env.template", ".env.dist",
    "*.env.example", "*.env.sample", "*.env.template",
]

TEXT_EXTS = {
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".txt",
    ".md", ".rst", ".html", ".htm", ".css", ".sh", ".bash", ".ps1", ".bat",
    ".cmd", ".sql", ".xml", ".service", ".env", ".example", ".sample",
    ".template", ".j2", ".jinja", ".vue", ".svelte", "",
}
CONFIG_EXTS = {
    ".ini", ".cfg", ".conf", ".properties", ".yaml", ".yml", ".toml",
    ".service", ".example", ".sample", ".template", ".txt", "",
}

# --------------------------------------------------------------------------
# Geheimnis-Erkennung
# --------------------------------------------------------------------------

TOKEN_PATTERNS = [
    ("Anthropic-Key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI-Key", r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"),
    ("AWS-Key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub-Token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    ("GitHub-Token", r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    ("Slack-Token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("Google-Key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Google-OAuth", r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    ("Telegram-Bot-Token", r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
    ("HuggingFace-Token", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("Groq-Key", r"\bgsk_[A-Za-z0-9]{40,}\b"),
    ("Replicate-Token", r"\br8_[A-Za-z0-9]{30,}\b"),
    ("Stripe-Key", r"\b(?:sk|rk|pk)_live_[A-Za-z0-9]{20,}\b"),
    ("SendGrid-Key", r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{30,}\b"),
    ("Discord-Token", r"\b[MN][A-Za-z\d]{23,25}\.[\w\-]{6}\.[\w\-]{27,}\b"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]
TOKEN_RES = [(n, re.compile(p)) for n, p in TOKEN_PATTERNS]

# Zugangsdaten in Verbindungs-URLs: scheme://user:PASSWORT@host
URL_CRED_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@'\"]+:)([^\s@'\"]{3,})(@)")

SECRET_NAME = (
    r"[A-Za-z0-9_\-]*(?:password|passwd|passwort|kennwort|pwd|secret|token|"
    r"api[_\-]?key|apikey|access[_\-]?key|private[_\-]?key|client[_\-]?secret|"
    r"auth[_\-]?key|credential|webhook)[A-Za-z0-9_\-]*"
)
# name = "wert"   name: 'wert'   "name": "wert"
QUOTED_ASSIGN_RE = re.compile(
    r"(?i)(['\"]?" + SECRET_NAME + r"['\"]?\s*[:=]\s*)(['\"])([^'\"\r\n]{6,})(\2)"
)
# Konfigurationsdateien ohne Anfuehrungszeichen:  token = abc123...
PLAIN_ASSIGN_RE = re.compile(
    r"(?im)^(\s*" + SECRET_NAME + r"\s*[:=]\s*)([^\s'\"#;]{8,})\s*$"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")

PLACEHOLDER_HINTS = (
    "environ", "getenv", "${", "{{", "<", "your", "xxx", "***", "example",
    "changeme", "change_me", "placeholder", "redacted", "dummy",
)
NOT_SECRET_WORDS = {
    "true", "false", "none", "null", "bearer", "basic", "oauth", "oauth2",
    "sha256", "sha512", "hs256", "rs256", "utf-8", "ascii", "string",
}


def looks_like_placeholder(value):
    v = value.strip().lower()
    if not v or v in NOT_SECRET_WORDS:
        return True
    if any(h in v for h in PLACEHOLDER_HINTS):
        return True
    # Formatstrings (f"Bearer {token}", "%(pw)s") sind keine Geheimnisse.
    if "%(" in v or "{" in v:
        return True
    # Namen von Umgebungsvariablen/Konstanten: "OPENAI_API_KEY"
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", value.strip()):
        return True
    # Bezeichner wie "jarvis_password", "api_key", "access-token"
    if re.fullmatch(r"[a-z_.\-]+", v) and re.search(r"pass|token|key|secret|cred|auth", v):
        return True
    return False


def redact_text(text, ext):
    """Gibt (neuer_text, [(zeile, art), ...]) zurueck."""
    findings = []

    def line_of(pos):
        return text.count("\n", 0, pos) + 1

    spans = []  # (start, ende, art)
    for name, rx in TOKEN_RES:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), name))
    for m in URL_CRED_RE.finditer(text):
        if not looks_like_placeholder(m.group(2)):
            spans.append((m.start(2), m.end(2), "Passwort in URL"))
    for m in QUOTED_ASSIGN_RE.finditer(text):
        if not looks_like_placeholder(m.group(3)):
            spans.append((m.start(3), m.end(3), "Zugangsdaten-Zuweisung"))
    if ext in CONFIG_EXTS or ext == ".env":
        for m in PLAIN_ASSIGN_RE.finditer(text):
            if not looks_like_placeholder(m.group(2)):
                spans.append((m.start(2), m.end(2), "Zugangsdaten-Zuweisung"))

    if not spans:
        return text, findings
    spans.sort()
    merged = []
    for s, e, n in spans:
        if merged and s < merged[-1][1]:
            ps, pe, pn = merged[-1]
            merged[-1] = (ps, max(pe, e), pn)
        else:
            merged.append((s, e, n))
    out = []
    last = 0
    for s, e, n in merged:
        out.append(text[last:s])
        out.append(REDACTED)
        findings.append((line_of(s), n))
        last = e
    out.append(text[last:])
    return "".join(out), findings


def strong_hits(text):
    hits = [n for n, rx in TOKEN_RES if rx.search(text)]
    if PRIVATE_KEY_RE.search(text):
        hits.append("Privater Schluessel")
    return hits


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def say(msg=""):
    print(msg, flush=True)


def head(msg):
    say()
    say("=" * 70)
    say(msg)
    say("=" * 70)


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def ask_yes(prompt):
    return ask(prompt + " [ja/nein]: ").lower() in {"j", "ja", "y", "yes"}


def die(msg):
    say()
    say("ABBRUCH: " + msg)
    say("Es wurde nichts hochgeladen. Dein laufender JARVIS ist unveraendert.")
    sys.exit(1)


def run(cmd, cwd=None, env=None, check=True):
    r = subprocess.run(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    if check and r.returncode != 0:
        raise RuntimeError("Befehl fehlgeschlagen: " + " ".join(cmd[:3]) + "\n" + r.stdout[-2000:])
    return r


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.0f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def low(name):
    return name.lower()


def matches_any(name, globs):
    n = low(name)
    return any(fnmatch.fnmatchcase(n, g) for g in globs)


def is_venv(path):
    return (path / "pyvenv.cfg").exists()


def is_sqlite(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


# --------------------------------------------------------------------------
# Schritt 1: Projektordner finden
# --------------------------------------------------------------------------

def running_jarvis_dirs():
    """Liest (nur lesend) laufende Prozesse und systemd-Dienste aus."""
    found = {}
    if sys.platform.startswith("linux"):
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cmd = Path("/proc", pid, "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
                if "jarvis" not in cmd.lower() or "jarvis_export" in cmd:
                    continue
                cwd = os.readlink("/proc/%s/cwd" % pid)
                found[cwd] = "laufender Prozess (PID %s): %s" % (pid, cmd.strip()[:80])
            except OSError:
                continue
        unit_dirs = [Path("/etc/systemd/system"), Path("/lib/systemd/system"),
                     HOME / ".config/systemd/user"]
        for d in unit_dirs:
            if not d.is_dir():
                continue
            for unit in d.glob("*.service"):
                try:
                    txt = unit.read_text(errors="replace")
                except OSError:
                    continue
                if "jarvis" not in txt.lower() and "jarvis" not in unit.name.lower():
                    continue
                m = re.search(r"(?m)^WorkingDirectory=(.+)$", txt)
                if m:
                    found.setdefault(m.group(1).strip(), "systemd-Dienst " + unit.name)
    elif os.name == "nt":
        try:
            r = run(["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'jarvis' } | "
                     "ForEach-Object { $_.ExecutablePath + '|' + $_.CommandLine }"], check=False)
            for line in r.stdout.splitlines():
                for part in re.findall(r"[A-Za-z]:\\[^\"|]+?\.py", line):
                    p = Path(part).parent
                    found.setdefault(str(p), "laufender Prozess: " + line.strip()[:80])
        except (OSError, RuntimeError):
            pass
    return found


def search_jarvis_dirs():
    roots = [HOME, Path("/opt"), Path("/srv"), Path("/var/www"), Path("/home"), Path("/root")]
    if os.name == "nt":
        roots = [HOME, Path("C:/"), Path("D:/")]
    found = []
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(str(root)):
            p = Path(dirpath)
            depth = len(p.parts) - base_depth
            dirnames[:] = [d for d in dirnames
                           if low(d) not in SKIP_DIRS and not d.startswith(".")
                           and low(d) not in {"windows", "program files", "program files (x86)",
                                              "programdata", "appdata", "proc", "sys"}]
            if depth >= 4:
                dirnames[:] = []
            if "jarvis" in p.name.lower() and str(p) not in seen:
                if any(f.endswith(".py") for f in filenames) or any(
                        (p / d).is_dir() for d in dirnames):
                    seen.add(str(p))
                    found.append(str(p))
                    dirnames[:] = []
    return found


def count_py(path):
    n = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if low(d) not in SKIP_DIRS and not is_venv(Path(dirpath) / d)]
        n += sum(1 for f in filenames if f.endswith(".py"))
        if n > 5000:
            break
    return n


def choose_project(argv):
    if len(argv) > 1:
        p = Path(argv[1]).expanduser().resolve()
        if not p.is_dir():
            die("Ordner nicht gefunden: %s" % p)
        return p

    head("Schritt 1/6: JARVIS-Projektordner suchen (nur lesen)")
    running = running_jarvis_dirs()
    candidates = list(running.keys())
    for d in search_jarvis_dirs():
        if d not in candidates:
            candidates.append(d)
    if not candidates:
        say("Kein Ordner mit 'jarvis' im Namen gefunden.")
    for i, d in enumerate(candidates, 1):
        hint = running.get(d, "Ordnername enthaelt 'jarvis'")
        say("  [%d] %s\n      %s, %d Python-Dateien" % (i, d, hint, count_py(d)))
    say()
    say("Der laufende JARVIS ist meist der Eintrag mit 'laufender Prozess' oder 'systemd-Dienst'.")
    say("Achtung: Ist das ein Unterordner (z.B. .../jarvis/src), waehle lieber den Hauptordner")
    say("des Projekts, also den Ordner, in dem auch README, requirements.txt usw. liegen.")
    while True:
        a = ask("Nummer eingeben ODER den vollstaendigen Pfad eintippen: ")
        if a.isdigit() and 1 <= int(a) <= len(candidates):
            p = Path(candidates[int(a) - 1])
        elif a:
            p = Path(a).expanduser()
        else:
            continue
        if p.is_dir():
            return p.resolve()
        say("Diesen Ordner gibt es nicht. Bitte nochmal.")


# --------------------------------------------------------------------------
# Schritt 2: Backup (vollstaendig, bleibt auf dem Server)
# --------------------------------------------------------------------------

def git_state(project):
    info = []
    if not (project / ".git").exists() or shutil.which("git") is None:
        return info, False
    def g(*a):
        return run(["git", "-C", str(project)] + list(a), check=False).stdout.strip()
    branch = g("rev-parse", "--abbrev-ref", "HEAD")
    commit = g("rev-parse", "--short", "HEAD")
    status = g("status", "--porcelain")
    remotes = g("remote", "-v")
    stashes = g("stash", "list")
    info.append("Git-Branch: %s, Commit: %s" % (branch, commit))
    info.append("Nicht gespeicherte (uncommittete) Aenderungen: %d Datei(en)" % (len(status.splitlines()) if status else 0))
    info.append("Gespeicherte Stashes: %d" % (len(stashes.splitlines()) if stashes else 0))
    # Remote-URLs ohne evtl. eingebettete Zugangsdaten anzeigen.
    for line in remotes.splitlines():
        info.append("Remote (unveraendert gelassen): " + URL_CRED_RE.sub(r"\1***\3", line))
    return info, True


def make_backup(project):
    head("Schritt 2/6: Vollstaendiges Backup auf dem Server anlegen")
    backup_dir = HOME / "jarvis-backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    target = backup_dir / ("jarvis-backup-%s.tar.gz" % STAMP)

    size = 0
    for dirpath, dirnames, filenames in os.walk(str(project)):
        dirnames[:] = [d for d in dirnames if low(d) not in BACKUP_SKIP_DIRS and not is_venv(Path(dirpath) / d)]
        for f in filenames:
            try:
                size += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    free = shutil.disk_usage(str(backup_dir)).free
    say("Projektgroesse (ohne venv/node_modules): %s, freier Speicher: %s" % (human(size), human(free)))
    if free < size * 1.2 + 200 * 1024 * 1024:
        die("Zu wenig freier Speicher fuer ein sicheres Backup.")

    tmpdir = Path(tempfile.mkdtemp(prefix="jarvis-sqlite-"))
    count = 0

    def add_filter(ti):
        parts = Path(ti.name).parts
        if any(low(p) in BACKUP_SKIP_DIRS for p in parts):
            return None
        return ti

    try:
        with tarfile.open(str(target), "w:gz") as tar:
            for dirpath, dirnames, filenames in os.walk(str(project)):
                dp = Path(dirpath)
                dirnames[:] = [d for d in dirnames
                               if low(d) not in BACKUP_SKIP_DIRS and not is_venv(dp / d)]
                for f in filenames:
                    src = dp / f
                    arc = str(Path(project.name) / src.relative_to(project))
                    try:
                        if src.is_file() and not src.is_symlink() and is_sqlite(src):
                            # Konsistente Kopie einer evtl. gerade benutzten Datenbank,
                            # nur lesend geoeffnet.
                            snap = tmpdir / ("%d.sqlite" % count)
                            s = sqlite3.connect("file:%s?mode=ro" % src.as_posix(), uri=True)
                            d = sqlite3.connect(str(snap))
                            s.backup(d)
                            d.close()
                            s.close()
                            tar.add(str(snap), arcname=arc)
                        else:
                            tar.add(str(src), arcname=arc, recursive=False, filter=add_filter)
                        count += 1
                    except (OSError, sqlite3.Error) as e:
                        say("  Hinweis: konnte %s nicht sichern (%s)" % (arc, type(e).__name__))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)
    try:
        os.chmod(str(target), 0o600)
    except OSError:
        pass
    # Pruefen, ob das Backup lesbar ist.
    with tarfile.open(str(target), "r:gz") as tar:
        n = sum(1 for _ in tar)
    if n < count:
        die("Backup unvollstaendig (%d von %d Dateien)." % (n, count))
    say("Backup fertig und geprueft: %s (%s, %d Dateien)" % (target, human(target.stat().st_size), n))
    say("Es enthaelt ALLES inkl. .env, Datenbanken und Git-Historie und bleibt nur auf diesem Server.")
    return target


# --------------------------------------------------------------------------
# Schritt 3+4: bereinigte Kopie erstellen und auf Geheimnisse pruefen
# --------------------------------------------------------------------------

def build_staging(project):
    head("Schritt 3/6: Bereinigte Upload-Kopie erstellen")
    staging = WORK / ("upload-" + STAMP)
    staging.mkdir(parents=True, mode=0o700)
    stats = {}
    env_keys = {}
    db_schemas = {}
    big = []

    def skip(reason):
        stats[reason] = stats.get(reason, 0) + 1

    for dirpath, dirnames, filenames in os.walk(str(project)):
        dp = Path(dirpath)
        keep_dirs = []
        for d in dirnames:
            if low(d) in SKIP_DIRS or is_venv(dp / d) or (dp / d).is_symlink():
                skip("Ordner (venv, Cache, Logs, Backups, Secrets, Uploads, Vektor-DB)")
            else:
                keep_dirs.append(d)
        dirnames[:] = keep_dirs
        rel_dir = dp.relative_to(project)
        in_data_dir = any(low(p) in DATA_DIRS for p in rel_dir.parts)
        for f in filenames:
            src = dp / f
            rel = rel_dir / f
            ext = src.suffix.lower()
            if src.is_symlink() or not src.is_file():
                skip("Verknuepfungen/Sonderdateien")
                continue
            if matches_any(f, KEEP_FILE_GLOBS):
                pass
            elif low(f) == ".env" or low(f).startswith(".env.") or low(f).endswith(".env"):
                skip(".env-Dateien (Passwoerter/API-Schluessel)")
                try:
                    keys = re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=",
                                      src.read_text(errors="replace"))
                    env_keys[str(rel)] = sorted(set(keys))
                except OSError:
                    pass
                continue
            elif matches_any(f, SKIP_FILE_GLOBS):
                if is_sqlite(src):
                    skip("Datenbanken (nur Tabellen-Struktur wird uebernommen)")
                    try:
                        c = sqlite3.connect("file:%s?mode=ro" % src.as_posix(), uri=True)
                        rows = c.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                                         "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name").fetchall()
                        c.close()
                        db_schemas[str(rel)] = ";\n\n".join(r[0] for r in rows) + ";\n"
                    except sqlite3.Error:
                        pass
                else:
                    skip("Schluessel, Zertifikate, Logs, Mails, Medien, Modelle, Archive, Datenbanken")
                continue
            elif in_data_dir and ext in DATA_EXTS:
                skip("Daten-Dateien in Daten-/Speicher-/Chat-Ordnern (private Inhalte)")
                continue
            try:
                size = src.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                big.append("%s (%s)" % (rel, human(size)))
                skip("Sehr grosse Dateien (> 10 MB)")
                continue
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            stats["__copied__"] = stats.get("__copied__", 0) + 1
    say("Kopiert: %d Dateien" % stats.pop("__copied__", 0))
    for k, v in sorted(stats.items()):
        say("  ausgelassen: %4d  %s" % (v, k))
    if big:
        say("  Grosse Dateien (nicht hochgeladen): " + ", ".join(big[:10]))
    return staging, stats, env_keys, db_schemas, big


def scan_and_redact(staging):
    head("Schritt 4/6: Upload-Kopie auf Geheimnisse pruefen und bereinigen")
    report = []
    removed = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in TEXT_EXTS:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        text = raw.decode("utf-8", "replace")
        rel = path.relative_to(staging)
        if PRIVATE_KEY_RE.search(text):
            path.unlink()
            removed.append(str(rel))
            report.append((str(rel), 0, "Privater Schluessel -> Datei entfernt"))
            continue
        new, findings = redact_text(text, ext)
        if findings:
            path.write_text(new, encoding="utf-8")
            for line, kind in findings:
                report.append((str(rel), line, kind))
    # Zweiter Durchgang: es darf nichts Eindeutiges mehr uebrig sein.
    leftovers = []
    for path in staging.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_EXTS:
            try:
                hits = strong_hits(path.read_text(errors="replace"))
            except OSError:
                continue
            if hits:
                leftovers.append("%s (%s)" % (path.relative_to(staging), ", ".join(hits)))
    if leftovers:
        die("Nach der Bereinigung wurden noch Geheimnisse gefunden:\n  " + "\n  ".join(leftovers))
    if report:
        say("Gefunden und in der UPLOAD-KOPIE durch '%s' ersetzt (Werte werden nicht angezeigt):" % REDACTED)
        for rel, line, kind in report[:60]:
            say("  %s:%s  %s" % (rel, line, kind))
        if len(report) > 60:
            say("  ... und %d weitere (siehe IMPORT_REPORT.md)" % (len(report) - 60))
        say("Die Originaldateien auf dem Server bleiben unveraendert.")
    else:
        say("Keine Geheimnisse im Code gefunden.")
    return report


def write_reports(staging, project, stats, env_keys, db_schemas, big, redactions, git_info):
    lines = [
        "# Import-Bericht (Server -> GitHub)",
        "",
        "Erstellt am %s mit tools/jarvis-export/jarvis_export.py." % time.strftime("%Y-%m-%d %H:%M"),
        "Original-Ordner auf dem Server: `%s`" % project,
        "",
        "Der Code ist ein bereinigter Schnappschuss. Die alte Git-Historie wurde",
        "bewusst NICHT uebernommen (Schutz vor alten Geheimnissen); sie liegt im",
        "Server-Backup unter ~/jarvis-backups/.",
        "",
        "## Git-Zustand auf dem Server",
        "",
    ]
    lines += ["- " + i for i in git_info] or ["- Kein Git-Repository im Projektordner."]
    lines += ["", "## Ausgelassen", ""]
    lines += ["- %d x %s" % (v, k) for k, v in sorted(stats.items())] or ["- nichts"]
    if big:
        lines += ["", "Grosse Dateien (Pfad, Groesse):", ""] + ["- `%s`" % b for b in big]
    lines += ["", "## Ersetzte Geheimnisse (`%s`)" % REDACTED, ""]
    lines += ["- `%s`:%s %s" % r for r in redactions] or ["- keine"]
    lines += ["", "## Umgebungsvariablen aus .env-Dateien (nur Namen, keine Werte)", ""]
    if env_keys:
        for f, keys in sorted(env_keys.items()):
            lines.append("- `%s`: %s" % (f, ", ".join("`%s`" % k for k in keys) or "(leer)"))
    else:
        lines.append("- keine .env-Dateien gefunden")
    lines += ["", "## Datenbanken", "", "Nur die Struktur (CREATE-Befehle) liegt unter",
              "`IMPORT_DB_SCHEMA/`. Inhalte wurden nicht hochgeladen.", ""]
    lines += ["- `%s`" % f for f in sorted(db_schemas)] or ["- keine SQLite-Datenbanken gefunden"]
    (staging / "IMPORT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if db_schemas:
        d = staging / "IMPORT_DB_SCHEMA"
        d.mkdir(exist_ok=True)
        for f, schema in db_schemas.items():
            name = re.sub(r"[^A-Za-z0-9_.-]+", "__", f) + ".sql"
            (d / name).write_text(schema, encoding="utf-8")

    if env_keys:
        out = ["# Automatisch erzeugt: Namen der Variablen aus den .env-Dateien des Servers.",
               "# Werte stehen NICHT im Repository. Echte Werte nur auf dem Server/Secret-Store.", ""]
        for f, keys in sorted(env_keys.items()):
            out.append("# aus %s" % f)
            out += ["%s=" % k for k in keys]
            out.append("")
        (staging / ".env.example.import").write_text("\n".join(out), encoding="utf-8")

    gi = staging / ".gitignore"
    existing = gi.read_text(errors="replace") if gi.exists() else ""
    extra = [
        "", "# --- ergaenzt beim Server-Import (Schutz vor Geheimnissen) ---",
        ".env", ".env.*", "!.env.example", "!.env.example.import", "*.pem", "*.key",
        "*.db", "*.sqlite", "*.sqlite3", "*.log", "logs/", "backups/", "secrets/",
        "__pycache__/", ".venv/", "venv/", "node_modules/", "credentials*.json",
        "token*.json", "client_secret*.json",
    ]
    gi.write_text(existing.rstrip("\n") + "\n" + "\n".join(extra) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Schritt 5+6: Zugang einrichten und hochladen
# --------------------------------------------------------------------------

def ssh_env(keyfile, known_hosts):
    k = keyfile.as_posix()
    kh = known_hosts.as_posix()
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = (
        'ssh -i "%s" -o IdentitiesOnly=yes -o UserKnownHostsFile="%s" '
        "-o StrictHostKeyChecking=yes -o BatchMode=yes" % (k, kh)
    )
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def setup_deploy_key():
    head("Schritt 5/6: Zugang zu GitHub einrichten (nur fuer dieses eine Repository)")
    for tool in ("git", "ssh", "ssh-keygen"):
        if shutil.which(tool) is None:
            if os.name == "nt":
                hint = "Installiere 'Git for Windows' (https://git-scm.com/download/win) und starte das Skript erneut."
            else:
                hint = "Installiere es mit:  sudo apt-get install -y git openssh-client   (danach Skript erneut starten)"
            die("Das Programm '%s' fehlt. %s" % (tool, hint))
    keydir = HOME / ".jarvis-github-key"
    keydir.mkdir(mode=0o700, exist_ok=True)
    keyfile = keydir / "id_ed25519"
    known = keydir / "known_hosts"
    known.write_text("".join(
        "%s %s\n" % (host, k)
        for host in ("[ssh.github.com]:443", "github.com") for k in GITHUB_HOST_KEYS))
    if not keyfile.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "jarvis-server-deploy-key",
             "-f", str(keyfile)])
    env = ssh_env(keyfile, known)

    def test():
        r = run(["ssh", "-i", str(keyfile), "-o", "IdentitiesOnly=yes", "-o",
                 "UserKnownHostsFile=" + str(known), "-o", "StrictHostKeyChecking=yes",
                 "-o", "BatchMode=yes", "-p", "443", "-T", "git@ssh.github.com"], check=False)
        return "successfully authenticated" in r.stdout, r.stdout

    ok, _ = test()
    if ok:
        say("Zugang zu GitHub funktioniert bereits.")
        return env
    pub = (keyfile.with_suffix(".pub")).read_text().strip()
    say("Dieser Server braucht einmalig die Erlaubnis, in dein Repository zu schreiben.")
    say("Das ist ein 'Deploy Key': er gilt NUR fuer %s und fuer kein anderes Repository." % GITHUB_REPO)
    say()
    say("1. Oeffne im Browser (eingeloggt bei GitHub):")
    say("   " + DEPLOY_KEY_URL)
    say("2. Title:  JARVIS Server")
    say("3. Key:    die folgende EINE Zeile komplett kopieren und einfuegen:")
    say()
    say(pub)
    say()
    say("4. Haken setzen bei 'Allow write access'")
    say("5. Auf 'Add key' klicken")
    say()
    for attempt in range(5):
        ask("Wenn erledigt, hier ENTER druecken ... ")
        ok, out = test()
        if ok:
            say("Zugang zu GitHub funktioniert.")
            return env
        if "Permission denied" in out:
            say("GitHub kennt den Schluessel noch nicht. Bitte Schritte 1-5 pruefen.")
        else:
            say("Verbindung zu GitHub nicht moeglich: " + out.strip()[-300:])
    die("GitHub-Zugang konnte nicht eingerichtet werden.")


def push(staging, env):
    head("Schritt 6/6: Hochladen nach GitHub")
    is_local_test = "JARVIS_EXPORT_REMOTE" in os.environ
    remote = run(["git", "ls-remote", "--heads", REMOTE_URL], env=env, check=False)
    if remote.returncode != 0:
        die("Repository nicht erreichbar:\n" + remote.stdout[-500:])
    branch = "main"
    if remote.stdout.strip():
        branch = "server-import-" + STAMP
        say("Das Repository ist nicht leer. Es wird NICHTS ueberschrieben;")
        say("der Stand wird in den neuen Branch '%s' hochgeladen." % branch)

    def g(*a):
        return run(["git"] + list(a), cwd=str(staging), env=env)

    g("init", "-q")
    g("symbolic-ref", "HEAD", "refs/heads/" + branch)
    g("config", "user.name", "JARVIS Server Import")
    g("config", "user.email", "jarvis-server-import@localhost")
    g("config", "core.autocrlf", "false")
    g("add", "-A")
    files = g("ls-files").stdout.splitlines()
    say("Bereit zum Hochladen: %d Dateien." % len(files))
    say("Vorschau (die ersten 40):")
    for f in files[:40]:
        say("  " + f)
    say("Die vollstaendige Liste steht in: %s" % (staging / "IMPORT_REPORT.md"))
    if not is_local_test and not ask_yes("Jetzt in das PRIVATE Repository %s hochladen?" % GITHUB_REPO):
        die("Vom Benutzer abgebrochen.")
    g("commit", "-q", "-m", "Import: JARVIS-Stand vom Server (bereinigt, ohne Secrets und Daten)")
    local_head = g("rev-parse", "HEAD").stdout.strip()
    # Kein Force-Push.
    g("push", "-q", REMOTE_URL, "HEAD:refs/heads/" + branch)
    check = run(["git", "ls-remote", REMOTE_URL, "refs/heads/" + branch], env=env).stdout.split()
    if not check or check[0] != local_head:
        die("Upload konnte nicht bestaetigt werden.")
    say("Upload bestaetigt: Branch '%s', Commit %s" % (branch, local_head[:10]))
    return branch, local_head


def main():
    say("JARVIS-Export nach GitHub (%s)" % GITHUB_REPO)
    say("Dein laufender JARVIS wird dabei NICHT veraendert oder neu gestartet.")
    if sys.version_info < (3, 7):
        die("Python 3.7 oder neuer wird benoetigt.")
    project = choose_project(sys.argv)
    say("Gewaehlter Ordner: %s" % project)
    git_info, _ = git_state(project)
    for i in git_info:
        say("  " + i)
    backup = make_backup(project)
    staging, stats, env_keys, db_schemas, big = build_staging(project)
    redactions = scan_and_redact(staging)
    write_reports(staging, project, stats, env_keys, db_schemas, big, redactions, git_info)
    env = dict(os.environ)
    if "JARVIS_EXPORT_REMOTE" not in os.environ:
        env = setup_deploy_key()
    branch, commit = push(staging, env)
    head("FERTIG")
    say("Backup (bleibt auf dem Server): %s" % backup)
    say("GitHub: https://github.com/%s/tree/%s" % (GITHUB_REPO, branch))
    say("Commit: %s" % commit[:10])
    say()
    say("Schreibe Claude jetzt einfach:  'Upload ist fertig'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("Mit Strg+C abgebrochen.")
    except RuntimeError as e:
        die(str(e))
