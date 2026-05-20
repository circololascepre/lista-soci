/**
 * Esegui questa funzione UNA SOLA VOLTA manualmente dall'editor Apps Script
 * (menu Esegui → setupProperties) per configurare tutte le proprietà dello script.
 *
 * NON committare valori reali in questo file: sostituisci i placeholder
 * qui sotto prima di eseguire, poi ripristina i placeholder prima del commit.
 */
function setupProperties() {
  PropertiesService.getScriptProperties().setProperties({

    // Email autorizzate ad accedere alla web app (separate da virgola, senza spazi)
    // Esempio: 'circololascepre@gmail.com,altroammin@gmail.com'
    'WHITELIST_EMAILS': 'INSERISCI_EMAIL_AUTORIZZATE',

    // ID del Google Spreadsheet che contiene il foglio "Lista Soci"
    // Lo trovi nell'URL: https://docs.google.com/spreadsheets/d/<ID>/edit
    'SPREADSHEET_ID': 'INSERISCI_SPREADSHEET_ID',

    // Personal Access Token GitHub con scope "workflow"
    // Crea su: https://github.com/settings/tokens → Generate new token (classic)
    'GITHUB_TOKEN': 'ghp_INSERISCI_TOKEN',

    // Repository GitHub nel formato utente/nome-repo
    // Esempio: 'circololascepre/lista-soci-aics'
    'GITHUB_REPO': 'INSERISCI_UTENTE/lista-soci-aics',

    // Nome del file workflow da triggherare
    'WORKFLOW_FILE': 'aggiorna-soci.yml'

  });

  Logger.log('Proprietà configurate correttamente.');
}
