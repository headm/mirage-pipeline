# Daily run (scheduled Claude Code cloud agent)

You are running the TikTok video pipeline unattended. Work only through the commands below.
Never edit pipeline code, never commit or push, never edit topics.csv by hand, and never print
API keys or tokens.

## 1. Set up

```bash
bash scripts/cloud_setup.sh && source tools/env.sh
```

Run `source tools/env.sh` again at the start of every later shell command that runs the pipeline
(each command may start a fresh shell). If setup fails, stop and report the error.

## 2. Plan

```bash
source tools/env.sh && python3 -m pipeline plan
```

This prints a JSON list of videos to work on. Unfinished videos from earlier runs come first.

## 3. Write scripts

For each video with `"needs_script": true`:

1. Read `instructions/script_writer.md` in full, every time.
2. Write `script.json` at the given `script_path`, for the given `topic`. If
   `previous_videos_on_this_topic` is not empty, follow the "Reused topics" rules.
3. Read the hook, disclosure and next sentence aloud to yourself, and review every piece of
   on-screen text on its own, before saving.

## 4. Produce

Production takes 10-15 minutes per video (most of it is the avatar render). Shell commands time
out after about 10 minutes, so run it in the background and check on it:

```bash
source tools/env.sh && nohup python3 -u -m pipeline produce <id> > work/<id>.log 2>&1 &
```

Then wait for it with a background wait loop (long `sleep` commands are blocked), and act when
it reports back:

```bash
until tail -3 work/<id>.log | grep -qiE 'queued|error|rejected|Traceback'; do sleep 15; done; tail -12 work/<id>.log
```

(run that with `run_in_background: true`).

- If the log says `script.json rejected`, fix `script.json` as the message says and run produce
  again. Finished steps are skipped, so re-running is safe and never pays twice for a render.
- For any other error, run produce once more. If it fails again, stop working on that video and
  report the error.

## 5. Deliver

```bash
source tools/env.sh && python3 -m pipeline deliver && python3 -m pipeline status
```

## 6. Report

End with a short summary: which video went to `ready/` (id, topic, hook), which videos were
produced into the queue, and any errors with the exact message.
