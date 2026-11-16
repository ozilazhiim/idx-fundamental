# Otomatisasi Fundamental 950 Saham BEI ke Google Sheets

Paket ini memakai `ihsg-cli` (nama perintah: `idx`) untuk mengambil fundamental terkini saham BEI, GitHub Actions untuk menjalankan proses terjadwal, dan Apps Script untuk mengimpor hasil ke Google Sheets.

## Penting: cakupan metrik

Sumber `idx stocks fundamental` menyediakan metrik fundamental terkini seperti P/E, P/B, ROE, margin, DER, EPS TTM, book value per share, dan dividend yield.

Sumber tersebut **tidak menyediakan** `mean_per_3y`, `mean_per_5y`, `mean_pbv_3y`, atau `mean_pbv_5y` sebagai data historis siap pakai. Karena itu, program ini mengeluarkan empat kolom tersebut sebagai `null` dan Apps Script tidak menimpanya. Jangan menganggap nilai kosong sebagai nol.

Kolom `book_value` pada paket ini adalah **book value per share (BVPS)**, sesuai field `per_share.book_value` dari sumber.

## Struktur file

```text
idx_fundamental_automation/
├── .github/workflows/update_fundamentals.yml
├── data/
│   └── tickers.txt
├── scripts/
│   └── fetch_fundamentals.py
├── AppsScript.gs
└── README.md
```

## A. Siapkan GitHub repository

1. Buat repository baru di GitHub, misalnya `idx-fundamental-950`.
2. Disarankan repository **Public**, karena Apps Script akan membaca file JSON melalui raw.githubusercontent.com. File yang diterbitkan hanya data pasar publik dan ticker, bukan token rahasia.
3. Upload seluruh isi folder paket ini ke root repository. Pastikan file workflow berada pada `.github/workflows/update_fundamentals.yml`.
4. Buka `data/tickers.txt`, hapus ticker contoh, lalu tempel 950 ticker saham dari kolom ticker Google Sheets. Satu ticker per baris. Akhiran `.JK` boleh ada atau tidak.
5. Commit ke branch `main`.

Contoh `data/tickers.txt`:

```text
BBCA
BBRI
BMRI
TLKM
ASII
ANTM
```

Pastikan setiap ticker benar dan tidak menyertakan header kolom.

## B. Aktifkan GitHub Actions

1. Buka repository > **Settings > Actions > General**.
2. Pada Workflow permissions, pilih **Read and write permissions** lalu Save. Workflow sudah meminta `contents: write` untuk menyimpan JSON/CSV hasil.
3. Buka tab **Actions**.
4. Pilih workflow **Update IDX Fundamentals**.
5. Klik **Run workflow** pada branch `main` untuk uji pertama.
6. Buka proses yang berjalan. Langkah `Fetch fundamentals` akan memanggil `idx stocks compare` per batch 8 ticker.
7. Jika berhasil, workflow membuat commit berisi:
   - `data/fundamentals_latest.json`
   - `data/fundamentals_latest.csv`

Workflow juga dijadwalkan otomatis Senin-Jumat pukul 05.00 WIB. Jadwal GitHub Actions dapat terlambat saat antrean padat. Data gratis dari sumber pihak ketiga juga dapat berubah, tertunda, dibatasi, atau gagal diakses.

### Jika workflow gagal karena provider memblokir runner

Dokumentasi `idx` menyebut sumber tertentu dapat lebih sering menolak koneksi dari runner CI/data center. Coba jalankan ulang beberapa saat kemudian. Jika tetap diblokir, jalankan skrip Python secara lokal di komputer yang memiliki koneksi internet biasa:

1. Install Node.js LTS.
2. Jalankan `npm install -g ihsg-cli@0.8.3`.
3. Pastikan perintah `idx version` berjalan.
4. Install Python 3.12 atau lebih baru.
5. Jalankan `python scripts/fetch_fundamentals.py` dari folder proyek.
6. Commit file JSON dan CSV yang dihasilkan ke repository.

Jika koneksi dari runner terus diblokir, jangan mengubah data error menjadi nol. Pertahankan file terakhir yang valid dan coba kembali dari jaringan lokal.

## C. Pasang Apps Script ke Google Sheets

1. Buka spreadsheet yang berisi 950 ticker.
2. Pastikan baris 1 memiliki header berikut (ejaan harus sama):

```text
ticker | pe_ratio | mean_per_3y | mean_per_5y | book_value | pbv_ratio | mean_pbv_3y | mean_pbv_5y | roe | npm | eps_ttm | der | div_yield
```

3. Pastikan header `ticker` memang berada pada baris 1. Ticker saham dimulai di baris 2.
4. Klik **Extensions > Apps Script**.
5. Hapus contoh `myFunction`, lalu salin seluruh isi `AppsScript.gs` ke editor.
6. Ubah nilai konfigurasi berikut sesuai repository dan nama worksheet:
   - `SHEET_NAME`: nama tab worksheet, misalnya `Sheet1`.
   - `DATA_URL`: `https://raw.githubusercontent.com/USERNAME/REPOSITORY/main/data/fundamentals_latest.json`
   - `GITHUB_OWNER`: username GitHub.
   - `GITHUB_REPO`: nama repository.
7. Klik Save.
8. Jalankan fungsi `UPDATE_FUNDAMENTAL` pertama kali dari editor Apps Script. Berikan izin saat diminta.
9. Kembali ke Google Sheets lalu refresh halaman. Menu **Fundamental Tools** akan muncul.
10. Gunakan **Fundamental Tools > Import data terbaru dari GitHub** untuk impor berikutnya.

Apps Script menulis per kolom metrik secara batch, bukan membuat 950 custom formula.

## D. Opsional: jalankan workflow langsung dari Google Sheets

Jika ingin tombol pada Google Sheets meminta GitHub mengambil data baru:

1. Buat **fine-grained personal access token** di GitHub.
2. Batasi token hanya ke repository ini.
3. Berikan permission **Actions: Read and write**.
4. Di Apps Script, buka **Project Settings > Script Properties > Add script property**.
5. Tambahkan:
   - Property: `GH_TOKEN`
   - Value: token GitHub tadi.
6. Simpan.
7. Gunakan menu **Fundamental Tools > Minta GitHub Actions mengambil data baru**.
8. Setelah workflow selesai (cek tab Actions GitHub), pilih **Import data terbaru dari GitHub**.

Token disimpan di Script Properties, bukan di source code. Jangan pernah menempel token GitHub di spreadsheet atau repository.

## E. Arti kolom dan satuan

| Kolom | Definisi paket | Satuan |
|---|---|---|
| `pe_ratio` | Trailing P/E | Kali |
| `book_value` | Book value per share (BVPS) | Mata uang laporan per saham |
| `pbv_ratio` | Price-to-book | Kali |
| `roe` | Return on equity | Persen, contoh `21.8` berarti 21,8% |
| `npm` | Net profit margin | Persen, contoh `12.5` berarti 12,5% |
| `eps_ttm` | EPS 12 bulan terakhir | Mata uang laporan per saham |
| `der` | Debt-to-equity | Rasio, contoh `0.6` berarti 0,6x atau 60% dari ekuitas |
| `div_yield` | Dividend yield | Persen, contoh `6.27` berarti 6,27% |

Nilai persentase dikirim sebagai angka persen (misalnya `6.27`, bukan `0.0627`). Jika ingin format persen bawaan Google Sheets, konversi angka menjadi pecahan desimal terlebih dahulu. Paket ini tidak mengubah format sel.

Jika mata uang harga saham dan mata uang laporan keuangan berbeda, `book_value` dan `pbv_ratio` dikosongkan untuk mencegah rasio yang mencampur mata uang.

## F. Tes cepat

Sebelum menjalankan 950 ticker, uji `data/tickers.txt` dengan 5-10 ticker dulu. Pastikan:

- Workflow selesai tanpa error.
- File JSON berisi `meta.successful_tickers` lebih besar dari nol.
- File CSV berisi header dan baris ticker.
- Apps Script mengisi delapan metrik terkini.
- Empat kolom mean PE/PBV historis tetap kosong, karena belum disediakan sumber.

## G. Catatan penggunaan

- `ihsg-cli` adalah proyek pihak ketiga, bukan API resmi BEI, Yahoo Finance, atau Microsoft.
- Data gratis bukan data real-time terjamin dan dapat berubah atau tidak tersedia.
- Program menggunakan output JSON yang terdokumentasi, retry, dan mempertahankan file sebelumnya jika semua batch gagal.
- Jangan gunakan data ini sebagai satu-satunya dasar keputusan investasi. Periksa laporan keuangan emiten untuk validasi.
