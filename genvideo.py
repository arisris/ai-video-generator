# -*- coding: utf-8 -*-
"""
genvideo.py - Generator Video Cerita Pendek Otomatis

Skrip ini mengubah sebuah topik teks menjadi video cerita pendek secara otomatis.
Alur kerja:
1.  Menerima topik dari pengguna melalui CLI.
2.  Membuat cerita dalam format JSON menggunakan API, termasuk deteksi bahasa.
3.  Mengunduh aset yang diperlukan (gambar, audio narasi, font).
4.  Membuat subtitle, baik per segmen atau per kata (menggunakan Whisper CLI dengan deteksi bahasa).
5.  Mengkompilasi semua aset menjadi file video MP4 menggunakan MoviePy dengan transisi acak.

Dependensi:
- requests
- moviepy==1.0.3
- openai-whisper (CLI, bukan modul Python)

Contoh Penggunaan:
# Penggunaan dasar dalam Bahasa Indonesia (akan menggunakan --language id untuk Whisper)
python genvideo.py "Petualangan seekor kucing pemberani di hutan ajaib" --use_whisper

# Penggunaan dalam Bahasa Inggris (akan menggunakan --language en untuk Whisper)
python genvideo.py "A lonely robot" --use_whisper --whisper_path "/home/user/.local/bin/whisper"
"""
import argparse
import json
import os
import random
import re
import sys
import requests
import subprocess # Ditambahkan untuk menjalankan proses eksternal (Whisper CLI)
from urllib.parse import quote
from pathlib import Path

# Coba impor pustaka yang diperlukan
try:
    from moviepy.editor import (
        VideoFileClip, AudioFileClip, ImageClip, TextClip,
        CompositeVideoClip, concatenate_videoclips
    )
    from moviepy.video.fx.all import fadein, fadeout
    from moviepy.video.compositing.transitions import slide_in
except ImportError:
    print("Error: MoviePy tidak terinstal. Silakan instal dengan 'pip install moviepy==1.0.3'")
    sys.exit(1)

# --- KONFIGURASI URL ENDPOINT ---
URL_STORY = "https://text.pollinations.ai/{prompt}?model=openai&json=true"
URL_IMAGE = "https://image.pollinations.ai/prompt/{prompt}?width=720&height=1280&nologo=true&safe=true&seed={seed}"
URL_AUDIO = "https://text.pollinations.ai/{prompt}?model=openai-audio&voice=nova"
URL_FONT = "https://cdn.jsdelivr.net/fontsource/fonts/{id}@latest/latin-700-normal.ttf"

DEFAULT_SEED = 5000

# --- FUNGSI HELPER ---

def slugify(text):
    """
    Mengubah teks menjadi "slug" yang aman untuk nama file atau direktori.
    Contoh: "Hello World!" -> "hello-world"
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text).strip('-')
    return text

def setup_cache_directories(story_title):
    """
    Membuat struktur direktori cache untuk proyek video.
    """
    slug_title = slugify(story_title)
    base_cache_path = Path("cache") / slug_title
    image_path = base_cache_path / "images"
    audio_path = base_cache_path / "audio"
    subtitle_path = base_cache_path / "subtitles"
    
    for path in [base_cache_path, image_path, audio_path, subtitle_path]:
        path.mkdir(parents=True, exist_ok=True)
        
    print(f"✅ Direktori cache dibuat di: {base_cache_path}")
    return {
        "base": base_cache_path,
        "images": image_path,
        "audio": audio_path,
        "subtitles": subtitle_path
    }

def download_file(url, destination):
    """

    Mengunduh file dari URL dan menyimpannya ke tujuan.
    """
    if destination.exists():
        print(f"☑️ File sudah ada: {destination.name}")
        return True
    
    try:
        print(f"📥 Mengunduh {destination.name} dari {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"✅ Berhasil mengunduh: {destination.name}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Gagal mengunduh {destination.name}. Error: {e}")
        return False

# --- FUNGSI ALUR KERJA UTAMA ---

def generate_story_from_topic(topic, cache_path):
    """
    Membuat cerita dari topik menggunakan API.
    """
    print("\n--- Langkah 1: Membuat Cerita ---")
    prompt_template = f"""
You are an expert multilingual storyteller AI. A user has provided a story topic. Your task is to generate a short story script based on this topic.
The user's topic is: "{topic}"
You MUST adhere to the following rules:
1. Detect the language of the user's topic.
2. The 'title' and all 'voice_prompt' values in your response MUST be in the same language as the user's topic.
3. The 'image_prompt' values MUST be in English and be highly descriptive for a text-to-image AI.
4. The output MUST be a single, valid JSON object.
5. The JSON structure must be: {{"title": "A story title", "lang": "id", "segments": [{{"voice_prompt": "A sentence for the narrator.", "image_prompt": "A descriptive English image prompt."}}, ...]}}
6. The story must contain exactly 5 segments.
7. The 'lang' field MUST contain the appropriate two-letter language code for the detected language. Supported codes are: af, am, ar, as, az, ba, be, bg, bn, bo, br, bs, ca, cs, cy, da, de, el, en, es, et, eu, fa, fi, fo, fr, gl, gu, ha, haw, he, hi, hr, ht, hu, hy, id, is, it, ja, jw, ka, kk, km, kn, ko, la, lb, ln, lo, lt, lv, mg, mi, mk, ml, mn, mr, ms, mt, my, ne, nl, nn, no, oc, pa, pl, ps, pt, ro, ru, sa, sd, si, sk, sl, sn, so, sq, sr, su, sv, sw, ta, te, tg, th, tk, tl, tr, tt, uk, ur, uz, vi, yi, yo, yue, zh.
"""
    
    story_json_path = cache_path / "story.json"
    if story_json_path.exists():
        print("☑️ Menggunakan cerita dari cache.")
        with open(story_json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    encoded_prompt = quote(prompt_template)
    url = URL_STORY.format(prompt=encoded_prompt)
    
    try:
        print("🧠 Menghubungi AI untuk membuat cerita...")
        response = requests.get(url)
        response.raise_for_status()
        story_data = response.json()
        
        with open(story_json_path, 'w', encoding='utf-8') as f:
            json.dump(story_data, f, ensure_ascii=False, indent=4)
            
        print(f"✅ Cerita berhasil dibuat: '{story_data.get('title', 'Tanpa Judul')}' (Bahasa: {story_data.get('lang', 'N/A')})")
        return story_data
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"❌ Gagal membuat cerita. Error: {e}")
        sys.exit(1)


def download_all_assets(story_data, seed, cache_paths):
    """
    Mengunduh semua gambar dan file audio narasi.
    """
    print("\n--- Langkah 2: Mengunduh Aset ---")
    segments = story_data.get('segments', [])

    image_paths = []
    for i, segment in enumerate(segments):
        image_prompt = segment.get('image_prompt', 'a blank white background')
        encoded_prompt = quote(image_prompt)
        url = URL_IMAGE.format(prompt=encoded_prompt, seed=seed)
        
        image_dest = cache_paths["images"] / f"image_{i+1}.jpg"
        if download_file(url, image_dest):
            image_paths.append(str(image_dest))

    if len(image_paths) != len(segments):
        print("❌ Tidak semua gambar berhasil diunduh. Proses dihentikan.")
        sys.exit(1)

    combined_voice_prompt = " ".join([seg['voice_prompt'] for seg in segments])
    audio_prompt = f"Use a storyteller tone and read the following text exactly as it is, without any changes: {combined_voice_prompt}"
    encoded_audio_prompt = quote(audio_prompt)
    audio_url = URL_AUDIO.format(prompt=encoded_audio_prompt)
    
    audio_dest = cache_paths["audio"] / "narration.mp3"
    if not download_file(audio_url, audio_dest):
        print("❌ Gagal mengunduh audio narasi. Proses dihentikan.")
        sys.exit(1)
        
    return {"images": image_paths, "audio": str(audio_dest)}

def generate_subtitles(use_whisper, audio_path, story_data, cache_paths, whisper_executable_path):
    """
    Membuat data subtitle, baik dengan Whisper CLI atau metode standar.
    """
    print("\n--- Langkah 3: Membuat Subtitle ---")
    if use_whisper:
        print("🎤 Mencoba membuat subtitle dengan Whisper CLI...")
        audio_file = Path(audio_path)
        expected_json_output = cache_paths["subtitles"] / f"{audio_file.stem}.json"

        if expected_json_output.exists():
            print(f"☑️ Menggunakan transkripsi Whisper dari cache: {expected_json_output}")
            with open(expected_json_output, 'r', encoding='utf-8') as f:
                return {"type": "whisper", "data": json.load(f)}
        
        command = [
            whisper_executable_path,
            str(audio_file),
            "--model", "base",
            "--word_timestamps", "True",
            "--output_format", "json",
            "--output_dir", str(cache_paths["subtitles"])
        ]
        
        lang_code = story_data.get("lang")
        if lang_code:
            print(f"🌐 Menambahkan parameter bahasa untuk Whisper: --language {lang_code}")
            command.extend(["--language", lang_code])
        else:
            print("⚠️ Peringatan: Kode bahasa ('lang') tidak ditemukan di story.json. Whisper akan melakukan deteksi otomatis.")

        try:
            print(f"🏃 Menjalankan perintah: {' '.join(command)}")
            subprocess.run(command, check=True, capture_output=True, text=True)
            
            print(f"✅ Whisper CLI selesai. Membaca file output: {expected_json_output}")
            with open(expected_json_output, 'r', encoding='utf-8') as f:
                result = json.load(f)
            return {"type": "whisper", "data": result}
            
        except FileNotFoundError:
            print(f"❌ Error: Whisper executable tidak ditemukan di '{whisper_executable_path}'.")
            print("   Pastikan Whisper CLI terinstal dan berada di PATH, atau tentukan lokasinya dengan --whisper_path.")
            print("   Beralih ke metode subtitle standar.")
            return generate_subtitles(False, audio_path, story_data, cache_paths, whisper_executable_path)
        except subprocess.CalledProcessError as e:
            print(f"❌ Terjadi error saat menjalankan Whisper CLI: {e}")
            print(f"   Stderr: {e.stderr}")
            print("   Beralih ke metode subtitle standar.")
            return generate_subtitles(False, audio_path, story_data, cache_paths, whisper_executable_path)

    else:
        print("📄 Menggunakan subtitle standar per segmen.")
        return {"type": "standard", "data": story_data["segments"]}


def create_final_video(story_data, assets, subtitles, font_path, font_size, output_path=None):
    """
    Menggabungkan semua aset menjadi video MP4 menggunakan MoviePy.
    Logika dipisah total antara mode Whisper dan mode standar untuk sinkronisasi yang lebih baik.
    """
    print("\n--- Langkah 4: Mengkompilasi Video ---")
    print("🎬 Proses ini mungkin memakan waktu cukup lama...")

    narration_audio = AudioFileClip(assets["audio"])
    raw_image_clips = [ImageClip(path) for path in assets["images"]]

    # --- PERUBAHAN BESAR: Memisahkan total logika Whisper dan Standar ---

    if subtitles["type"] == "whisper":
        # --- LOGIKA BARU KHUSUS UNTUK WHISPER (UNTUK SINKRONISASI) ---
        print("⚙️ Menggunakan logika kompilasi khusus Whisper untuk sinkronisasi presisi.")
        
        whisper_segments = subtitles["data"].get("segments", [])
        if not whisper_segments:
            print("❌ Error: Output Whisper tidak mengandung 'segments'. Tidak bisa melanjutkan.")
            sys.exit(1)

        # 1. Buat klip video dasar dari gambar dengan durasi dari Whisper
        video_clips = []
        for i, seg_info in enumerate(whisper_segments):
            duration = seg_info['end'] - seg_info['start']
            img_clip = raw_image_clips[i % len(raw_image_clips)] # Daur ulang gambar jika segmen > gambar
            
            # Animasi Ken Burns
            w, h = img_clip.size
            zoom_factor = 1.25
            def animate_zoom(t): return 1 + (zoom_factor - 1) * (t / duration)
            
            animated_clip = (img_clip.resize(animate_zoom)
                                     .set_position("center", "center")
                                     .set_duration(duration))
            video_clips.append(animated_clip)

        # 2. Gabungkan klip video dasar dengan transisi
        final_video_base = video_clips[0]
        transition_duration = 0.5
        for i in range(1, len(video_clips)):
            clip_to_add = video_clips[i]
            # Logika transisi tetap sama
            transition_type = random.choice(["crossfade", "slide_in_left", "slide_in_top", "fade"])
            print(f"  -> Menerapkan transisi '{transition_type}' antara segmen {i} dan {i+1}")
            if transition_type == "crossfade":
                final_video_base = CompositeVideoClip([final_video_base, clip_to_add.set_start(final_video_base.duration - transition_duration).crossfadein(transition_duration)])
            elif transition_type == "slide_in_left":
                final_video_base = CompositeVideoClip([final_video_base, clip_to_add.set_start(final_video_base.duration - transition_duration).fx(slide_in, duration=transition_duration, side='left')])
            elif transition_type == "slide_in_top":
                final_video_base = CompositeVideoClip([final_video_base, clip_to_add.set_start(final_video_base.duration - transition_duration).fx(slide_in, duration=transition_duration, side='top')])
            elif transition_type == "fade":
                final_video_base = concatenate_videoclips([final_video_base.fx(fadeout, transition_duration), clip_to_add.fx(fadein, transition_duration)], padding=-transition_duration, method="compose")

        # 3. Buat semua klip subtitle (karaoke) untuk seluruh video
        all_subtitle_clips = []
        for seg_info in whisper_segments:
            w, h = final_video_base.size
            full_sentence = seg_info['text'].strip()
            
            # Teks latar belakang (putih)
            bg_text = (TextClip(full_sentence, fontsize=font_size, font=font_path, color='white',
                                stroke_color='black', stroke_width=1.5, method='caption', size=(w*0.9, None))
                                .set_position(('center', 0.8), relative=True)
                                .set_start(seg_info['start'])
                                .set_duration(seg_info['end'] - seg_info['start']))
            all_subtitle_clips.append(bg_text)

            # Teks highlight (kuning) kata per kata
            if 'words' in seg_info:
                for j, word_info in enumerate(seg_info['words']):
                    highlighted_sentence = ' '.join([w['word'].strip() for w in seg_info['words'][:j+1]])
                    hl_clip = (TextClip(highlighted_sentence, fontsize=font_size, font=font_path, color='yellow',
                                        method='caption', size=(w*0.9, None), align='West')
                                        .set_position(('center', 0.8), relative=True)
                                        .set_start(word_info['start'])
                                        .set_duration(word_info['end'] - word_info['start']))
                    all_subtitle_clips.append(hl_clip)
        
        # 4. Gabungkan video dasar dengan semua subtitle
        final_video = CompositeVideoClip([final_video_base] + all_subtitle_clips)

    else:
        # --- LOGIKA STANDAR (TANPA WHISPER) - Dipertahankan karena sudah bekerja baik ---
        print("⚙️ Menggunakan logika kompilasi standar (non-Whisper).")
        
        avg_duration = narration_audio.duration / len(raw_image_clips)
        
        processed_clips = []
        for i, img_clip in enumerate(raw_image_clips):
            w, h = img_clip.size
            zoom_factor = 1.25
            def animate_zoom(t): return 1 + (zoom_factor - 1) * (t / avg_duration)

            animated_clip = (img_clip.resize(animate_zoom)
                                     .set_position("center", "center")
                                     .set_duration(avg_duration))
            
            text = subtitles["data"][i]['voice_prompt']
            txt_clip = (TextClip(text, fontsize=font_size, font=font_path, color='white',
                                 stroke_color='black', stroke_width=1.5, method='caption', size=(w*0.9, None))
                                 .set_position(('center', 0.8), relative=True)
                                 .set_duration(avg_duration))
            
            segment_video = CompositeVideoClip([animated_clip, txt_clip], size=img_clip.size)
            processed_clips.append(segment_video)

        final_video_base = processed_clips[0]
        transition_duration = 0.5
        for i in range(1, len(processed_clips)):
            # Logika transisi sama
            transition_type = random.choice(["crossfade", "slide_in_left", "slide_in_top", "fade"])
            print(f"  -> Menerapkan transisi '{transition_type}' antara segmen {i} dan {i+1}")
            clip_to_add = processed_clips[i]
            if transition_type == "crossfade":
                final_video_base = CompositeVideoClip([final_video_base, clip_to_add.set_start(final_video_base.duration - transition_duration).crossfadein(transition_duration)])
            elif transition_type == "slide_in_left":
                final_video_base = CompositeVideoClip([final_video_base, clip_to_add.set_start(final_video_base.duration - transition_duration).fx(slide_in, duration=transition_duration, side='left')])
            elif transition_type == "slide_in_top":
                final_video_base = CompositeVideoClip([final_video_base, clip_to_add.set_start(final_video_base.duration - transition_duration).fx(slide_in, duration=transition_duration, side='top')])
            elif transition_type == "fade":
                final_video_base = concatenate_videoclips([final_video_base.fx(fadeout, transition_duration), clip_to_add.fx(fadein, transition_duration)], padding=-transition_duration, method="compose")
        final_video = final_video_base

    # --- Finalisasi (Berlaku untuk kedua mode) ---
    final_video = final_video.set_audio(narration_audio)
    
    if final_video.duration > narration_audio.duration:
        final_video = final_video.subclip(0, narration_audio.duration)
    
    if output_path:
        output_filename = Path(output_path)
        output_filename.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_filename = Path(f"{slugify(story_data.get('title', 'untitled-video'))}.mp4")
    
    print(f" exporting video ke '{output_filename}'...")
    final_video.write_videofile(str(output_filename), codec='libx264', audio_codec='aac', preset='medium', fps=24, threads=4)
    
    narration_audio.close()
    for clip in raw_image_clips:
        clip.close()
    if isinstance(final_video, (CompositeVideoClip, VideoFileClip)):
        final_video.close()
        
    print(f"\n🎉 Video berhasil dibuat: {output_filename}")

def main():
    parser = argparse.ArgumentParser(description="Generator Video Cerita Pendek Otomatis.")
    parser.add_argument("topic", type=str, help="Ide atau topik cerita yang ingin dibuatkan video.")
    parser.add_argument("--seed", type=int, default=None, help="Seed untuk generator gambar agar hasilnya konsisten.")
    parser.add_argument("--use_whisper", action="store_true", help="Gunakan Whisper CLI untuk subtitle per-kata.")
    parser.add_argument("--font_id", type=str, default="inter", help="ID font dari Fontsource.org (contoh: 'roboto', 'lato').")
    parser.add_argument("--font_size", type=int, default=36, help="Ukuran font untuk subtitle.")
    parser.add_argument("--output_path", type=str, default=None, help="Jalur file output untuk video (contoh: 'videos/hasil.mp4').")
    parser.add_argument("--whisper_path", type=str, default="whisper", help="Path ke file executable Whisper CLI.")
    
    args = parser.parse_args()

    print("--- Memulai Proses Pembuatan Video ---")
    
    font_cache_dir = Path("cache") / "fonts"
    font_cache_dir.mkdir(parents=True, exist_ok=True)
    font_path = font_cache_dir / f"{args.font_id}.ttf"
    if not download_file(URL_FONT.format(id=args.font_id), font_path):
        print(f"❌ Gagal mengunduh font '{args.font_id}'. Pastikan ID font valid.")
        sys.exit(1)

    initial_slug = slugify(args.topic)
    story_json_path = (Path("cache") / initial_slug) / "story.json"
    story_title_for_cache = args.topic

    if story_json_path.exists():
         with open(story_json_path, 'r', encoding='utf-8') as f:
            story_title_for_cache = json.load(f).get("title", args.topic)

    cache_paths = setup_cache_directories(story_title_for_cache)
    
    story_data = generate_story_from_topic(args.topic, cache_paths["base"])
    actual_slug_title = slugify(story_data.get("title", story_title_for_cache))
    
    if actual_slug_title != slugify(story_title_for_cache):
        new_base_path = Path("cache") / actual_slug_title
        try:
            if not new_base_path.exists():
                os.rename(cache_paths["base"], new_base_path)
                print(f"🔄 Mengganti nama direktori cache ke: {new_base_path}")
                cache_paths = setup_cache_directories(story_data.get("title"))
        except OSError as e:
            print(f"⚠️ Tidak dapat mengganti nama direktori cache: {e}. Melanjutkan dengan nama lama.")

    current_seed = DEFAULT_SEED if args.seed is None else args.seed
    
    assets = download_all_assets(story_data, current_seed, cache_paths)
    subtitles = generate_subtitles(args.use_whisper, assets["audio"], story_data, cache_paths, args.whisper_path)
    create_final_video(story_data, assets, subtitles, str(font_path), args.font_size, args.output_path)

if __name__ == "__main__":
    main()
