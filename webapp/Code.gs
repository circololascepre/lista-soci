var SHEET_NAME = 'Lista Soci';
var CACHE_KEY   = 'soci_data';
var CACHE_TTL   = 300; // 5 minuti

// ---------------------------------------------------------------------------
// Entrypoint web app
// ---------------------------------------------------------------------------

function doGet(e) {
  var email = Session.getActiveUser().getEmail();
  var props = PropertiesService.getScriptProperties();
  var whitelistRaw = props.getProperty('WHITELIST_EMAILS') || '';
  var whitelist = whitelistRaw.split(',').map(function (s) { return s.trim().toLowerCase(); });

  if (!email || whitelist.indexOf(email.toLowerCase()) === -1) {
    return HtmlService.createHtmlOutput(
      '<!DOCTYPE html><html lang="it"><head>' +
      '<meta charset="UTF-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>Accesso negato</title>' +
      '<style>' +
        'body{font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;' +
        'justify-content:center;min-height:100vh;margin:0;background:#f0f2f5;}' +
        '.box{background:#fff;padding:32px 28px;border-radius:16px;' +
        'box-shadow:0 2px 12px rgba(0,0,0,.1);text-align:center;max-width:380px;width:90%;}' +
        'h2{color:#ef4444;margin:0 0 12px;}' +
        'p{color:#555;line-height:1.6;margin:0 0 8px;}' +
        'strong{color:#333;}' +
      '</style></head><body>' +
      '<div class="box">' +
        '<h2>Accesso negato</h2>' +
        '<p>Il tuo account (<strong>' + escHtml_(email || 'sconosciuto') + '</strong>)<br>' +
        'non è autorizzato ad accedere a questa applicazione.</p>' +
        '<p>Contatta l\'amministratore per richiedere l\'accesso.</p>' +
      '</div></body></html>'
    ).setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Soci Circolo La Scepre')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// ---------------------------------------------------------------------------
// Helper template (usato con <?!= include('Stylesheet') ?>)
// ---------------------------------------------------------------------------

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

// ---------------------------------------------------------------------------
// Lettura soci con cache 5 minuti
// ---------------------------------------------------------------------------

function getSoci() {
  var cache  = CacheService.getScriptCache();
  var cached = cache.get(CACHE_KEY);
  if (cached) {
    return JSON.parse(cached);
  }

  var props         = PropertiesService.getScriptProperties();
  var spreadsheetId = props.getProperty('SPREADSHEET_ID');
  var sheet         = SpreadsheetApp.openById(spreadsheetId).getSheetByName(SHEET_NAME);
  var data          = sheet.getDataRange().getValues();

  var soci = [];
  for (var i = 1; i < data.length; i++) {
    var row       = data[i];
    var nominativo = String(row[0] || '').trim();
    if (!nominativo) continue;
    soci.push({
      nominativo: nominativo,
      tessera:    String(row[1] || '').trim(),
      tipo:       String(row[2] || '').trim(),
      rilascio:   String(row[3] || '').trim(),
      scadenza:   String(row[4] || '').trim()
    });
  }

  cache.put(CACHE_KEY, JSON.stringify(soci), CACHE_TTL);
  return soci;
}

// ---------------------------------------------------------------------------
// Trigger workflow GitHub Actions
// ---------------------------------------------------------------------------

function triggerAggiornamento() {
  var props    = PropertiesService.getScriptProperties();
  var token    = props.getProperty('GITHUB_TOKEN');
  var repo     = props.getProperty('GITHUB_REPO');
  var workflow = props.getProperty('WORKFLOW_FILE');
  var url      = 'https://api.github.com/repos/' + repo + '/actions/workflows/' + workflow + '/dispatches';

  try {
    var response = UrlFetchApp.fetch(url, {
      method:           'POST',
      muteHttpExceptions: true,
      headers: {
        'Authorization':        'Bearer ' + token,
        'Accept':               'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type':         'application/json'
      },
      payload: JSON.stringify({ ref: 'main' })
    });

    var code = response.getResponseCode();
    if (code === 204) {
      return { ok: true, message: 'Aggiornamento avviato. I dati saranno disponibili tra qualche minuto.' };
    }

    var body = response.getContentText();
    Logger.log('GitHub API error ' + code + ': ' + body);
    return { ok: false, message: 'Errore GitHub (HTTP ' + code + '). Controlla il log.' };

  } catch (e) {
    Logger.log('triggerAggiornamento exception: ' + e.toString());
    return { ok: false, message: 'Errore di rete: ' + e.toString() };
  }
}

// ---------------------------------------------------------------------------
// Email utente corrente (mostrata nel footer)
// ---------------------------------------------------------------------------

function getUserEmail() {
  return Session.getActiveUser().getEmail();
}

// ---------------------------------------------------------------------------
// Utilità interna
// ---------------------------------------------------------------------------

function escHtml_(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
