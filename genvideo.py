# -*- coding: utf-8 -*-
"""
genvideo.py - Generator Video Cerita Pendek Otomatis

Skrip ini mengubah sebuah topik teks menjadi video cerita pendek secara otomatis.
Alur kerja:
1.  Menerima topik dari pengguna melalui CLI atau mode interaktif.
2.  Membuat cerita dalam format JSON menggunakan API, termasuk deteksi bahasa.
3.  Mengunduh aset yang diperlukan (gambar, audio narasi, font, musik).
4.  Membuat subtitle, baik per segmen atau per kata (menggunakan Whisper CLI).
5.  Mengkompilasi semua aset menjadi file video MP4 menggunakan MoviePy dengan transisi.

Dependensi:
- requests
- moviepy==1.0.3
- openai-whisper (CLI, bukan modul Python)

Contoh Penggunaan:
# Mode Interaktif Penuh
python genvideo.py -i

# Penggunaan Lanjutan dengan Kustomisasi Penuh
python genvideo.py "A journey through a cyberpunk city at night" --use_whisper --use_gpu --music "path/to/your/music.mp3" --highlight_color "#00FFFF" --subtitle_position center
"""
import argparse
import json
import os
import random
import re
import sys
import time
import requests
import subprocess
from urllib.parse import quote
from pathlib import Path
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    CompositeAudioClip,
)
from moviepy.video.fx.all import fadein, fadeout
import moviepy.audio.fx.all as afx

# --- KONFIGURASI URL ENDPOINT ---
URL_STORY = "https://text.pollinations.ai/{prompt}?model=openai&json=true"
URL_IMAGE = "https://image.pollinations.ai/prompt/{prompt}?width=720&height=1280&nologo=true&safe=true&seed={seed}"
URL_AUDIO = "https://text.pollinations.ai/{prompt}?model=openai-audio&voice=nova"
URL_FONT = "https://cdn.jsdelivr.net/fontsource/fonts/{id}@latest/latin-700-normal.ttf"

DEFAULT_SEED = 5000
MAX_RETRIES = 3
SEPARATOR = "=" * 50

# --- FUNGSI HELPER ---

def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text


def setup_cache_directories(story_title):
    slug_title = slugify(story_title)
    base_cache_path = Path("cache") / slug_title
    image_path = base_cache_path / "images"
    audio_path = base_cache_path / "audio"
    subtitle_path = base_cache_path / "subtitles"
    for path in [base_cache_path, image_path, audio_path, subtitle_path]:
        path.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Direktori cache siap di: {base_cache_path}")
    return {"base": base_cache_path, "images": image_path, "audio": audio_path, "subtitles": subtitle_path}


def download_file(url, destination):
    """Mengunduh file dengan logika coba-ulang (retry)."""
    if destination.exists():
        print(f"[INFO] File sudah ada: {destination.name}")
        return True
    
    for attempt in range(MAX_RETRIES):
        try:
            print(f"[>] Mengunduh {destination.name} (Percobaan {attempt + 1}/{MAX_RETRIES})...")
            # Menambahkan timeout untuk mencegah hang
            response = requests.get(url, stream=True, timeout=20)
            response.raise_for_status()

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"[SUCCESS] Berhasil mengunduh: {destination.name}")
            return True # Berhasil, keluar dari fungsi

        except requests.exceptions.RequestException as e:
            print(f"[WARN] Percobaan {attempt + 1} gagal: {e}")
            if attempt < MAX_RETRIES - 1:
                print("[INFO] Mencoba lagi dalam 3 detik...")
                time.sleep(3) # Jeda sebelum mencoba lagi
            else:
                print(f"[ERROR] Gagal total mengunduh {destination.name} setelah {MAX_RETRIES} percobaan.")
                return False # Gagal total setelah semua percobaan

    return False # Seharusnya tidak pernah tercapai, tapi sebagai pengaman


# --- FUNGSI ALUR KERJA UTAMA ---

def generate_story_from_topic(topic, cache_path):
    print(f"\n{SEPARATOR}\n[LANGKAH 1/5] Membuat Cerita\n{SEPARATOR}")
    story_json_path = cache_path / "story.json"
    if story_json_path.exists():
        print("[INFO] Menggunakan cerita dari cache.")
        with open(story_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    prompt_template = f'You are an expert multilingual storyteller AI. A user has provided a story topic. Your task is to generate a short story script based on this topic. The user\'s topic is: "{topic}". You MUST adhere to the following rules: 1. Detect the language of the user\'s topic. 2. The \'title\' and all \'voice_prompt\' values in your response MUST be in the same language as the user\'s topic. 3. The \'image_prompt\' values MUST be in English and be highly descriptive for a text-to-image AI. 4. The output MUST be a single, valid JSON object. 5. The JSON structure must be: {{"title": "A story title", "lang": "id", "segments": [{{"voice_prompt": "A sentence for the narrator.", "image_prompt": "A descriptive English image prompt."}}, ...]}} 6. The story must contain exactly 5 segments. 7. The \'lang\' field MUST contain the appropriate two-letter language code for the detected language.'
    encoded_prompt = quote(prompt_template)
    url = URL_STORY.format(prompt=encoded_prompt)
    try:
        print("[INFO] Menghubungi AI untuk membuat cerita...")
        response = requests.get(url)
        response.raise_for_status()
        story_data = response.json()
        with open(story_json_path, "w", encoding="utf-8") as f:
            json.dump(story_data, f, ensure_ascii=False, indent=4)
        print(f"[SUCCESS] Cerita berhasil dibuat: '{story_data.get('title', 'Tanpa Judul')}'")
        return story_data
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"[ERROR] Gagal membuat cerita. Error: {e}")
        sys.exit(1)


def download_all_assets(story_data, seed, cache_paths):
    print(f"\n{SEPARATOR}\n[LANGKAH 2/5] Mengunduh Aset\n{SEPARATOR}")
    segments = story_data.get("segments", [])
    image_paths = []
    for i, segment in enumerate(segments):
        image_prompt = segment.get("image_prompt", "a blank white background")
        encoded_prompt = quote(image_prompt)
        url = URL_IMAGE.format(prompt=encoded_prompt, seed=seed)
        image_dest = cache_paths["images"] / f"image_{i+1}.jpg"
        if not download_file(url, image_dest):
             print(f"[FATAL] Proses dihentikan karena gagal mengunduh aset.")
             sys.exit(1)
        image_paths.append(str(image_dest))
    
    print("[INFO] Semua aset gambar berhasil diunduh.")

    combined_voice_prompt = " ".join([seg["voice_prompt"] for seg in segments])
    audio_prompt = f"Use a storyteller tone and read the following text exactly as it is, without any changes: {combined_voice_prompt}"
    encoded_audio_prompt = quote(audio_prompt)
    audio_url = URL_AUDIO.format(prompt=encoded_audio_prompt)
    audio_dest = cache_paths["audio"] / "narration.mp3"
    if not download_file(audio_url, audio_dest):
        print("[FATAL] Proses dihentikan karena gagal mengunduh audio narasi.")
        sys.exit(1)
    
    print("[SUCCESS] Semua aset berhasil diunduh.")
    return {"images": image_paths, "audio": str(audio_dest)}


def generate_subtitles(use_whisper, audio_path, story_data, cache_paths, whisper_executable_path, use_gpu):
    print(f"\n{SEPARATOR}\n[LANGKAH 3/5] Membuat Subtitle\n{SEPARATOR}")
    if use_whisper:
        print("[INFO] Mode subtitle per-kata (Whisper) dipilih.")
        if use_gpu:
            print("[INFO] Opsi --use_gpu aktif. Whisper akan otomatis menggunakan GPU jika instalasi PyTorch mendukung CUDA.")
        audio_file = Path(audio_path)
        expected_json_output = cache_paths["subtitles"] / f"{audio_file.stem}.json"
        if expected_json_output.exists():
            print(f"[INFO] Menggunakan transkripsi Whisper dari cache.")
            with open(expected_json_output, "r", encoding="utf-8") as f:
                return {"type": "whisper", "data": json.load(f)}
        command = [whisper_executable_path, str(audio_file), "--model", "base", "--word_timestamps", "True", "--output_format", "json", "--output_dir", str(cache_paths["subtitles"])]
        lang_code = story_data.get("lang")
        if lang_code:
            print(f"[INFO] Menambahkan parameter bahasa untuk Whisper: --language {lang_code}")
            command.extend(["--language", lang_code])
        else:
            print("[WARN] Kode bahasa ('lang') tidak ditemukan. Whisper akan deteksi otomatis.")
        try:
            print(f"[>] Menjalankan perintah Whisper CLI...")
            subprocess.run(command, check=True, capture_output=True, text=True)
            print("[SUCCESS] Transkripsi Whisper berhasil dibuat.")
            with open(expected_json_output, "r", encoding="utf-8") as f:
                return {"type": "whisper", "data": json.load(f)}
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(f"[ERROR] Gagal saat menjalankan Whisper: {e}")
            print("[INFO] Beralih ke metode subtitle standar.")
            return generate_subtitles(False, audio_path, story_data, cache_paths, whisper_executable_path, use_gpu)
    else:
        print("[INFO] Mode subtitle standar (per segmen) dipilih.")
        return {"type": "standard", "data": story_data["segments"]}


def create_final_video(story_data, assets, subtitles, args):
    print(f"\n{SEPARATOR}\n[LANGKAH 4/5] Mengkompilasi Klip Video\n{SEPARATOR}")
    
    PADDING_DURATION = 5
    print(f"[INFO] Menambahkan padding {PADDING_DURATION} detik di awal dan akhir video.")

    POSITIONS = {'bottom': ('center', 0.8), 'center': ('center', 'center'), 'top': ('center', 0.1)}
    subtitle_pos = POSITIONS.get(args.subtitle_position, ('center', 0.8))

    narration_audio = AudioFileClip(assets["audio"])
    raw_image_clips = [ImageClip(path) for path in assets["images"]]

    # --- Buat klip visual utama ---
    if subtitles["type"] == "whisper":
        whisper_segments = subtitles["data"].get("segments", [])
        if not whisper_segments:
            print("[ERROR] Output Whisper tidak mengandung 'segments'. Tidak bisa melanjutkan.")
            sys.exit(1)
        total_visual_duration = whisper_segments[-1]["end"]
        image_duration = total_visual_duration / len(raw_image_clips)
        video_clips = [img.resize(lambda t: 1 + 0.2 * (t / image_duration)).set_position("center", "center").set_duration(image_duration) for img in raw_image_clips]
        main_visual_track = concatenate_videoclips(video_clips, method="compose")
        all_subtitle_clips = []
        for seg_info in whisper_segments:
            w, h = main_visual_track.size
            if "words" in seg_info:
                for word_info in seg_info["words"]:
                    highlighted_sentence = " ".join([w["word"].strip() for w in seg_info["words"] if w['start'] <= word_info['start']])
                    hl_clip = TextClip(highlighted_sentence, fontsize=args.font_size, font=args.font_path, color=args.highlight_color, method="caption", size=(w * 0.9, None), align="Center").set_position(subtitle_pos, relative=True).set_start(word_info["start"]).set_duration(word_info["end"] - word_info["start"])
                    all_subtitle_clips.append(hl_clip)
        main_visual_track = CompositeVideoClip([main_visual_track] + all_subtitle_clips)
    else: # Mode Standar
        avg_duration = narration_audio.duration / len(raw_image_clips)
        processed_clips = []
        for i, img_clip in enumerate(raw_image_clips):
            w, h = img_clip.size
            animated_clip = img_clip.resize(lambda t: 1 + 0.2 * (t / avg_duration)).set_position("center", "center").set_duration(avg_duration)
            text = subtitles["data"][i]["voice_prompt"]
            txt_clip = TextClip(text, fontsize=args.font_size, font=args.font_path, color=args.font_color, stroke_color="black", stroke_width=1.5, method="caption", size=(w * 0.9, None), align="Center").set_position(subtitle_pos, relative=True).set_duration(avg_duration)
            segment_video = CompositeVideoClip([animated_clip, txt_clip], size=img_clip.size)
            if processed_clips:
                segment_video = segment_video.fadein(1)
            processed_clips.append(segment_video)
        main_visual_track = concatenate_videoclips(processed_clips)

    # --- Buat Klip Padding ---
    intro_clip = raw_image_clips[0].set_duration(PADDING_DURATION).fadein(1)
    outro_clip = raw_image_clips[-1].set_duration(PADDING_DURATION).fadeout(1)
    
    # --- Gabungkan semua klip visual ---
    final_visual_track = concatenate_videoclips([intro_clip, main_visual_track, outro_clip])
    
    print(f"\n{SEPARATOR}\n[LANGKAH 5/5] Finalisasi Audio & Ekspor Video\n{SEPARATOR}")
    
    # --- Atur Audio ---
    narration_audio = narration_audio.set_start(PADDING_DURATION)
    
    final_audio_clips = [narration_audio]
    if args.music:
        try:
            music_clip = AudioFileClip(args.music).volumex(0.15)
            looped_music = afx.audio_loop(music_clip, duration=final_visual_track.duration)
            final_audio_clips.append(looped_music)
            print("[INFO] Musik latar ditambahkan.")
        except Exception as e:
            print(f"[WARN] Gagal memuat atau memproses file musik: {e}")
    
    final_audio = CompositeAudioClip(final_audio_clips)
    
    # PERBAIKAN: Secara eksplisit set durasi audio agar sama dengan video
    final_audio = final_audio.set_duration(final_visual_track.duration)

    final_video = final_visual_track.set_audio(final_audio)

    # --- Ekspor Video ---
    output_filename = Path(args.output_path) if args.output_path else Path(f"{slugify(story_data.get('title', 'untitled-video'))}.mp4")
    output_filename.parent.mkdir(parents=True, exist_ok=True)
    video_codec = "h264_nvenc" if args.use_gpu else "libx264"
    try:
        print(f"[>] Mengekspor video ke '{output_filename}' menggunakan codec: {video_codec}...")
        final_video.write_videofile(str(output_filename), codec=video_codec, audio_codec="aac", preset="medium", fps=24, threads=8)
    except Exception as e:
        if args.use_gpu:
            print(f"[ERROR] Gagal encoding dengan GPU: {e}\n[INFO] Beralih ke encoding CPU (libx264)...")
            final_video.write_videofile(str(output_filename), codec="libx264", audio_codec="aac", preset="medium", fps=24, threads=8)
        else:
            print(f"[ERROR] Gagal saat menulis file video: {e}")
            sys.exit(1)
    
    for clip in [narration_audio, final_video] + raw_image_clips:
        if clip: clip.close()
    
    print(f"\n{SEPARATOR}")
    print(f"🎉 [SUCCESS] Video berhasil dibuat! 🎉")
    print(f"   > Lokasi File: {output_filename.resolve()}")
    print(f"{SEPARATOR}")


def run_interactive_mode(defaults):
    """Memandu pengguna melalui serangkaian pertanyaan untuk mengonfigurasi skrip."""
    print(f"\n{SEPARATOR}\n--- Mode Konfigurasi Interaktif ---\n{SEPARATOR}")
    print("Jawab pertanyaan berikut. Tekan Enter untuk menggunakan nilai default.")

    while not (topic := input("1. Masukkan topik cerita: ")):
        print("[ERROR] Topik tidak boleh kosong.")
    defaults.topic = topic
    
    print(SEPARATOR)

    use_whisper_choice = input(f"2. Gunakan subtitle per-kata (Whisper)? (y/n) [default: {'y' if defaults.use_whisper else 'n'}]: ").lower()
    if use_whisper_choice == 'y':
        defaults.use_whisper = True
    elif use_whisper_choice == 'n':
        defaults.use_whisper = False

    use_gpu_choice = input(f"3. Coba gunakan akselerasi GPU? (y/n) [default: {'y' if defaults.use_gpu else 'n'}]: ").lower()
    if use_gpu_choice == 'y':
        defaults.use_gpu = True
    elif use_gpu_choice == 'n':
        defaults.use_gpu = False

    defaults.music = input(f"4. Path ke file musik latar (opsional): ") or defaults.music
    seed_input = input(f"5. Seed gambar (angka, kosongkan untuk acak): ")
    defaults.seed = int(seed_input) if seed_input.isdigit() else None
    
    print(f"{SEPARATOR}\n--- Kustomisasi Tampilan Subtitle ---\n{SEPARATOR}")
    defaults.font_color = input(f"6. Warna font (e.g., 'white', '#FFFF00') [default: {defaults.font_color}]: ") or defaults.font_color
    if defaults.use_whisper:
        defaults.highlight_color = input(f"7. Warna highlight (mode whisper) [default: {defaults.highlight_color}]: ") or defaults.highlight_color
    
    pos_choice = input(f"8. Posisi subtitle (top, center, bottom) [default: {defaults.subtitle_position}]: ").lower()
    if pos_choice in ['top', 'center', 'bottom']:
        defaults.subtitle_position = pos_choice
        
    defaults.output_path = input(f"9. Path file output (opsional): ") or defaults.output_path
    
    print("\n[SUCCESS] Konfigurasi selesai. Memulai proses pembuatan video...")
    return defaults


def main():
    parser = argparse.ArgumentParser(description="Generator Video Cerita Pendek Otomatis.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("topic", nargs='?', default=None, help="Ide atau topik cerita. Opsional jika menggunakan mode interaktif.")
    parser.add_argument("-i", "--interactive", action="store_true", help="Jalankan dalam mode interaktif penuh untuk semua opsi.")
    parser.add_argument("--use_whisper", action="store_true", help="Gunakan Whisper CLI untuk subtitle per-kata.")
    parser.add_argument("--use_gpu", action="store_true", help="Coba gunakan akselerasi GPU (NVIDIA/NVENC).")
    parser.add_argument("--seed", type=int, default=None, help="Seed untuk generator gambar agar hasilnya konsisten.")
    parser.add_argument("--music", type=str, default=None, help="Path ke file musik latar (MP3, WAV, dll).")
    parser.add_argument("--font_id", type=str, default="inter", help="ID font dari Fontsource.org (e.g., 'roboto').")
    parser.add_argument("--font_size", type=int, default=40, help="Ukuran font untuk subtitle.")
    parser.add_argument("--font_color", type=str, default="white", help="Warna font subtitle (e.g., 'white', '#FFFF00').")
    parser.add_argument("--highlight_color", type=str, default="yellow", help="Warna highlight untuk subtitle mode Whisper.")
    parser.add_argument("--subtitle_position", type=str, default="bottom", choices=['top', 'center', 'bottom'], help="Posisi vertikal subtitle.")
    parser.add_argument("--output_path", type=str, default=None, help="Jalur file output untuk video (e.g., 'videos/hasil.mp4').")
    parser.add_argument("--whisper_path", type=str, default="whisper", help="Path ke file executable Whisper CLI.")
    args = parser.parse_args()

    if args.interactive:
        args = run_interactive_mode(args)
    
    if not args.topic:
        parser.error("[ERROR] Topik cerita dibutuhkan. Gunakan argumen posisi atau jalankan dengan flag -i/--interactive.")

    print("\n[INFO] Memulai Proses Pembuatan Video...")
    font_cache_dir = Path("cache") / "fonts"
    font_cache_dir.mkdir(parents=True, exist_ok=True)
    args.font_path = font_cache_dir / f"{args.font_id}.ttf"
    if not download_file(URL_FONT.format(id=args.font_id), args.font_path):
        sys.exit(1)

    cache_paths = setup_cache_directories(args.topic)
    story_data = generate_story_from_topic(args.topic, cache_paths["base"])
    
    current_seed = DEFAULT_SEED if args.seed is None else args.seed
    assets = download_all_assets(story_data, current_seed, cache_paths)
    subtitles = generate_subtitles(args.use_whisper, assets["audio"], story_data, cache_paths, args.whisper_path, args.use_gpu)
    
    create_final_video(story_data, assets, subtitles, args)


if __name__ == "__main__":
    main()
