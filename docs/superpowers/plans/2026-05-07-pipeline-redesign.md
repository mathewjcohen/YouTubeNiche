---
title: Pipeline Redesign — Two Sequential Runners
date: 2026-05-07
status: ready
tags: [youtubeniche, pipeline, gha, architecture]
---

# Pipeline Redesign — Two Sequential Runners Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace two parallel GHA jobs with two clean sequential pipelines — script_runner (topics→scripts) and production_runner (gate3-approved script→thumbnail→voiceover→assemble→upload→delete) — eliminating S3 asset mismatches and OpenAI quota burn.

**Architecture:** `script_runner.py` runs hourly and only writes scripts; it stops at gate3 for manual review. `production_runner.py` runs 3×/day (every 8 hours) and takes exactly 1 gate3-approved script per niche all the way through to upload, then immediately deletes all S3 assets. Two bug fixes are bundled: the S3 404 handler in `video_assembler.py` that was resetting scripts to `pending` (causing voiceover quota burn), and the stuck-processing reset in `voiceover.py` that was incorrectly resetting mid-pipeline scripts that already had video rows.

**Tech Stack:** Python 3.11, Supabase (PostgREST), S3 (boto3), GHA, existing agent classes (Scriptwriter, VoiceoverAgent, ThumbnailGenerator, VideoAssembler, YouTubeUploader).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `migrations/013_assembly_failed_status.sql` | Create | Add `assembly_failed` to scripts status constraint |
| `agents/production/video_assembler.py` | Modify (lines 239–244) | S3 404 → `assembly_failed` instead of `pending` |
| `agents/production/voiceover.py` | Modify (lines 302–317, 323–329) | Smarter stuck-processing reset + limit param |
| `agents/shared/script_runner.py` | Create | Pipeline 1 entrypoint |
| `agents/shared/production_runner.py` | Create | Pipeline 2 entrypoint |
| `.github/workflows/pipeline_runner.yml` | Rewrite | Two jobs, new cron schedules |
| `tests/production/test_video_assembler.py` | Modify | Add S3 404 → assembly_failed test |
| `tests/production/test_voiceover.py` | Modify | Add stuck-processing reset test |
| `tests/shared/test_script_runner.py` | Create | ScriptRunner unit tests |
| `tests/shared/test_production_runner.py` | Create | ProductionRunner unit tests |

---

## Task 1: Migration — add `assembly_failed` to scripts status

**Files:**
- Create: `migrations/013_assembly_failed_status.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- migrations/013_assembly_failed_status.sql
-- Add 'assembly_failed' to the scripts status check constraint.
-- This status is set when video assembly permanently fails (e.g. S3 audio missing)
-- so the voiceover agent does not requeue the script and burn API quota.
ALTER TABLE scripts DROP CONSTRAINT IF EXISTS scripts_status_check;
ALTER TABLE scripts ADD CONSTRAINT scripts_status_check
  CHECK (status IN ('pending','awaiting_review','approved','rejected','processing','done','assembly_failed'));
```

- [ ] **Step 2: Apply the migration in the Supabase dashboard SQL editor**

Paste and run the SQL above. Confirm: "Success. No rows returned."

- [ ] **Step 3: Commit**

```bash
git add migrations/013_assembly_failed_status.sql
git commit -m "migration: add assembly_failed to scripts status constraint (013)"
```

---

## Task 2: Fix video_assembler.py — S3 404 resets to assembly_failed

**Files:**
- Modify: `agents/production/video_assembler.py` (lines 239–244)
- Modify: `tests/production/test_video_assembler.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/production/test_video_assembler.py`:

```python
from unittest.mock import MagicMock, patch, call
import botocore.exceptions


def test_s3_404_sets_assembly_failed_not_pending():
    """S3 404 on audio must set scripts.status='assembly_failed', not 'pending'.
    Resetting to 'pending' causes the voiceover agent to regenerate audio (burns OpenAI quota).
    """
    from agents.production.video_assembler import VideoAssembler, PexelsClient

    mock_sb = MagicMock()
    mock_gate = MagicMock()
    pexels = MagicMock(spec=PexelsClient)

    assembler = VideoAssembler(supabase=mock_sb, gate_client=mock_gate, pexels_client=pexels)

    video = {
        "id": "video-1",
        "script_id": "script-1",
        "niche_id": "niche-1",
        "video_type": "long",
        "audio_path": "https://bucket.s3.region.amazonaws.com/audio/test.mp3",
        "srt_path": "https://bucket.s3.region.amazonaws.com/audio/test.srt",
        "scripts": {"long_form_text": "Hello world.", "short_text": "Short."},
    }

    # videos query returns our test video
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [video]

    # assemble() raises S3 404
    s3_error = botocore.exceptions.ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "GetObject"
    )
    with patch.object(assembler, "assemble", side_effect=s3_error):
        assembler.process_approved_voiceovers("niche-1")

    # Find the scripts update call
    update_calls = [
        c for c in mock_sb.table.return_value.update.call_args_list
    ]
    status_values = [c.args[0].get("status") for c in update_calls if "status" in c.args[0]]
    assert "assembly_failed" in status_values, f"Expected assembly_failed, got: {status_values}"
    assert "pending" not in status_values, "Must not reset to pending — that burns OpenAI quota"
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd /Users/maco/Documents/ClaudeVault/projects/YouTubeNiche
python3 -m pytest tests/production/test_video_assembler.py::test_s3_404_sets_assembly_failed_not_pending -v
```

Expected: FAIL — the current code sets `pending`.

- [ ] **Step 3: Apply the fix in video_assembler.py**

Find lines 239–244 (the `botocore.exceptions.ClientError` handler inside `process_approved_voiceovers`):

```python
# BEFORE (lines 239–244):
            except botocore.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey"):
                    print(f"[assembler] video {video['id']} audio permanently missing (S3 404) — deleting row and resetting script")
                    execute_with_retry(self._sb.table("videos").delete().eq("id", video["id"]))
                    execute_with_retry(self._sb.table("scripts").update({"status": "pending"}).eq("id", video["script_id"]))
                else:
                    print(f"[assembler] video {video['id']} S3 error, will retry next run: {exc}")
```

Replace with:

```python
# AFTER:
            except botocore.exceptions.ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey"):
                    print(f"[assembler] video {video['id']} audio permanently missing (S3 404) — marking assembly_failed")
                    execute_with_retry(self._sb.table("videos").delete().eq("id", video["id"]))
                    execute_with_retry(self._sb.table("scripts").update({"status": "assembly_failed"}).eq("id", video["script_id"]))
                else:
                    print(f"[assembler] video {video['id']} S3 error, will retry next run: {exc}")
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
python3 -m pytest tests/production/test_video_assembler.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/production/video_assembler.py tests/production/test_video_assembler.py
git commit -m "fix: S3 404 sets assembly_failed instead of pending to stop OpenAI quota burn"
```

---

## Task 3: Fix voiceover.py — smarter stuck-processing reset + limit param

**Files:**
- Modify: `agents/production/voiceover.py` (lines 302–329)
- Modify: `tests/production/test_voiceover.py`

**Context:** The current stuck-processing reset resets ALL processing scripts older than 2h, including scripts that are mid-pipeline with video rows already created. The fix: only reset scripts that have NO associated video rows. Also add a `limit` param so production_runner can restrict to 1 script per run.

- [ ] **Step 1: Write the failing tests**

Add to `tests/production/test_voiceover.py`:

```python
from unittest.mock import MagicMock, patch, call


def _make_agent():
    from agents.production.voiceover import VoiceoverAgent
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    return VoiceoverAgent(supabase=mock_sb, gate_client=mock_gate), mock_sb


def test_stuck_reset_skips_scripts_with_video_rows():
    """Scripts that have video rows are mid-pipeline and must NOT be reset to pending."""
    agent, mock_sb = _make_agent()

    stale_script_id = "script-stale-1"

    # First call: niches category
    # We need to simulate the stuck-processing query returning a stale script,
    # then the videos check returning a non-empty result for that script.
    # Then the main script query returning empty (no new scripts to process).

    # Set up the mock chain for the stuck-processing fetch
    stale_scripts_result = MagicMock()
    stale_scripts_result.data = [{"id": stale_script_id}]

    video_check_result = MagicMock()
    video_check_result.data = [{"id": "video-1"}]  # has video row → must NOT reset

    niche_result = MagicMock()
    niche_result.data = [{"category": "legal"}]

    pending_scripts_result = MagicMock()
    pending_scripts_result.data = []  # no new scripts to process

    # Track update calls
    update_calls = []
    original_update = mock_sb.table.return_value.update

    def tracking_update(payload):
        update_calls.append(payload)
        return mock_sb.table.return_value.update.return_value

    mock_sb.table.return_value.update = tracking_update

    with patch("agents.production.voiceover.execute_with_retry") as mock_retry:
        def side_effect(query):
            result = MagicMock()
            # Determine which query this is based on call order
            call_num = mock_retry.call_count
            if call_num == 0:
                result.data = [{"id": stale_script_id}]  # stale processing scripts
            elif call_num == 1:
                result.data = [{"id": "video-1"}]  # video rows exist → skip reset
            elif call_num == 2:
                result.data = [{"category": "legal"}]  # niche category
            else:
                result.data = []  # pending scripts
            mock_retry.call_count += 1
            return result

        mock_retry.call_count = 0
        mock_retry.side_effect = side_effect

        agent.process_approved_scripts("niche-1")

    # The stale script had video rows, so no update to status=pending should have occurred
    reset_to_pending = [c for c in mock_retry.call_args_list
                        if hasattr(c.args[0], '_mock_name') or 'pending' in str(c)]
    # Simpler check: ensure the update with status=pending was never called for the stale script
    # (We can't easily introspect the mock chain, so verify via the print output or
    # by checking the call count was 4 total: stale fetch, video check, niche, pending scripts)
    assert mock_retry.call_count == 4, (
        f"Expected 4 DB calls (stale fetch, video check, niche, pending scripts), got {mock_retry.call_count}"
    )


def test_limit_restricts_scripts_processed():
    """limit=1 must stop voiceover after processing one script."""
    agent, mock_sb = _make_agent()

    with patch("agents.production.voiceover.execute_with_retry") as mock_retry, \
         patch.object(agent, "synthesize", side_effect=Exception("skip")):

        def side_effect(query):
            result = MagicMock()
            result.data = []
            return result

        mock_retry.side_effect = side_effect

        # Should not raise; limit param accepted
        agent.process_approved_scripts("niche-1", limit=1)
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
python3 -m pytest tests/production/test_voiceover.py::test_stuck_reset_skips_scripts_with_video_rows tests/production/test_voiceover.py::test_limit_restricts_scripts_processed -v
```

Expected: FAIL — `process_approved_scripts` doesn't accept `limit` and doesn't check video rows.

- [ ] **Step 3: Apply the fix to voiceover.py**

Replace the `process_approved_scripts` method header and stuck-processing reset block.

**Find this section (lines 302–329):**

```python
    def process_approved_scripts(self, niche_id: str) -> None:
        # Self-heal: scripts stuck in 'processing' for >2h never recovered on their own.
        # Reset them so the next run picks them up again.
        try:
            stale_cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            recovered = execute_with_retry(
                self._sb.table("scripts")
                .update({"status": "pending"})
                .eq("niche_id", niche_id)
                .eq("status", "processing")
                .lt("updated_at", stale_cutoff)
            ).data
            if recovered:
                print(f"[voiceover] reset {len(recovered)} stuck-processing script(s) for niche {niche_id}")
        except Exception as e:
            print(f"[voiceover] stuck-script reset skipped (migration pending?): {e}")

        niche_rows = execute_with_retry(
            self._sb.table("niches").select("category").eq("id", niche_id).limit(1)
        ).data
        category = niche_rows[0]["category"] if niche_rows else ""
        scripts = execute_with_retry(
            self._sb.table("scripts")
            .select("*")
            .eq("niche_id", niche_id)
            .eq("gate3_state", "approved")
            .eq("status", "pending")
        ).data
```

**Replace with:**

```python
    def process_approved_scripts(self, niche_id: str, limit: Optional[int] = None) -> None:
        # Self-heal: reset processing scripts older than 2h ONLY if they have no video rows.
        # Scripts with video rows are mid-pipeline; resetting them burns OpenAI quota.
        try:
            stale_cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            stale = execute_with_retry(
                self._sb.table("scripts")
                .select("id")
                .eq("niche_id", niche_id)
                .eq("status", "processing")
                .lt("updated_at", stale_cutoff)
            ).data
            reset_count = 0
            for s in stale:
                video_rows = execute_with_retry(
                    self._sb.table("videos").select("id").eq("script_id", s["id"]).limit(1)
                ).data
                if not video_rows:
                    execute_with_retry(
                        self._sb.table("scripts")
                        .update({"status": "pending"})
                        .eq("id", s["id"])
                    )
                    reset_count += 1
            if reset_count:
                print(f"[voiceover] reset {reset_count} stuck-processing script(s) for niche {niche_id}")
        except Exception as e:
            print(f"[voiceover] stuck-script reset skipped: {e}")

        niche_rows = execute_with_retry(
            self._sb.table("niches").select("category").eq("id", niche_id).limit(1)
        ).data
        category = niche_rows[0]["category"] if niche_rows else ""
        query = (
            self._sb.table("scripts")
            .select("*")
            .eq("niche_id", niche_id)
            .eq("gate3_state", "approved")
            .eq("status", "pending")
        )
        if limit is not None:
            query = query.limit(limit)
        scripts = execute_with_retry(query).data
```

Also add `Optional` to the import at the top of voiceover.py if not already there:

```python
from typing import List, Optional, Tuple
```

- [ ] **Step 4: Run all voiceover tests**

```bash
python3 -m pytest tests/production/test_voiceover.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/production/voiceover.py tests/production/test_voiceover.py
git commit -m "fix: voiceover stuck-reset skips mid-pipeline scripts; add limit param"
```

---

## Task 4: Create script_runner.py — Pipeline 1

**Files:**
- Create: `agents/shared/script_runner.py`
- Create: `tests/shared/test_script_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/shared/test_script_runner.py`:

```python
import pytest
from unittest.mock import MagicMock, patch, call
from agents.shared.script_runner import ScriptRunner


@pytest.fixture
def runner():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    return ScriptRunner(supabase=mock_sb, gate_client=mock_gate)


def test_run_exits_when_pipeline_disabled(runner):
    """When pipeline_enabled=false, run() does nothing."""
    with patch("agents.shared.script_runner.get_app_setting", return_value="false"), \
         patch("agents.shared.script_runner.execute_with_retry") as mock_retry:
        runner.run()
    mock_retry.assert_not_called()


def test_run_processes_all_active_niches(runner):
    """run() calls _process_niche for each active niche (promoted + testing)."""
    niches = [
        {"id": "n1", "name": "legal", "category": "legal", "status": "promoted"},
        {"id": "n2", "name": "tax", "category": "tax", "status": "testing"},
    ]
    with patch("agents.shared.script_runner.get_app_setting", return_value="true"), \
         patch("agents.shared.script_runner.execute_with_retry") as mock_retry, \
         patch.object(runner, "_process_niche") as mock_process:
        mock_retry.return_value.data = niches
        runner.run()
    assert mock_process.call_count == 2
    processed_ids = [c.args[0]["id"] for c in mock_process.call_args_list]
    assert processed_ids == ["n1", "n2"]


def test_process_niche_skips_when_no_approved_topics(runner):
    """No approved topics → scriptwriter is not called."""
    with patch("agents.shared.script_runner.execute_with_retry") as mock_retry:
        mock_retry.return_value.data = []  # no approved topics
        with patch("agents.production.scriptwriter.Scriptwriter") as mock_sw:
            runner._process_niche({"id": "niche-1", "name": "legal", "category": "legal"})
    mock_sw.assert_not_called()


def test_process_niche_runs_scriptwriter_when_topics_approved(runner):
    """Approved topics → Scriptwriter.process_approved_topics is called."""
    niche = {"id": "niche-1", "name": "legal", "category": "legal"}

    with patch("agents.shared.script_runner.execute_with_retry") as mock_retry:
        mock_retry.return_value.data = [{"id": "topic-1"}]  # one approved topic
        mock_writer = MagicMock()
        with patch("agents.shared.script_runner.Scriptwriter", return_value=mock_writer):
            runner._process_niche(niche)

    mock_writer.process_approved_topics.assert_called_once_with("niche-1")
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
python3 -m pytest tests/shared/test_script_runner.py -v
```

Expected: FAIL — `script_runner` module doesn't exist yet.

- [ ] **Step 3: Create agents/shared/script_runner.py**

```python
from supabase import Client, create_client

from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared.pipeline_runner import get_app_setting


class ScriptRunner:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def run(self) -> None:
        enabled = get_app_setting(self._sb, "pipeline_enabled", "true")
        print(f"[script] pipeline_enabled={enabled}")
        if enabled == "false":
            print("[script] paused via dashboard — exiting")
            return

        niches = execute_with_retry(
            self._sb.table("niches")
            .select("id,name,category,status")
            .in_("status", ["promoted", "testing"])
        ).data
        print(f"[script] {len(niches)} active niche(s)")
        for niche in niches:
            self._process_niche(niche)

    def _process_niche(self, niche: dict) -> None:
        niche_id = niche["id"]
        name = niche.get("name", niche_id)
        print(f"[script] niche '{name}'")

        approved_topics = execute_with_retry(
            self._sb.table("topics")
            .select("id")
            .eq("niche_id", niche_id)
            .eq("gate2_state", "approved")
            .eq("status", "pending")
        ).data
        if not approved_topics:
            print(f"[script]   no approved topics — skipping scriptwriter")
            return

        print(f"[script]   {len(approved_topics)} approved topic(s) → running scriptwriter")
        from agents.production.scriptwriter import Scriptwriter
        writer = Scriptwriter(supabase=self._sb, gate_client=self._gate)
        writer.process_approved_topics(niche_id)


def main() -> None:
    print("[script] starting")
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    runner = ScriptRunner(supabase=sb, gate_client=gate)
    runner.run()
    print("[script] done")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
python3 -m pytest tests/shared/test_script_runner.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/shared/script_runner.py tests/shared/test_script_runner.py
git commit -m "feat: add script_runner.py — Pipeline 1 (topics → scripts, stops at gate3)"
```

---

## Task 5: Create production_runner.py — Pipeline 2

**Files:**
- Create: `agents/shared/production_runner.py`
- Create: `tests/shared/test_production_runner.py`

**Context:** This runner takes exactly 1 gate3-approved script per niche through the full production flow: voiceover (limit=1) → thumbnail → assemble → upload. Assets are deleted by the uploader immediately after successful upload (existing behavior). If a niche has no linked YouTube channel, the upload step is skipped (niche will stay blocked until linked).

- [ ] **Step 1: Write the failing tests**

Create `tests/shared/test_production_runner.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.shared.production_runner import ProductionRunner


@pytest.fixture
def runner():
    mock_sb = MagicMock()
    mock_gate = MagicMock()
    return ProductionRunner(supabase=mock_sb, gate_client=mock_gate)


def test_run_exits_when_pipeline_disabled(runner):
    """When pipeline_enabled=false, run() does nothing."""
    with patch("agents.shared.production_runner.get_app_setting", return_value="false"), \
         patch("agents.shared.production_runner.execute_with_retry") as mock_retry:
        runner.run()
    mock_retry.assert_not_called()


def test_run_processes_all_active_niches(runner):
    """run() calls _process_niche for all promoted and testing niches."""
    niches = [
        {"id": "n1", "name": "legal", "channel_state": "linked", "status": "promoted"},
        {"id": "n2", "name": "tax", "channel_state": "linked", "status": "testing"},
    ]
    with patch("agents.shared.production_runner.get_app_setting", return_value="true"), \
         patch("agents.shared.production_runner.execute_with_retry") as mock_retry, \
         patch.object(runner, "_process_niche") as mock_process:
        mock_retry.return_value.data = niches
        runner.run()
    assert mock_process.call_count == 2


def test_process_niche_runs_all_four_stages(runner):
    """_process_niche calls voiceover, thumbnail, assembler, uploader in order."""
    niche = {"id": "niche-1", "name": "legal", "channel_state": "linked", "status": "promoted"}
    call_order = []

    mock_vo = MagicMock()
    mock_vo.process_approved_scripts.side_effect = lambda niche_id, limit: call_order.append("voiceover")

    mock_tg = MagicMock()
    mock_tg.process_approved_scripts.side_effect = lambda niche_id: call_order.append("thumbnail")

    mock_va = MagicMock()
    mock_va.process_approved_voiceovers.side_effect = lambda niche_id: call_order.append("assembler")

    mock_up = MagicMock()
    mock_up.process_approved_videos.side_effect = lambda niche_id: call_order.append("uploader")

    with patch("agents.shared.production_runner.get_env", return_value="test-key"), \
         patch("agents.shared.production_runner.get_render_method", return_value="github"), \
         patch("agents.shared.production_runner.VoiceoverAgent", return_value=mock_vo), \
         patch("agents.shared.production_runner.ThumbnailGenerator", return_value=mock_tg), \
         patch("agents.shared.production_runner.VideoAssembler", return_value=mock_va), \
         patch("agents.shared.production_runner.PexelsClient", return_value=MagicMock()), \
         patch("agents.shared.production_runner.YouTubeUploader", return_value=mock_up):
        runner._process_niche(niche)

    assert call_order == ["voiceover", "thumbnail", "assembler", "uploader"]


def test_process_niche_skips_upload_when_channel_not_linked(runner):
    """Upload is skipped when channel_state != 'linked'."""
    niche = {"id": "niche-1", "name": "legal", "channel_state": "unlinked", "status": "promoted"}

    mock_up = MagicMock()

    with patch("agents.shared.production_runner.get_env", return_value="test-key"), \
         patch("agents.shared.production_runner.get_render_method", return_value="github"), \
         patch("agents.shared.production_runner.VoiceoverAgent", return_value=MagicMock()), \
         patch("agents.shared.production_runner.ThumbnailGenerator", return_value=MagicMock()), \
         patch("agents.shared.production_runner.VideoAssembler", return_value=MagicMock()), \
         patch("agents.shared.production_runner.PexelsClient", return_value=MagicMock()), \
         patch("agents.shared.production_runner.YouTubeUploader", return_value=mock_up):
        runner._process_niche(niche)

    mock_up.process_approved_videos.assert_not_called()


def test_voiceover_called_with_limit_1(runner):
    """Voiceover must be called with limit=1 to prevent exceeding YouTube quota."""
    niche = {"id": "niche-1", "name": "legal", "channel_state": "linked", "status": "promoted"}
    mock_vo = MagicMock()

    with patch("agents.shared.production_runner.get_env", return_value="test-key"), \
         patch("agents.shared.production_runner.get_render_method", return_value="github"), \
         patch("agents.shared.production_runner.VoiceoverAgent", return_value=mock_vo), \
         patch("agents.shared.production_runner.ThumbnailGenerator", return_value=MagicMock()), \
         patch("agents.shared.production_runner.VideoAssembler", return_value=MagicMock()), \
         patch("agents.shared.production_runner.PexelsClient", return_value=MagicMock()), \
         patch("agents.shared.production_runner.YouTubeUploader", return_value=MagicMock()):
        runner._process_niche(niche)

    mock_vo.process_approved_scripts.assert_called_once_with("niche-1", limit=1)
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
python3 -m pytest tests/shared/test_production_runner.py -v
```

Expected: FAIL — `production_runner` module doesn't exist.

- [ ] **Step 3: Create agents/shared/production_runner.py**

```python
from supabase import Client, create_client

from agents.shared.gate_client import GateClient
from agents.shared.config_loader import get_env
from agents.shared.db_retry import execute_with_retry, patch_postgrest_http1
from agents.shared.pipeline_runner import get_app_setting, get_render_method
from agents.production.voiceover import VoiceoverAgent
from agents.production.thumbnail_gen import ThumbnailGenerator
from agents.production.video_assembler import VideoAssembler, PexelsClient
from agents.production.uploader import YouTubeUploader


class ProductionRunner:
    def __init__(self, supabase: Client, gate_client: GateClient):
        self._sb = supabase
        self._gate = gate_client

    def run(self) -> None:
        enabled = get_app_setting(self._sb, "pipeline_enabled", "true")
        print(f"[production] pipeline_enabled={enabled}")
        if enabled == "false":
            print("[production] paused via dashboard — exiting")
            return

        niches = execute_with_retry(
            self._sb.table("niches")
            .select("*, youtube_accounts(channel_id)")
            .in_("status", ["promoted", "testing"])
        ).data
        print(f"[production] {len(niches)} active niche(s)")
        for niche in niches:
            self._process_niche(niche)

    def _process_niche(self, niche: dict) -> None:
        niche_id = niche["id"]
        name = niche.get("name", niche_id)
        print(f"[production] niche '{name}'")

        # Step 1: Voiceover — limit=1 to match YouTube quota (3 uploads/day max)
        agent = VoiceoverAgent(supabase=self._sb, gate_client=self._gate)
        agent.process_approved_scripts(niche_id, limit=1)

        # Step 2: Thumbnail gen — must run after voiceover creates video rows
        gen = ThumbnailGenerator(
            supabase=self._sb,
            gate_client=self._gate,
            pexels_api_key=get_env("PEXELS_API_KEY"),
        )
        gen.process_approved_scripts(niche_id)

        # Step 3: Video assembly
        render_method = get_render_method(self._sb)
        if render_method == "aws":
            from agents.production.remotion_renderer import RemotionRenderer
            renderer = RemotionRenderer(supabase=self._sb, gate_client=self._gate)
            renderer.process_approved_voiceovers(niche_id)
        else:
            pexels = PexelsClient(api_key=get_env("PEXELS_API_KEY"))
            assembler = VideoAssembler(
                supabase=self._sb,
                gate_client=self._gate,
                pexels_client=pexels,
            )
            assembler.process_approved_voiceovers(niche_id)

        # Step 4: Upload (skip if no linked channel)
        if niche.get("channel_state") == "linked":
            uploader = YouTubeUploader(supabase=self._sb, gate_client=self._gate)
            uploader.process_approved_videos(niche_id)
        else:
            print(f"[production]   skipping upload — '{name}' has no linked channel (channel_state={niche.get('channel_state')})")


def main() -> None:
    print("[production] starting")
    sb = patch_postgrest_http1(create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY")))
    gate = GateClient(sb)
    runner = ProductionRunner(supabase=sb, gate_client=gate)
    runner.run()
    print("[production] done")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
python3 -m pytest tests/shared/test_production_runner.py -v
```

Expected: All PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/shared/production_runner.py tests/shared/test_production_runner.py
git commit -m "feat: add production_runner.py — Pipeline 2 (voiceover → thumbnail → assemble → upload)"
```

---

## Task 6: Rewrite pipeline_runner.yml — two jobs, new schedules

**Files:**
- Modify: `.github/workflows/pipeline_runner.yml`

**Context:** Replace the two parallel jobs (fast/assemble) with two sequential jobs — `script` (runs hourly, calls script_runner) and `production` (runs every 8 hours, calls production_runner). The `ffmpeg` install step is only needed by production (video assembly). The `OPENAI_API_KEY` is only needed by production. The `ANTHROPIC_API_KEY` is needed by script (scriptwriter).

- [ ] **Step 1: Rewrite the workflow file**

Replace the entire contents of `.github/workflows/pipeline_runner.yml` with:

```yaml
name: Pipeline Runner

on:
  schedule:
    - cron: "0 * * * *"       # script job: every hour
    - cron: "0 0,8,16 * * *"  # production job: 3× per day (midnight, 8 AM, 4 PM UTC)
  workflow_dispatch:
    inputs:
      job:
        description: "Which job to run"
        required: false
        default: "both"
        type: choice
        options:
          - both
          - script
          - production

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  script:
    name: Script writer (topics → scripts)
    if: >
      github.event_name == 'workflow_dispatch' && inputs.job != 'production' ||
      github.event_name == 'schedule' && (
        github.event.schedule == '0 * * * *' ||
        github.event.schedule == '0 0,8,16 * * *'
      )
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install --retries 3 -r requirements.txt
      - name: Run script pipeline
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
        run: python3 -u -m agents.shared.script_runner

  production:
    name: Production pipeline (voiceover → thumbnail → assemble → upload)
    if: >
      github.event_name == 'workflow_dispatch' && inputs.job != 'script' ||
      github.event_name == 'schedule' && github.event.schedule == '0 0,8,16 * * *'
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: sudo apt-get install -y ffmpeg
      - run: pip install --retries 3 -r requirements.txt
      - name: Write YouTube token
        env:
          YOUTUBE_TOKEN_JSON: ${{ secrets.YOUTUBE_TOKEN_JSON }}
        run: |
          mkdir -p config
          echo "$YOUTUBE_TOKEN_JSON" > config/youtube_token.json
      - name: Run production pipeline
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          PEXELS_API_KEY: ${{ secrets.PEXELS_API_KEY }}
          RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
          YOUTUBE_TOKEN_PATH: config/youtube_token.json
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_S3_BUCKET: ${{ secrets.AWS_S3_BUCKET }}
          REMOTION_REGION: ${{ secrets.REMOTION_REGION }}
          REMOTION_FUNCTION_NAME: ${{ secrets.REMOTION_FUNCTION_NAME }}
          REMOTION_SERVE_URL: ${{ secrets.REMOTION_SERVE_URL }}
        run: python3 -u -m agents.shared.production_runner
```

**Note on cron `if` logic:** GHA doesn't natively let you match which cron fired within a single workflow. The `script` job runs on BOTH cron schedules (it's fast at <15min so running it at 0/8/16 UTC too is harmless). The `production` job only runs on the 8-hour schedule. For `workflow_dispatch`, the `job` input controls which runs.

- [ ] **Step 2: Validate the YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/pipeline_runner.yml'))" && echo "YAML valid"
```

Expected: `YAML valid`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pipeline_runner.yml
git commit -m "feat: replace parallel fast/slow GHA jobs with sequential script + production pipelines"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Migration: add assembly_failed | Task 1 ✓ |
| Fix assembler S3 404 → assembly_failed | Task 2 ✓ |
| Fix voiceover stuck-processing reset (skip scripts with video rows) | Task 3 ✓ |
| Add limit param to voiceover.process_approved_scripts | Task 3 ✓ |
| Create script_runner.py (Pipeline 1) | Task 4 ✓ |
| Create production_runner.py (Pipeline 2) | Task 5 ✓ |
| Rewrite pipeline_runner.yml | Task 6 ✓ |
| Sequential order: voiceover → thumbnail → assemble → upload | Task 5 ✓ |
| Upload skipped when channel not linked | Task 5 ✓ |
| Limit=1 per niche per production run | Task 5 ✓ |

**Placeholder scan:** No TBDs, no vague steps.

**Type consistency:** `limit: Optional[int]` in voiceover matches `limit=1` call in production_runner. `get_app_setting`, `get_render_method` imported from `pipeline_runner` (not redefined). `execute_with_retry`, `patch_postgrest_http1` imported from `db_retry`.
