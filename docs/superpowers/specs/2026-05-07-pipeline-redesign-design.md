---
title: Pipeline Redesign — Two Sequential Runners
date: 2026-05-07
status: approved
tags: [youtubeniche, pipeline, architecture, gha]
---

# Pipeline Redesign — Two Sequential Runners

## Problem

The current architecture runs two parallel GHA jobs on the same hourly cron:

- **fast** (55 min): topics → scripts → voiceover → thumbnails
- **assemble** (350 min): video assembly → upload

These jobs race each other. The assembler picks up videos while the fast job is still
generating voiceovers. When the assembler finishes and deletes the audio from S3, a
subsequent fast run regenerates voiceovers for videos that already have assembled video
files — burning OpenAI quota. When S3 audio has already been deleted and the assembler
retries, it hits a 404 and resets the script to `pending`, which triggers another
voiceover generation cycle.

Secondary bug: `voiceover.py` resets ALL scripts stuck in `processing` for >2 hours,
including scripts that are mid-pipeline with video rows already created. This causes
unnecessary regeneration.

Additional constraint: YouTube Data API allows ~3 uploads per day (10,000 units/day;
1,600 units per upload). Pre-generating videos and storing them in S3 burns storage
quota waiting for upload slots.

## Design

Replace the two parallel jobs with two clean, sequential pipelines:

### Pipeline 1 — Script Writer (`script_runner.py`)

**Purpose:** Turn approved topics into scripts and stop. Mat reviews scripts before anything else runs.

**GHA schedule:** Every hour (`0 * * * *`), 10-minute timeout.

**Flow per niche:**
1. Query `topics` where `gate2_state='approved'` and `status='pending'`
2. For each topic: run `Scriptwriter.generate()` → insert script with `gate3_state='awaiting_review'`
3. Set topic `status='processing'`
4. Stop — nothing else runs until Mat approves a script

**Output state:** `scripts.gate3_state = 'awaiting_review'` (waiting for Mat)

---

### Pipeline 2 — Production Runner (`production_runner.py`)

**Purpose:** Take one gate3-approved script per niche all the way through to upload, then immediately delete all assets. No orphaned S3 data between runs.

**GHA schedule:** Three times daily (`0 0,8,16 * * *`), 90-minute timeout. Aligns with YouTube quota of ~3 uploads/day.

**Flow per niche (exactly 1 script):**
1. Query `scripts` where `gate3_state='approved'` and `status='pending'` — take first, mark `status='processing'`
2. **Thumbnail gen** — generate long and short thumbnails, upload to S3, write `thumbnail_path` to video rows
3. **Voiceover** — generate audio + SRT for long and short video rows, upload to S3, write `audio_path`/`srt_path`
4. **Video assembly** — download audio, fetch Pexels clips, encode video, upload to S3, write `video_path`
5. **Upload** — upload to YouTube, insert `published_videos`, set `scripts.status='done'`
6. **Delete assets** — delete all S3 objects (audio, video, thumbnails, b-roll) immediately after successful upload

**Output state:** Script marked `done`; all video rows deleted; all S3 assets deleted.

---

## Bug Fixes (bundled with redesign)

### Fix 1: `assembly_failed` status for S3 404

**File:** `agents/production/video_assembler.py`  
**Current:** On S3 404, sets `scripts.status='pending'` — triggers voiceover regeneration  
**Fix:** Set `scripts.status='assembly_failed'` — blocks requeue; requires migration 013

Production runner will also skip scripts with `assembly_failed` status. Mat can manually
reset to `pending` to retry after investigating.

### Fix 2: Smarter stuck-processing reset in voiceover

**File:** `agents/production/voiceover.py`  
**Current:** Resets ALL `processing` scripts older than 2h — catches mid-pipeline scripts  
**Fix:** Only reset `processing` scripts that have **no associated video rows** (LEFT JOIN check)

A script with video rows is actively mid-pipeline; it should not be reset.

---

## Migration

**`migrations/013_assembly_failed_status.sql`**

Adds `assembly_failed` to the scripts status check constraint.

---

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `agents/shared/script_runner.py` | Create | Pipeline 1 entrypoint |
| `agents/shared/production_runner.py` | Create | Pipeline 2 entrypoint |
| `agents/shared/pipeline_runner.py` | Keep | Unchanged (not used by new workflows) |
| `agents/production/video_assembler.py` | Modify | S3 404 → assembly_failed |
| `agents/production/voiceover.py` | Modify | Smarter stuck-processing reset |
| `.github/workflows/pipeline_runner.yml` | Rewrite | Two jobs, new schedules and entrypoints |
| `migrations/013_assembly_failed_status.sql` | Create | Add assembly_failed to check constraint |

---

## Constraints and Non-Goals

- Gate3 (script review) remains the only active gate — all other gates are auto-approved
- `production_runner.py` processes exactly **1 script per niche per run**
- Existing agent classes (`Scriptwriter`, `VoiceoverAgent`, `ThumbnailGenerator`, `VideoAssembler`, `YouTubeUploader`) are **not modified** except for the two bug fixes
- `pipeline_runner.py` and the `PIPELINE_STAGES` env var are left in place (not deleted)
- The `remotion_renderer.py` AWS render path is not used; `video_assembler.py` (moviepy) remains the assembler
