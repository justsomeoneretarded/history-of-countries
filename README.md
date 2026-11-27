# History of Countries

Give GitHub Actions a **title and short brief**, choose a Gemini voice, and download a complete history video with its YouTube thumbnail, title, description and subtitles.

The production style is **real historical images and footage, natural storytelling, clean cuts and minimal text**. Source images remain whole and keep their proportions. Widescreen sources are preferred; occasional portraits use subtle side fill. There are no character animations, animated maps, artificial image pans or zooms, branding overlays or chapter cards.

## Run a video

1. Add the repository Actions secret **gemini_api_key**.
2. Open **Actions → Create a simple history video → Run workflow**.
3. Enter the title and brief. Charon is the default narrator. Choose **auto** to compare actual Puck and Charon recordings for intelligibility, naturalness and delivery.
4. Download **countries-video** after a successful full run. A finished full export has **upload_ready: true** in delivery.json.

Use final.mp4, thumbnail.jpg, title.txt, description.txt and captions.srt for YouTube. The runner does not publish to YouTube.

The default target is 8.75 minutes; supported targets are 0.5–10 minutes. A preview contains the first three consecutive scenes and is explicitly marked as a preview.

## Story and voice

The five internal chapters are Hook, Roots, Catalyst, Turning Point and Aftermath. Narration starts inside a consequential event, follows decisions and consequences through the centuries, and pays off the opening at the end. The writer rejects repeated padding without forcing every paragraph into the same short-sentence pattern.

The refined Ethiopia production has a complete original director's draft in episodes/ethiopia-story.json. Gemini makes one bounded edit for spoken language; the chronology, scene IDs, source metadata and chapter intake limits remain fixed. Other subjects use the Gemini chapter writer and the same narration style.

Gemini 3.8 Flash TTS records complete chapters, with no more than 450 words in one intake. If its free daily quota is exhausted, an unrecorded chapter can use the verified free Gemini 3.8 Flash Lite TTS variant with the same prebuilt voice; accepted chapters remain intact. Transcript-assisted checks verify spoken completeness and split recordings only between words. The recording is never sped up or stretched to reach a target duration.

Chapter-level audio processing uses a 70 Hz high-pass, gentle presence EQ, light compression and measured normalization. Licensed instrumental music is ducked beneath speech, with silence for difficult passages. The final mix targets −16 LUFS and −1.5 dBTP. Opening, middle and ending excerpts from the actual final soundtrack receive an additional Gemini listening report when available.

## Pictures, editing and text

- The entire foreground image is contained in the output frame, preserving its edges and aspect ratio.
- Cuts follow phrase endings or pauses where possible, usually every 3–6 seconds.
- Consecutive excerpts advance through the original footage instead of replaying its opening.
- The only regular overlay is a small, high-contrast date in a consistent corner.
- Subtitles are supplied separately as SRT; words do not flash over the picture.
- The ending holds briefly after the last line, with no padded credits or subscription screen.

Real media comes from identified Internet Archive newsreels, Wikimedia Commons, museum open-access collections and optional reusable YouTube clips. Every work retains its provenance and license. A modern view of a surviving place is distinguished from contemporary evidence of a historical event.

YouTube discovery requires an explicit Creative Commons attribution license plus matching subject and date. Optional source URLs can be supplied in the workflow. media-discovery.json reports what was actually selected; unavailable or unsuitable clips are not substituted with unrelated material.

## What creates each part

| Part | Tools and models |
| --- | --- |
| Research and chapter writing | Source extracts, Gemini 3.1 Flash Lite |
| Ethiopia spoken edit | Original director draft, Gemini 3.5 Flash Lite |
| Narration | Gemini 3.8 Flash TTS; free Flash Lite TTS quota recovery; selectable prebuilt voices |
| Voice comparison | Actual recordings, faster-whisper completeness checks, Gemini 3.5 Flash Lite listening |
| Media order | Gemini 3.1 Flash Lite using compact approved-media IDs and word-timed cues |
| Images and editing | Pillow, FFmpeg; no generated animation |
| Audio | FFmpeg mastering and ducking, licensed Scott Buckley instrumentals |
| Thumbnail and upload text | Authentic image composition, Pillow, Gemini 3.5 Flash Lite |
| Delivery checks | Full media decode, frame/audio timing, loudness, speech, framing and package limits |

Source components and their pinned revision are listed in REUSED_FROM.md.

## Free-tier operation and recovery

These are application guardrails, rather than universal provider quotas:

- Requests start at least 65 seconds apart, with bounded network retries.
- The input guard is approximately 40,000 tokens; media ordering allows 14,000 output tokens, including model reasoning.
- Accepted writing, voice takes, alignments and rendered clips are checkpointed.
- The main TTS model reported a 10-request daily free limit for this key on 27 November 2026. Quotas vary by model/project. Accepted work is preserved when quota stops generation.
- Optional editing or metadata requests can use the approved local material when unavailable.
- No paid model fallback is used.

To resume, provide the saved run ID and countries-checkpoint in the workflow. A History-of-X director-audio checkpoint can also be imported. Animation programs are omitted.

## Output and verification

A full export is 1920×1080 at 30 fps, H.264 video and AAC stereo audio. Delivery includes the MP4, thumbnail, title, description, captions, script, full credits and measured reports.

The test suite currently passes 91 checks. Tests encode and inspect actual media using synthetic fixtures. They verify transport and editing contracts, not human pronunciation or audience retention. Real productions also record speech-completeness measurements, actual voice comparisons and sampled listening observations.

The refined Ethiopia edition completed successfully on **27 November 2026**: **9:02, 1920×1080 at 30 fps, Charon narration**, and a 1,488-word original story. All **91 tests** and full output checks passed.

- [Download the refined video, upload files and voice-comparison samples](https://github.com/justsomeoneretarded/history-of-countries/actions/runs/46054314537/artifacts/15226312314).
- [Inspect the successful full production](https://github.com/justsomeoneretarded/history-of-countries/actions/runs/46054314537).
- [Run another video](https://github.com/justsomeoneretarded/history-of-countries/actions/workflows/video.yml).

The export contains 126 phrase-aligned cuts, whole source images with no artificial camera motion, 45 image sources and one archive-video excerpt. No YouTube clip was selected. The final AAC soundtrack measured −16.05 LUFS and −2.56 dBTP, with no detected black gaps. The 74-character title, 4,870-character description and thumbnail passed upload-package limits.

Gemini listened to actual opening, middle and ending excerpts: naturalness 8/10, clarity 9/10, rhythm 8/10, with no overacting. It noted occasional mechanical cadence and minor room-tone variation. These are model observations on sampled audio, not a claim of perfect speech or audience retention. Measured reports are recorded in [VALIDATION.json](VALIDATION.json).

For local use:

    pip install -e '.[alignment]'
    export GEMINI_API_KEY='your key'
    history-countries --title "The Entire History of Japan" --brief "Explain how rulers, trade and political reforms changed who held power."

FFmpeg and DejaVu fonts are required. The Actions workflow installs its system dependencies.
