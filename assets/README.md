# Audio assets for AampEasyScheduler

Curated audio files used as source material for AXIS Audio Manager Pro
schedules (bells, announcements, music).

## Layout

```
assets/
├── bells/        — period-change bells, chimes, buzzers, gentle elementary tones
├── effects/      — alarms, attention-getters, melodic chimes for special events
├── music/        — background instrumental tracks for cafeteria/lounge play
├── voice/        — (output dir) ElevenLabs-generated voice announcements
├── README.md     — this file
└── ATTRIBUTION.md — licenses + required credits (especially CC-BY music)
```

## How to use these

1. **Upload to AAM Pro**: drop one or more files into the matching AAM Pro
   library (announcement library for bells/effects, music library for music)
   via the SPA, OR via the chat once the `upload_tone_file` tool is wired.
2. **Reference in schedules**: the chat client can list them via
   `search_library(library_id=...)` and use them in `create_template` /
   `add_template_content` / `create_event` / `create_music_event`.
3. **CC-BY tracks need attribution displayed somewhere** if you use them in
   a production deployment. See `ATTRIBUTION.md`.

## What's here

### Bells (CC0 — public domain)

| File | What it is |
|---|---|
| `school_bell_classic.mp3` | Classic electric school/fire-house bell, single ring |
| `bell_hand_cranked.mp3` | Old-school hand-cranked dismissal bell |
| `bell_metallic_tone.mp3` | Short metallic period-change ping |
| `bell_single_ding.flac` | Single warning ding (FLAC — convert to MP3 if AAM Pro rejects) |
| `chime_calm_signal.mp3` | Gentle elementary-school chime |
| `chime_xylophone.mp3` | Soft mallet chime, kindergarten-friendly |
| `chime_pa_attention.flac` | Multi-note PA-style attention chime (FLAC) |
| `buzzer_warning.mp3` | Harsh buzzer for warning / late bell |

### Effects (CC0 — public domain)

| File | What it is |
|---|---|
| `alarm_emergency_bell.mp3` | Fire-drill style continuous bell — **test before deploying as a real drill cue** |
| `alarm_attention.mp3` | Loud attention-getter |
| `chime_westminster.mp3` | Westminster-style melodic chime, good for lunch / recess |
| `chime_crossing.mp3` | Traffic-crossing chime analogue |

### Music (CC-BY 3.0 — Kevin MacLeod / incompetech.com — attribution required)

| File | Approx. mood |
|---|---|
| `accralate.mp3` | Light instrumental |
| `ashton_manor.mp3` | Calm / classical |
| `beach_bum.mp3` | Upbeat |

## Adding more

Re-run the seed downloader:

```powershell
& powershell -ExecutionPolicy Bypass -File C:\20260520_AampEasyScheduler\tools\download_seed_assets.ps1
```

It skips files that already exist. Edit the `$downloads` array to add new sources.

For larger curations:

- **Internet Archive** is the easiest to script against — CC0 items return direct redirects to MP3/WAV/FLAC. Search at https://archive.org/details and look for items marked "Creative Commons 0" or "Public Domain".
- **Pixabay** and **Mixkit** are good but require a real browser (their direct asset URLs are JS-injected). Use the existing `tools/observer.py` if you want to grab from those.
- **ElevenLabs sound effects** (https://elevenlabs.io/sound-effects) need an API key + account. Once `ELEVENLABS_API_KEY` is configured, the chat can generate effects on demand.
- **Bundled Windows tones** (`C:\Windows\Media\Ring*.wav`) are convenient for testing but Microsoft's license is unclear for redistribution.

## File formats

AAM Pro 5.1 ships ffmpeg DLLs (libmp3lame, ogg, opus, vorbis, flac all present)
so it should handle MP3, WAV, FLAC, OGG, M4A, AAC. If a specific upload is
rejected, convert to MP3 first:

```powershell
# Requires ffmpeg on PATH. Replace input/output paths as needed.
ffmpeg -i .\assets\bells\bell_single_ding.flac -codec:a libmp3lame -qscale:a 4 .\assets\bells\bell_single_ding.mp3
```
