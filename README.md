# NEXUS

NEXUS berjalan di laptop ini. Phase 1 memantau CPU, RAM, disk, dan proses. Phase 2 membantu merapikan satu folder, dengan Downloads sebagai folder standar.

Phase 1 hanya membaca sistem. Phase 2 membaca metadata file, dan memindahkan file hanya setelah persetujuan di dashboard. Tidak ada penghapusan file, penimpaan file, penghentian proses, pemindaian seluruh drive, atau panggilan LLM.

## Menjalankan

Dari PowerShell, di folder proyek:

```powershell
cd D:\Projects\NEXUS
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py
```

Buka `http://127.0.0.1:8501`. Dashboard hanya menerima koneksi dari laptop ini.

Pemeriksaan satu kali, tanpa membiarkan sampler tetap hidup:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Satu sampler

Dashboard Streamlit adalah satu-satunya sampler yang terus berjalan. `main.py` hanya mengambil satu sampel, mencetaknya, lalu selesai.

Jangan jalankan `main.py` bersamaan dengan Streamlit. Jangan jalankan dua perintah `streamlit run` bersamaan. Masing-masing adalah proses terpisah, sehingga sampling dan penulisan histori terjadi dua kali.

Jika aktivasi `.\.venv\Scripts\Activate.ps1` diblokir execution policy, panggil `python.exe` di dalam `.venv` seperti contoh di atas.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Konfigurasi

Semua interval dan threshold ada di `config/settings.yaml`. Setelah mengubah file itu, hentikan Streamlit dan jalankan lagi.

Nilai awal:

- CPU dan RAM setiap 5 detik
- Proses setiap 10 detik
- Disk dan penyimpanan histori setiap 30 detik
- CPU warning 70%, critical 90%
- RAM warning 70%, critical 85%
- Disk kosong warning 20%, critical di bawah 10%

## Alur data

1. Dashboard atau `main.py` meminta satu snapshot ke `SystemCollector`.
2. Collector membaca CPU, RAM, disk, atau proses hanya jika intervalnya sudah lewat.
3. `health.py` menilai snapshot dengan threshold dari YAML.
4. Setiap 30 detik hasilnya ditulis ke `database/nexus.db`.
5. Dashboard menggambar histori dari database, bukan dengan memindai disk lagi.

## Keamanan

Phase 1 tidak menghapus atau memindahkan apa pun. Database, log, dan virtual environment berada di folder proyek pada Drive D.

## Phase 2 — Smart File Organizer

Buka dashboard, pilih **File Organizer**, lalu tekan **Pindai folder**. Tidak ada pemindai yang berjalan sendiri.

Alurnya:

1. Pindaian membaca nama, ekstensi, ukuran, dan waktu ubah. Isi file tidak dibaca.
2. Ekstensi menentukan kategori: Documents, Images, Videos, Audio, Archives, Installers, Spreadsheets, Development, atau Others.
3. Deteksi duplikat dihitung ketika tombolnya ditekan. Hanya file yang ukurannya sama yang di-hash, per potongan, dengan SHA-256.
4. Rencana menampilkan lokasi asal dan tujuan. Contoh: `report.pdf` menjadi `Documents/PDF/report.pdf`, dan `archive.zip` menjadi `Archives/archive.zip`.
5. File dipindahkan setelah kotak persetujuan dicentang. Nama file tidak diubah. File yang sudah ada di tujuan tidak ditimpa. Folder aktif adalah hasil pindaian terakhir, bukan teks yang baru diketik.
6. Setiap percobaan masuk ke tabel `file_operations`, termasuk status tertunda dan alasan kegagalan. Undo tersedia untuk pemindahan berstatus berhasil, selama lokasi asal kosong. Operasi yang terputus diperiksa dari riwayat dan tidak dipulihkan dengan menimpa atau menghapus file.

Folder `C:\`, `D:\`, dan direktori Windows tidak dipindai. Symbolic link dan junction di dalam folder sumber tidak diikuti. Pengujian memakai folder sementara, bukan Downloads asli.

Ambang file besar, batas jumlah file, kedalaman, dan ukuran potongan hash ada di `file_organizer` pada `config/settings.yaml`.

## Known issues

- Mesin ini memakai Python 3.10.6. Kode kompatibel dengan 3.12, tetapi 3.12 belum terpasang.
- CPU sebuah proses tertulis `n/a` pada sampel pertama PID itu, karena persentase butuh dua titik waktu.
- Frekuensi CPU bisa tertulis "tidak tersedia" jika Windows tidak memberikannya.
- Dua proses `streamlit run`, atau `main.py` yang dijalankan saat dashboard masih terbuka, menulis histori dua kali. Cukup satu sampler.
- Drive yang hilang ditampilkan sebagai tidak tersedia dan tidak menjatuhkan aplikasi.
