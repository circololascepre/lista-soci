var SHEET_NAME    = 'Lista Soci';
var ACCESSI_SHEET = 'Accessi';
var META_SHEET    = 'Meta';
var CACHE_KEY     = 'soci_v3';
var CACHE_TTL     = 300; // 5 minuti

// ---------------------------------------------------------------------------
// Entrypoint web app
// ---------------------------------------------------------------------------

function doGet(e) {
  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Soci Circolo La Scepre')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// ---------------------------------------------------------------------------
// Verifica password (chiamata dal client via google.script.run)
// Imposta APP_PASSWORD nelle Script Properties per attivare la protezione.
// ---------------------------------------------------------------------------

function checkPassword(pw) {
  var correctPw = PropertiesService.getScriptProperties().getProperty('APP_PASSWORD');
  if (!correctPw) return true; // Nessuna password impostata = accesso libero
  return String(pw).trim() === String(correctPw).trim();
}

// ---------------------------------------------------------------------------
// Helper template
// ---------------------------------------------------------------------------

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

// ---------------------------------------------------------------------------
// Legge la whitelist dal foglio "Accessi" (una email per riga, colonna A).
// Se il foglio non esiste o è vuoto → nessuna restrizione.
// ---------------------------------------------------------------------------

function getWhitelist_() {
  try {
    var props = PropertiesService.getScriptProperties();
    var ss    = SpreadsheetApp.openById(props.getProperty('SPREADSHEET_ID'));
    var sheet = ss.getSheetByName(ACCESSI_SHEET);
    if (!sheet) return [];
    var vals = sheet.getDataRange().getValues();
    return vals
      .map(function (r) { return String(r[0] || '').trim().toLowerCase(); })
      .filter(function (e) { return e.indexOf('@') !== -1; });
  } catch (err) {
    Logger.log('getWhitelist_ error: ' + err);
    return [];
  }
}

// ---------------------------------------------------------------------------
// Lettura soci con cache 5 minuti
// ---------------------------------------------------------------------------

function getSoci() {
  var cache  = CacheService.getScriptCache();
  var cached = cache.get(CACHE_KEY);
  if (cached) return JSON.parse(cached);

  var props         = PropertiesService.getScriptProperties();
  var ss            = SpreadsheetApp.openById(props.getProperty('SPREADSHEET_ID'));
  var sheet         = ss.getSheetByName(SHEET_NAME);
  var data          = sheet.getDataRange().getValues();

  var aggiornato = '';
  try {
    var metaSheet = ss.getSheetByName(META_SHEET);
    if (metaSheet) {
      aggiornato = String(metaSheet.getRange('A1').getValue() || '').trim();
    }
  } catch (e) { Logger.log('Meta sheet: ' + e); }

  var soci = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var nom = String(row[0] || '').trim();
    if (!nom) continue;
    soci.push({
      nominativo: nom,
      tessera:    String(row[1] || '').trim(),
      tipo:       String(row[2] || '').trim(),
      rilascio:   formatData_(row[3]),
      scadenza:   formatData_(row[4])
    });
  }

  var result = { soci: soci, aggiornato: aggiornato };
  try {
    cache.put(CACHE_KEY, JSON.stringify(result), CACHE_TTL);
  } catch (e) {
    Logger.log('Cache skip (dati troppo grandi): ' + e);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Trigger workflow GitHub Actions
// ---------------------------------------------------------------------------

function triggerAggiornamento() {
  var props    = PropertiesService.getScriptProperties();
  var token    = props.getProperty('GITHUB_TOKEN');
  var repo     = props.getProperty('GITHUB_REPO');
  var workflow = props.getProperty('WORKFLOW_FILE');
  var url      = 'https://api.github.com/repos/' + repo +
                 '/actions/workflows/' + workflow + '/dispatches';
  try {
    var response = UrlFetchApp.fetch(url, {
      method: 'POST', muteHttpExceptions: true,
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify({ ref: 'main' })
    });
    var code = response.getResponseCode();
    if (code === 204) return { ok: true, message: 'Workflow avviato.' };
    return { ok: false, message: 'Errore GitHub (HTTP ' + code + '): ' + response.getContentText() };
  } catch (e) {
    return { ok: false, message: 'Errore di rete: ' + e.toString() };
  }
}

// ---------------------------------------------------------------------------
// Polling stato workflow
// ---------------------------------------------------------------------------

function getWorkflowStatus() {
  var props    = PropertiesService.getScriptProperties();
  var token    = props.getProperty('GITHUB_TOKEN');
  var repo     = props.getProperty('GITHUB_REPO');
  var workflow = props.getProperty('WORKFLOW_FILE');
  var url      = 'https://api.github.com/repos/' + repo +
                 '/actions/workflows/' + workflow +
                 '/runs?per_page=1&event=workflow_dispatch';
  try {
    var resp = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
      }
    });
    var code = resp.getResponseCode();
    if (code !== 200) return { status: 'error', message: 'Errore GitHub API (HTTP ' + code + ').' };
    var runs = JSON.parse(resp.getContentText()).workflow_runs;
    if (!runs || runs.length === 0) return { status: 'queued', message: 'In attesa di avvio...' };
    var run = runs[0];
    return { status: run.status, conclusion: run.conclusion, runUrl: run.html_url,
             message: messaggioStato_(run.status, run.conclusion) };
  } catch (e) {
    return { status: 'error', message: 'Errore di rete: ' + e.toString() };
  }
}

function messaggioStato_(status, conclusion) {
  if (status === 'queued')      return 'In coda su GitHub...';
  if (status === 'in_progress') return 'Scraper in esecuzione...';
  if (status === 'completed') {
    if (conclusion === 'success')   return 'Aggiornamento completato con successo!';
    if (conclusion === 'failure')   return 'Il workflow è fallito. Vedi log su GitHub per i dettagli.';
    if (conclusion === 'cancelled') return 'Workflow annullato.';
    return 'Completato con esito: ' + conclusion;
  }
  return 'Stato: ' + status;
}

// ---------------------------------------------------------------------------
// Email utente corrente
// ---------------------------------------------------------------------------

function getUserEmail() {
  return Session.getActiveUser().getEmail();
}

// ---------------------------------------------------------------------------
// Utilità interne
// ---------------------------------------------------------------------------

function formatData_(val) {
  if (!val) return '';
  if (val instanceof Date) {
    return Utilities.formatDate(val, 'Europe/Rome', 'dd/MM/yyyy');
  }
  var s = String(val).trim();
  if (!s || s === 'NaN' || s === 'undefined' || s === 'null') return '';
  // Se la stringa contiene spazio o T (es. "2024-01-15 00:00:00" o ISO), prendi solo la parte data
  s = s.split(' ')[0].split('T')[0];
  // Converti YYYY-MM-DD → DD/MM/YYYY se necessario
  var iso = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) return iso[3] + '/' + iso[2] + '/' + iso[1];
  return s;
}

function escHtml_(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
