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
import stat as stat_module
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
# Begriffe, an denen laufende JARVIS-Prozesse/-Dienste erkannt werden.
PROCESS_KEYWORDS = ("jarvis", "maaker")
# Git gegen das Projekt-Repository NUR lesend und ohne dass eine im Repo
# hinterlegte Konfiguration (fsmonitor, Hooks, Filter, Pager, Alias) als root
# Befehle ausfuehren kann. safe.directory=* erlaubt fremde Besitzer (root vs.
# maaker), GIT_OPTIONAL_LOCKS=0 verhindert jedes Schreiben am Index.
PROJECT_GIT = [
    "git",
    "-c", "safe.directory=*",
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.pager=cat",
    "-c", "gc.auto=0",
    "-c", "maintenance.auto=false",
    "-c", "core.askpass=",
    "-c", "protocol.ext.allow=never",
]
PROJECT_GIT_ENV = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
                       GIT_PAGER="cat", GIT_ALLOW_PROTOCOL="file:http:https:ssh:git")

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
    "jarvis-export", "jarvis-backups", "site-packages",
    # personenbezogene Daten Dritter
    "leads", "lead", "contacts", "kontakte", "kunden", "customers", "clients", "crm",
    # WhatsApp-/Browser-Sitzungen (wirken wie Passwoerter)
    ".wwebjs_auth", ".wwebjs_cache", "auth_info", "auth_info_baileys",
    "baileys_auth_info", "browser_data", "browser-data", "chrome_profile",
    "chrome-profile", "user_data_dir", "user-data-dir",
}
# Ordnernamen-Muster, die komplett ausgelassen werden.
SKIP_DIR_GLOBS = [
    "auth_info*", "*session*", ".wwebjs*", "*_auth", "*-auth", "*cookie*",
    "*secret*", "*credential*", "*token*",
]
# Ordner, die nur im Backup fehlen (reproduzierbar, sehr gross).
BACKUP_SKIP_DIRS = {
    "__pycache__", ".venv", "venv", ".virtualenv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".cache",
    "site-packages", "jarvis-export", "jarvis-backups",
}
# Ordner, in denen Daten-Dateien (keine Code-Dateien) als privat gelten.
DATA_DIRS = {
    "data", "memory", "memories", "chats", "chat", "chat_history",
    "conversations", "history", "inbox", "mail", "mails", "messages",
    "transcripts", "personal", "private", "user_data", "userdata", "storage",
    "exports", "downloads", "db", "database", "dumps", "media",
}
# In Daten-Ordnern werden NUR diese Code-Dateien uebernommen, sonst nichts.
DATA_DIR_CODE_EXTS = {
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh",
    ".bash", ".ps1", ".go", ".rs",
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
    "creds*.json", "pre-key-*.json", "sender-key-*.json", "app-state-sync-*.json",
    "session-*.json", "auth*.json", ".credentials.json", "settings.local.json",
    "*secret*.json", "*secret*.yaml", "*secret*.yml", "*secret*.toml", "*secret*.txt",
    "*credential*.json", "*credential*.yaml", "*credential*.yml", "*credential*.txt",
    "*.ldb", "*.jsonl", "*.ndjson", "*.har", "*.pcap",
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

CONFIG_EXTS = {
    ".ini", ".cfg", ".conf", ".config", ".properties", ".env", "",
    ".htpasswd", ".netrc",
}
MARKDOWN_EXTS = {".md", ".markdown", ".rst", ".txt"}

# ALLOW-LIST: nur Dateien mit diesen Endungen werden hochgeladen. Alles andere
# (Binaerdateien, unbekannte Typen) bleibt grundsaetzlich draussen (fail-closed).
UPLOAD_EXTS = {
    ".py", ".pyw", ".pyi", ".ipynb", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".jsx", ".vue", ".svelte", ".json", ".jsonc", ".json5", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".config", ".properties", ".env",
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".html", ".htm", ".css",
    ".scss", ".sass", ".less", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".bat", ".cmd", ".sql", ".xml", ".svg", ".go", ".rs", ".rb", ".php",
    ".java", ".kt", ".kts", ".gradle", ".c", ".h", ".cpp", ".hpp", ".cc",
    ".hh", ".cs", ".swift", ".m", ".mm", ".lua", ".pl", ".pm", ".r", ".jl",
    ".dart", ".ex", ".exs", ".erl", ".clj", ".cljs", ".scala", ".groovy",
    ".tf", ".tfvars", ".hcl", ".proto", ".graphql", ".gql", ".prisma",
    ".example", ".sample", ".template", ".dist", ".j2", ".jinja", ".jinja2",
    ".tmpl", ".mustache", ".hbs", ".service", ".timer", ".socket", ".path",
    ".desktop", ".editorconfig", ".gitignore", ".gitattributes", ".csv",
    ".tsv", ".po", ".pot", ".http", ".rest", ".env.example", ".cnf", ".lock",
    ".mk", ".cmake", ".bazel", ".bzl", ".nix", ".dockerfile", ".containerfile",
}
# Bekannte Dateien ohne Endung.
KNOWN_NAMES = {
    "dockerfile", "containerfile", "makefile", "gnumakefile", "caddyfile",
    "procfile", "readme", "license", "licence", "changelog", "authors",
    "contributors", "notice", "copying", "vagrantfile", "jenkinsfile",
    "gemfile", "rakefile", "pipfile", "brewfile", "justfile", "taskfile",
    ".gitignore", ".gitattributes", ".dockerignore", ".editorconfig",
    ".npmrc", ".nvmrc", ".python-version", ".ruby-version", ".tool-versions",
    ".prettierrc", ".eslintrc", ".babelrc", ".bashrc", ".profile",
}

# --------------------------------------------------------------------------
# Geheimnis-Erkennung
# --------------------------------------------------------------------------

# Hochkonfidente Token-Muster. Diese fuehren beim strengen Abschlusscheck
# (strong_hits) zum ABBRUCH, falls nach der Bereinigung noch vorhanden.
TOKEN_PATTERNS = [
    ("Anthropic-Key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI-Key", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"),
    ("Schluessel sk_", r"\bsk_[A-Za-z0-9]{24,}"),            # Stripe, ElevenLabs, u.a.
    ("Schluessel pk_/rk_", r"\b[pr]k_(?:live|test)_[A-Za-z0-9]{20,}"),
    ("AWS-Key", r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b"),
    ("GitHub-Token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    ("GitHub-Token", r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    ("GitLab-Token", r"\bglpat-[A-Za-z0-9_\-]{18,}\b"),
    ("Slack-Token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("Slack-Webhook", r"https://hooks\.slack\.com/services/[A-Za-z0-9/+_\-]{20,}"),
    ("Discord-Webhook", r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]{20,}"),
    ("Telegram-Bot-URL", r"https://api\.telegram\.org/bot\d{6,}:[A-Za-z0-9_\-]{30,}"),
    ("Google-Key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Google-OAuth", r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    ("Firebase/GCP-Key", r"-----BEGIN[A-Z ]*PRIVATE KEY"),
    ("Telegram-Bot-Token", r"\b\d{8,10}:[A-Za-z0-9_\-]{33,40}\b"),
    ("HuggingFace-Token", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("Groq-Key", r"\bgsk_[A-Za-z0-9]{40,}\b"),
    ("Replicate-Token", r"\br8_[A-Za-z0-9]{30,}\b"),
    ("Stripe-Key", r"\b(?:sk|rk|pk)_live_[A-Za-z0-9]{20,}\b"),
    ("SendGrid-Key", r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{30,}\b"),
    ("Twilio-Key", r"\bSK[0-9a-fA-F]{32}\b"),
    ("Mailgun-Key", r"\bkey-[0-9a-f]{32}\b"),
    ("Discord-Token", r"\b[MN][A-Za-z\d]{23,25}\.[\w\-]{6}\.[\w\-]{27,}\b"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    ("npm-Token", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("OpenSSH-Key", r"-----BEGIN OPENSSH PRIVATE KEY"),
]
TOKEN_RES = [(n, re.compile(p)) for n, p in TOKEN_PATTERNS]

# Zugangsdaten in Verbindungs-URLs: scheme://user:PASSWORT@host
URL_CRED_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@'\"]+:)([^\s@'\"]{3,})(@)")

# Namen, die auf ein Geheimnis hindeuten. Der zweite Teil (pass, pw, key, ...)
# steht am Wort-Ende, damit auch ein blankes `pass =` oder `encryptionKey:`
# erkannt wird (fail-closed: im Zweifel schwaerzen).
_SECRET_WORD = (
    r"(?:password|passwort|passwd|kennwort|secret|token|credential|webhook|"
    r"api[_\-]?key|apikey|access[_\-]?key|private[_\-]?key|client[_\-]?secret|"
    r"auth[_\-]?(?:key|token)|session[_\-]?key|signing[_\-]?key|"
    r"encryption[_\-]?key|bearer)[A-Za-z0-9_\-]*"
    r"|(?:pass|pw|pwd|passphrase|creds?|salt|dsn|pin|seed|mnemonic|keys?)"
)
# Prefix auf 64 Zeichen begrenzt -> kein katastrophales Backtracking (ReDoS).
SECRET_NAME = r"[A-Za-z0-9_\-.]{0,64}(?:" + _SECRET_WORD + r")"
# name = "wert"   name: 'wert'   "name": "wert"   \"name\": \"wert\" (JSON-escaped)
QUOTED_ASSIGN_RE = re.compile(
    r"(?i)(\\?['\"]?" + SECRET_NAME + r"\\?['\"]?\s*[:=]\s*)(\\?['\"])([^'\"\r\n\\]{5,})(\2)"
)
# Zuweisung ohne Anfuehrungszeichen, mit : = | als Trenner. Fuehrende Markdown-/
# Shell-Zeichen (- * | > # export set $env:) und ** fett ** werden mitgefressen:
#   token = abc   export API_KEY=abc   - Passwort: abc   | Key | abc |
#   - **API-Key:** abc
PLAIN_ASSIGN_RE = re.compile(
    r"(?im)^[\s\-*|>#]*(?:export\s+|set\s+|\$env:)?(['\"*]*\s*" + SECRET_NAME +
    r"['\"*]*\s*[:=|]\s*\**\s*)([^\s'\"|#;]{6,})"
)
# Konfig-Dateien mit Leerzeichen als Trenner:  password foobar   apikey abc123
SPACE_ASSIGN_RE = re.compile(
    r"(?im)^[\s\-*>#]*(" + SECRET_NAME + r"\s+)([^\s'\"|#;]{6,})\s*$"
)
# "root / PASSWORT"  oder  "Login: user / PASSWORT"
SLASH_CRED_RE = re.compile(r"(?i)\b(root|admin|user|login|benutzer)\b\s*[:/]\s*\S+\s*/\s*(\S{4,})")
# HTTP-Kopfzeilen / CLI-Argumente mit Zugangsdaten
HEADER_RE = re.compile(
    r"(?i)(\\?['\"]?(?:x-api-key|api-key|apikey|x-auth-token|x-access-token|"
    r"authorization|proxy-authorization)\\?['\"]?\s*[:=]\s*)"
    r"(?:(bearer|basic|token)\s+)?([^\s'\"\\]{8,})"
)
# CLI-Argumente mit Zugangsdaten. Das blanke "-p" wurde bewusst entfernt: es
# traf harmlose Dinge wie "--probe", "-py3-none-any.whl" oder "-prime" und
# zerstoerte damit massenhaft Code/Doku. Echte Passwort-Flags und sshpass
# bleiben erfasst; ein Token im Wert faengt zusaetzlich TOKEN_RES ab.
CLI_CRED_RE = re.compile(
    r"(?i)(--(?:password|passwd|pass|token|api-?key|access-?token|secret|auth-?token)"
    r"[=\s]+|sshpass\s+-p\s*)"
    r"([^\s'\"]{4,})"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")

PLACEHOLDER_HINTS = (
    "your", "xxx", "yyy", "zzz", "***", "...", "example", "beispiel",
    "changeme", "change_me", "change-me", "placeholder", "redacted",
    "dummy", "todo", "tbd", "hier_", "dein_", "deine_", "<", "insert",
)
NOT_SECRET_WORDS = {
    "true", "false", "none", "null", "nil", "bearer", "basic", "oauth",
    "oauth2", "sha256", "sha512", "hs256", "rs256", "utf-8", "ascii",
    "string", "number", "boolean", "required", "optional", "default",
}


def looks_like_placeholder(value):
    """Konservativ: nur eindeutige Nicht-Geheimnisse als Platzhalter einstufen.
    Im Zweifel False -> es wird geschwaerzt (fail-closed)."""
    v = value.strip().strip("\\").lower()
    if len(v) < 4 or v in NOT_SECRET_WORDS:
        return True
    if any(h in v for h in PLACEHOLDER_HINTS):
        return True
    # Variablen-Verweis: $VAR, ${VAR}, %VAR%, os.environ[...], process.env.X
    if re.fullmatch(r"\$\{?[a-z_][a-z0-9_]*\}?", v) or re.fullmatch(r"%[a-z0-9_]+%", v):
        return True
    if v.startswith(("os.environ", "process.env", "getenv", "config.", "settings.",
                     "self.", "this.", "env.", "secrets.", "vault")):
        return True
    # Formatplatzhalter:  {token}  {{ .Values.x }}  %(pw)s  $(cmd)
    if re.search(r"\{[a-z0-9_. ]*\}|%\([a-z0-9_]+\)|\$\(", v):
        return True
    val = value.strip()
    # Name einer Umgebungsvariable als Wert: OPENAI_API_KEY (Grossbuchstaben MIT _)
    if re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+", val):
        return True
    # Rein kleingeschriebener Bezeichner ohne Ziffern (Feldname/Verweis, keine
    # echte Losung): access_token, api.key, mode-token -> ja; Hunter2 / X_secret
    # -> nein (Originalschreibweise pruefen, nicht die kleingeschriebene Kopie!)
    if re.fullmatch(r"[a-z][a-z_.\-]*", val) and re.search(r"pass|token|key|secret|cred|auth", val):
        return True
    return False


# Zuweisungs-Regeln werden pro Zeile angewandt. Sehr lange Zeilen (z.B.
# minimiertes JS/JSON, Daten-Blobs) werden dabei uebersprungen, damit kein
# katastrophales Backtracking (ReDoS) entsteht. Token-Muster (TOKEN_RES)
# laufen weiterhin ueber den ganzen Text und sind linear.
LINE_SCAN_LIMIT = 2000


def _iter_lines(text):
    """(zeilenstart_offset, zeile) fuer jede Zeile."""
    start = 0
    for line in text.splitlines(keepends=True):
        yield start, line
        start += len(line)


def _add_assign_spans(text, rx, value_group, label, spans):
    for off, line in _iter_lines(text):
        if len(line) > LINE_SCAN_LIMIT:
            continue
        for m in rx.finditer(line):
            val = m.group(value_group)
            if val and not looks_like_placeholder(val):
                spans.append((off + m.start(value_group), off + m.end(value_group), label))


_MD_SECRET_COL = re.compile(
    r"(?i)pass|passwort|kennwort|key|token|secret|zugang|credential|login|schl(?:ue|\u00fc)ssel|api")


def _md_table_spans(text, spans):
    """Markdown-Tabellen: Spalten, deren Kopf auf ein Geheimnis hindeutet
    (z.B. 'Passwort', 'Key'), werden in allen Datenzeilen geschwaerzt."""
    lines = text.split("\n")
    offset = 0
    offsets = []
    for ln in lines:
        offsets.append(offset)
        offset += len(ln) + 1
    i = 0
    while i < len(lines) - 1:
        row, sep = lines[i], lines[i + 1]
        if len(row) > LINE_SCAN_LIMIT:
            i += 1
            continue
        if row.count("|") >= 2 and re.fullmatch(r"\s*\|?[\s:\-|]*-[\s:\-|]*\|?\s*", sep):
            headers = [h.strip().lower() for h in row.strip().strip("|").split("|")]
            secret_cols = {idx for idx, h in enumerate(headers) if _MD_SECRET_COL.search(h)}
            if secret_cols:
                j = i + 2
                while j < len(lines) and lines[j].count("|") >= 2:
                    base = offsets[j]
                    pos = 0
                    cells = lines[j].split("|")
                    lead = 1 if lines[j].lstrip().startswith("|") else 0
                    for idx, cell in enumerate(cells):
                        col = idx - lead
                        val = cell.strip()
                        if col in secret_cols and val and not looks_like_placeholder(val):
                            s = base + pos + (len(cell) - len(cell.lstrip()))
                            spans.append((s, s + len(val), "Zugangsdaten in Tabelle"))
                        pos += len(cell) + 1
                    j += 1
                i = j
                continue
        i += 1


def redact_text(text, ext):
    """Gibt (neuer_text, [(zeile, art), ...]) zurueck. ext steuert nur, welche
    zusaetzlichen Regeln (Konfig/Markdown) greifen."""
    findings = []

    def line_of(pos):
        return text.count("\n", 0, pos) + 1

    spans = []  # (start, ende, art)
    for name, rx in TOKEN_RES:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), name))
    _add_assign_spans(text, URL_CRED_RE, 2, "Passwort in URL", spans)
    _add_assign_spans(text, QUOTED_ASSIGN_RE, 3, "Zugangsdaten-Zuweisung", spans)
    _add_assign_spans(text, HEADER_RE, 3, "Zugangsdaten in Kopfzeile", spans)
    _add_assign_spans(text, CLI_CRED_RE, 2, "Zugangsdaten in Befehl", spans)
    _add_assign_spans(text, SLASH_CRED_RE, 2, "Login/Passwort", spans)
    # Zuweisungen ohne Anfuehrungszeichen (name = wert) ueberall, als Netz.
    _add_assign_spans(text, PLAIN_ASSIGN_RE, 2, "Zugangsdaten-Zuweisung", spans)
    if ext in CONFIG_EXTS:
        _add_assign_spans(text, SPACE_ASSIGN_RE, 2, "Zugangsdaten-Zuweisung", spans)
    if ext in MARKDOWN_EXTS:
        _md_table_spans(text, spans)

    if not spans:
        return text, findings
    spans = [s for s in spans if s[1] > s[0]]
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
    """Nur hochkonfidente Geheimnisse. Werden diese nach der Bereinigung noch
    gefunden, bricht der Export ab (fail-closed, keine Fehlalarme)."""
    hits = [n for n, rx in TOKEN_RES if rx.search(text)]
    if PRIVATE_KEY_RE.search(text):
        hits.append("Privater Schluessel")
    # Passwort in Verbindungs-URL ist ebenfalls hochkonfident (pro Zeile, da
    # URL_CRED_RE auf sehr langen Zeilen sonst stark zurueckverfolgt).
    for _, line in _iter_lines(text):
        if len(line) > LINE_SCAN_LIMIT:
            continue
        m = URL_CRED_RE.search(line)
        if m and not looks_like_placeholder(m.group(2)):
            hits.append("Passwort in URL")
            break
    return sorted(set(hits))


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
        universal_newlines=True, errors="replace",
    )
    if check and r.returncode != 0:
        raise RuntimeError("Befehl fehlgeschlagen: " + " ".join(cmd[:3]) + "\n" + (r.stdout or "")[-2000:])
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


def owner_only(path, is_dir=False):
    """True, wenn nur der Besitzer lesen darf (Linux). So werden oft
    Geheimnisse geschuetzt, z.B. Installer mit Schluesseln oder Sitzungen."""
    if os.name == "nt":
        return False
    try:
        mode = os.stat(str(path)).st_mode
    except OSError:
        return False
    return (mode & (0o055 if is_dir else 0o044)) == 0


def git_allowed_files(repo_dir):
    """Dateien, die das Projekt selbst NICHT per .gitignore ausschliesst
    (nur lesend, ohne das Repository zu veraendern). None, wenn unbekannt."""
    if shutil.which("git") is None:
        return None
    r = run(PROJECT_GIT + ["-C", str(repo_dir), "ls-files", "-z", "-c", "-o",
                           "--exclude-standard"], env=PROJECT_GIT_ENV, check=False)
    if r.returncode != 0:
        return None
    return set(p for p in r.stdout.split("\0") if p)


def mask(text):
    """Zugangsdaten in Befehlszeilen/Konfigurationen unkenntlich machen."""
    text = re.sub(r"\s+", " ", text).strip()
    text = URL_CRED_RE.sub(r"\1***\3", text)
    for _, rx in TOKEN_RES:
        text = rx.sub("***", text)
    return re.sub(r"(?i)((?:key|token|pass|secret|auth|pwd)[^\s=:]*[\s=:]+)\S+", r"\1***", text)


def is_sqlite(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def is_text_file(path, probe=65536):
    """True nur fuer echte Textdateien. Binaerdateien (NUL-Bytes oder nicht als
    UTF-8/UTF-16 dekodierbar) werden nie hochgeladen (sonst ungescannt)."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(probe)
    except OSError:
        return False
    if not chunk:
        return True
    if chunk[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return False  # UTF-16: enthaelt NUL-Bytes, lieber auslassen
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError as e:
        # Ein abgeschnittenes Multibyte-Zeichen am Pufferende ist kein Fehler.
        if e.start < len(chunk) - 4:
            return False
    return True


def read_text_safe(path):
    return path.read_bytes().decode("utf-8", "replace")


def sqlite_schema(path):
    """Nur die Tabellenstruktur (CREATE-Befehle) aus einer Kopie lesen, damit
    keine Sperre und keine -wal/-shm-Dateien im Projekt entstehen."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-schema-")) / "db"
    try:
        shutil.copy2(str(path), str(tmp))
        c = sqlite3.connect(str(tmp))
        rows = c.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                         "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name").fetchall()
        c.close()
        text = ";\n\n".join(r[0] for r in rows)
        # Sicherheitsnetz: auch die Struktur bereinigen (DEFAULT-Werte u.ae.).
        text, _ = redact_text(text, ".sql")
        return text + ";\n"
    except (OSError, sqlite3.Error):
        return "-- Struktur nicht lesbar\n"
    finally:
        shutil.rmtree(str(tmp.parent), ignore_errors=True)


# --------------------------------------------------------------------------
# Schritt 1: Projektordner finden
# --------------------------------------------------------------------------

PROJECT_MARKERS = (".git", "requirements.txt", "pyproject.toml", "setup.py",
                   "setup.cfg", "Pipfile", "poetry.lock")
BROAD_DIRS = {"/home", "/root", "/opt", "/srv", "/var", "/var/www", "/var/lib",
              "/usr", "/usr/local", "/etc", "/tmp", "/mnt", "/media"}


def too_broad(path):
    """True fuer Ordner, die sicher mehr als nur JARVIS enthalten
    (Laufwerk, ganzer Benutzerordner, Systemordner)."""
    p = Path(os.path.abspath(str(path)))
    if p == HOME or len(p.parts) <= 1:
        return True
    if os.name == "nt":
        return len(p.parts) <= 3 and low(p.parts[1]) == "users"
    return str(p) in BROAD_DIRS or p.parent == Path("/home")


def project_root(start):
    """Vom Ordner eines Python-Skripts nach oben bis zum Projekt-Hauptordner
    (dort, wo z.B. .git oder requirements.txt liegt)."""
    start = Path(start)
    cur = start
    for _ in range(4):
        if too_broad(cur):
            break
        if any((cur / m).exists() for m in PROJECT_MARKERS):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


def script_dir_from_args(args, cwd):
    """Ordner des gestarteten Python-Skripts/-Moduls aus der Befehlszeile."""
    for i, a in enumerate(args[1:], 1):
        if args[i - 1] == "-m":
            mod = Path(cwd) / a.split(".")[0]
            return mod if mod.is_dir() else Path(cwd)
        if a.endswith(".py"):
            sp = Path(a) if os.path.isabs(a) else Path(cwd) / a
            return sp.parent
    return Path(cwd)


def running_jarvis_dirs():
    """Liest (nur lesend) laufende Prozesse und systemd-Dienste aus.
    Gibt ({ordner: hinweis}, [hinweise_zu_docker]) zurueck."""
    found = {}
    notes = []
    if sys.platform.startswith("linux"):
        try:
            own_ns = os.readlink("/proc/self/ns/mnt")
        except OSError:
            own_ns = None
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                args = [a.decode("utf-8", "replace")
                        for a in Path("/proc", pid, "cmdline").read_bytes().split(b"\0") if a]
                cmd = " ".join(args)
                if not any(k in cmd.lower() for k in PROCESS_KEYWORDS) or "jarvis_export" in cmd:
                    continue
                if own_ns and os.readlink("/proc/%s/ns/mnt" % pid) != own_ns:
                    notes.append("JARVIS scheint (auch) in einem Docker-Container zu laufen: " + cmd[:70])
                    continue
                cwd = os.readlink("/proc/%s/cwd" % pid)
                root = project_root(script_dir_from_args(args, cwd))
                found.setdefault(str(root), "laufender Prozess (PID %s): %s" % (pid, cmd.strip()[:80]))
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
                if not any(k in txt.lower() or k in unit.name.lower() for k in PROCESS_KEYWORDS):
                    continue
                m = re.search(r"(?m)^WorkingDirectory=-?(/.+)$", txt)
                wd = m.group(1).strip() if m else None
                start = Path(wd) if wd else None
                e = re.search(r"(?m)^ExecStart=(.+)$", txt)
                py = re.search(r"(\S+\.py)\b", e.group(1)) if e else None
                if py:
                    sp = Path(py.group(1).lstrip("-@"))
                    if not sp.is_absolute() and wd:
                        sp = Path(wd) / sp
                    if sp.is_absolute():
                        start = sp.parent
                if start:
                    found.setdefault(str(project_root(start)), "systemd-Dienst " + unit.name)
    elif os.name == "nt":
        try:
            r = run(["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'jarvis|maaker' } | "
                     "ForEach-Object { $_.ExecutablePath + '|' + $_.CommandLine }"], check=False)
            for line in r.stdout.splitlines():
                if "jarvis_export" in line:
                    continue
                for part in re.findall(r"[A-Za-z]:\\[^\"|]+?\.py", line):
                    p = project_root(Path(part).parent)
                    found.setdefault(str(p), "laufender Prozess: " + line.strip()[:80])
        except (OSError, RuntimeError):
            pass
    return found, notes


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


TOO_BROAD_MSG = ("Das ist kein einzelner Projektordner, sondern z.B. dein ganzer Benutzer- "
                 "oder Systemordner. Darin liegen auch Dinge, die nicht zu JARVIS gehoeren.")


def choose_project(argv):
    if len(argv) > 1:
        p = Path(argv[1]).expanduser().resolve()
        if not p.is_dir():
            die("Ordner nicht gefunden: %s" % p)
        if too_broad(p):
            die(TOO_BROAD_MSG)
        return p

    head("Schritt 1/6: JARVIS-Projektordner suchen (nur lesen)")
    running, notes = running_jarvis_dirs()
    candidates = []
    for d in list(running.keys()) + search_jarvis_dirs():
        if d in candidates or not Path(d).is_dir():
            continue
        if too_broad(d):
            notes.append("Uebersprungen, weil zu allgemein: %s" % d)
            continue
        candidates.append(d)
    for n in sorted(set(notes)):
        say("Hinweis: " + n)
    if not candidates:
        say("Kein Ordner mit 'jarvis' im Namen gefunden.")
    for i, d in enumerate(candidates, 1):
        hint = running.get(d, "Ordnername enthaelt 'jarvis'")
        say("  [%d] %s\n      %s, %d Python-Dateien" % (i, d, hint, count_py(d)))
    say()
    say("Der laufende JARVIS ist meist der Eintrag mit 'laufender Prozess' oder 'systemd-Dienst'.")
    say("Achtung: Ist das ein Unterordner (z.B. .../jarvis/src), waehle lieber den Hauptordner")
    say("des Projekts, also den Ordner, in dem auch README, requirements.txt usw. liegen.")
    empties = 0
    while True:
        a = ask("Nummer eingeben ODER den vollstaendigen Pfad eintippen: ")
        if a.isdigit() and 1 <= int(a) <= len(candidates):
            p = Path(candidates[int(a) - 1])
        elif a:
            p = Path(a).expanduser()
        else:
            empties += 1
            if empties >= 5:
                die("Keine Eingabe moeglich. Bitte das Skript mit dem Ordner als "
                    "Argument starten, z.B.:  python3 jarvis_export.py /opt/maaker")
            continue
        empties = 0
        if not p.is_dir():
            say("Diesen Ordner gibt es nicht. Bitte nochmal.")
        elif too_broad(p):
            say(TOO_BROAD_MSG + " Bitte den JARVIS-Ordner darin waehlen.")
        else:
            return p.resolve()


# --------------------------------------------------------------------------
# Schritt 2: Backup (vollstaendig, bleibt auf dem Server)
# --------------------------------------------------------------------------

def git_state(project):
    info = []
    if not (project / ".git").exists() or shutil.which("git") is None:
        return info, False
    def g(*a):
        return run(PROJECT_GIT + ["-C", str(project)] + list(a),
                   env=PROJECT_GIT_ENV, check=False).stdout.strip()
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


def git_states(project, max_depth=3):
    """Git-Zustand des Hauptordners und aller Git-Repositories darunter."""
    lines = []
    base = len(project.parts)
    for dirpath, dirnames, _ in os.walk(str(project)):
        dp = Path(dirpath)
        if (dp / ".git").exists():
            info, _ = git_state(dp)
            where = dp.relative_to(project).as_posix()
            where = "Hauptordner" if where == "." else "`%s/`" % where
            lines += ["%s: %s" % (where, i) for i in info]
        if len(dp.parts) - base >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if low(d) not in SKIP_DIRS
                           and not matches_any(d, SKIP_DIR_GLOBS) and not is_venv(dp / d)]
    return lines


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
    # Platz fuer das Backup plus spaetere bereinigte Kopie plus Spielraum.
    if free < size * 2.2 + 300 * 1024 * 1024:
        die("Zu wenig freier Speicher fuer Backup und bereinigte Kopie. "
            "Bitte Speicher freiraeumen und erneut starten.")

    tmpdir = Path(tempfile.mkdtemp(prefix="jarvis-sqlite-"))
    count = 0
    added = 0

    try:
        with tarfile.open(str(target), "w:gz") as tar:
            for dirpath, dirnames, filenames in os.walk(str(project)):
                dp = Path(dirpath)
                dirnames[:] = [d for d in dirnames
                               if low(d) not in BACKUP_SKIP_DIRS and not is_venv(dp / d)]
                for f in sorted(filenames):
                    src = dp / f
                    arc = str(Path(project.name) / src.relative_to(project))
                    try:
                        # Nur regulaere Dateien: Sockets/Pipes/Geraete wuerden
                        # beim Lesen haengen bleiben.
                        if src.is_symlink():
                            tar.add(str(src), arcname=arc, recursive=False)
                            continue
                        st = src.stat()
                        if not stat_module.S_ISREG(st.st_mode):
                            continue
                        count += 1
                        if is_sqlite(src):
                            # Kopie zuerst, dann als .backup sichern -> keine Sperre,
                            # keine -wal/-shm-Dateien im Projekt, Sonderzeichen egal.
                            snap = tmpdir / ("%d.sqlite" % count)
                            try:
                                shutil.copy2(str(src), str(snap))
                                s = sqlite3.connect(str(snap))
                                dbk = tmpdir / ("%d.bak" % count)
                                d = sqlite3.connect(str(dbk))
                                s.backup(d)
                                d.close()
                                s.close()
                                tar.add(str(dbk), arcname=arc)
                                snap.unlink(missing_ok=True)
                                dbk.unlink(missing_ok=True)
                            except (OSError, sqlite3.Error):
                                tar.add(str(src), arcname=arc, recursive=False)
                        else:
                            tar.add(str(src), arcname=arc, recursive=False)
                        added += 1
                    except OSError as e:
                        say("  Hinweis: konnte %s nicht sichern (%s)" % (arc, type(e).__name__))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)
    try:
        os.chmod(str(target), 0o600)
    except OSError:
        pass
    # Pruefen, ob das Archiv vollstaendig lesbar ist (nicht abgeschnitten).
    try:
        with tarfile.open(str(target), "r:gz") as tar:
            n = sum(1 for _ in tar)
    except tarfile.TarError:
        die("Backup-Archiv ist beschaedigt. Bitte erneut starten.")
    missed = count - added
    if n < added:
        die("Backup unvollstaendig (%d von %d Dateien im Archiv)." % (n, added))
    say("Backup fertig und geprueft: %s (%s, %d Dateien%s)"
        % (target, human(target.stat().st_size), n,
           ", %d uebersprungen" % missed if missed else ""))
    say("Es enthaelt alle regulaeren Dateien inkl. .env, Datenbanken und Git-"
        "Historie und bleibt nur auf diesem Server.")
    return target


# --------------------------------------------------------------------------
# Schritt 3+4: bereinigte Kopie erstellen und auf Geheimnisse pruefen
# --------------------------------------------------------------------------

def build_staging(project, staging, title):
    head(title)
    staging.mkdir(parents=True, mode=0o700)
    res = {
        "staging": staging, "stats": {}, "env_keys": {}, "db_schemas": {},
        "big": [], "skipped_dirs": [], "skipped_files": [], "data_skips": {},
        "copied": 0,
    }
    stats = res["stats"]

    def skip(reason):
        stats[reason] = stats.get(reason, 0) + 1

    def note_dir(rel, reason):
        skip(reason)
        if len(rel.parts) <= 4:
            res["skipped_dirs"].append((rel.as_posix(), reason))

    # Fuer jeden Ordner: das naechstgelegene Git-Repository und dessen
    # erlaubte Dateien (alles, was das Projekt selbst per .gitignore ausschliesst,
    # bleibt draussen).
    git_scope = {}
    for dirpath, dirnames, filenames in os.walk(str(project)):
        dp = Path(dirpath)
        rel_dir = dp.relative_to(project)
        scope = git_scope.get(str(dp.parent)) if dp != project else None
        if (dp / ".git").exists():
            allowed = git_allowed_files(dp)
            if allowed is not None:
                dirs_ok = set()
                for f in allowed:
                    parts = f.split("/")[:-1]
                    for i in range(1, len(parts) + 1):
                        dirs_ok.add("/".join(parts[:i]))
                scope = (dp, allowed, dirs_ok)
        git_scope[str(dp)] = scope

        keep_dirs = []
        for d in sorted(dirnames):
            sub = dp / d
            rel_sub = rel_dir / d
            if low(d) in SKIP_DIRS or matches_any(d, SKIP_DIR_GLOBS):
                note_dir(rel_sub, "Ordner (venv, Cache, Logs, Backups, Secrets, Sitzungen, Kontakte/Leads)")
            elif is_venv(sub) or sub.is_symlink():
                note_dir(rel_sub, "Ordner (venv, Cache, Logs, Backups, Secrets, Sitzungen, Kontakte/Leads)")
            elif owner_only(sub, is_dir=True):
                note_dir(rel_sub, "Ordner nur fuer den Besitzer lesbar (oft Geheimnisse)")
            elif scope and not (sub / ".git").exists() and \
                    sub.relative_to(scope[0]).as_posix() not in scope[2]:
                note_dir(rel_sub, "Vom Projekt selbst per .gitignore ausgeschlossen")
            else:
                keep_dirs.append(d)
        dirnames[:] = keep_dirs

        in_data_dir = any(low(p) in DATA_DIRS for p in rel_dir.parts)

        def note_file(rel, reason):
            if len(res["skipped_files"]) < 800:
                res["skipped_files"].append((rel.as_posix(), reason))

        for f in sorted(filenames):
            src = dp / f
            rel = rel_dir / f
            ext = src.suffix.lower()
            name = low(f)
            try:
                if src.is_symlink() or not src.is_file():
                    skip("Verknuepfungen/Sonderdateien (Socket, Pipe, Geraet)")
                    continue
            except OSError:
                continue
            # Vom Projekt selbst per .gitignore ausgeschlossen -> nicht hochladen.
            if scope and src.relative_to(scope[0]).as_posix() not in scope[1]:
                skip("Vom Projekt selbst per .gitignore ausgeschlossen")
                continue
            # SQLite-Datenbank (egal welche Endung): nur Tabellenstruktur.
            if is_sqlite(src):
                skip("Datenbanken (nur Tabellen-Struktur wird uebernommen)")
                res["db_schemas"][rel.as_posix()] = sqlite_schema(src)
                continue
            # .env: nur Variablennamen merken, Datei selbst nie hochladen.
            if not matches_any(f, KEEP_FILE_GLOBS) and (
                    name == ".env" or name.startswith(".env.") or name.endswith(".env")):
                skip(".env-Dateien (Passwoerter/API-Schluessel)")
                try:
                    keys = re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=",
                                      read_text_safe(src))
                    res["env_keys"][rel.as_posix()] = sorted(set(keys))
                except OSError:
                    pass
                continue
            # Schluessel, Sitzungen, Logs, Mails, Medien, Modelle, Archive, DBs.
            if matches_any(f, SKIP_FILE_GLOBS) and not matches_any(f, KEEP_FILE_GLOBS):
                skip("Schluessel, Zertifikate, Sitzungen, Logs, Mails, Medien, Modelle, Archive")
                continue
            # In Daten-/Chat-/Speicher-Ordnern nur echten Code uebernehmen.
            if in_data_dir and ext not in DATA_DIR_CODE_EXTS:
                skip("Daten-Dateien in Daten-/Speicher-/Chat-Ordnern (private Inhalte)")
                key = "/".join(rel_dir.parts[:2])
                res["data_skips"][key] = res["data_skips"].get(key, 0) + 1
                continue
            if owner_only(src):
                skip("Dateien nur fuer den Besitzer lesbar (oft Geheimnisse)")
                note_file(rel, "nur fuer Besitzer lesbar")
                continue
            # ALLOW-LIST: nur bekannte Text-/Code-Endungen oder bekannte Namen.
            if not (ext in UPLOAD_EXTS or name in KNOWN_NAMES):
                skip("Unbekannter Dateityp (zur Sicherheit nicht hochgeladen)")
                note_file(rel, "unbekannter Dateityp")
                continue
            try:
                size = src.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                res["big"].append("%s (%s)" % (rel.as_posix(), human(size)))
                skip("Sehr grosse Dateien (> 10 MB)")
                continue
            # Nur echte Textdateien: alles, was hochgeht, wird auch gescannt.
            if not is_text_file(src):
                skip("Nicht-Text-/Binaerdatei (zur Sicherheit nicht hochgeladen)")
                note_file(rel, "keine Textdatei")
                continue
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(src), str(dst))
            except OSError:
                skip("Waehrend des Kopierens verschwunden/nicht lesbar")
                continue
            res["copied"] += 1
    say("Uebernommen: %d Dateien" % res["copied"])
    for k, v in sorted(stats.items()):
        say("  ausgelassen: %5d  %s" % (v, k))
    return res


def text_files(root):
    """Alle Textdateien (unabhaengig von der Endung), Binaerdateien nicht."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue
        yield path, raw.decode("utf-8", "replace")


def scan_and_redact(staging, title, strict=True):
    head(title)
    report = []
    for path, text in list(text_files(staging)):
        rel = path.relative_to(staging).as_posix()
        if PRIVATE_KEY_RE.search(text):
            path.unlink()
            report.append((rel, 0, "Privater Schluessel -> Datei entfernt"))
            continue
        new, findings = redact_text(text, path.suffix.lower())
        if findings:
            path.write_text(new, encoding="utf-8")
            for line, kind in findings:
                report.append((rel, line, kind))
    # Zweiter Durchgang: es darf nichts Eindeutiges mehr uebrig sein.
    leftovers = []
    for path, text in text_files(staging):
        hits = strong_hits(text)
        if hits:
            leftovers.append("%s (%s)" % (path.relative_to(staging).as_posix(), ", ".join(hits)))
    if leftovers and strict:
        die("Nach der Bereinigung wurden noch Geheimnisse gefunden:\n  " + "\n  ".join(leftovers))
    if report:
        say("Gefunden und in der Kopie durch '%s' ersetzt (Werte werden nicht angezeigt):" % REDACTED)
        for rel, line, kind in report[:40]:
            say("  %s:%s  %s" % (rel, line, kind))
        if len(report) > 40:
            say("  ... und %d weitere (siehe Bericht)" % (len(report) - 40))
        say("Die Originaldateien auf dem Server bleiben unveraendert.")
    else:
        say("Keine Geheimnisse im Code gefunden.")
    return report, leftovers


def system_overview():
    """Dienste, Zeitplaene und Prozesse (nur lesend, Zugangsdaten maskiert)."""
    lines = []
    if not sys.platform.startswith("linux"):
        return lines
    unit_files = []
    for d in (Path("/etc/systemd/system"), HOME / ".config/systemd/user"):
        if d.is_dir():
            unit_files += [u for u in sorted(d.glob("*.service")) if not u.is_symlink()]
    if Path("/lib/systemd/system").is_dir():
        unit_files += [u for u in sorted(Path("/lib/systemd/system").glob("*.service"))
                       if any(k in u.name.lower() for k in PROCESS_KEYWORDS)]
    for unit in unit_files:
        try:
            txt = unit.read_text(errors="replace")
        except OSError:
            continue
        keep = [ln.strip() for ln in txt.splitlines()
                if re.match(r"\s*(Description|WorkingDirectory|ExecStart|User)=", ln)]
        lines.append("Dienst `%s`: %s" % (unit, " | ".join(mask(k)[:220] for k in keep)))
    cron_dir = Path("/var/spool/cron/crontabs")
    if cron_dir.is_dir():
        for tab in sorted(cron_dir.iterdir()):
            try:
                for ln in tab.read_text(errors="replace").splitlines():
                    if ln.strip() and not ln.lstrip().startswith("#"):
                        lines.append("Zeitplan (%s): %s" % (tab.name, mask(ln.strip())[:200]))
            except OSError:
                continue
    try:
        import pwd
    except ImportError:
        pwd = None
    for pid in sorted((p for p in os.listdir("/proc") if p.isdigit()), key=int):
        try:
            comm = Path("/proc", pid, "comm").read_bytes().decode("utf-8", "replace").strip()
            cmd = Path("/proc", pid, "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace").lower()
            is_claude = bool(re.fullmatch(r"\d+\.\d+\.\d+", comm))
            interesting = comm in {"python", "python3", "node", "bun", "deno", "server",
                                   "uvicorn", "gunicorn", "whatsapp-bridge", "caddy", "go"}
            if not (is_claude or interesting or any(k in cmd for k in PROCESS_KEYWORDS)):
                continue
            if "jarvis_export" in cmd:
                continue
            uid = os.stat("/proc/%s" % pid).st_uid
            user = pwd.getpwuid(uid).pw_name if pwd else str(uid)
            cwd = os.readlink("/proc/%s/cwd" % pid)
            label = "Claude Code" if is_claude else comm
            # Nur Programmname, Benutzer und Ordner. KEINE Befehlszeilen-Argumente
            # (koennten private Prompts/Nachrichten enthalten).
            lines.append("Prozess %s (%s, Benutzer %s): Ordner `%s`"
                         % (pid, label, user, cwd))
        except (OSError, KeyError):
            continue
    return lines


def report_sections(project, res, redactions, leftovers, git_info, overview):
    lines = ["Original-Ordner auf dem Server: `%s`" % project, "",
             "## Dienste, Zeitplaene und Prozesse auf dem Server", ""]
    lines += ["- " + o for o in overview] or ["- (keine Angaben)"]
    lines += ["", "## Git-Zustand auf dem Server", ""]
    lines += ["- " + i for i in git_info] or ["- Kein Git-Repository gefunden."]
    lines += ["", "## Ausgelassen (Anzahl)", ""]
    lines += ["- %d x %s" % (v, k) for k, v in sorted(res["stats"].items())] or ["- nichts"]
    lines += ["", "## Ausgelassene Ordner (nur Namen)", ""]
    lines += ["- `%s/` - %s" % d for d in res["skipped_dirs"]] or ["- keine"]
    lines += ["", "## Ausgelassene Einzeldateien", ""]
    lines += ["- `%s` - %s" % f for f in res["skipped_files"]]
    lines += ["- `%s` - groesser als 10 MB" % b for b in res["big"]]
    if not res["skipped_files"] and not res["big"]:
        lines.append("- keine")
    lines += ["", "## Daten-Ordner: nicht uebernommene Dateien (Anzahl je Ordner)", ""]
    lines += ["- `%s/`: %d" % kv for kv in sorted(res["data_skips"].items())] or ["- keine"]
    lines += ["", "## Ersetzte Geheimnisse (`%s`)" % REDACTED, ""]
    lines += ["- `%s`:%s %s" % r for r in redactions] or ["- keine"]
    if leftovers:
        lines += ["", "## ACHTUNG: noch gefundene Geheimnisse (Werte nicht gezeigt)", ""]
        lines += ["- " + x for x in leftovers]
    lines += ["", "## Umgebungsvariablen aus .env-Dateien (nur Namen, keine Werte)", ""]
    if res["env_keys"]:
        for f, keys in sorted(res["env_keys"].items()):
            lines.append("- `%s`: %s" % (f, ", ".join("`%s`" % k for k in keys) or "(leer)"))
    else:
        lines.append("- keine .env-Dateien gefunden")
    lines += ["", "## Datenbanken (nur Struktur, keine Inhalte)", ""]
    lines += ["- `%s`" % f for f in sorted(res["db_schemas"])] or ["- keine SQLite-Datenbanken gefunden"]
    return lines


def write_reports(project, res, redactions, leftovers, git_info, overview):
    staging = res["staging"]
    lines = [
        "# Import-Bericht (Server -> GitHub)",
        "",
        "Erstellt am %s mit tools/jarvis-export/jarvis_export.py." % time.strftime("%Y-%m-%d %H:%M"),
        "",
        "Der Code ist ein bereinigter Schnappschuss. Die alte Git-Historie wurde",
        "bewusst NICHT uebernommen (Schutz vor alten Geheimnissen); sie liegt im",
        "Server-Backup unter ~/jarvis-backups/.",
        "",
    ] + report_sections(project, res, redactions, leftovers, git_info, overview)
    (staging / "IMPORT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if res["db_schemas"]:
        d = staging / "IMPORT_DB_SCHEMA"
        d.mkdir(exist_ok=True)
        for f, schema in res["db_schemas"].items():
            name = re.sub(r"[^A-Za-z0-9_.-]+", "__", f) + ".sql"
            (d / name).write_text(schema, encoding="utf-8")

    if res["env_keys"]:
        out = ["# Automatisch erzeugt: Namen der Variablen aus den .env-Dateien des Servers.",
               "# Werte stehen NICHT im Repository. Echte Werte nur auf dem Server/Secret-Store.", ""]
        for f, keys in sorted(res["env_keys"].items()):
            out.append("# aus %s" % f)
            out += ["%s=" % k for k in keys]
            out.append("")
        (staging / ".env.example.import").write_text("\n".join(out), encoding="utf-8")

    gi = staging / ".gitignore"
    existing = gi.read_text(errors="replace") if gi.exists() else ""
    extra = [
        "", "# --- ergaenzt beim Server-Import (Schutz vor Geheimnissen) ---",
        ".env", ".env.*", "!.env.example", "!.env.example.import", "*.pem", "*.key",
        "*.db", "*.sqlite", "*.sqlite3", "*.log", "*.jsonl", "logs/", "backups/", "secrets/",
        "__pycache__/", ".venv/", "venv/", "node_modules/", "credentials*.json",
        "token*.json", "client_secret*.json", "settings.local.json", "leads/",
    ]
    gi.write_text(existing.rstrip("\n") + "\n" + "\n".join(extra) + "\n", encoding="utf-8")


def tree_lines(root, max_depth=3):
    """Ordneruebersicht: Anzahl Dateien und haeufigste Endungen je Ordner."""
    info = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts[:-1]
        ext = path.suffix.lower() or "(ohne)"
        for depth in range(0, min(len(parts), max_depth) + 1):
            key = "/".join(parts[:depth]) or "."
            n, exts = info.setdefault(key, [0, {}])
            info[key][0] = n + 1
            exts[ext] = exts.get(ext, 0) + 1
    out = []
    for key in sorted(info):
        n, exts = info[key]
        top = sorted(exts.items(), key=lambda kv: -kv[1])[:4]
        out.append("- `%s/` %d Dateien (%s)" % (key, n, ", ".join("%s:%d" % kv for kv in top)))
    return out


# --------------------------------------------------------------------------
# Schritt 5+6: Zugang einrichten und hochladen
# --------------------------------------------------------------------------

def check_push_error(out):
    low_out = (out or "").lower()
    if "denied" in low_out or "not authorized" in low_out or "read-only" in low_out \
            or "permission" in low_out or "403" in low_out:
        die("GitHub hat das Hochladen abgelehnt. Sehr wahrscheinlich wurde der "
            "Deploy Key OHNE 'Allow write access' hinzugefuegt.\n"
            "Bitte den Schluessel unter %s loeschen und neu hinzufuegen, diesmal "
            "MIT Haken bei 'Allow write access'. Danach das Skript erneut starten.\n"
            "Details: %s" % (DEPLOY_KEY_URL, (out or "").strip()[-400:]))
    die("Hochladen fehlgeschlagen:\n" + (out or "").strip()[-600:])


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
    remote = run(["git", "ls-remote", "--heads", REMOTE_URL, "refs/heads/main"], env=env, check=False)
    if remote.returncode != 0:
        die("Repository nicht erreichbar:\n" + remote.stdout[-500:])
    branch = "main"
    if remote.stdout.strip():
        branch = "server-import-" + STAMP
        say("Im Repository gibt es schon einen Stand. Es wird NICHTS ueberschrieben;")
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
    if len(files) > 3000:
        say("ACHTUNG: Das sind ungewoehnlich viele Dateien. Pruefe, ob wirklich nur der")
        say("JARVIS-Ordner gewaehlt wurde. Im Zweifel 'nein' eingeben und mir die Liste schicken.")
    say("Vorschau (die ersten 40):")
    for f in files[:40]:
        say("  " + f)
    say("Die vollstaendige Liste steht in: %s" % (staging / "IMPORT_REPORT.md"))
    if not is_local_test and not ask_yes("Jetzt in das PRIVATE Repository %s hochladen?" % GITHUB_REPO):
        die("Vom Benutzer abgebrochen.")
    g("commit", "-q", "-m", "Import: JARVIS-Stand vom Server (bereinigt, ohne Secrets und Daten)")
    local_head = g("rev-parse", "HEAD").stdout.strip()
    # Kein Force-Push.
    r = run(["git", "push", REMOTE_URL, "HEAD:refs/heads/" + branch], cwd=str(staging),
            env=env, check=False)
    if r.returncode != 0:
        check_push_error(r.stdout)
    check = run(["git", "ls-remote", REMOTE_URL, "refs/heads/" + branch], env=env).stdout.split()
    if not check or check[0] != local_head:
        die("Upload konnte nicht bestaetigt werden.")
    say("Upload bestaetigt: Branch '%s', Commit %s" % (branch, local_head[:10]))
    return branch, local_head


def push_probe_report(report_text, env):
    head("Probe 3/3: Bericht hochladen")
    say("Der Bericht enthaelt NUR Ordner-/Dateinamen, Anzahlen und Dienst-Namen,")
    say("keine Dateiinhalte und keine Passwoerter.")
    if "JARVIS_EXPORT_REMOTE" not in os.environ and \
            not ask_yes("Bericht in das PRIVATE Repository %s hochladen?" % GITHUB_REPO):
        die("Vom Benutzer abgebrochen.")
    d = WORK / ("probe-report-" + STAMP)
    d.mkdir(parents=True, mode=0o700)
    branch = "probe-report-" + STAMP
    try:
        (d / "PROBE_REPORT.md").write_text(report_text, encoding="utf-8")

        def g(*a):
            return run(["git"] + list(a), cwd=str(d), env=env)

        g("init", "-q")
        g("symbolic-ref", "HEAD", "refs/heads/" + branch)
        g("config", "user.name", "JARVIS Server Import")
        g("config", "user.email", "jarvis-server-import@localhost")
        g("add", "-A")
        g("commit", "-q", "-m", "Probelauf-Bericht (nur Namen und Zahlen, keine Inhalte)")
        local_head = g("rev-parse", "HEAD").stdout.strip()
        # Neuer Branch, kein Force-Push, nichts wird ueberschrieben.
        r = run(["git", "push", REMOTE_URL, "HEAD:refs/heads/" + branch], cwd=str(d),
                env=env, check=False)
        if r.returncode != 0:
            check_push_error(r.stdout)
        check = run(["git", "ls-remote", REMOTE_URL, "refs/heads/" + branch], env=env).stdout.split()
        if not check or check[0] != local_head:
            die("Upload des Berichts konnte nicht bestaetigt werden.")
    finally:
        shutil.rmtree(str(d), ignore_errors=True)
    say("Bericht hochgeladen (Branch '%s')." % branch)
    return branch


def probe(project):
    head("PROBELAUF: Es wird nichts gesichert, nichts veraendert und kein Code hochgeladen")
    overview = system_overview()
    for o in overview:
        say("  " + o)
    git_info = git_states(project)
    for i in git_info:
        say("  " + i)
    staging = WORK / ("probe-" + STAMP)
    try:
        res = build_staging(project, staging, "Probe 1/3: Was wuerde uebernommen?")
        redactions, leftovers = scan_and_redact(staging, "Probe 2/3: Geheimnis-Pruefung", strict=False)
        files = sorted(p for p in staging.rglob("*") if p.is_file())
        size = sum(p.stat().st_size for p in files)
        names = [p.relative_to(staging).as_posix() for p in files]
        n_files = len(names)
        lines = [
            "# Probelauf-Bericht",
            "",
            "Erstellt am %s mit tools/jarvis-export/jarvis_export.py --probe." % time.strftime("%Y-%m-%d %H:%M"),
            "Dieser Bericht enthaelt nur Namen und Zahlen. Es wurde kein Code hochgeladen.",
            "",
        ] + report_sections(project, res, redactions, leftovers, git_info, overview)
        lines += ["", "## Ordneruebersicht der geplanten Kopie", ""] + tree_lines(staging)
        lines += ["", "## Alle Dateien, die hochgeladen wuerden (%d Dateien, %s)" % (n_files, human(size)), ""]
        lines += ["- `%s`" % n for n in names[:8000]]
        if n_files > 8000:
            lines.append("- ... und %d weitere" % (n_files - 8000))
    finally:
        shutil.rmtree(str(staging), ignore_errors=True)
    # Auch den Bericht selbst bereinigen (z.B. Token in einer git-Remote-URL).
    report_text, _ = redact_text("\n".join(lines) + "\n", ".md")
    say()
    say("Ergebnis: %d Dateien (%s) wuerden hochgeladen, %d Geheimnisse wuerden ersetzt."
        % (n_files, human(size), len(redactions)))
    if leftovers:
        say("ACHTUNG: %d Datei(en) mit moeglichen Geheimnissen - bitte Bericht pruefen." % len(leftovers))
    env = dict(os.environ)
    if "JARVIS_EXPORT_REMOTE" not in os.environ:
        env = setup_deploy_key()
    branch = push_probe_report(report_text, env)
    head("PROBELAUF FERTIG")
    say("Es wurde nur der Bericht hochgeladen (Branch '%s')." % branch)
    say("Dein laufender JARVIS ist unveraendert.")
    say()
    say("Schreibe Claude jetzt einfach:  'Probelauf fertig'.")


def main():
    args = sys.argv[1:]
    flags = [a for a in args if a.startswith("-")]
    paths = [a for a in args if not a.startswith("-")]
    unknown = [f for f in flags if f != "--probe"]
    if unknown:
        die("Unbekannte Option(en): %s. Erlaubt ist nur --probe." % " ".join(unknown))
    if len(paths) > 1:
        die("Bitte nur EINEN Ordner angeben, nicht mehrere: %s" % " ".join(paths))
    say("JARVIS-Export nach GitHub (%s)" % GITHUB_REPO)
    say("Dein laufender JARVIS wird dabei NICHT veraendert oder neu gestartet.")
    if sys.version_info < (3, 8):
        die("Python 3.8 oder neuer wird benoetigt (gefunden: %s)."
            % ".".join(map(str, sys.version_info[:3])))
    project = choose_project([sys.argv[0]] + paths)
    say("Gewaehlter Ordner: %s" % project)
    if "--probe" in flags:
        probe(project)
        return
    overview = system_overview()
    git_info = git_states(project)
    for i in git_info:
        say("  " + i)
    backup = make_backup(project)
    staging = WORK / ("upload-" + STAMP)
    try:
        res = build_staging(project, staging, "Schritt 3/6: Bereinigte Upload-Kopie erstellen")
        redactions, leftovers = scan_and_redact(
            staging, "Schritt 4/6: Upload-Kopie auf Geheimnisse pruefen und bereinigen",
            strict=False)
        write_reports(project, res, redactions, leftovers, git_info, overview)
        # Abschlusspruefung ueber ALLES (auch Bericht, Schema, .env.example):
        # redigiert erneut und bricht ab, falls noch ein Geheimnis uebrig ist.
        scan_and_redact(staging, "Schritt 4b/6: Abschlusspruefung (inkl. Bericht)",
                        strict=True)
        env = dict(os.environ)
        if "JARVIS_EXPORT_REMOTE" not in os.environ:
            env = setup_deploy_key()
        branch, commit = push(staging, env)
    finally:
        shutil.rmtree(str(staging), ignore_errors=True)
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
