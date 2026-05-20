import json
import os
import sys
import glob
import time
import tempfile
import logging
from datetime import datetime

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# --- CONFIGURAZIONE DA VARIABILI D'AMBIENTE ---
USERNAME      = os.environ["AICS_USERNAME"]
PASSWORD      = os.environ["AICS_PASSWORD"]
GOOGLE_SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

LOGIN_URL  = "https://www.aicsnetwork.net/aicsnw/default.aspx"
SHEET_NAME = "Lista Soci"
META_SHEET = "Meta"
COLUMNS    = ["NOMINATIVO", "N° TESSERA", "TIPO TESSERA", "RILASCIO", "SCADENZA"]


def crea_driver(download_dir: str) -> uc.Chrome:
    opts = uc.ChromeOptions()
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-features=InsecureDownloadWarnings")
    opts.add_experimental_option("prefs", {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": False,
    })

    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        log.info("Chrome binary: %s", chrome_bin)

    driver = uc.Chrome(
        options=opts,
        browser_executable_path=chrome_bin if chrome_bin else None,
        headless=False,
    )
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": download_dir,
    })
    return driver


def leggi_file(file_path: str) -> pd.DataFrame:
    log.info("Lettura file: %s", file_path)
    try:
        tabelle = pd.read_html(file_path, encoding="utf-8")
        if tabelle:
            log.info("File letto come HTML.")
            return tabelle[0]
    except Exception as e_html:
        log.warning("Lettura HTML fallita (%s), provo come Excel...", e_html)

    try:
        df = pd.read_excel(file_path)
        log.info("File letto come Excel standard.")
        return df
    except Exception as e_xls:
        raise RuntimeError(f"Impossibile leggere il file: {e_xls}")


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

    log.info("Svuoto il foglio '%s'...", SHEET_NAME)
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

    # Scrivi timestamp su foglio Meta (letto dalla webapp)
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
    log.info("Timestamp aggiornamento scritto sul foglio Meta: %s", ts)


def scarica_soci() -> None:
    download_dir = tempfile.mkdtemp()
    log.info("Cartella download temporanea: %s", download_dir)

    driver = crea_driver(download_dir)
    wait   = WebDriverWait(driver, 60)

    try:
        log.info("Apertura pagina di login: %s", LOGIN_URL)
        driver.get(LOGIN_URL)

        log.info("Inserimento credenziali...")
        log.info("URL pagina login: %s", driver.current_url)
        wait.until(EC.presence_of_element_located((By.ID, "Txt_UtIn_Id"))).send_keys(USERNAME)
        driver.find_element(By.ID, "Txt_UtIn_Passwo").send_keys(PASSWORD)
        # Stesso approccio del copione locale che funziona su Windows
        login_btn = driver.find_element(By.ID, "Cmd_SingIn")
        driver.execute_script("arguments[0].click();", login_btn)

        log.info("Login inviato. Attesa caricamento dashboard...")
        time.sleep(15)
        log.info("URL dopo login: %s", driver.current_url)
        log.info("Titolo pagina dopo login: %s", driver.title)
        driver.save_screenshot("/tmp/screenshot_dopo_login.png")
        log.info("Screenshot post-login salvato.")

        log.info("Click su menu SOCI (ctl00_Mnu040)...")
        menu_soci = wait.until(EC.presence_of_element_located((By.ID, "ctl00_Mnu040")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_soci)
        time.sleep(2)
        try:
            ActionChains(driver).move_to_element(menu_soci).perform()
            time.sleep(1)
        except Exception:
            pass
        driver.execute_script("arguments[0].click();", menu_soci)

        log.info("Click su 'TUTTI I SOCI' (ctl00_Mnu040_Link01)...")
        time.sleep(3)
        tutti_soci = wait.until(
            EC.presence_of_element_located((By.ID, "ctl00_Mnu040_Link01"))
        )
        driver.execute_script("arguments[0].click();", tutti_soci)

        log.info("Ricerca pulsante 'STAMPA LISTA'...")
        time.sleep(10)
        try:
            btn_stampa = wait.until(EC.presence_of_element_located(
                (By.ID, "ctl00_ContentPlaceHolder2_Tab1_Tab_Soci_Lnk_Stampa")
            ))
        except Exception:
            log.warning("ID specifico non trovato, cerco per testo 'STAMPA LISTA'...")
            btn_stampa = wait.until(
                EC.presence_of_element_located((By.PARTIAL_LINK_TEXT, "STAMPA LISTA"))
            )

        for f in glob.glob(os.path.join(download_dir, "Lista soci*.xls*")):
            try:
                os.remove(f)
            except Exception:
                pass

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn_stampa)
        time.sleep(2)
        driver.execute_script("arguments[0].click();", btn_stampa)
        log.info("Pulsante STAMPA LISTA cliccato. Attesa download...")

        timeout    = 60
        start_time = time.time()
        possible_targets = ["Lista soci.xlsx", "Lista soci.xls"]

        while time.time() - start_time < timeout:
            files      = os.listdir(download_dir)
            temp_files = [
                f for f in files
                if "Lista soci" in f and (f.endswith(".crdownload") or f.endswith(".tmp"))
            ]
            found_file = next((t for t in possible_targets if t in files), None)

            if temp_files:
                log.info("Download in corso... (%s)", temp_files)
            elif found_file:
                log.info("File '%s' pronto.", found_file)
                driver.quit()
                log.info("Browser chiuso.")

                final_path = os.path.join(download_dir, found_file)

                if found_file.endswith(".xls"):
                    new_path = os.path.join(download_dir, "Lista soci.xlsx")
                    for tentativo in range(10):
                        try:
                            os.rename(final_path, new_path)
                            final_path = new_path
                            log.info("File rinominato in .xlsx.")
                            break
                        except OSError:
                            log.warning("File bloccato, tentativo %d/10...", tentativo + 1)
                            time.sleep(2)
                    else:
                        raise RuntimeError("Impossibile rinominare il file dopo 10 tentativi.")

                df_completo = leggi_file(final_path)
                df_soci     = estrai_colonne(df_completo)
                carica_su_sheets(df_soci)

                log.info("=== PROCESSO COMPLETATO CON SUCCESSO ===")
                return

            time.sleep(2)

        raise RuntimeError(f"Timeout {timeout}s raggiunto senza trovare il file scaricato.")

    except Exception:
        log.exception("ERRORE DURANTE L'ESECUZIONE")
        try:
            screenshot_path = "/tmp/screenshot_errore.png"
            driver.save_screenshot(screenshot_path)
            log.info("Screenshot salvato: %s", screenshot_path)
            log.info("URL al momento dell'errore: %s", driver.current_url)
            log.info("Titolo pagina: %s", driver.title)
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    try:
        scarica_soci()
        sys.exit(0)
    except Exception:
        sys.exit(1)
