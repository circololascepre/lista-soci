# lista-soci-aics

Scarica automaticamente la lista soci dal portale AICS e la sincronizza su Google Sheets.

Il workflow gira ogni giorno alle 06:00 UTC (08:00 ora italiana) e può essere avviato manualmente da GitHub Actions.

---

## Struttura

```
scraper/
  soci.py           # scraper principale
  requirements.txt  # dipendenze Python
.github/
  workflows/
    aggiorna-soci.yml  # workflow GitHub Actions
```

---

## Configurazione dei GitHub Secrets

Lo script non contiene credenziali hardcoded: tutte le informazioni sensibili si passano come **Secrets** del repository.

### Passaggi

1. Apri il tuo repository su GitHub.
2. Vai su **Settings** → **Secrets and variables** → **Actions**.
3. Clicca su **New repository secret** per ciascuno dei quattro secrets:

---

### Secret 1 — `AICS_USERNAME`

Il tuo codice utente per accedere ad [aicsnetwork.net](https://www.aicsnetwork.net).

```
Nome:   AICS_USERNAME
Valore: <il tuo codice affiliazione, es. 116371>
```

---

### Secret 2 — `AICS_PASSWORD`

La tua password per il portale AICS.

```
Nome:   AICS_PASSWORD
Valore: <la tua password>
```

---

### Secret 3 — `GOOGLE_SERVICE_ACCOUNT_JSON`

Il contenuto **intero** del file JSON del Service Account Google (quello che hai scaricato da Google Cloud Console quando hai creato l'account di servizio).

**Come ottenerlo:**

1. Vai su [console.cloud.google.com](https://console.cloud.google.com).
2. **IAM & Admin** → **Service Accounts** → seleziona il tuo account.
3. Scheda **Keys** → **Add Key** → **Create new key** → formato **JSON**.
4. Apri il file scaricato con un editor di testo.
5. Copia **tutto il contenuto** (dalla prima `{` all'ultima `}`).

```
Nome:   GOOGLE_SERVICE_ACCOUNT_JSON
Valore: { "type": "service_account", "project_id": "...", ... }
```

> L'account di servizio deve avere accesso allo spreadsheet:
> condividi il foglio Google con l'email del service account
> (es. `nome@progetto.iam.gserviceaccount.com`) con ruolo **Editor**.

---

### Secret 4 — `SPREADSHEET_ID`

L'ID del Google Spreadsheet dove verranno scritti i dati.

Lo trovi nell'URL del foglio:

```
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```

```
Nome:   SPREADSHEET_ID
Valore: <l'ID alfanumerico, es. 12ohgezDU2o1M88gWUY1sFwS152sqUW6P5MjYboQMZWI>
```

> Il foglio deve contenere un tab chiamato esattamente **Lista Soci**.

---

## Avvio manuale

Puoi avviare il workflow in qualsiasi momento:

1. Vai su **Actions** nel tuo repository.
2. Seleziona **Aggiorna Lista Soci**.
3. Clicca **Run workflow** → **Run workflow**.

---

## Colonne aggiornate nel foglio

| Colonna      | Note                                      |
|--------------|-------------------------------------------|
| NOMINATIVO   | Nome e cognome del socio                  |
| N° TESSERA   | Numero tessera (senza decimali superflui) |
| TIPO TESSERA | Categoria della tessera                   |
| RILASCIO     | Data di rilascio (gg/mm/aaaa)             |
| SCADENZA     | Data di scadenza (gg/mm/aaaa)             |
