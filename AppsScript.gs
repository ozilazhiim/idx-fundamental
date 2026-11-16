/**
 * Google Sheets importer for data/fundamentals_latest.json.
 *
 * Before use:
 * 1) Change SHEET_NAME if your worksheet has another name.
 * 2) Change DATA_URL to your public GitHub raw URL.
 * 3) Make sure row 1 contains a ticker header and the metric headers shown below.
 * 4) Four historical mean fields are intentionally not overwritten because
 *    the selected free source does not provide those historical averages.
 */
const FUNDAMENTAL_CONFIG = {
  SHEET_NAME: 'Sheet1',
  HEADER_ROW: 1,
  DATA_START_ROW: 2,
  TICKER_HEADER: 'ticker',
  DATA_URL: 'https://raw.githubusercontent.com/OWNER/REPO/main/data/fundamentals_latest.json',
  GITHUB_OWNER: 'OWNER',
  GITHUB_REPO: 'REPO',
  GITHUB_BRANCH: 'main',
  WORKFLOW_FILE: 'update_fundamentals.yml'
};

// Current fields supported by the data source.
// The four mean_* fields are NOT included here to avoid writing false values.
const FUNDAMENTAL_FIELDS_TO_IMPORT = [
  'pe_ratio',
  'book_value',
  'pbv_ratio',
  'roe',
  'npm',
  'eps_ttm',
  'der',
  'div_yield'
];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Fundamental Tools')
    .addItem('Import data terbaru dari GitHub', 'UPDATE_FUNDAMENTAL')
    .addSeparator()
    .addItem('Minta GitHub Actions mengambil data baru', 'TRIGGER_GITHUB_UPDATE')
    .addToUi();
}

/**
 * Import the latest JSON file into the active spreadsheet worksheet.
 * This does not scrape market data itself; GitHub Actions performs that job.
 */
function UPDATE_FUNDAMENTAL() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(FUNDAMENTAL_CONFIG.SHEET_NAME);
  if (!sheet) {
    throw new Error('Sheet tidak ditemukan: ' + FUNDAMENTAL_CONFIG.SHEET_NAME);
  }

  const response = UrlFetchApp.fetch(FUNDAMENTAL_CONFIG.DATA_URL, {
    method: 'get',
    muteHttpExceptions: true,
    headers: {
      'Cache-Control': 'no-cache',
      'Pragma': 'no-cache'
    }
  });

  const httpCode = response.getResponseCode();
  if (httpCode !== 200) {
    throw new Error(
      'Gagal mengambil JSON GitHub. HTTP ' + httpCode + '. Periksa DATA_URL dan pastikan repo bersifat public.'
    );
  }

  let payload;
  try {
    payload = JSON.parse(response.getContentText());
  } catch (error) {
    throw new Error('File GitHub bukan JSON yang valid: ' + error.message);
  }

  if (!payload || !Array.isArray(payload.rows)) {
    throw new Error('Format JSON tidak sesuai: properti rows[] tidak ditemukan.');
  }

  const lastColumn = sheet.getLastColumn();
  const lastRow = sheet.getLastRow();
  if (lastColumn < 1 || lastRow < FUNDAMENTAL_CONFIG.DATA_START_ROW) {
    throw new Error('Sheet belum memiliki header atau data ticker.');
  }

  const headers = sheet
    .getRange(FUNDAMENTAL_CONFIG.HEADER_ROW, 1, 1, lastColumn)
    .getDisplayValues()[0];
  const headerMap = {};
  headers.forEach((header, index) => {
    const key = normalizeHeader_(header);
    if (key) headerMap[key] = index + 1;
  });

  const tickerColumn = headerMap[normalizeHeader_(FUNDAMENTAL_CONFIG.TICKER_HEADER)];
  if (!tickerColumn) {
    throw new Error(
      'Header ticker tidak ditemukan. Tambahkan header "' + FUNDAMENTAL_CONFIG.TICKER_HEADER + '" pada baris ' + FUNDAMENTAL_CONFIG.HEADER_ROW + '.'
    );
  }

  const rowCount = lastRow - FUNDAMENTAL_CONFIG.DATA_START_ROW + 1;
  const sheetTickers = sheet
    .getRange(FUNDAMENTAL_CONFIG.DATA_START_ROW, tickerColumn, rowCount, 1)
    .getDisplayValues()
    .map(row => normalizeTicker_(row[0]));

  const dataByTicker = {};
  payload.rows.forEach(row => {
    const ticker = normalizeTicker_(row.ticker || row.symbol || '');
    if (ticker) dataByTicker[ticker] = row;
  });

  let updatedTickerCount = 0;
  const missingHeaders = [];

  FUNDAMENTAL_FIELDS_TO_IMPORT.forEach(field => {
    let targetColumn = headerMap[normalizeHeader_(field)];
    // The screenshot header uses `eps(ttm)` rather than `eps_ttm`.
    if (!targetColumn && field === 'eps_ttm') {
      targetColumn = headerMap['eps(ttm)'];
    }
    if (!targetColumn) {
      missingHeaders.push(field);
      return;
    }

    // Read the existing column once so rows with provider errors keep their old values.
    const existingValues = sheet
      .getRange(FUNDAMENTAL_CONFIG.DATA_START_ROW, targetColumn, rowCount, 1)
      .getValues();

    const output = sheetTickers.map((ticker, rowIndex) => {
      if (!ticker) return [existingValues[rowIndex][0]];
      const row = dataByTicker[ticker];

      // Preserve existing values when a ticker had a provider/network error or no result.
      if (!row || row.status === 'FETCH_ERROR' || row.status === 'NO_DATA') {
        return [existingValues[rowIndex][0]];
      }

      const value = row[field];
      return [value === null || value === undefined ? '' : value];
    });

    sheet
      .getRange(FUNDAMENTAL_CONFIG.DATA_START_ROW, targetColumn, rowCount, 1)
      .setValues(output);
  });

  // Count tickers with a usable row once, independently of the number of columns.
  sheetTickers.forEach(ticker => {
    if (ticker && dataByTicker[ticker] && ['OK', 'STALE'].includes(dataByTicker[ticker].status)) {
      updatedTickerCount++;
    }
  });
  const skippedTickerCount = sheetTickers.filter(ticker => {
    const row = ticker ? dataByTicker[ticker] : null;
    return ticker && (!row || !['OK', 'STALE'].includes(row.status));
  }).length;

  const updatedAt = payload.meta && payload.meta.updated_at_utc
    ? payload.meta.updated_at_utc
    : 'waktu tidak tersedia';

  let message = 'Import selesai. Ticker dengan data: ' + updatedTickerCount + '. Data sumber diperbarui: ' + updatedAt;
  if (missingHeaders.length) {
    message += '. Header yang tidak ditemukan: ' + missingHeaders.join(', ');
  }
  message += '. Empat kolom mean PE/PBV historis tidak diubah karena belum tersedia dari sumber.';

  ss.toast(message, 'Fundamental', 10);
  Logger.log(message);
  Logger.log('Ticker dilewati karena tidak ada data/error: ' + skippedTickerCount);
}

/**
 * Optional: dispatch the GitHub Actions workflow from Sheets.
 * Store a fine-grained GitHub token in Apps Script Project Settings > Script Properties:
 * GH_TOKEN = token with Actions: Read and write on this repository.
 */
function TRIGGER_GITHUB_UPDATE() {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) {
    throw new Error('Script Property GH_TOKEN belum diisi. Lihat README untuk membuat token GitHub.');
  }

  const owner = FUNDAMENTAL_CONFIG.GITHUB_OWNER;
  const repo = FUNDAMENTAL_CONFIG.GITHUB_REPO;
  const workflow = FUNDAMENTAL_CONFIG.WORKFLOW_FILE;
  const url = 'https://api.github.com/repos/' + owner + '/' + repo + '/actions/workflows/' + workflow + '/dispatches';

  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers: {
      'Authorization': 'Bearer ' + token,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    payload: JSON.stringify({ ref: FUNDAMENTAL_CONFIG.GITHUB_BRANCH })
  });

  const code = response.getResponseCode();
  if (code !== 204) {
    throw new Error('Gagal menjalankan GitHub Actions. HTTP ' + code + ': ' + response.getContentText());
  }

  SpreadsheetApp.getActiveSpreadsheet().toast(
    'Workflow berhasil diminta. Tunggu sampai GitHub Actions selesai, lalu pilih Import data terbaru dari GitHub.',
    'Fundamental',
    10
  );
}

function normalizeTicker_(value) {
  return String(value || '').trim().toUpperCase().replace(/\.JK$/, '');
}

function normalizeHeader_(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, '');
}
