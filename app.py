# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MAINTIX — Suite de gestion de maintenance industrielle                      ║
║  Streamlit · Pandas · Matplotlib                                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Lancement :   streamlit run app.py                                          ║
║                                                                              ║
║  Organisation du fichier                                                     ║
║   1. Configuration & constantes                                              ║
║   2. Utilitaires (formats, icônes, HTML, CSS)                                ║
║   3. Couche DONNÉES  : lecture / écriture CSV sécurisée, sauvegardes         ║
║   4. Nettoyage       : normalisation, doublons, valeurs manquantes           ║
║   5. Authentification: comptes uniques, mots de passe hachés, rôles          ║
║   6. KPI & graphiques (Matplotlib)                                           ║
║   7. Pages           : Connexion, Dashboard, Saisie, Administration, Guide   ║
║   8. Point d'entrée  : main()                                                ║
║   9. Icônes embarquées (base64) : aucun dossier externe nécessaire           ║
║                                                                              ║
║  MISE À JOUR AUTOMATIQUE (résumé — détail dans la page « Guide ») :          ║
║   saisie → écriture atomique dans dataset_maintenance.csv                    ║
║          → l'empreinte du fichier (date de modif. + taille) change           ║
║          → le cache pandas (st.cache_data) est invalidé automatiquement      ║
║          → KPI + graphiques sont recalculés au rerun                         ║
║          → les autres sessions ouvertes détectent le changement (fragment    ║
║            qui surveille le fichier toutes les 10 s) et se rafraîchissent.   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
import warnings
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # rendu sans interface graphique (serveur)
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

# ══════════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
APP_NAME = "MAINTIX"
APP_TAGLINE = "Piloter · Anticiper · Optimiser"
APP_VERSION = "1.0"

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "dataset_maintenance.csv"   # ← source de vérité des données
USERS_FILE = BASE_DIR / "users.json"               # ← comptes (créé automatiquement)
BACKUP_DIR = BASE_DIR / "backups"                  # ← sauvegardes automatiques du CSV
ICON_DIR = BASE_DIR / "icones"

# Code à fournir pour créer un compte soi-même. Chaîne vide = inscription libre.
# Recommandé : le définir via une variable d'environnement (MAINTIX_INVITE_CODE).
INVITE_CODE = os.getenv("MAINTIX_INVITE_CODE", "MAINTIX-2026")
# Compte administrateur créé au tout premier lancement (à changer immédiatement).
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = os.getenv("MAINTIX_ADMIN_PASSWORD", "Admin@2026")

PBKDF2_ITERATIONS = 200_000
MAX_FAILED_LOGINS = 5
LOCK_SECONDS = 300
LIVE_REFRESH_SECONDS = 10
MAX_BACKUPS = 30

# Colonnes du fichier de données
C_ID, C_DATE, C_MACH = "ID", "Date", "Machine"
C_TYPE, C_EQ = "Type_Maintenance", "Equipement"
C_DUR, C_COST = "Duree_Maintenance_h", "Cout_Maintenance_MAD"
C_TECH, C_PART, C_STAT = "Technicien", "Piece_Remplacee", "Statut"
C_BY, C_AT = "Saisi_Par", "Date_Saisie"
COLUMNS = [C_ID, C_DATE, C_MACH, C_TYPE, C_EQ, C_DUR, C_COST, C_TECH, C_PART, C_STAT, C_BY, C_AT]
BUSINESS_COLS = [C_DATE, C_MACH, C_TYPE, C_EQ, C_DUR, C_COST, C_TECH, C_PART, C_STAT]
TEXT_COLS = [C_MACH, C_TYPE, C_EQ, C_TECH, C_PART, C_STAT]

TYPES = ["Préventive", "Corrective", "Prédictive"]
EQUIPEMENTS = ["Compresseur", "Convoyeur", "Moteur", "Pompe", "Presse", "Robot"]
PIECES = ["Aucune", "Capteur", "Courroie", "Filtre", "Joint", "Roulement"]
STATUTS = ["Planifiée", "En cours", "Terminée"]
NA_TECH, NA_PART, NA_STAT = "Non assigné", "Non renseignée", "Non renseigné"

ROLES = ["admin", "technicien", "lecteur"]
ROLE_LABELS = {"admin": "Administrateur", "technicien": "Technicien", "lecteur": "Lecteur"}

# Charte graphique
INK = "#0F2540"
NAVY = "#0B3C5D"
BLUE = "#1F4E79"
TEAL = "#2BB3B1"
AMBER = "#F5A623"
RED = "#E4572E"
GREY = "#8FA3BF"
TYPE_COLORS = {"Préventive": TEAL, "Corrective": RED, "Prédictive": BLUE}
STATUS_COLORS = {"Terminée": TEAL, "En cours": AMBER, "Planifiée": GREY}
MOIS = ["Janv", "Févr", "Mars", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"]

# Icônes fournies (dossier icones/)
ICONS = {
    "logo": "performance.png",
    "dash": "surveiller.png",
    "interv": "gestion-de-projet.png",
    "cout": "efficacite.png",
    "duree": "efficacite (1).png",
    "taux": "presse-papiers.png",
    "machine": "controle.png",
    "tech": "hrm.png",
    "piece": "paquet.png",
}
# Nouvelles icônes (icones2), uniquement embarquées : add_user, present, kpi, analysis, monitor,
# chart, user_cfg, filters, gears, support, donnees

# st.button / st.dataframe… : « width="stretch" » (récent) ou « use_container_width » (ancien)
try:
    _v = tuple(int(x) for x in st.__version__.split(".")[:2])
except Exception:  # pragma: no cover
    _v = (1, 50)
STRETCH = {"width": "stretch"} if _v >= (1, 50) else {"use_container_width": True}


# ══════════════════════════════════════════════════════════════════════════════
# 2. UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════
def fmt_int(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{int(round(x)):,}".replace(",", "\u202f")


def fmt_dec(x, n: int = 1) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{n}f}".replace(",", "\u202f").replace(".", ",")


def fmt_mad(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{fmt_int(x)} MAD"


def fmt_mad_compact(x) -> str:
    """4 036 800 → « 4,04 M MAD » (tient sur une ligne dans une carte KPI)."""
    if x is None or pd.isna(x):
        return "—"
    if abs(x) >= 1e6:
        return f"{fmt_dec(x / 1e6, 2)} M MAD"
    if abs(x) >= 1e4:
        return f"{fmt_dec(x / 1e3, 1)} k MAD"
    return fmt_mad(x)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def norm_key(s) -> str:
    return strip_accents(s).strip().lower()


def ui_html(s: str) -> None:
    """Affiche du HTML : supprime indentations et lignes vides (sinon Markdown le casse)."""
    s = "\n".join(line.strip() for line in s.strip().splitlines() if line.strip())
    st.markdown(s, unsafe_allow_html=True)


def icon_b64(key: str, size: int = 96) -> str:
    """Icône en base64 : d'abord les icônes EMBARQUÉES (section 9), sinon le dossier icones/."""
    data = ICON_DATA.get(key, "")
    if data:
        return data
    try:
        img = Image.open(ICON_DIR / ICONS[key]).convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def icon_img(key: str, size: int = 44, extra_style: str = "") -> str:
    b = icon_b64(key)
    if not b:
        return f'<span style="font-size:{size * 0.7}px">⚙️</span>'
    return f'<img src="data:image/png;base64,{b}" width="{size}" height="{size}" style="object-fit:contain;{extra_style}">'


def page_icon():
    try:
        return Image.open(io.BytesIO(base64.b64decode(ICON_DATA["logo"])))
    except Exception:
        return "🛠️"


def ensure_theme_config() -> None:
    """Crée .streamlit/config.toml (thème clair) s'il n'existe pas — effet au prochain démarrage."""
    cfg = BASE_DIR / ".streamlit" / "config.toml"
    if cfg.exists():
        return
    try:
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(
            '[theme]\nbase = "light"\nprimaryColor = "#0B6E99"\nbackgroundColor = "#FFFFFF"\n'
            'secondaryBackgroundColor = "#F1F5F9"\ntextColor = "#0F2540"\n\n'
            '[browser]\ngatherUsageStats = false\n',
            encoding="utf-8",
        )
    except OSError:
        pass


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
.block-container { padding-top: 1.3rem; padding-bottom: 3rem; max-width: 1480px; }
footer, .stDeployButton { visibility: hidden; }
h1, h2, h3 { color: #0F2540; letter-spacing: -0.01em; }

/* Sidebar */
section[data-testid="stSidebar"] { border-right: 1px solid #E2E8F0; }
.brand { display:flex; align-items:center; gap:12px; padding:14px 14px; border-radius:16px;
  background: linear-gradient(135deg,#0B3C5D 0%,#1F4E79 60%,#2BB3B1 140%); color:#fff; margin-bottom:12px;
  box-shadow: 0 6px 18px rgba(11,60,93,.25); }
.brand img { background:#fff; border-radius:12px; padding:5px; }
.brand-name { font-weight:800; font-size:1.25rem; letter-spacing:.08em; line-height:1.1; }
.brand-sub { font-size:.72rem; opacity:.85; letter-spacing:.04em; }
.usercard { display:flex; align-items:center; gap:10px; padding:10px 12px; border:1px solid #E2E8F0;
  border-radius:14px; background:#fff; margin-bottom:10px; }
.avatar { width:38px; height:38px; border-radius:50%; background:#0B3C5D; color:#fff; display:flex;
  align-items:center; justify-content:center; font-weight:700; }
.uname { font-weight:600; font-size:.92rem; color:#0F2540; line-height:1.15; }
.badge { display:inline-block; font-size:.68rem; font-weight:600; padding:2px 8px; border-radius:99px;
  background:#E6F6F6; color:#0B7B79; margin-top:2px; }
.badge.admin { background:#FFF1D6; color:#9A6200; }
.badge.lecteur { background:#EEF2F7; color:#51627A; }
.sidebar-title { font-size:.72rem; text-transform:uppercase; letter-spacing:.1em; color:#64748B;
  font-weight:700; margin:14px 0 4px; }

/* En-tête de page */
.page-head { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:14px;
  padding:16px 20px; border-radius:18px; background:linear-gradient(120deg,#F1F7FC 0%,#FFFFFF 70%);
  border:1px solid #E2E8F0; }
.page-head .l { display:flex; align-items:center; gap:16px; }
.page-title { font-size:1.55rem; font-weight:800; color:#0F2540; line-height:1.15; }
.page-sub { color:#64748B; font-size:.9rem; margin-top:2px; }
.live { font-size:.78rem; color:#0B7B79; background:#E6F6F6; padding:6px 12px; border-radius:99px; font-weight:600;
  white-space:nowrap; }

/* KPI */
.kpi { display:flex; align-items:center; gap:14px; padding:16px 18px; border-radius:18px; background:#fff;
  border:1px solid #E2E8F0; box-shadow:0 2px 10px rgba(15,37,64,.05); height:100%; min-height:104px;
  border-left:5px solid var(--c,#1F4E79); }
.kpi-icon { flex:0 0 auto; width:54px; height:54px; display:flex; align-items:center; justify-content:center;
  background:#F4F8FC; border-radius:14px; }
.kpi-label { font-size:.74rem; color:#64748B; text-transform:uppercase; letter-spacing:.07em; font-weight:700; }
.kpi-value { font-size:1.6rem; font-weight:800; color:#0F2540; line-height:1.2; }
.kpi-sub { font-size:.78rem; color:#64748B; }
.delta { font-size:.76rem; font-weight:700; }
.delta.pos { color:#0B8A5B; } .delta.neg { color:#D6452B; } .delta.neu { color:#64748B; }

/* Titres de graphiques */
.chart-title { font-weight:700; color:#0F2540; font-size:1rem; margin-bottom:0; }
.chart-sub { color:#64748B; font-size:.8rem; margin-bottom:6px; }

/* Connexion */
.hero { background:linear-gradient(145deg,#0B3C5D 0%,#1F4E79 55%,#2BB3B1 150%); border-radius:26px; padding:40px 38px;
  color:#fff; min-height:560px; box-shadow:0 18px 40px rgba(11,60,93,.28); }
.hero-logo { display:flex; align-items:center; gap:16px; margin-bottom:26px; }
.hero-logo img { background:#fff; border-radius:20px; padding:9px; }
.hero-name { font-size:2.5rem; font-weight:800; letter-spacing:.1em; line-height:1; }
.hero-tag { font-size:.95rem; opacity:.9; letter-spacing:.14em; text-transform:uppercase; margin-top:6px; }
.hero h2 { color:#fff; font-size:1.55rem; font-weight:700; line-height:1.3; margin:10px 0 24px; }
.feat { display:flex; align-items:center; gap:14px; background:rgba(255,255,255,.12); border-radius:16px;
  padding:12px 16px; margin-bottom:12px; backdrop-filter: blur(4px); }
.feat img { background:#fff; border-radius:12px; padding:4px; }
.feat b { display:block; font-size:.98rem; } .feat span { font-size:.84rem; opacity:.88; }
.login-title { font-size:1.6rem; font-weight:800; color:#0F2540; margin-bottom:2px; }
.login-sub { color:#64748B; margin-bottom:10px; }
</style>
"""


# ══════════════════════════════════════════════════════════════════════════════
# 3. COUCHE DONNÉES (lecture / écriture CSV sécurisée)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def get_lock() -> threading.RLock:
    """Verrou partagé par TOUTES les sessions utilisateurs du serveur (une seule instance).
    Évite que deux saisies simultanées s'écrasent mutuellement."""
    return threading.RLock()


def data_token() -> tuple:
    """Empreinte du fichier de données = (date de modification, taille).
    C'est la CLÉ de la mise à jour automatique : dès que le CSV change (saisie dans
    l'app, import, ou édition manuelle dans Excel), l'empreinte change, donc le cache
    pandas est invalidé et tout est recalculé."""
    try:
        s = DATA_FILE.stat()
        return (s.st_mtime_ns, s.st_size)
    except FileNotFoundError:
        return (0, 0)


def ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les colonnes manquantes (ID, Saisi_Par, Date_Saisie) pour un CSV « historique »."""
    df = df.copy()
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    ids = pd.to_numeric(df[C_ID], errors="coerce")
    start = int(ids.max()) if ids.notna().any() else 0
    missing = ids.isna()
    ids.loc[missing] = np.arange(start + 1, start + 1 + missing.sum())
    df[C_ID] = ids.astype(int)
    df[C_BY] = df[C_BY].fillna("import_initial")
    df[C_AT] = df[C_AT].fillna("")
    return df[COLUMNS]


def read_raw() -> pd.DataFrame:
    """Lit le CSV tel quel (tout en texte). Aucun nettoyage ici."""
    if not DATA_FILE.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(DATA_FILE, encoding="utf-8-sig", dtype=str)
    return ensure_schema(df)


def write_raw(df: pd.DataFrame) -> None:
    """Écriture ATOMIQUE : on écrit un fichier temporaire puis on le renomme.
    Le CSV n'est donc jamais lu à moitié écrit par une autre session."""
    with get_lock():
        tmp = DATA_FILE.with_suffix(".tmp")
        df[COLUMNS].to_csv(tmp, index=False, encoding="utf-8-sig")
        try:
            os.replace(tmp, DATA_FILE)
        except PermissionError as e:  # fichier ouvert dans Excel (Windows)
            raise PermissionError(
                "Impossible d'écrire dans dataset_maintenance.csv : fermez le fichier s'il est ouvert dans Excel."
            ) from e


def backup_data(force: bool = False) -> Path | None:
    """Copie datée du CSV (1 par jour automatiquement ; sur demande avec force=True)."""
    if not DATA_FILE.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    if not force and any(BACKUP_DIR.glob(f"dataset_{today}_*.csv")):
        return None
    dest = BACKUP_DIR / f"dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    shutil.copy2(DATA_FILE, dest)
    for old in sorted(BACKUP_DIR.glob("dataset_*.csv"))[:-MAX_BACKUPS]:
        old.unlink(missing_ok=True)
    return dest


@st.cache_resource(show_spinner=False)
def init_storage() -> bool:
    """Au 1er lancement : crée/migre le CSV et crée le compte administrateur."""
    with get_lock():
        if not DATA_FILE.exists():
            write_raw(pd.DataFrame(columns=COLUMNS))
        else:
            head = pd.read_csv(DATA_FILE, encoding="utf-8-sig", dtype=str, nrows=0)
            if [c.strip() for c in head.columns] != COLUMNS:
                backup_data(force=True)
                write_raw(read_raw())
        if not USERS_FILE.exists():
            salt, h = new_credentials(DEFAULT_ADMIN_PASSWORD)
            _save_users({
                DEFAULT_ADMIN_USER: {
                    "name": "Administrateur", "role": "admin", "salt": salt, "hash": h, "active": True,
                    "tech_code": "", "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "failed": 0, "locked_until": 0, "default_pwd": True,
                }
            })
    return True


def _normalize_new_row(row: dict) -> dict:
    return {
        C_DATE: pd.Timestamp(row[C_DATE]).strftime("%Y-%m-%d"),
        C_MACH: str(row[C_MACH]).strip().upper(),
        C_TYPE: row[C_TYPE],
        C_EQ: row[C_EQ],
        C_DUR: round(float(row[C_DUR]), 1),
        C_COST: "" if row.get(C_COST) is None or pd.isna(row.get(C_COST)) else round(float(row[C_COST]), 2),
        C_TECH: row.get(C_TECH) or "",
        C_PART: row.get(C_PART) or "",
        C_STAT: row[C_STAT],
    }


def is_duplicate(row: dict, raw: pd.DataFrame) -> bool:
    """Même date + machine + type + équipement + technicien + durée = doublon probable."""
    if raw.empty:
        return False
    r = _normalize_new_row(row)
    m = (
        (raw[C_DATE].astype(str).str[:10] == r[C_DATE])
        & (raw[C_MACH].astype(str).str.upper() == r[C_MACH])
        & (raw[C_TYPE] == r[C_TYPE])
        & (raw[C_EQ] == r[C_EQ])
        & (raw[C_TECH].fillna("") == r[C_TECH])
        & ((pd.to_numeric(raw[C_DUR], errors="coerce") - r[C_DUR]).abs() < 1e-6)
    )
    return bool(m.any())


def append_rows(rows: list[dict], username: str) -> list[int]:
    """AJOUTE des interventions au CSV (verrou + sauvegarde quotidienne + écriture atomique)."""
    with get_lock():
        backup_data()
        raw = read_raw()
        ids = pd.to_numeric(raw[C_ID], errors="coerce")
        next_id = int(ids.max()) + 1 if ids.notna().any() else 1
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new, new_ids = [], []
        for i, row in enumerate(rows):
            r = _normalize_new_row(row)
            r.update({C_ID: next_id + i, C_BY: username, C_AT: stamp})
            new.append(r)
            new_ids.append(next_id + i)
        out = pd.concat([raw, pd.DataFrame(new)], ignore_index=True) if len(raw) else pd.DataFrame(new)
        write_raw(out)
    return new_ids


# ══════════════════════════════════════════════════════════════════════════════
# 4. NETTOYAGE DES DONNÉES
# ══════════════════════════════════════════════════════════════════════════════
def canon(series: pd.Series, allowed: list[str]) -> pd.Series:
    """Ramène « preventive », « PRÉVENTIVE »… à la forme canonique « Préventive »."""
    m = {norm_key(x): x for x in allowed}
    return series.map(lambda v: v if pd.isna(v) else m.get(norm_key(v), str(v).strip()))


def parse_dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    left = d.isna() & s.notna()
    if left.any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            d.loc[left] = pd.to_datetime(s[left], dayfirst=True, errors="coerce")
    return d


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalisation commune au nettoyage ET à l'import : espaces, casse, types."""
    df = df.copy()
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    for c in TEXT_COLS:
        s = df[c].astype("string").str.strip()
        s = s.mask(s.fillna("") == "")
        df[c] = s.astype(object).where(s.notna(), np.nan)
    df[C_MACH] = (
        df[C_MACH].str.upper().str.replace(r"\s+", "-", regex=True).str.replace(r"^([A-Z]+)(\d+)$", r"\1-\2", regex=True)
    )
    df[C_TECH] = df[C_TECH].str.upper()
    df[C_TYPE] = canon(df[C_TYPE], TYPES)
    df[C_EQ] = canon(df[C_EQ], EQUIPEMENTS)
    df[C_PART] = canon(df[C_PART], PIECES)
    df[C_STAT] = canon(df[C_STAT], STATUTS)
    sd = df[C_DATE].astype("string").str.strip()
    sd = sd.mask(sd.fillna("") == "")
    df[C_DATE] = parse_dates(sd.astype(object).where(sd.notna(), np.nan))
    for c in (C_DUR, C_COST):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def clean_data(raw: pd.DataFrame, impute: bool = True) -> tuple[pd.DataFrame, dict]:
    """Pipeline de nettoyage. Retourne (données propres, rapport de qualité)."""
    rep: dict = {"lignes_brutes": len(raw)}
    df = normalize_frame(raw)

    # 1) dates invalides et champs obligatoires → lignes écartées
    bad = df[C_DATE].isna() | df[C_MACH].isna() | df[C_TYPE].isna() | df[C_EQ].isna()
    rep["lignes_invalides"] = int(bad.sum())
    df = df[~bad]

    # 2) valeurs aberrantes impossibles (durée ≤ 0, valeurs négatives) → manquantes
    neg_dur, neg_cost = int((df[C_DUR] <= 0).sum()), int((df[C_COST] < 0).sum())
    df.loc[df[C_DUR] <= 0, C_DUR] = np.nan
    df.loc[df[C_COST] < 0, C_COST] = np.nan
    rep["valeurs_negatives"] = neg_dur + neg_cost

    # 3) doublons exacts
    dup = df.duplicated(subset=BUSINESS_COLS, keep="first")
    rep["doublons_supprimes"] = int(dup.sum())
    df = df[~dup]

    # 4) valeurs manquantes
    rep["cout_manquant"] = int(df[C_COST].isna().sum())
    rep["duree_manquante"] = int(df[C_DUR].isna().sum())
    rep["technicien_manquant"] = int(df[C_TECH].isna().sum())
    rep["piece_manquante"] = int(df[C_PART].isna().sum())
    df[C_TECH] = df[C_TECH].fillna(NA_TECH)
    df[C_PART] = df[C_PART].fillna(NA_PART)
    df[C_STAT] = df[C_STAT].fillna(NA_STAT)
    df["Cout_Impute"] = df[C_COST].isna()
    if impute:
        # médiane du groupe (équipement × type), sinon de l'équipement, sinon globale
        med1 = df.groupby([C_EQ, C_TYPE])[C_COST].transform("median")
        med2 = df.groupby(C_EQ)[C_COST].transform("median")
        df[C_COST] = df[C_COST].fillna(med1).fillna(med2).fillna(df[C_COST].median())
        med_d = df.groupby(C_EQ)[C_DUR].transform("median")
        df[C_DUR] = df[C_DUR].fillna(med_d).fillna(df[C_DUR].median())
    rep["cout_impute"] = int(df["Cout_Impute"].sum()) if impute else 0

    # 5) anomalies (méthode IQR) : signalées, jamais supprimées
    df["Anomalie_Cout"] = False
    if df[C_COST].notna().sum() > 10:
        q1, q3 = df[C_COST].quantile([0.25, 0.75])
        iqr = q3 - q1
        df["Anomalie_Cout"] = (df[C_COST] < q1 - 1.5 * iqr) | (df[C_COST] > q3 + 1.5 * iqr)
    rep["anomalies_cout"] = int(df["Anomalie_Cout"].sum())

    # 6) colonnes dérivées
    df["Mois"] = df[C_DATE].dt.to_period("M").dt.to_timestamp()
    df["Annee"] = df[C_DATE].dt.year
    df[C_ID] = pd.to_numeric(df[C_ID], errors="coerce").astype("Int64")
    df = df.sort_values([C_DATE, C_ID]).reset_index(drop=True)
    rep["lignes_propres"] = len(df)
    return df, rep


@st.cache_data(show_spinner=False, max_entries=8)
def load_clean(token: tuple, impute: bool = True) -> tuple[pd.DataFrame, dict]:
    """Données nettoyées, MISES EN CACHE.
    Le paramètre `token` (empreinte du fichier) fait partie de la clé de cache :
    si le CSV change → token différent → le cache est contourné → rechargement
    automatique. Sinon le résultat est servi instantanément depuis le cache."""
    return clean_data(read_raw(), impute)


# ══════════════════════════════════════════════════════════════════════════════
# 5. AUTHENTIFICATION (comptes uniques, hachage PBKDF2, rôles)
# ══════════════════════════════════════════════════════════════════════════════
def _hash(pwd: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS).hex()


def new_credentials(pwd: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)  # sel unique par utilisateur
    return salt, _hash(pwd, salt)


def load_users() -> dict:
    with get_lock():
        if not USERS_FILE.exists():
            return {}
        try:
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}


def _save_users(users: dict) -> None:
    with get_lock():
        tmp = USERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, USERS_FILE)


def check_password_policy(pwd: str) -> str | None:
    if len(pwd) < 8:
        return "Le mot de passe doit contenir au moins 8 caractères."
    if not re.search(r"[A-Za-z]", pwd) or not re.search(r"\d", pwd):
        return "Le mot de passe doit contenir au moins une lettre et un chiffre."
    return None


def authenticate(username: str, pwd: str) -> tuple[bool, str, dict | None]:
    key = username.strip().lower()
    users = load_users()
    u = users.get(key)
    if not u:
        _hash(pwd, "00" * 16)  # même durée de calcul → pas d'indice sur l'existence du compte
        return False, "Identifiant ou mot de passe incorrect.", None
    if not u.get("active", True):
        return False, "Ce compte est désactivé. Contactez l'administrateur.", None
    remaining = int(u.get("locked_until", 0) - time.time())
    if remaining > 0:
        return False, f"Trop de tentatives. Réessayez dans {remaining // 60 + 1} min.", None
    if hmac.compare_digest(_hash(pwd, u["salt"]), u["hash"]):
        u["failed"], u["locked_until"] = 0, 0
        u["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        users[key] = u
        _save_users(users)
        return True, "", {"username": key, **u}
    u["failed"] = u.get("failed", 0) + 1
    if u["failed"] >= MAX_FAILED_LOGINS:
        u["failed"], u["locked_until"] = 0, time.time() + LOCK_SECONDS
    users[key] = u
    _save_users(users)
    time.sleep(0.4)
    return False, "Identifiant ou mot de passe incorrect.", None


def create_user(username: str, name: str, pwd: str, role: str = "technicien", tech_code: str = "") -> str | None:
    """Crée un compte. Retourne un message d'erreur, ou None si OK."""
    key = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,30}", key):
        return "Identifiant : 3 à 30 caractères (lettres minuscules, chiffres, . _ -)."
    if len(name.strip()) < 2:
        return "Le nom complet est obligatoire."
    err = check_password_policy(pwd)
    if err:
        return err
    tech_code = tech_code.strip().upper()
    if tech_code and not re.fullmatch(r"TECH-\d{2}", tech_code):
        return "Code technicien invalide (format attendu : TECH-05)."
    with get_lock():
        users = load_users()
        if key in users:
            return "Cet identifiant est déjà utilisé : chaque utilisateur doit avoir un identifiant unique."
        salt, h = new_credentials(pwd)
        users[key] = {
            "name": name.strip(), "role": role, "salt": salt, "hash": h, "active": True,
            "tech_code": tech_code, "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "failed": 0, "locked_until": 0, "default_pwd": False,
        }
        _save_users(users)
    return None


def set_password(username: str, pwd: str) -> str | None:
    err = check_password_policy(pwd)
    if err:
        return err
    with get_lock():
        users = load_users()
        if username not in users:
            return "Utilisateur introuvable."
        users[username]["salt"], users[username]["hash"] = new_credentials(pwd)
        users[username]["default_pwd"] = False
        users[username]["failed"], users[username]["locked_until"] = 0, 0
        _save_users(users)
    return None


def current_user() -> dict | None:
    """Utilisateur de la session, revalidé à chaque rerun (compte supprimé/désactivé → déconnexion)."""
    a = st.session_state.get("auth")
    if not a:
        return None
    u = load_users().get(a["username"])
    if not u or not u.get("active", True):
        st.session_state.pop("auth", None)
        return None
    return {"username": a["username"], **u}


def logout() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]


# ══════════════════════════════════════════════════════════════════════════════
# 6. KPI & GRAPHIQUES
# ══════════════════════════════════════════════════════════════════════════════
def compute_kpis(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {k: np.nan for k in ("n", "cout", "cout_moy", "mttr", "duree", "taux", "proactif",
                                    "machines", "techs", "pieces", "corr")}
    corr = df[df[C_TYPE] == "Corrective"]
    return {
        "n": n,
        "cout": df[C_COST].sum(),
        "cout_moy": df[C_COST].mean(),
        "mttr": corr[C_DUR].mean() if len(corr) else np.nan,   # durée moyenne d'une réparation corrective
        "duree": df[C_DUR].sum(),
        "taux": (df[C_STAT] == "Terminée").mean() * 100,
        "proactif": df[C_TYPE].isin(["Préventive", "Prédictive"]).mean() * 100,
        "machines": df[C_MACH].nunique(),
        "techs": df.loc[df[C_TECH] != NA_TECH, C_TECH].nunique(),
        "pieces": int((~df[C_PART].isin(["Aucune", NA_PART])).sum()),
        "corr": len(corr),
    }


def pct_delta(cur, prev):
    if prev is None or pd.isna(prev) or prev == 0 or pd.isna(cur):
        return None
    return (cur - prev) / prev * 100


def kpi_card(icon: str, label: str, value: str, sub: str = "", delta=None, good: str | None = None,
             color: str = BLUE, delta_unit: str = "%") -> str:
    d_html = ""
    if delta is not None and not pd.isna(delta):
        cls = "neu"
        if good and abs(delta) > 0.05:
            cls = "pos" if ((delta > 0) == (good == "up")) else "neg"
        arrow = "▲" if delta > 0 else "▼"
        d_html = f'<div class="delta {cls}">{arrow} {fmt_dec(abs(delta), 1)} {delta_unit} vs période préc.</div>'
    return (
        f'<div class="kpi" style="--c:{color}"><div class="kpi-icon">{icon_img(icon, 38)}</div>'
        f'<div><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div>'
        f'<div class="kpi-sub">{sub}</div>{d_html}</div></div>'
    )


def setup_mpl() -> None:
    plt.rcParams.update({
        "figure.facecolor": "none", "axes.facecolor": "none", "savefig.facecolor": "none",
        "font.size": 10, "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": "#CBD5E1",
        "xtick.color": INK, "ytick.color": INK, "axes.titleweight": "bold",
        "legend.frameon": False, "figure.dpi": 110,
    })


def style_ax(ax, grid: str | None = "y") -> None:
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#CBD5E1")
    ax.tick_params(length=0)
    if grid:
        ax.grid(axis=grid, color="#E5EAF2", lw=0.8)
        ax.set_axisbelow(True)


def _k(v: float) -> str:
    return f"{v / 1000:,.0f}k".replace(",", "\u202f")


def fig_monthly(df):
    full = pd.date_range(df["Mois"].min(), df["Mois"].max(), freq="MS")
    m = df.groupby("Mois").agg(cout=(C_COST, "sum"), n=(C_ID, "size")).reindex(full, fill_value=0)
    x = np.arange(len(m))
    fig, ax = plt.subplots(figsize=(9.6, 3.7))
    ax.bar(x, m["cout"] / 1000, color=BLUE, width=0.64, label="Coût (k MAD)", zorder=2)
    ax.set_ylabel("Coût (k MAD)")
    style_ax(ax)
    ax2 = ax.twinx()
    ax2.plot(x, m["n"], color=AMBER, marker="o", lw=2.5, ms=6, label="Interventions", zorder=3)
    ax2.set_ylabel("Interventions")
    ax2.set_ylim(0, max(m["n"].max() * 1.25, 1))
    for s in ("top", "left"):
        ax2.spines[s].set_visible(False)
    ax2.spines["right"].set_color("#CBD5E1")
    ax2.tick_params(length=0)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{MOIS[d.month - 1]} {str(d.year)[2:]}" for d in m.index],
                       rotation=45 if len(m) > 9 else 0, ha="right" if len(m) > 9 else "center")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=2)
    return fig


def fig_type_donut(df):
    c = df[C_TYPE].value_counts()
    fig, ax = plt.subplots(figsize=(4.8, 3.7))
    wedges, _ = ax.pie(c.values, colors=[TYPE_COLORS.get(t, GREY) for t in c.index], startangle=90,
                       counterclock=False, wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2))
    ax.text(0, 0.06, fmt_int(c.sum()), ha="center", va="center", fontsize=22, fontweight="bold")
    ax.text(0, -0.2, "interventions", ha="center", va="center", fontsize=9, color="#64748B")
    ax.legend(wedges, [f"{t}  {v / c.sum() * 100:.0f} %" for t, v in c.items()], loc="center left",
              bbox_to_anchor=(0.92, 0.5))
    ax.set_aspect("equal")
    return fig


def fig_status_type(df):
    ct = pd.crosstab(df[C_TYPE], df[C_STAT]).reindex(columns=[s for s in STATUTS + [NA_STAT] if s in set(df[C_STAT])])
    ct = ct.reindex([t for t in TYPES if t in ct.index] + [t for t in ct.index if t not in TYPES])
    fig, ax = plt.subplots(figsize=(4.8, 3.7))
    bottom = np.zeros(len(ct))
    for s in ct.columns:
        ax.bar(ct.index, ct[s], bottom=bottom, color=STATUS_COLORS.get(s, "#CBD5E1"), label=s, width=0.6, zorder=2)
        for i, v in enumerate(ct[s]):
            if v > ct.values.max() * 0.07:
                ax.text(i, bottom[i] + v / 2, int(v), ha="center", va="center", color="white", fontsize=9,
                        fontweight="bold")
        bottom += ct[s].values
    style_ax(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=3)
    return fig


def fig_cost_equip(df):
    g = df.groupby(C_EQ)[C_COST].sum().sort_values()
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.barh(g.index, g.values / 1000, color=BLUE, height=0.62, zorder=2)
    for i, v in enumerate(g.values):
        ax.text(v / 1000 + g.max() / 1000 * 0.01, i, _k(v), va="center", fontsize=9)
    ax.set_xlabel("Coût total (k MAD)")
    ax.set_xlim(0, g.max() / 1000 * 1.14)
    style_ax(ax, "x")
    return fig


def fig_top_machines(df, n: int = 10):
    g = df.groupby(C_MACH)[C_COST].sum().sort_values(ascending=False).head(n).iloc[::-1]
    cmap = LinearSegmentedColormap.from_list("m", ["#9EC5E3", NAVY])
    cols = cmap(np.linspace(0.15, 1, len(g)))
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.barh(g.index, g.values / 1000, color=cols, height=0.62, zorder=2)
    for i, v in enumerate(g.values):
        ax.text(v / 1000 + g.max() / 1000 * 0.01, i, _k(v), va="center", fontsize=9)
    ax.set_xlabel("Coût total (k MAD)")
    ax.set_xlim(0, g.max() / 1000 * 1.14)
    style_ax(ax, "x")
    return fig


def fig_heatmap(df):
    p = df.pivot_table(index=C_EQ, columns=C_TYPE, values=C_COST, aggfunc="mean")
    p = p.reindex(columns=[t for t in TYPES if t in p.columns])
    cmap = LinearSegmentedColormap.from_list("h", ["#EAF3FA", "#6FA8D2", NAVY])
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    im = ax.imshow(p.values, cmap=cmap, aspect="auto")
    ax.set_xticks(range(p.shape[1]))
    ax.set_xticklabels(p.columns)
    ax.set_yticks(range(p.shape[0]))
    ax.set_yticklabels(p.index)
    for i in range(p.shape[0]):
        for j in range(p.shape[1]):
            v = p.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, fmt_int(v), ha="center", va="center", fontsize=9, fontweight="bold",
                        color="white" if im.norm(v) > 0.5 else INK)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=0, labelsize=8)
    return fig


def fig_scatter(df):
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for t in [t for t in TYPES if t in set(df[C_TYPE])]:
        d = df[df[C_TYPE] == t]
        ax.scatter(d[C_DUR], d[C_COST] / 1000, s=22, alpha=0.55, color=TYPE_COLORS[t], label=t, edgecolors="none")
    ax.set_xlabel("Durée (h)")
    ax.set_ylabel("Coût (k MAD)")
    style_ax(ax, "both")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=3, markerscale=1.6)
    return fig


def fig_duration_box(df):
    order = sorted(df[C_EQ].unique())
    data = [df.loc[df[C_EQ] == e, C_DUR].dropna().values for e in order]
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    bp = ax.boxplot(data, patch_artist=True, widths=0.55, showfliers=True,
                    medianprops=dict(color="white", lw=2), whiskerprops=dict(color="#94A3B8"),
                    capprops=dict(color="#94A3B8"), flierprops=dict(marker="o", ms=3, markerfacecolor="#94A3B8",
                                                                  markeredgecolor="none"))
    pal = [BLUE, TEAL, AMBER, RED, "#7A5195", GREY]
    for i, b in enumerate(bp["boxes"]):
        b.set_facecolor(pal[i % len(pal)])
        b.set_edgecolor("none")
    ax.set_xticks(range(1, len(order) + 1))
    ax.set_xticklabels(order, rotation=20 if len(order) > 5 else 0)
    ax.set_ylabel("Durée (h)")
    style_ax(ax)
    return fig


def fig_duration_hist(df):
    d = df[C_DUR].dropna()
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.hist(d, bins=14, color=TEAL, edgecolor="white", zorder=2)
    ax.axvline(d.mean(), color=RED, lw=2, ls="--", zorder=3)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    ax.text(d.mean(), ax.get_ylim()[1] * 0.98, f" moyenne {fmt_dec(d.mean())} h ", color=RED, fontsize=9,
            fontweight="bold", va="top", bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=RED, lw=1))
    ax.set_xlabel("Durée d'intervention (h)")
    ax.set_ylabel("Nombre d'interventions")
    style_ax(ax)
    return fig


def fig_mttr(df):
    c = df[df[C_TYPE] == "Corrective"]
    if c.empty:
        return None
    g = c.groupby(C_EQ)[C_DUR].mean().sort_values()
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.barh(g.index, g.values, color=RED, height=0.62, zorder=2)
    for i, v in enumerate(g.values):
        ax.text(v - g.max() * 0.015, i, f"{fmt_dec(v)} h", va="center", ha="right", fontsize=9,
                color="white", fontweight="bold")
    ax.axvline(c[C_DUR].mean(), color=INK, lw=1.4, ls="--")
    ax.set_xlabel("MTTR — durée moyenne des interventions correctives (h)")
    ax.set_xlim(0, g.max() * 1.15)
    style_ax(ax, "x")
    return fig


def fig_tech(df):
    d = df[df[C_TECH] != NA_TECH]
    g = d.groupby(C_TECH).agg(n=(C_ID, "size"), h=(C_DUR, "sum")).sort_values("n", ascending=False).head(15)
    g = g.iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.2, max(3.6, len(g) * 0.28)))
    ax.barh(g.index, g["n"], color=BLUE, height=0.65, zorder=2)
    for i, (n, h) in enumerate(zip(g["n"], g["h"])):
        ax.text(n + g["n"].max() * 0.01, i, f"{int(n)}  ·  {fmt_int(h)} h", va="center", fontsize=8.5)
    ax.set_xlabel("Interventions  ·  heures cumulées")
    ax.set_xlim(0, g["n"].max() * 1.28)
    style_ax(ax, "x")
    return fig


def fig_pieces(df):
    d = df[~df[C_PART].isin(["Aucune", NA_PART])]
    if d.empty:
        return None
    g = d.groupby(C_PART).agg(n=(C_ID, "size"), cout=(C_COST, "mean")).sort_values("n", ascending=False)
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.bar(g.index, g["n"], color=AMBER, width=0.6, zorder=2)
    for i, v in enumerate(g["n"]):
        ax.text(i, v + g["n"].max() * 0.015, int(v), ha="center", fontsize=9, fontweight="bold")
    ax.set_ylabel("Remplacements")
    ax.set_ylim(0, g["n"].max() * 1.15)
    style_ax(ax)
    return fig


def show_fig(fig) -> None:
    if fig is None:
        st.info("Pas assez de données pour ce graphique avec les filtres actuels.")
        return
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


def chart_card(title: str, subtitle: str, fig) -> None:
    with st.container(border=True):
        ui_html(f'<div class="chart-title">{title}</div><div class="chart-sub">{subtitle}</div>')
        show_fig(fig)


# ══════════════════════════════════════════════════════════════════════════════
# 7. PAGES
# ══════════════════════════════════════════════════════════════════════════════
def section_title(icon: str, title: str, sub: str = "") -> None:
    ui_html(f'<div style="display:flex;align-items:center;gap:12px;margin:4px 0 12px">'
            f'<div class="kpi-icon" style="width:46px;height:46px">{icon_img(icon, 30)}</div><div>'
            f'<div class="chart-title" style="font-size:1.08rem">{title}</div>'
            f'<div class="chart-sub" style="margin:0">{sub}</div></div></div>')


def side_title(icon: str, text: str) -> None:
    ui_html(f'<div class="sidebar-title" style="display:flex;align-items:center;gap:8px">'
            f'{icon_img(icon, 18)}<span>{text}</span></div>')


def page_header(icon: str, title: str, subtitle: str, live: bool = False) -> None:
    badge = ""
    if live:
        ts = datetime.fromtimestamp(DATA_FILE.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S") if DATA_FILE.exists() else "—"
        badge = f'<div class="live">● Données synchronisées · MAJ fichier : {ts}</div>'
    ui_html(
        f'<div class="page-head"><div class="l">{icon_img(icon, 56)}<div><div class="page-title">{title}</div>'
        f'<div class="page-sub">{subtitle}</div></div></div>{badge}</div>'
    )


# ─────────────────────────────── Connexion ───────────────────────────────────
def render_login() -> None:
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']{display:none}</style>",
                unsafe_allow_html=True)
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        ui_html(f"""
        <div class="hero">
          <div class="hero-logo">{icon_img('logo', 84)}<div><div class="hero-name">{APP_NAME}</div>
          <div class="hero-tag">{APP_TAGLINE}</div></div></div>
          <h2>La maintenance industrielle,<br>pilotée par la donnée.</h2>
          <div class="feat">{icon_img('present', 46)}<div><b>Dashboard temps réel</b><span>KPI et graphiques recalculés à chaque saisie</span></div></div>
          <div class="feat">{icon_img('taux', 46)}<div><b>Saisie des interventions</b><span>Formulaire contrôlé, import CSV, traçabilité</span></div></div>
          <div class="feat">{icon_img('kpi', 46)}<div><b>KPI & analyses détaillées</b><span>Coûts, durées, MTTR, charge des techniciens</span></div></div>
          <div class="feat">{icon_img('user_cfg', 46)}<div><b>Comptes personnels sécurisés</b><span>Un identifiant unique et un rôle par utilisateur</span></div></div>
        </div>""")
    with right:
        st.write("")
        st.write("")
        ui_html('<div class="login-title">Bienvenue 👋</div><div class="login-sub">Connectez-vous pour accéder à votre espace.</div>')
        tab_in, tab_up = st.tabs(["Connexion", "Créer un compte"])
        with tab_in:
            with st.form("login_form"):
                u = st.text_input("Identifiant", placeholder="ex. y.benali")
                p = st.text_input("Mot de passe", type="password")
                go = st.form_submit_button("Se connecter", type="primary", **STRETCH)
            if go:
                if not u or not p:
                    st.error("Saisissez votre identifiant et votre mot de passe.")
                else:
                    ok, msg, user = authenticate(u, p)
                    if ok:
                        st.session_state["auth"] = {"username": user["username"]}
                        st.session_state["page"] = "Dashboard"
                        st.rerun()
                    st.error(msg)
        with tab_up:
            section_title("add_user", "Rejoindre l'équipe", "Créez votre compte personnel avec un identifiant unique")
            with st.form("signup_form"):
                name = st.text_input("Nom complet")
                uid = st.text_input("Identifiant unique", help="3-30 caractères : lettres minuscules, chiffres, . _ -")
                c1, c2 = st.columns(2)
                p1 = c1.text_input("Mot de passe", type="password", help="8 caractères min., lettres + chiffres")
                p2 = c2.text_input("Confirmation", type="password")
                tc = st.text_input("Code technicien (optionnel)", placeholder="ex. TECH-05",
                                   help="Pré-remplit automatiquement vos saisies.")
                inv = st.text_input("Code d'invitation", type="password") if INVITE_CODE else ""
                su = st.form_submit_button("Créer mon compte", type="primary", **STRETCH)
            if su:
                if INVITE_CODE and not hmac.compare_digest(inv.encode(), INVITE_CODE.encode()):
                    st.error("Code d'invitation incorrect.")
                elif p1 != p2:
                    st.error("Les deux mots de passe ne correspondent pas.")
                else:
                    err = create_user(uid, name, p1, "technicien", tc)
                    st.error(err) if err else st.success("Compte créé ✔ — vous pouvez maintenant vous connecter.")


# ─────────────────────────────── Dashboard ───────────────────────────────────
FILTER_KEYS = ["f_period", "f_dates", "f_types", "f_eq", "f_mach", "f_stat", "f_tech", "f_part"]


def reset_filters() -> None:
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


def sidebar_filters(df: pd.DataFrame):
    """Filtres interactifs. Liste vide = « tous » (évite tout problème quand de nouvelles
    valeurs apparaissent après une saisie). Retourne (df filtré, période, df sans filtre date)."""
    with st.sidebar:
        side_title("filters", "Filtres")
        dmin, dmax = df[C_DATE].min().date(), df[C_DATE].max().date()
        for key, col in (("f_types", C_TYPE), ("f_eq", C_EQ), ("f_mach", C_MACH), ("f_stat", C_STAT),
                         ("f_tech", C_TECH), ("f_part", C_PART)):
            if key in st.session_state:  # retire les valeurs qui n'existent plus
                valid = set(df[col])
                st.session_state[key] = [v for v in st.session_state[key] if v in valid]
        fd = st.session_state.get("f_dates")
        if fd is not None and not (isinstance(fd, (tuple, list)) and len(fd) == 2 and dmin <= fd[0] <= dmax and dmin <= fd[1] <= dmax):
            st.session_state.pop("f_dates", None)
        period = st.selectbox("Période", ["Toutes les dates", "30 derniers jours", "90 derniers jours",
                                          "Année en cours", "Personnalisée"], key="f_period",
                              help="Les périodes relatives sont calculées à partir de la date la plus récente de la base.")
        rng = None
        if period == "30 derniers jours":
            rng = (dmax - timedelta(days=29), dmax)
        elif period == "90 derniers jours":
            rng = (dmax - timedelta(days=89), dmax)
        elif period == "Année en cours":
            rng = (date(dmax.year, 1, 1), dmax)
        elif period == "Personnalisée":
            v = st.date_input("Du … au …", value=(dmin, dmax), min_value=dmin, max_value=dmax, key="f_dates",
                              format="DD/MM/YYYY")
            rng = (v[0], v[1]) if isinstance(v, (tuple, list)) and len(v) == 2 else (dmin, dmax)
        types = st.multiselect("Type de maintenance", sorted(df[C_TYPE].unique()), key="f_types", placeholder="Tous")
        eqs = st.multiselect("Équipement", sorted(df[C_EQ].unique()), key="f_eq", placeholder="Tous")
        machs = st.multiselect("Machine", sorted(df[C_MACH].unique()), key="f_mach", placeholder="Toutes")
        stats = st.multiselect("Statut", sorted(df[C_STAT].unique()), key="f_stat", placeholder="Tous")
        techs = st.multiselect("Technicien", sorted(df[C_TECH].unique()), key="f_tech", placeholder="Tous")
        parts = st.multiselect("Pièce remplacée", sorted(df[C_PART].unique()), key="f_part", placeholder="Toutes")
        st.button("↺ Réinitialiser les filtres", on_click=reset_filters, **STRETCH)

    m = pd.Series(True, index=df.index)
    for col, sel in ((C_TYPE, types), (C_EQ, eqs), (C_MACH, machs), (C_STAT, stats), (C_TECH, techs), (C_PART, parts)):
        if sel:
            m &= df[col].isin(sel)
    df_nd = df[m]
    if rng:
        d = df_nd[C_DATE].dt.date
        return df_nd[(d >= rng[0]) & (d <= rng[1])], rng, df_nd
    return df_nd, None, df_nd


def previous_period(df_nd: pd.DataFrame, rng) -> pd.DataFrame | None:
    if not rng:
        return None
    n_days = (rng[1] - rng[0]).days + 1
    p_end = rng[0] - timedelta(days=1)
    p_start = p_end - timedelta(days=n_days - 1)
    d = df_nd[C_DATE].dt.date
    return df_nd[(d >= p_start) & (d <= p_end)]


def page_dashboard(df: pd.DataFrame, rep: dict) -> None:
    page_header("dash", "Dashboard de maintenance", "Vue d'ensemble des interventions, coûts et performances", live=True)
    if df.empty:
        st.info("Aucune donnée pour le moment. Rendez-vous dans « Saisie » pour ajouter une première intervention.")
        return
    dff, rng, df_nd = sidebar_filters(df)
    if dff.empty:
        st.warning("Aucune intervention ne correspond aux filtres sélectionnés.")
        return

    section_title("kpi", "Indicateurs clés", "Calculés sur la sélection courante · comparés à la période précédente")
    k = compute_kpis(dff)
    prev = previous_period(df_nd, rng)
    kp = compute_kpis(prev) if prev is not None and len(prev) else None

    def dl(key):
        return pct_delta(k[key], kp[key]) if kp else None

    taux_delta = (k["taux"] - kp["taux"]) if kp and not pd.isna(kp["taux"]) else None

    c = st.columns(4)
    c[0].markdown(kpi_card("interv", "Interventions", fmt_int(k["n"]),
                           f'dont {fmt_int(k["corr"])} correctives', dl("n"), None, BLUE), unsafe_allow_html=True)
    c[1].markdown(kpi_card("cout", "Coût total", fmt_mad_compact(k["cout"]),
                           f'{fmt_mad(k["cout"])} · moy. {fmt_mad(k["cout_moy"])}', dl("cout"), "down", AMBER),
                  unsafe_allow_html=True)
    c[2].markdown(kpi_card("duree", "MTTR corrective", f'{fmt_dec(k["mttr"])} h',
                           f'Durée totale : {fmt_int(k["duree"])} h', None, "down", RED), unsafe_allow_html=True)
    c[3].markdown(kpi_card("taux", "Taux de réalisation", f'{fmt_dec(k["taux"])} %',
                           "Interventions terminées", taux_delta, "up", TEAL, "pts"), unsafe_allow_html=True)
    st.write("")
    c = st.columns(4)
    c[0].markdown(kpi_card("logo", "Indice de proactivité", f'{fmt_dec(k["proactif"])} %',
                           "Préventive + prédictive", None, None, TEAL), unsafe_allow_html=True)
    c[1].markdown(kpi_card("machine", "Machines concernées", fmt_int(k["machines"]),
                           f'sur {fmt_int(df[C_MACH].nunique())} au total', None, None, BLUE), unsafe_allow_html=True)
    c[2].markdown(kpi_card("tech", "Techniciens actifs", fmt_int(k["techs"]),
                           f'{fmt_dec(k["n"] / max(k["techs"], 1), 1)} interv. / technicien', None, None, NAVY),
                  unsafe_allow_html=True)
    c[3].markdown(kpi_card("piece", "Pièces remplacées", fmt_int(k["pieces"]),
                           f'{fmt_dec(k["pieces"] / k["n"] * 100, 0)} % des interventions', None, None, AMBER),
                  unsafe_allow_html=True)
    st.write("")

    t1, t2, t3, t4, t5 = st.tabs(["📈 Vue d'ensemble", "💰 Coûts", "⏱ Durées & performance",
                                  "👷 Équipes & pièces", "🗃 Données"])
    with t1:
        section_title("chart", "Vue d'ensemble", "Tendance et répartition de l'activité")
        chart_card("Évolution mensuelle", "Coût total (barres) et nombre d'interventions (courbe)", fig_monthly(dff))
        a, b = st.columns(2)
        with a:
            chart_card("Répartition par type de maintenance", "Part de chaque stratégie de maintenance", fig_type_donut(dff))
        with b:
            chart_card("Statuts par type", "Avancement des interventions", fig_status_type(dff))
    with t2:
        section_title("cout", "Analyse des coûts", "Où part le budget de maintenance ?")
        a, b = st.columns(2)
        with a:
            chart_card("Coût par équipement", "Coût cumulé en k MAD", fig_cost_equip(dff))
        with b:
            chart_card("Top 10 machines les plus coûteuses", "Coût cumulé en k MAD", fig_top_machines(dff))
        a, b = st.columns(2)
        with a:
            chart_card("Coût moyen : équipement × type", "Carte de chaleur (MAD par intervention)", fig_heatmap(dff))
        with b:
            chart_card("Durée vs coût", "Chaque point est une intervention", fig_scatter(dff))
    with t3:
        section_title("duree", "Durées & performance", "Rapidité et fiabilité des interventions")
        a, b = st.columns(2)
        with a:
            chart_card("MTTR par équipement", "Durée moyenne des interventions correctives", fig_mttr(dff))
        with b:
            chart_card("Distribution des durées", "Histogramme des durées d'intervention", fig_duration_hist(dff))
        chart_card("Dispersion des durées par équipement", "Médiane, quartiles et valeurs extrêmes", fig_duration_box(dff))
    with t4:
        section_title("tech", "Équipes & pièces", "Charge de travail et consommation de pièces")
        a, b = st.columns(2)
        with a:
            chart_card("Charge par technicien", "Nombre d'interventions · heures cumulées", fig_tech(dff))
        with b:
            chart_card("Pièces remplacées", "Fréquence de remplacement par type de pièce", fig_pieces(dff))
    with t5:
        section_title("monitor", "Explorer les données", "Tableau détaillé des interventions filtrées")
        cols = [C_ID, C_DATE, C_MACH, C_EQ, C_TYPE, C_STAT, C_DUR, C_COST, C_TECH, C_PART, C_BY, "Cout_Impute",
                "Anomalie_Cout"]
        show = dff[cols].sort_values([C_DATE, C_ID], ascending=False)
        st.caption(f"{fmt_int(len(show))} interventions affichées · tri : plus récentes d'abord")
        st.dataframe(show, hide_index=True, height=430, column_config={
            C_ID: st.column_config.NumberColumn("ID", format="%d", width="small"),
            C_DATE: st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
            C_DUR: st.column_config.NumberColumn("Durée (h)", format="%.1f"),
            C_COST: st.column_config.NumberColumn("Coût (MAD)", format="%.2f"),
            C_BY: st.column_config.TextColumn("Saisi par"),
            "Cout_Impute": st.column_config.CheckboxColumn("Coût estimé", help="Valeur manquante remplacée par la médiane"),
            "Anomalie_Cout": st.column_config.CheckboxColumn("Anomalie coût"),
        }, **STRETCH)
        st.download_button("⬇ Télécharger la sélection (CSV)", show.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"maintenance_selection_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv")
        with st.expander("🧹 Rapport de nettoyage des données"):
            section_title("analysis", "Qualité des données", "Résultat du nettoyage automatique")
            show_quality_report(rep)


def show_quality_report(rep: dict) -> None:
    c = st.columns(4)
    c[0].metric("Lignes brutes", fmt_int(rep["lignes_brutes"]))
    c[1].metric("Lignes exploitables", fmt_int(rep["lignes_propres"]))
    c[2].metric("Doublons supprimés", fmt_int(rep["doublons_supprimes"]))
    c[3].metric("Lignes invalides écartées", fmt_int(rep["lignes_invalides"]))
    c = st.columns(4)
    c[0].metric("Coûts manquants", fmt_int(rep["cout_manquant"]), help="Remplacés par la médiane (équipement × type) si l'option est activée")
    c[1].metric("Techniciens manquants", fmt_int(rep["technicien_manquant"]), help=f"Affichés « {NA_TECH} »")
    c[2].metric("Pièces manquantes", fmt_int(rep["piece_manquante"]), help=f"Affichées « {NA_PART} »")
    c[3].metric("Anomalies de coût (IQR)", fmt_int(rep["anomalies_cout"]), help="Signalées, jamais supprimées")


# ─────────────────────────────── Saisie ──────────────────────────────────────
def page_saisie(df: pd.DataFrame, user: dict) -> None:
    page_header("interv", "Saisie des interventions", "Ajoutez de nouvelles données : elles alimentent immédiatement le dashboard")
    if user["role"] not in ("admin", "technicien"):
        st.warning("Votre rôle (Lecteur) ne permet pas la saisie. Contactez un administrateur.")
        return

    machines = sorted(set(df[C_MACH]) if len(df) else [])
    techs = sorted(set(df.loc[df[C_TECH] != NA_TECH, C_TECH]) if len(df) else [])
    eqs = sorted(set(EQUIPEMENTS) | set(df[C_EQ] if len(df) else []))
    pieces = sorted(set(PIECES) | set(df.loc[df[C_PART] != NA_PART, C_PART] if len(df) else []))

    tab_form, tab_import = st.tabs(["✍️ Nouvelle intervention", "📥 Import CSV en masse"])
    with tab_form:
        left, right = st.columns([1.35, 1], gap="large")
        with left:
            with st.form("saisie_form", clear_on_submit=True):
                st.markdown("##### Informations générales")
                c1, c2 = st.columns(2)
                d = c1.date_input("Date de l'intervention", value=date.today(), format="DD/MM/YYYY")
                statut = c2.selectbox("Statut", STATUTS, index=2)
                c1, c2 = st.columns(2)
                mach_sel = c1.selectbox("Machine", machines if machines else ["—"])
                mach_new = c2.text_input("… ou nouvelle machine", placeholder="ex. M-21",
                                         help="Si renseigné, remplace la machine sélectionnée.")
                c1, c2 = st.columns(2)
                eq = c1.selectbox("Équipement", eqs)
                typ = c2.selectbox("Type de maintenance", TYPES)
                st.markdown("##### Détails techniques")
                c1, c2 = st.columns(2)
                dur = c1.number_input("Durée (heures)", min_value=0.1, max_value=500.0, value=1.0, step=0.1, format="%.1f")
                cost = c2.number_input("Coût (MAD)", min_value=0.0, value=None, step=50.0, format="%.2f",
                                       placeholder="ex. 4500", help="Laissez vide si inconnu (sera estimé dans le dashboard).")
                c1, c2 = st.columns(2)
                my_code = user.get("tech_code") or ""
                options_t = [NA_TECH] + techs
                idx_t = options_t.index(my_code) if my_code in options_t else 0
                tech_sel = c1.selectbox("Technicien", options_t, index=idx_t)
                tech_new = c2.text_input("… ou nouveau technicien", placeholder="ex. TECH-16")
                piece = st.selectbox("Pièce remplacée", pieces, index=pieces.index("Aucune") if "Aucune" in pieces else 0)
                dup_ok = st.checkbox("Enregistrer même si un doublon est détecté")
                sub = st.form_submit_button("💾 Enregistrer l'intervention", type="primary", **STRETCH)
            if sub:
                machine = (mach_new.strip() or mach_sel).upper().replace(" ", "-")
                machine = re.sub(r"^([A-Z]+)(\d+)$", r"\1-\2", machine)
                tech = (tech_new.strip().upper() or tech_sel)
                errors = []
                if not re.fullmatch(r"[A-Z]-\d{1,4}", machine):
                    errors.append("Machine invalide (format attendu : M-07).")
                if tech_new.strip() and not re.fullmatch(r"TECH-\d{2}", tech):
                    errors.append("Technicien invalide (format attendu : TECH-05).")
                if d > date.today() + timedelta(days=365):
                    errors.append("La date est trop éloignée dans le futur.")
                if statut == "Terminée" and d > date.today():
                    errors.append("Une intervention future ne peut pas être « Terminée ».")
                row = {C_DATE: d, C_MACH: machine, C_TYPE: typ, C_EQ: eq, C_DUR: dur, C_COST: cost,
                       C_TECH: "" if tech == NA_TECH else tech, C_PART: piece, C_STAT: statut}
                if not errors and not dup_ok and is_duplicate(row, read_raw()):
                    errors.append("Une intervention identique existe déjà (même date, machine, type, équipement, "
                                  "technicien et durée). Cochez « Enregistrer même si un doublon est détecté » pour forcer.")
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    try:
                        new_id = append_rows([row], user["username"])[0]
                    except PermissionError as e:
                        st.error(str(e))
                    else:
                        st.session_state["flash"] = (f"Intervention #{new_id} enregistrée — KPI et graphiques mis à jour.", "✅")
                        st.rerun()
        with right:
            mine = int((df[C_BY] == user["username"]).sum()) if len(df) else 0
            ui_html(f'<div class="kpi" style="--c:{TEAL}"><div class="kpi-icon">{icon_img("tech", 38)}</div><div>'
                    f'<div class="kpi-label">Vos saisies</div><div class="kpi-value">{fmt_int(mine)}</div>'
                    f'<div class="kpi-sub">interventions enregistrées par vous</div></div></div>')
            st.write("")
            st.markdown("##### Dernières interventions enregistrées")
            if len(df):
                last = df.sort_values(C_ID, ascending=False).head(8)[[C_ID, C_DATE, C_MACH, C_TYPE, C_COST, C_BY]]
                st.dataframe(last, hide_index=True, column_config={
                    C_ID: st.column_config.NumberColumn("ID", format="%d", width="small"),
                    C_DATE: st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                    C_COST: st.column_config.NumberColumn("Coût", format="%.0f"),
                    C_BY: "Saisi par", C_TYPE: "Type", C_MACH: "Machine"}, **STRETCH)
            st.caption("💡 Dès l'enregistrement, le fichier CSV est mis à jour, le cache est invalidé et le "
                       "Dashboard se recalcule. Les autres utilisateurs connectés sont synchronisés automatiquement.")

    with tab_import:
        section_title("donnees", "Import en masse", "Ajoutez plusieurs interventions depuis un fichier CSV")
        st.markdown("Importez un fichier CSV contenant au minimum ces colonnes :")
        st.code(",".join(BUSINESS_COLS), language="text")
        tpl = ",".join(BUSINESS_COLS) + "\n2026-01-15,M-05,Préventive,Pompe,3.5,1200.00,TECH-04,Filtre,Terminée\n"
        st.download_button("⬇ Télécharger un modèle", tpl.encode("utf-8-sig"), "modele_import.csv", "text/csv")
        up = st.file_uploader("Fichier CSV", type=["csv"], key="import_file")
        if up is not None:
            try:
                raw_up = pd.read_csv(up, dtype=str, sep=None, engine="python", encoding="utf-8-sig")
            except Exception as e:
                st.error(f"Lecture impossible : {e}")
                return
            raw_up.columns = [c.strip() for c in raw_up.columns]
            miss = [c for c in BUSINESS_COLS if c not in raw_up.columns]
            if miss:
                st.error("Colonnes manquantes : " + ", ".join(miss))
                return
            n = normalize_frame(raw_up)
            bad = n[C_DATE].isna() | n[C_MACH].isna() | n[C_TYPE].isna() | n[C_EQ].isna() | n[C_DUR].isna()
            valid = n[~bad].drop_duplicates(subset=BUSINESS_COLS)
            existing = normalize_frame(read_raw())
            key = [C_DATE, C_MACH, C_TYPE, C_EQ, C_DUR, C_TECH]
            if len(existing):
                merged = valid.merge(existing[key].drop_duplicates(), on=key, how="left", indicator=True)
                valid = merged[merged["_merge"] == "left_only"].drop(columns="_merge")
            c = st.columns(3)
            c[0].metric("Lignes lues", fmt_int(len(raw_up)))
            c[1].metric("Lignes valides à importer", fmt_int(len(valid)))
            c[2].metric("Rejetées / déjà présentes", fmt_int(len(raw_up) - len(valid)))
            if len(valid):
                st.dataframe(valid[BUSINESS_COLS].head(15), hide_index=True, **STRETCH)
                if st.button(f"✅ Importer {len(valid)} ligne(s)", type="primary"):
                    rows = valid[BUSINESS_COLS].to_dict("records")
                    for r in rows:
                        r[C_TECH] = "" if pd.isna(r[C_TECH]) else r[C_TECH]
                        r[C_PART] = "" if pd.isna(r[C_PART]) else r[C_PART]
                        r[C_STAT] = NA_STAT if pd.isna(r[C_STAT]) else r[C_STAT]
                    try:
                        with get_lock():
                            backup_data(force=True)
                            append_rows(rows, user["username"])
                    except PermissionError as e:
                        st.error(str(e))
                    else:
                        st.session_state["flash"] = (f"{len(rows)} intervention(s) importée(s).", "📥")
                        st.rerun()


# ─────────────────────────────── Administration ──────────────────────────────
def page_admin(user: dict, rep: dict) -> None:
    page_header("user_cfg", "Administration", "Comptes utilisateurs, données brutes et sauvegardes")
    t_users, t_data, t_qual = st.tabs(["👥 Utilisateurs", "🗂 Données brutes", "🛡 Qualité & sauvegardes"])

    with t_users:
        users = load_users()
        df_u = pd.DataFrame([{
            "Identifiant": k, "Nom": v["name"], "Rôle": v["role"], "Code technicien": v.get("tech_code", ""),
            "Actif": v.get("active", True), "Créé le": v.get("created", ""), "Dernière connexion": v.get("last_login", "—"),
        } for k, v in users.items()])
        st.markdown("##### Comptes existants")
        edited = st.data_editor(df_u, hide_index=True, key=f"users_editor_{st.session_state.get('ver_users', 0)}",
                                disabled=["Identifiant", "Créé le", "Dernière connexion"], column_config={
                                    "Rôle": st.column_config.SelectboxColumn(options=ROLES, required=True),
                                    "Actif": st.column_config.CheckboxColumn()}, **STRETCH)
        if st.button("💾 Enregistrer les modifications des comptes", type="primary"):
            err = None
            new = {r["Identifiant"]: r for r in edited.to_dict("records")}
            if not any(r["Rôle"] == "admin" and r["Actif"] for r in new.values()):
                err = "Il doit rester au moins un administrateur actif."
            elif not new[user["username"]]["Actif"] or new[user["username"]]["Rôle"] != "admin":
                err = "Vous ne pouvez pas vous désactiver ou vous retirer le rôle administrateur."
            if err:
                st.error(err)
            else:
                with get_lock():
                    users = load_users()
                    for k, r in new.items():
                        users[k].update({"name": str(r["Nom"]).strip() or users[k]["name"], "role": r["Rôle"],
                                         "active": bool(r["Actif"]), "tech_code": ("" if pd.isna(r["Code technicien"]) else str(r["Code technicien"]).strip().upper())})
                    _save_users(users)
                st.session_state["ver_users"] = st.session_state.get("ver_users", 0) + 1
                st.success("Comptes mis à jour.")
        st.divider()
        a, b = st.columns(2, gap="large")
        with a:
            section_title("add_user", "Créer un compte", "Ajouter un utilisateur")
            with st.form("admin_create", clear_on_submit=True):
                n = st.text_input("Nom complet")
                i = st.text_input("Identifiant")
                p = st.text_input("Mot de passe initial", type="password")
                r = st.selectbox("Rôle", ROLES, index=1, format_func=lambda x: ROLE_LABELS[x])
                tc = st.text_input("Code technicien (optionnel)")
                if st.form_submit_button("Créer", **STRETCH):
                    err = create_user(i, n, p, r, tc)
                    st.error(err) if err else st.success(f"Compte « {i.strip().lower()} » créé.")
        with b:
            st.markdown("##### Réinitialiser un mot de passe / supprimer")
            with st.form("admin_reset"):
                target = st.selectbox("Utilisateur", list(users.keys()))
                newp = st.text_input("Nouveau mot de passe", type="password")
                c1, c2 = st.columns(2)
                reset = c1.form_submit_button("Réinitialiser", **STRETCH)
                confirm = st.checkbox("Je confirme la suppression définitive du compte")
                delete = c2.form_submit_button("Supprimer", **STRETCH)
            if reset:
                err = set_password(target, newp)
                st.error(err) if err else st.success("Mot de passe réinitialisé.")
            if delete:
                if target == user["username"]:
                    st.error("Vous ne pouvez pas supprimer votre propre compte.")
                elif not confirm:
                    st.warning("Cochez la case de confirmation.")
                else:
                    with get_lock():
                        users = load_users()
                        users.pop(target, None)
                        _save_users(users)
                    st.success(f"Compte « {target} » supprimé.")
                    st.rerun()

    with t_data:
        section_title("donnees", "Données brutes", "Édition directe du fichier de données")
        st.markdown("Modification directe du fichier **dataset_maintenance.csv** (une sauvegarde est créée avant chaque enregistrement).")
        raw = read_raw()
        raw_view = raw.copy()
        raw_view[C_DATE] = pd.to_datetime(raw_view[C_DATE], errors="coerce").dt.date
        for c in (C_DUR, C_COST):
            raw_view[c] = pd.to_numeric(raw_view[c], errors="coerce")
        raw_view[C_ID] = pd.to_numeric(raw_view[C_ID], errors="coerce")
        token_at_load = data_token()
        ed = st.data_editor(raw_view, num_rows="dynamic", hide_index=True, height=420, key=f"raw_editor_{st.session_state.get('ver_raw', 0)}",
                            disabled=[C_ID, C_BY, C_AT], column_config={
                                C_DATE: st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                                C_TYPE: st.column_config.SelectboxColumn(options=TYPES),
                                C_STAT: st.column_config.SelectboxColumn(options=STATUTS),
                                C_ID: st.column_config.NumberColumn("ID", format="%d")}, **STRETCH)
        if st.button("💾 Enregistrer les modifications des données", type="primary"):
            if data_token() != token_at_load:
                st.error("Le fichier a été modifié par quelqu'un d'autre entre-temps. Rechargez la page puis recommencez.")
            else:
                out = ed.copy()
                out = out[out[C_DATE].notna() & out[C_MACH].notna()]
                out[C_DATE] = pd.to_datetime(out[C_DATE]).dt.strftime("%Y-%m-%d")
                ids = pd.to_numeric(out[C_ID], errors="coerce")
                nxt = int(ids.max()) if ids.notna().any() else 0
                new_mask = ids.isna()
                ids.loc[new_mask] = np.arange(nxt + 1, nxt + 1 + new_mask.sum())
                out[C_ID] = ids.astype(int)
                out.loc[new_mask, C_BY] = user["username"]
                out.loc[new_mask, C_AT] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    with get_lock():
                        backup_data(force=True)
                        write_raw(out)
                except PermissionError as e:
                    st.error(str(e))
                else:
                    st.session_state["ver_raw"] = st.session_state.get("ver_raw", 0) + 1
                    st.session_state["flash"] = ("Données enregistrées.", "💾")
                    st.rerun()

    with t_qual:
        section_title("analysis", "Qualité & sauvegardes", "Fiabilité et protection des données")
        st.markdown("##### Qualité des données (calculée sur le fichier actuel)")
        show_quality_report(rep)
        st.divider()
        st.markdown("##### Sauvegardes")
        BACKUP_DIR.mkdir(exist_ok=True)
        files = sorted(BACKUP_DIR.glob("dataset_*.csv"), reverse=True)
        c1, c2 = st.columns([1, 2])
        if c1.button("Créer une sauvegarde maintenant", **STRETCH):
            backup_data(force=True)
            st.rerun()
        c2.caption(f"{len(files)} sauvegarde(s) · dossier : {BACKUP_DIR} · une sauvegarde automatique par jour, {MAX_BACKUPS} conservées")
        if files:
            sel = st.selectbox("Télécharger une sauvegarde", [f.name for f in files])
            st.download_button("⬇ Télécharger", (BACKUP_DIR / sel).read_bytes(), file_name=sel, mime="text/csv")
        st.caption(f"Fichier de données : `{DATA_FILE}`")


# ─────────────────────────────── Guide ───────────────────────────────────────
def page_guide() -> None:
    page_header("support", "Guide & architecture", "Comment fonctionne la mise à jour automatique des données")
    st.markdown("""
### 🔄 Comment les données se mettent à jour automatiquement

Le fichier **`dataset_maintenance.csv`** est la *source de vérité*. L'application ne garde pas de copie « figée » :
elle relit le fichier dès qu'il change.

```
 Utilisateur ── formulaire ──►  append_rows()  ──►  dataset_maintenance.csv
                                (verrou + écriture atomique)        │
                                                                    ▼
                                         data_token() = (date de modification, taille)
                                                                    │ change
                                                                    ▼
                              load_clean(token)  → cache invalidé → nettoyage relancé
                                                                    │
                                                                    ▼
                                    KPI + 12 graphiques recalculés → affichage
 Autres sessions ouvertes ◄── fragment « surveillance » (toutes les 10 s) ── compare le token → rerun
```

**Les 5 mécanismes clés**

1. **Écriture sûre** — chaque saisie est ajoutée au CSV via un *verrou partagé* (deux saisies simultanées ne s'écrasent pas)
   et une *écriture atomique* (fichier temporaire puis renommage : aucun lecteur ne voit un fichier à moitié écrit).
2. **Empreinte du fichier** — `data_token()` renvoie `(mtime, taille)`. Ce token est passé en paramètre de `load_clean()`
   décorée par `@st.cache_data` : **token différent = cache contourné = données relues**. Pas de token différent = résultat instantané.
3. **Rerun immédiat** — après l'enregistrement, `st.rerun()` relance la page : les KPI et graphiques utilisent déjà les nouvelles données.
4. **Synchronisation multi-utilisateurs** — un `@st.fragment(run_every=10)` compare toutes les 10 s l'empreinte du fichier
   à celle vue par la session ; si elle a changé (saisie d'un collègue), la page se rafraîchit seule. Désactivable dans la barre latérale.
5. **Modification manuelle par le propriétaire** — vous pouvez ouvrir `dataset_maintenance.csv` dans Excel, ajouter/corriger des lignes
   et enregistrer : le changement est détecté **sans redémarrer l'application** (pensez à fermer Excel pour que l'app puisse écrire ensuite).

### 🔐 Comptes et rôles
| Rôle | Dashboard | Saisie / Import | Administration |
|---|:-:|:-:|:-:|
| Administrateur | ✔ | ✔ | ✔ |
| Technicien | ✔ | ✔ | — |
| Lecteur | ✔ | — | — |

Chaque utilisateur possède un **identifiant unique** et son propre mot de passe (haché PBKDF2-SHA256 avec sel individuel, jamais stocké en clair).
Verrouillage 5 min après 5 échecs. Les comptes sont dans `users.json` (créé automatiquement).

### 🗂 Traçabilité & sécurité des données
Chaque ligne enregistre **qui** l'a saisie et **quand** (`Saisi_Par`, `Date_Saisie`). Une sauvegarde datée du CSV est créée chaque jour
et avant toute modification massive (dossier `backups/`).

### ⚠️ Déploiement
En local, tout fonctionne tel quel. Sur un hébergement dont le disque est éphémère (ex. Streamlit Community Cloud), le CSV serait réinitialisé
à chaque redéploiement : il faudrait alors remplacer la couche données (section 3 de `app.py`) par une base (SQLite/PostgreSQL) ou Google Sheets —
le reste de l'application ne change pas.
""")


# ══════════════════════════════════════════════════════════════════════════════
# 8. POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════════
def live_watcher() -> None:
    """Surveille le fichier de données et rafraîchit la session quand il change."""
    def _watch():
        tok = data_token()
        seen = st.session_state.get("_seen_token")
        if seen is not None and tok != seen:
            st.session_state["_seen_token"] = tok
            st.session_state["flash"] = ("Nouvelles données détectées — mise à jour automatique.", "🔄")
            st.rerun()
    st.fragment(run_every=LIVE_REFRESH_SECONDS)(_watch)()


def main() -> None:
    st.set_page_config(page_title=f"{APP_NAME} · Maintenance industrielle", page_icon=page_icon(),
                       layout="wide", initial_sidebar_state="expanded")
    ensure_theme_config()
    setup_mpl()
    st.markdown(CSS, unsafe_allow_html=True)
    init_storage()

    user = current_user()
    if user is None:
        render_login()
        return

    if "flash" in st.session_state:
        msg, ic = st.session_state.pop("flash")
        st.toast(msg, icon=ic)

    # Streamlit supprime l'état d'un widget non affiché : on « réécrit » les filtres pour qu'ils survivent au changement de page
    for k in FILTER_KEYS + ["impute", "live"]:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]

    # ── données (nettoyées, en cache, invalidées automatiquement par le token)
    impute = st.session_state.get("impute", True)
    token = data_token()
    st.session_state["_seen_token"] = token
    df, rep = load_clean(token, impute)

    # ── barre latérale : marque, utilisateur, navigation
    pages = ["Dashboard"] + (["Saisie"] if user["role"] in ("admin", "technicien") else []) \
        + (["Administration"] if user["role"] == "admin" else []) + ["Guide"]
    if st.session_state.get("page") not in pages:
        st.session_state["page"] = "Dashboard"
    with st.sidebar:
        ui_html(f'<div class="brand">{icon_img("logo", 46)}<div><div class="brand-name">{APP_NAME}</div>'
                f'<div class="brand-sub">{APP_TAGLINE}</div></div></div>')
        ui_html(f'<div class="usercard"><div class="avatar">{escape(user["name"][:1].upper())}</div><div>'
                f'<div class="uname">{escape(user["name"])}</div>'
                f'<span class="badge {user["role"]}">{ROLE_LABELS[user["role"]]}</span></div></div>')
        if user.get("default_pwd"):
            st.warning("Mot de passe par défaut : changez-le dans « Mon compte ».")
        ui_html('<div class="sidebar-title">Navigation</div>')
        st.radio("Navigation", pages, key="page", label_visibility="collapsed")

    # ── page courante
    page = st.session_state["page"]
    if page == "Dashboard":
        page_dashboard(df, rep)
    elif page == "Saisie":
        page_saisie(df, user)
    elif page == "Administration" and user["role"] == "admin":
        page_admin(user, rep)
    else:
        page_guide()

    # ── bas de la barre latérale : options, compte, déconnexion
    with st.sidebar:
        st.divider()
        side_title("gears", "Données & options")
        live = st.toggle(f"Actualisation auto ({LIVE_REFRESH_SECONDS} s)", value=True, key="live",
                         help="Rafraîchit la page quand un autre utilisateur ajoute des données.")
        st.toggle("Estimer les coûts manquants", value=True, key="impute",
                  help="Remplace un coût manquant par la médiane du même équipement et du même type.")
        if st.button("⟳ Actualiser maintenant", **STRETCH):
            st.cache_data.clear()
            st.rerun()
        with st.expander("Mon compte"):
            with st.form("pwd_form", clear_on_submit=True):
                old = st.text_input("Mot de passe actuel", type="password")
                n1 = st.text_input("Nouveau mot de passe", type="password")
                n2 = st.text_input("Confirmation", type="password")
                if st.form_submit_button("Changer le mot de passe", **STRETCH):
                    ok, _, _ = authenticate(user["username"], old)
                    if not ok:
                        st.error("Mot de passe actuel incorrect.")
                    elif n1 != n2:
                        st.error("Les deux mots de passe ne correspondent pas.")
                    else:
                        err = set_password(user["username"], n1)
                        st.error(err) if err else st.success("Mot de passe modifié.")
        if st.button("⏻ Se déconnecter", **STRETCH):
            logout()
            st.rerun()
        st.caption(f"{APP_NAME} v{APP_VERSION}")
        if live:
            live_watcher()


# ══════════════════════════════════════════════════════════════════════════════
# 9. ICÔNES EMBARQUÉES (base64) — l'application ne dépend d'aucun dossier externe
# ══════════════════════════════════════════════════════════════════════════════
ICON_DATA = {
    "logo": (
        "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"
    ),
    "dash": (
        "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAMAAADVRocKAAAB/lBMVEUDAwMAAAC82v1VVFrH5/4AAACvy+3E3vpaa31jcoUrKy+D2fVIZgKZ2AQQEhTsyj792UOuIwB6yeP+5EZUWWTl5eeL5v5VEQDT09UAAAAAAAAAAAAAAAA4Q000Njo0PEaNo7qhu9iRqcNebYB5jKL+pBIAAAAZHSJzhZt8Sgd9kadIS1LStjgZIidjOwZgb4BxutLLy8ybs81qrsR+0OuMHAA4UAFwVBTBKAAsCQCGm7Gwly+ow9zR8v/0mhEtNAY4TwE4XGhFDgBcmKxxFwB1ZB+dIACT8/87YW1AJgRDXwJ7e3xjpLmBTQiIUgmCgoOPygSk6ATHrDXxzkAfMzoyUlxIPhNEcH9Qg5Ngb39/cSOWgim+pTT/80sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB2E2KHAAAAgHRSTlP9Af///3z/////////////////////////hS5X0////////////7D/////////////////////////////////////////////////////////////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAC3+mKgAAAX4SURBVHjazZp5Q+I4FMBjCG1BrSAVbZH7cgBFHe9j1HEd5z529j6+/9fYHE1a2qRNBXf3/VEgTd8v78hLCIClZxaQeLeWp1LT0eSRzjUvE6AGfEkleO6233Xb9fQBLge4KfpFx3jvREAegJuVlRsA8snDp6O3f8GXc2aFpw9Y+fZtJQXgEZ03l6WSDUC5/ANlePqA1dU0AFH4Z6VSWcOvb8oYQRoyAtwlj+VTPpYlSwOs7q9KqVQigDKRY/xmkNUCkSSyTLsk+gMAtaGWESBSJNoHk0+p/hCg/DoYSQbAwx8PcQCJ8FopCngTxDkDoPR3KQ5whQElHmTfBFcJcMV8cWcAa1RF3EOXlZgFZ8fCR0CedszdsxasVeSAiQ8g82DTl9cLAwQhqPwIZiUJsH+0nxVQmdgZAOvV9YwuqkyITsuXX+9SXLS+rAsYsCAz/S+rvjx+FHN5XgBLU67/aJnKUfXnpDTNBKATjcX3ZXWZy3riRMsEIEF4mET0V+8SS0U2AF9Ww/rvk4tdNgAt18AO6/+YXK69AOAG64EAeNIF7a7KAdXqbzNLGgV4g+3ZOcIARBiACgMo5Kf7I5qgR/cNvnIMPA7Ix7pnB2Av1d9ab+sz0znPADUwN8BWfKpRAH7TODQgl7YAGBYHWIYAtEVHIyRta9fXuWu1WdNhg6YEIAYMIYK9ApUeggKAChxQQAIAEe9pBgIRgocj3Dg6xG/xB9IEh8QEmosWQjvcql4AgAEABoAe77mDhDEIjzhkF6R3kEXzmwC6iHxg0k0DdHlPSwCQZQd+t2272Ca3UFcAsAX4w/nm5rmvKwmAG9+dnr4jw+L6nWjQ6a2QBRa1YPPsbFMP8Lnf/xxYwPSHTfAtiAHKZU3Ai1evXggA1e/M5FQsBpkB/b4AMP0ImeGkgosD+PqhRBYCoNkn168EILHoRyba98p3v/FTv/+JAkyo1q8C0KrAti2kVLz/+vW93zgpTfzGIMh4BlgK/XFAuFTZkRIma2QxgCr9SoC2KIcuA8D2rqoI21ILbMBmkzYASXqzAmYoBKbojwB4uQ5JG5k9coWmVCA0MwCCch3yEG0cKp9HUGq3PmCYCECtpm03W0jfRVbXCkm3S5zTo1fp0yM2ihHSBaC4sEb50wa300CagGxyjQsGOD6mswFpA0xTUz1dAP0FCjQ7CGkBUrMitMQ3qXeoBaTaGUgnBqlZEeRP9NuYXZDNushM7qVmBXfPlPQr+Fl0cVUnL8WLuPGzAJEVKRWAucduIdSq23Yd+x9dFMlz9Vg+xyba7v4+rnjOVVIgmHuaBgrFDMEC9Znlj43ndqxcW4+PtGiPWyYyk9wzjQ4BGXTnMuyRTSPqFAodokBhAfXojiEzQ7hHQu7QxMIpC2lM6rgSKmLAMtB2DgVCmBy4R2Zcb0j9xJ4HdRTNIlFbDh2Whc0RdbFvMn6l7vldYhor3gjyVXFvD186SDYP6i2y9Bg7RVZOCyTgvslK99CtNV5/sE/atO9ev79HNiLqmWwi2BqzwYxbdfamMVS5h2yt/R01TtldNWBmhULoqjDkYTk5Ya9TeQKHd9TXHaWLJAvWiAXsZHX1ROUeMizmen8PgOqKIMszgwb8lgIahiw7iVybfAWlXlCkqWLiXrdw79tbanL8brsw7eJ1kH1l4wbJJ5q6NgQmx2UYLqk7sXmjuaL5JkNtgKTYTVV7H/oFlZos6UFcFEgPxW5PAwuU2zfDSNreRfaB0buBBcAGzyA2CADPJv8WoJgb5xYu41wxADi5XKPIpZFzxuQ6rzhhgNMI2dVw2HWRgNwzAsiBV85ZvIucHGDnReTEy36OINv+iZfszG5RUlOdOi5sFqjOTdOOFnVKS+jcVEPwAD6YB1u+HJgfJD/ZPeUH6/B59sFGSA5kp9hzAHCUGhtbQa3f2mik/QacDTAA4Mss4EvogH0BgKiHMvgI6HpoS4SYhnlL10dA98d6W5Wz7lwAnen0vwckl7SsgJqbD8TNkxAUE4UEIT/zUC0JkF9UifvPAPzfMvNI7UnF7unyD9D4sYRq6MUdAAAAAElFTkSuQmCC"
    ),
    "interv": (
        "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAMAAADVRocKAAAB/lBMVEWNXPqDT/WBT/RlYuFuZfRLm/kraewftLQPpO8AAH8/P78AVao9n/M8sfo7sPwq1P9/P79zX/F/T/NAofZmzMxEyP8AAAB9ff46qPcAAP8A//8/f/9LmPhCuv5Uqf44pfM9s/5Kpv44pvM5pvQ+vv5Vh/Y5pvQ5pvQ4pvNtd/s3p/JVqqoAf/9Fl/NQiPNXePVrhv5waPdVVapEl/NFl/RGlvRVVf9Jlfc1mflrZ/JQiPJZe/JShvN///95WfZRh/JGlvRce/RGlfRraPNcevNbevJRiPRic/P/AP9ic/Njk/+LVf3///9QiPN3WfN2WPFsZvRrZ/JkcvN5V/RsZ/M9nPE/f79/P/+FaP9Pi/NraPQxmNJcevN4WPJmmf+qVf8Af39cevQ+nvNjcvNJtP9+S/JuY/NjcfSETvc+nvI+nfI+nvNAo/iCTPNUf9hCovdV//+CTfU5jeQ+nvMqqtQzzP9BovVniPiATfODcf8qf9Q7sPtaffRIkdpCovp2XfQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABGnH71AAAAgHRSTlMWSaAR018GAwUCBANbvt8GBEugvgX/AAP2AQEE+f4Db/7+LtQE9pRNr/oTAwItKgz/9QNusdUDEwlwEyuwAvZzUumRrq1xk28Brf/+AVsRJxIoLpSUKwQE/tVYB1x4BQMClc+TCBXOXfJwru2QkQgtA3IOmgYFUA/O/wYqywfNttmbuEIAAApVSURBVHjarZr3Y9pIFsdJ293r/UkzEgIVIyyECaYpxDiE3OVyR+LYScCx2cQ+r5NLL5tsytZ/fd8bSSDJAmOS7y8IgeejeTOvDc4ASPD5pLjJOxkc/zfdWq/35k3hU5WzHQAtCZCg3NCziyqPiryTC06SkIGyqqv1Wq32+HHu5CrKslwI3xTMfFa2E4RMu6HXy4ua3DLzRWfy1rHNfD4HwxigpqptGCmKdXJ5SiFrDsEL3+Ojs4KMhOgcMnW9Bt8v9vyMmXkbvMgNTYJcXjZYKQJoqF2uLTQ+B0/GwWIbk4+gmC1CJwLYUbvucEGAgwBeit3UuIE3I4TMmt6DymIm2gczm4NW/GYJp5ADawK4oaplYNIqqnRC/dRBgzvAO1ErWTyHNppMKzNcU9Xu/UX3qZk37Xio0cDOmyyyBqzdUNVGPaonT4rzykRHM4sGuBGAkce9O0ZkXGj3VFUnBS8nDRX5fxQiNhcAJQKgYNrqXsJYgS5XC3WiuIExjs8AQOgGiqq2FlwKDqxDclMBhFAUT2njflIqiuJ/MLRG4b4I52/58WRyh1vWEVYqwH8IApDByqhBGSftGSQMZk5wQX/FwME7g/AjI7jwv2scD6hAjRZbxQiFgYBkHjrBhcM4cObIJhjiRt4E278oQiEvLnIwOhbQQwAi6lDW/YEdIx9c4JdcGpzb/p0ihTZSIbj4ow1vZwCW1BUBqN33ahhAXupPPc8TANOyjDjA9BwPF8DOFh2HbAbf0he+mG2iENBraQQo6081beADRGCLARyLxkWAiNPwFd3/Cr8wB0ANTDTAl8BE5ncUJB1mlRImQgB/xXFDuOIL/BjAUgRQw2SNL091UzNkcwTCRBBbA1rkMPi7ENjweMBVvUcb9RoBdP3NS/wL2bTE3zvFHAtN5O/OAOCeDFCj91jO6I2erj/Dva77AMvImhAAiv5fBWsw3wwq4xlIFUkigIpOodeHhi6bJsZNDy0jLlz/whS7078QT+DNBbiEM1BoBi21oUFXV3EDYoiV8zJtVYqeJjPEK87HzgcXGm4z0+PsWACOu+JHIwblFj7YYICBwTZs28Y4YIgLihC2LS74+AIXRwTV4wHJ2HVCHQ9gq+EtifIULgZIGgnfdcKLkrjYx/GERDpw3fkAVFBN1WeZAZudWj4ZgN+5H8pLSPvUGVyEJmuv7fhqxHVAG96MFhALARRYWVpS49LHkrFoUxYHXA4BK2OVozIGxaw9DeCKrN9hxwEkAkx9vCdTAWPDWfMA3q/+djWisBb9e6k+DcCCwuAH3AYzAJcDQFtqSkm5rmu50wAdyMlhZTAPYGq/UM++SwA0jv4uEqoIq7QLENByFTYVcBE300pCwSq36no3DhDZTOuIbOH8yXFz2QIBfKtNByQU3bG1GMACm2rrQw1TnEY4TEBDBOT+UGCMHwUsk6O9/3EWoRyNtyMsvPJ5bI2pJ8CIrTB69bNGcd/lCYC0vEwzgDPtSnuiVkwjiD8/FnXFvJzD/riILkbpG/tyqsTwg/3rPBXAYM5gVxLjA1aNKJm6Y84davaxkRUfuWSllBkwPkOxXokG6dCrXDBCd7CLMjb/h+LDkRsBXB8D5mwJuIZDWNddJHkOPSB3XRHqf6BbwnzkNHHALQIc8bEptmrRpv/OT6uKZonJYaPBqb8Ft3Ro5qmdTQHMnXxzenC24oomyXIsxLn7Lk6DdzpFrF/RpEcADCoXJyIva08hUMuNyymJUOfkRMNZsP2416GGwQAORwAKVJZJ5yNu0E6dF9MUzdTxKRl+nCN/wP2fpRWW4BVVZDaMWBxQRYDGpLPLl0OJ8XcqaZlYZM9cFh0Y7YM71cxhMMUtlKekZyFAxIsOjwA2q8EavJcqE0nTLKR4g8GBjhmuRI+bC9zHwN7fwQLGwXbKcKzYDBCwlepoKa53ndcalEux3lWokMxhx9lxXc0CdLUCaK+gkBUdhBMDVLeEo8XFWZp9utTJNX5+DC4aCEtsL7DiWwxLSNW4QVUyekoKoOlLS5dYbwXL7kaZ/AuX51DWbT6cBHB//2Pz6xi4EimAec5fcQZ1fyoSvPTr9nEELGBOUEBEFfsoYJVVvvmPr3+GWouofoOeQcxA+pL7IUmPHt/gBgrOi5jl2mkz2Fo+v3w+pv8KBRlnR0QGAmiWxGcAuOtpaQDGdv8d6l+hLo1VWyFrCIC/wSQY6E+dpIksv44xFl8DBHQxSdMia41IpuYdi846cZYjx7ALqYBJyaKkSAo6RDrQUNU6l76EXvZgfOyukdd58Aq3qcichRSA1FydIRYUcjfqjYbI0RYbqHoPbYN72KKkSYfLGmAmlc1iYeJo105iIj91Kq0GjqyVqBd9FhxhY5oxD93fUaFkj2JJPwQw2Ly1tbV1K6Jo7Mbg7c8B+yZaCbVFwQ4JegEbxBwFO0cEO2qpeUfhEcAGAf5MIam6HBft1bCCWYNm2MIBzqDeEsdo3Z/1bJbOE+WCB67I17Lvz3HATfzrzYfVQOH4keC9s3Q1tCKTKg290RL7UYPhu2d/OzCLOUMkTH+tbSr8ooB1BEjiV5GJKtHQjWXSi/EqrMJVWmOajyZNeivN1XwHx1V2+H4KgMFchREm/SX1kjj2pp2HG5iaWkucKeKkMPolkj4B1m8e18ZOWlDGX+yo9TY0MZx3y5HUYZ3z0O0syqLkcCmAvWaawnA9adOx0FcblO966HDdF1yMP3hmZjFpvqXxCzRa2gzmlE9oYU1Pua0GQzTN4KlOR4m2P34JjgJW2cadK3HFovfa15NnoIZR3dnR1W65julBE4lOt+mos0jjK5AC2Iab1bt3j7rBOHT/OPYDQaDEiSvQ1Ru85HoSvsJLnEMWI+qQpQEwXP/lQlKR6H3uYrSGGcJKr9eGltRVRfSGWrauDXTz989sKDFIBZzs8MaPrSK4llvYZPWydBx6ENnOKYCjHWYkeidLYYmqXfSJSI9VRv+2FJgOWEASdANAvUWAtDb2GjxIAtj29nZyBtMEL/weCyyFAMoXlqLx4wALauCna9FEzwIw2NjdxS20G+j/Ql9PdCOhbiD/p5pztXei74kB+lHANtz5GA3aSY/wy5m0Q5/glybMQSOIJpwH/f6ZCECC3SuUGh6mu3SiIPOrstiPZQ09i91DJmKRR/3kGmzuImDRtWjZMpZgmYjNP/RPse3o5kPaVrV6QVpI2KoNMDJlIjZ/3n8Oe/GnOAMXqldgdbGfmzV4kp3URTj0qf6jB9fiNmpKN6sPV4EtRFDcmn6QiVik+aF/GjKxwZpsq/qwuSiAd2OAPcg86r+Gvb3ob6lw7+6VRb3ve+jp9Uz0cXEVHr0m1HagTdg8e/fe9sb0pZwRPTz4VtW7UQDbQ0L/9KmNya2NX6pnm4vu0zLWTT9lYrdW4fWjfv/DX2/f83V7fX39F3ydkoJS+oewjUDVsf4uQyYZdzPPEUG6K7Re9V8/fpwdMiZN0CRcqPUySAkA+UHm1OvTp28ndCehb4T+F+pqUr1er1YWD3wkd+x9vn8G4rj9fgXmEKEyUb1tDgAAAABJRU5ErkJggg=="
    ),
    "cout": (
        "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"
    ),
    "duree": (
        "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"
    ),
    "taux": (
        "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"
    ),
    "machine": (
        "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"
    ),
    "tech": (
        "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"
    ),
    "piece": (
        "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"
    ),
    "add_user": (
        "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAMAAADVRocKAAAB/lBMVEUAAABNzuDU4fRQ1uhLzt44KU8A///Q3fD///9IzOB///9V///i8f9MzuA/v79SSGrg7f4/v//V4/VVqqpN0+RLy9tN19mQ2Ommq8PV4/Z/f/+dobrW4/bX5PYrG0FLzN1N0eJMzuBN0uNN0uJhWXpw1OW0//9Mzt5O0uTO2/FMydlL1Om/v//M2/AAf39dVndVqv9Mzt5Mzd5O0+TW4/Y+MFVMzd5T4PLU5PfW4vVJt9RMzuCqqv+/v7+s2+4AAP9NzuBpZIR/f396d5SxuM8zzMxNzeGKiqWqqqrQ3fE/v99EN1tOzeFP0t5/v79kzOWhpr7U3/PS3/IAf/8pGD8qqqo8zeA/1OlKP2JVqtRItrZN0N9mzMxz0uaEg5+anLaV5vm2yNrR3vLS3/Pf///i4v8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACSZTXsAAAAgHRSTlMA/v79/P8B/gIYAgP/rgT//gStA80wCv7/LwL/bMr/T66OdI///wOLMi0TFQQWAv8DrtJTjv9x/xZPC3cDBP8B1/8C//8FOf8DUgj/UigEFP+9xgL/BocM/wYHgwUz////DmWaCAkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPdMfvkAAAU6SURBVHjatVh3X9pcFD4Z3MQQkBGwUEYYKoqgiAquqrVq7W7fvff3/wrvSYjMm9ybm/T5ByP8zpOzB0AASBLA6DTta0lSVclqDdfw2YDYcADQbVqKC2ny0eoAJK9ikp+E3ZYjWkVIkvuBj3YBtYhDPMlDHeW5sqdwOVrfQT4G+QQay+InHJJiFVC7qPINYo+kVfEuhaJEZrhKQ2uk0uV7DEZE/26PJH8gQ5H0I8Un+lcNZBjoBxEcUN4Nlo9QTiK4AQ3Eko9G6pKXgvLLUGQqgAzbkBYkSLMVcAjULhBBhuIhmwAZ6oIqJDGE2PLRzQPBipGFX/gIpB/EbPQNpLgIVOVeKJ0JnwscgndCTiCwq3ISnKM5RbKgIHESNIQIDHjPI36SamIadL6uBugD6av6AI10zUUgYRQJFdQ8DDgJ3ou1tSyc8xCoyrVgNTWgwFcqGqL1mpBDReKqpknRfnDCoYJyeCfaDgg5Uzk6Wl24o6HmJ+yefHgXYTJiRqo7ekUYUA3SZcxFoxNxA3FMXqqSgiSJQoDZ5s+AI7xdLEeTH8SgqiP7DfQhKtJQsCj7gbuBQAzyHQZng1LnOdwFx6pDn0AcwDC8t5XpGqU6walYzZ+irzfTlMYJvdPy1kwX9vANxLGgzRICs/WqMzxv2KlUo9nZddKcQKwwFvIpH7N4YiSz2btisVs8Oysifs1m0/kFCr2sI8q60LtnfaoZSR+4JGV9b/oLfe8yXO0jrmW6nWFze3uQ8jBobDeHhaIbw4buvvW/451SaWf8n0tyya1I3wnETtNWqLBaw4/Or8anR1XZQ/XotIT/4qNwbixrkyPI051ilmjuvUKxvv/tNCdnTHkKMyPnKj1Ugyu/Ci03veibuOpU0z/lTEZehikjhc5aDZPwc1OhXilmemxoq9IRmkMBsBUcmHBvBYrH138h+8PM9WAvaPKFZrB4Sd3UAuRrqNujP4MBZ7YiBXfjTZmJRz8roXwr+PV55KOCf9ODyYBdizGu8Ly/w/BIYyDGGlO+InOitMpwlQSbOc+94CWo9l7rqxPpiDUubtANshpWmvnPsgp5HNrFDKRpPkbaWnRAkbk4qTQDaTdv397QKL7oeth5lxpB+7VEotamfXM6b6QyYRqI5gFNfpU4TiBeUfzweZ6A44gmKTQHP0+4eEYhmA/VPnQVEQsFEpiVmZt5Fkuai4M1+DLbckmS44KjhSWQe051nmwDBYW9VK7k1yqB5hNHWWiwLbQph9Vg5oQ+sBfjhSDVZO123cWPE4LJw/rtAo155BFw3bgWs0BbryUoqO3P/yiT80yUhw7HIXZjXoE/asc0guPapzlbTQnSMGSfDhYJfk/44IFGwOPjJYLnfho8o2vQCKeBV+MoPrhZnGDg0itEg9AE2kO73d7fb697UeT83W4/0KMoz3PqpRdr85OXB6ZMzYM9b5rgIVAofWwp0ZZ7Wwku+AmoDZ9Ri8aek/kIaB0/kGAaRLwEYftB5skFvCai1OtgE43DaRC2J2MWbEE4AupY1MaM+/aG9s0OvA5H4DPY3S5X6akCF7OhMeUuZExIWpjJbjZ4uVMjFzZ5Z1Mni+emopdQt7i8oG5k+IZrM6cvTI64eXbXePDxs6lxbSA93VjejfkwrmY4GDCC9NV7Mg8+QK+a4ZF/KXrguUAGM9g+GZS/J35CuoC/coE6mNVI8t1rR0UOUOLoQ/AtgYNBh52c7KNFbofr4MJWopRb1cKUq6f4ZRxXvTKWsVKlurS5HpVc9eLBhWPnUuXp5FXNVUo6Xfz/mGKAOyN1Bb8AAAAASUVORK5CYII="
    ),
    "donnees": (
        "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"
    ),
    "present": (
        "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"
    ),
    "kpi": (
        "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"
    ),
    "analysis": (
        "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"
    ),
    "monitor": (
        "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"
    ),
    "chart": (
        "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"
    ),
    "user_cfg": (
        "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAMAAADVRocKAAAB/lBMVEUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA9GyJsAAAAgHRSTlMA/s9PrY4ubwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACeg1ccAAAIZSURBVHja7VnZcsMwCIyW6///uImbNoljCXQwzUy9j3ULAolloZfLiRMngiABSilgoQzrXJ4A0bXm9cX8Bllp38oBsC4ILsegZPulWLL9NTFIaWH+HrRpv2DaAdoOppNEjv3pENhzMBmCuvYLry/hHZIzNJkjBBxMlXPA/hytRhxw7iOafEYfkSL56FckAQeaynWzlXxJvoIIV0z2NM3uB24I80059QbchzTf851aWKMeJdl+tXEuVL+E5d3eTROWTzn2HAVnDFEXJeErxFKs/yWUNqQNt0gZCw/pljMc8IrKJmPUqhfTMvV1xH9Lw6zAMFQIQm0rB35jv/uHQfO/ad74D+/tjrmjTRwsKH4CoBWdmhoiCAumEmm0YFsgx6T1ZwsksbRSu/8IMeG+diqtY+3EGOth3mREqtjBV6tUNUbE1oEDq/EGRuSiOASqsRSRVz9SvUoOXTLc1221PFBEM1HgdUstD5EbRoBjqMbPgTeqkaHbnAh4dLCkXZRcOx0NjsZ3M6hxmvmvNJIhVJskfMImnyKpSssWqGTxtwZWoxyKcBF3RvBUUhbqmui7g28tv4kJxHYkCPTyyAYDYwscCi8jdcwBoqs2Hl1BUXCPpKMrKMTOYeMrKHscBKb747DeftSeQPsUFfWPztZ3feiX71x68jsygKDHg43sB70YpPLLHYNHjzq/DnA3cN//Tx9jX9Ym7cSJ/4YvwLUQVKuYT6MAAAAASUVORK5CYII="
    ),
    "filters": (
        "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAMAAADVRocKAAAB/lBMVEUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA9GyJsAAAAgHRSTlMA/c4wsW+QTQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1jedQAAAGsSURBVHja7VnbssMgCFQE/P8/Pj2TNmNqUBPZtg/uWzoZKHJxs4SwsLDww0jKFCOxJIj5zHEHA1xoPEC87XN8g4LtO3uQeILsWD77yaf/Wno9uSeYX/7IO9FH+w9sHsitAzYHqfWLkTumEVQB7CHs4DxcGyak0XZGQi7ZP1blyX+bdtCJII61ZwNa56AEh2kPZ53Xtv94cQi5CuEZQPGOy6hT69ltFm3Vnsl9FhVFQ4S5c+qqsdLq5sHZflXS7vaP04FyQEC2KIzR6VSwUz2VRVVBtK28y0kQ9hXFSIwyV7B9bw/Uu8C8WohFdHfmWE3HU8nkPQzk/dTJedzT+x9OblmQgriluiloHCzd+XhCRu/TphPixaHJSq6xmo85YM8j6jK71Gaet+w/mZ1Vppou4KuNBh8V+GEHH9f4Cwd/ZeIvfTxtwROvT1DHL5NfNH1Hf4BUrUhg+84xoD9j4R/icCnBEEP6eZZB3mbJOcUrXWY3LUjNa3Y3JDW4KMieEcxrdnxHfBljbWJJy9lLs0OL43h5H76ggK9Y8Esi/JoLv6jDrxoDfFm6sLBwAX9Zeg5EcdVfbwAAAABJRU5ErkJggg=="
    ),
    "gears": (
        "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"
    ),
    "support": (
        "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"
    ),
}


if __name__ == "__main__":
    main()
