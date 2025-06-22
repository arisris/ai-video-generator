### **Prompt Base Untuk membuat Script genvideo.py**

Buat sebuah skrip Python `genvideo.py` yang berfungsi penuh untuk mengubah sebuah topik teks menjadi video cerita pendek secara otomatis, mengikuti semua spesifikasi di bawah ini.

**Konfigurasi URL Endpoint:**

  * **Cerita (JSON):** `https://text.pollinations.ai/{prompt}?model=openai&json=true`
  * **Gambar:** `https://image.pollinations.ai/prompt/{prompt}?width=720&height=1280&nologo=true&safe=true&seed={seed}`
  * **Audio:** `https://text.pollinations.ai/{prompt}?model=openai-audio&voice=nova`
  * **Font Template:** `https://cdn.jsdelivr.net/fontsource/fonts/{id}@latest/latin-700-normal.ttf`

**Fitur Utama:**

1.  **Input CLI (Gunakan `argparse`):**

      * `topic`: Argumen wajib, berisi string ide cerita.
      * `--seed`: Opsional, untuk seed generator gambar.
      * `--use_whisper`: Opsional (`action='store_true'`), flag untuk mengaktifkan subtitle per-kata.
      * `--font_id`: Opsional, untuk memilih jenis font dari Fontsource (default: `'inter'`). Contoh: `roboto`, `lato`.
      * `--font_size`: Opsional, untuk ukuran font subtitle (default: `24`).

2.  **Alur Kerja Otomatis:**

      * **1. Persiapan Awal:**

          * Buat direktori cache yang spesifik untuk topik (lihat Kebutuhan Teknis).
          * Unduh file font menggunakan URL Template Font. `{id}` pada URL harus diganti dengan nilai dari argumen `--font_id`. Simpan font di cache jika belum ada.

      * **2. Buat Cerita:** Panggil API Cerita dengan `topic`. Gunakan prompt yang dikembangkan dengan baik ini untuk memastikan output JSON yang tepat:

        ```
        You are an expert multilingual storyteller AI. A user has provided a story topic. Your task is to generate a short story script based on this topic.
        The user's topic is: "{topic}"
        You MUST adhere to the following rules:
        1. Detect the language of the user's topic.
        2. The 'title' and all 'voice_prompt' values in your response MUST be in the same language as the user's topic.
        3. The 'image_prompt' values MUST be in English and be highly descriptive for a text-to-image AI.
        4. The output MUST be a single, valid JSON object.
        5. The JSON structure must be: {"title": "A story title", "segments": [{"voice_prompt": "A sentence for the narrator.", "image_prompt": "A descriptive English image prompt."}, ...]}
        6. The story must contain exactly 5 segments.
        ```

      * **3. Unduh Aset:** Berdasarkan JSON dari langkah sebelumnya, unduh semua gambar dan satu file audio narasi gabungan.

          * Saat memanggil API Audio, **wajib** gunakan prefix berikut pada prompt: `Use a storyteller tone and read the following text exactly as it is, without any changes: {combined_voice_prompt}`.

      * **4. Buat Subtitle:**

          * **Jika `--use_whisper` aktif:** Jalankan `openai-whisper` pada file audio untuk mendapatkan transkripsi dengan **timestamp per-kata**.
          * **Jika tidak aktif:** Gunakan `voice_prompt` dari setiap segmen sebagai data subtitle standar (satu blok teks per segmen gambar).

      * **5. Kompilasi Video (MoviePy):**

          * **Animasi & Transisi:** Setiap gambar diberi animasi gerakan acak (efek Ken Burns). Hubungkan setiap gambar dengan transisi `crossfade` sekitar 1 detik.
          * **Subtitle Dinamis:** Gunakan file font yang sudah diunduh.
              * Jika menggunakan Whisper, buat efek subtitle karaoke (teks muncul/berubah warna kata demi kata sesuai timestamp).
              * Jika tidak, tampilkan satu blok teks subtitle untuk setiap segmen gambar.
              * Gunakan ukuran font dari argumen `--font_size`.
          * **Finalisasi:** Gabungkan video, audio narasi, dan subtitle menjadi satu file `.mp4`. Saat ekspor, gunakan **`preset="medium"`** untuk kualitas video.

**Kebutuhan Teknis:**

  * **Pustaka:** `requests`, `moviepy==1.0.3`. (Pustaka `openai-whisper` hanya diperlukan jika user menggunakan flag `--use_whisper`).
  * **Struktur Cache:** Buat direktori cache yang spesifik untuk setiap proyek untuk menghindari konflik. Contoh: `cache/petualangan-kucing-di-mars/images/`. Nama folder harus di-"slugify" dari judul cerita.
  * **Kualitas Kode:** Terapkan penanganan error (`try-except`) untuk panggilan API dan proses file. Kode harus bersih dan terstruktur.