import json
import os
import re
import sys
import logging
import tempfile
from datetime import datetime
from io import BytesIO

import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

USERNAME       = os.environ["AICS_USERNAME"]
PASSWORD       = os.environ["AICS_PASSWORD"]
GOOGLE_SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

LOGIN_URL  = "https://www.aicsnetwork.net/aicsnw/default.aspx"
SHEET_NAME = "Lista Soci"
META_SHEET = "Meta"
COLUMNS    = ["NOMINATIVO", "N° TESSERA", "TIPO TESSERA", "RILASCIO", "SCADENZA"]

SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


# ── Helpers HTTP ──────────────────────────────────────────────────────────────

def estrai_viewstate(soup: BeautifulSoup) -> dict:
    return {
        inp["name"]: inp.get("value", "")
        for inp in soup.find_all("input", {"type": "hidden"})
        if inp.get("name")
    }


def naviga_elemento(
    session: requests.Session,
    current_url: str,
    soup: BeautifulSoup,
    element_id: str,
) -> requests.Response:
    """Trova un elemento per ID e lo "clicca" (GET diretto o POST __doPostBack)."""
    el = soup.find(id=element_id)
    if not el:
        # Ricerca parziale per robustezza con prefissi ASP.NET variabili
        el = soup.find(id=re.compile(re.escape(element_id) + r"$"))
    if not el:
        ids_disponibili = [t.get("id") for t in soup.find_all(id=True)][:30]
        raise RuntimeError(
            f"Elemento '{element_id}' non trovato nel DOM. "
            f"IDs presenti (prime 30): {ids_disponibili}"
        )

    href    = el.get("href", "")
    onclick = el.get("onclick", "")
    log.info(
        "Elemento '%s' trovato: tag=<%s> href=%r onclick=%r",
        element_id, el.name, href[:100], onclick[:100],
    )

    # Href diretto (non JavaScript)
    if href and not href.startswith("javascript:") and href != "#":
        url = requests.compat.urljoin(current_url, href)
        log.info("GET %s", url)
        resp = session.get(url)
        resp.raise_for_status()
        return resp

    # __doPostBack dentro href o onclick
    for testo in [href, onclick]:
        m = re.search(r"__doPostBack\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]*)['\"]", testo)
        if m:
            target, argument = m.group(1), m.group(2)
            log.info("Postback: __EVENTTARGET=%r __EVENTARGUMENT=%r", target, argument)
            data = estrai_viewstate(soup)
            data["__EVENTTARGET"]   = target
            data["__EVENTARGUMENT"] = argument
            resp = session.post(current_url, data=data)
            resp.raise_for_status()
            return resp

    raise RuntimeError(
        f"Impossibile navigare '{element_id}': href={href!r} onclick={onclick!r}"
    )


def is_file_response(resp: requests.Response) -> bool:
    cd = resp.headers.get("Content-Disposition", "").lower()
    ct = resp.headers.get("Content-Type", "").lower()
    return (
        "attachment" in cd
        or "xls" in ct
        or "excel" in ct
        or "spreadsheet" in ct
        or "octet-stream" in ct
    )


# ── Lettura file ──────────────────────────────────────────────────────────────

def leggi_file(content: bytes) -> pd.DataFrame:
    try:
        tabelle = pd.read_html(BytesIO(content), encoding="utf-8")
        if tabelle:
            log.info("File letto come HTML (%d tabelle).", len(tabelle))
            return tabelle[0]
    except Exception as e_html:
        log.warning("Lettura HTML fallita (%s), provo come Excel...", e_html)

    try:
        df = pd.read_excel(BytesIO(content))
        log.info("File letto come Excel.")
        return df
    except Exception as e_xls:
        raise RuntimeError(f"Impossibile leggere il file scaricato: {e_xls}")


# ── Pulizia dati ──────────────────────────────────────────────────────────────

def pulisci_tessera(val) -> str:
    s = str(val).strip()
    if s in ("nan", "None", "NaT"):
        return ""
    return s[:-2] if s.endswith(".0") else s


def pulisci_data(val) -> str:
    s = str(val).strip()
    if s in ("nan", "None", "NaT", ""):
        return ""
    return s.split(" ")[0]


def estrai_colonne(df: pd.DataFrame) -> pd.DataFrame:
    mancanti = [c for c in COLUMNS if c not in df.columns]
    if mancanti:
        raise ValueError(
            f"Colonne mancanti: {mancanti}. Disponibili: {list(df.columns)}"
        )
    df_clean = df[COLUMNS].copy()
    df_clean = df_clean[
        df_clean["NOMINATIVO"].notna()
        & (df_clean["NOMINATIVO"].astype(str).str.strip() != "")
    ]
    df_clean["N° TESSERA"] = df_clean["N° TESSERA"].apply(pulisci_tessera)
    for col in ["RILASCIO", "SCADENZA"]:
        df_clean[col] = df_clean[col].apply(pulisci_data)
    log.info("Righe valide estratte: %d", len(df_clean))
    return df_clean


# ── Upload Google Sheets ──────────────────────────────────────────────────────

def carica_su_sheets(df: pd.DataFrame) -> None:
    log.info("--- CARICAMENTO SU GOOGLE SHEETS ---")
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    sa_dict = json.loads(GOOGLE_SA_JSON)
    creds   = ServiceAccountCredentials.from_json_keyfile_dict(sa_dict, scopes)
    client  = gspread.authorize(creds)

    log.info("Apertura spreadsheet: %s", SPREADSHEET_ID)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet   = spreadsheet.worksheet(SHEET_NAME)

    worksheet.clear()
    df_pulito = df.fillna("").infer_objects(copy=False)
    righe = [
        [str(v) if str(v) not in ("nan", "None", "NaT") else "" for v in row]
        for row in df_pulito.values.tolist()
    ]
    dati = [COLUMNS] + righe
    log.info("Carico %d righe + header...", len(righe))
    worksheet.update(dati, value_input_option="USER_ENTERED")
    log.info(
        "Caricamento completato: https://docs.google.com/spreadsheets/d/%s/edit",
        SPREADSHEET_ID,
    )

    try:
        import zoneinfo
        ts = datetime.now(tz=zoneinfo.ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        ts = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    try:
        meta_ws = spreadsheet.worksheet(META_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        meta_ws = spreadsheet.add_worksheet(title=META_SHEET, rows=2, cols=1)
    meta_ws.update([[ts]], "A1")
    log.info("Timestamp aggiornamento scritto: %s", ts)


# ── Flusso principale ─────────────────────────────────────────────────────────

def scarica_soci() -> None:
    session = requests.Session()
    session.headers.update(SESSION_HEADERS)

    # ── 1. Login ──────────────────────────────────────────────────────────────
    log.info("GET pagina di login: %s", LOGIN_URL)
    resp = session.get(LOGIN_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Log struttura form per diagnostica
    form = soup.find("form")
    if form:
        log.info("Form action=%r method=%r", form.get("action"), form.get("method"))
    for inp in soup.find_all("input"):
        if inp.get("type", "").lower() != "hidden":
            log.info(
                "INPUT name=%r id=%r type=%r value=%r onclick=%r",
                inp.get("name"), inp.get("id"), inp.get("type"),
                inp.get("value", "")[:40], inp.get("onclick", "")[:80],
            )

    data = estrai_viewstate(soup)
    data["Txt_UtIn_Id"]     = USERNAME
    data["Txt_UtIn_Passwo"] = PASSWORD

    btn = soup.find(id="Cmd_SingIn")
    if btn:
        log.info(
            "Pulsante login: tag=%s name=%r type=%r value=%r onclick=%r",
            btn.name, btn.get("name"), btn.get("type"),
            btn.get("value"), btn.get("onclick", "")[:80],
        )
        onclick = btn.get("onclick", "")
        m = re.search(r"__doPostBack\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]*)['\"]", onclick)
        if m:
            # Pulsante usa __doPostBack invece di submit standard
            data["__EVENTTARGET"]   = m.group(1)
            data["__EVENTARGUMENT"] = m.group(2)
            log.info("Login via __doPostBack: target=%r", m.group(1))
        else:
            btn_name = btn.get("name") or "Cmd_SingIn"
            data[btn_name] = btn.get("value", "")
    else:
        log.warning("Pulsante Cmd_SingIn non trovato nel DOM.")

    # Usa action del form se diversa dalla URL corrente
    post_url = LOGIN_URL
    if form:
        action = form.get("action", "")
        if action and not action.startswith("javascript:"):
            post_url = requests.compat.urljoin(LOGIN_URL, action)
    log.info("POST login a: %s | campi inviati: %s", post_url,
             [k for k in data if not k.startswith("__VIEW")])

    resp = session.post(post_url, data=data)
    resp.raise_for_status()

    current_url = resp.url
    soup        = BeautifulSoup(resp.text, "lxml")

    if soup.find("input", {"id": "Txt_UtIn_Id"}):
        raise RuntimeError("Login fallito: ancora sulla pagina di login dopo POST.")
    log.info("Login riuscito. URL: %s", current_url)

    # ── 2. Navigazione verso TUTTI I SOCI ─────────────────────────────────────
    log.info("Navigazione verso TUTTI I SOCI (ctl00_Mnu040_Link01)...")
    resp = naviga_elemento(session, current_url, soup, "ctl00_Mnu040_Link01")

    if is_file_response(resp):
        log.info("Risposta è già un file (download diretto da link menu).")
        df = leggi_file(resp.content)
        carica_su_sheets(estrai_colonne(df))
        log.info("=== PROCESSO COMPLETATO CON SUCCESSO ===")
        return

    current_url = resp.url
    soup        = BeautifulSoup(resp.text, "lxml")
    log.info("URL TUTTI I SOCI: %s", current_url)

    # ── 3. STAMPA LISTA ───────────────────────────────────────────────────────
    stampa_id = "ctl00_ContentPlaceHolder2_Tab1_Tab_Soci_Lnk_Stampa"
    log.info("Click su STAMPA LISTA (%s)...", stampa_id)
    try:
        resp = naviga_elemento(session, current_url, soup, stampa_id)
    except RuntimeError as e:
        log.warning("%s. Fallback: cerco per testo 'STAMPA LISTA'...", e)
        el = soup.find("a", string=re.compile(r"STAMPA\s+LISTA", re.I))
        if not el:
            raise RuntimeError("Pulsante STAMPA LISTA non trovato né per ID né per testo.")
        href = el.get("href", "")
        m    = re.search(r"__doPostBack\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]*)['\"]", href + el.get("onclick", ""))
        if m:
            data = estrai_viewstate(soup)
            data["__EVENTTARGET"]   = m.group(1)
            data["__EVENTARGUMENT"] = m.group(2)
            resp = session.post(current_url, data=data)
        elif href and not href.startswith("javascript:"):
            resp = session.get(requests.compat.urljoin(current_url, href))
        else:
            raise RuntimeError(f"STAMPA LISTA non cliccabile: href={href!r}")
        resp.raise_for_status()

    cd = resp.headers.get("Content-Disposition", "")
    ct = resp.headers.get("Content-Type", "")
    log.info("Risposta STAMPA LISTA — Content-Type: %s | Content-Disposition: %s", ct, cd)

    if not is_file_response(resp):
        log.warning("Risposta non è un file (len=%d). Primi 500 char:\n%s", len(resp.content), resp.text[:500])
        raise RuntimeError("STAMPA LISTA non ha restituito un file Excel scaricabile.")

    log.info("File ricevuto: %d bytes.", len(resp.content))
    df = leggi_file(resp.content)
    carica_su_sheets(estrai_colonne(df))
    log.info("=== PROCESSO COMPLETATO CON SUCCESSO ===")


if __name__ == "__main__":
    try:
        scarica_soci()
        sys.exit(0)
    except Exception:
        log.exception("ERRORE DURANTE L'ESECUZIONE")
        sys.exit(1)
