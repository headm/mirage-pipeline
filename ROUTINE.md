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

This starts one new video and prints its `id`, `topic`, `script_path` and
`previous_videos_on_this_topic`. Each run makes exactly this one video; videos that failed in
earlier runs are never picked up again. Never move, rename or delete anything in `ready/`;
that folder is the owner's.

## 3. Write scripts

For the planned video:

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
until tail -3 work/<id>.log | grep -qiE 'finished, in ready|error|rejected|Traceback'; do sleep 15; done; tail -12 work/<id>.log
```

(run that with `run_in_background: true`).

- If the log says `script.json rejected`, fix `script.json` as the message says and run produce
  again (nothing has been paid for yet at that point).
- For any other error, stop: don't retry. Report the exact error; the video is simply not made
  today, and tomorrow's run starts a new one.

## 5. Review each finished video (and fix what you can)

When produce reports `finished, in ready/`:

```bash
source tools/env.sh && python3 -m pipeline review <id>
```

This prints automatic check results (`problems`) and saves a contact sheet of frames
(`contact_sheet`). Open the contact sheet image with the Read tool and look at every frame:

- Is all on-screen text fully inside the frame, readable, and meaningful on its own?
- Does anything overlap badly (text over text, a sticker over a label, graphics over the face)?
- Does the closing card stay up through the last frame?
- Does anything look broken: missing graphics, odd cropping, a blank or black frame?

**What you may fix:** only that video's `script.json` (at `script_path`): the `moments`, their
`at_word`, their on-screen text, and which stickers, photos or circles they use, plus the
matching `on_screen_review`. Never change the spoken `script`, the disclosure, the caption, the
approved facts, or any code. After editing:

```bash
source tools/env.sh && python3 -m pipeline reedit <id> && python3 -u -m pipeline produce <id> > work/<id>.log 2>&1
```

(run produce in the background as in step 4; it only redoes the edit, which is free), then
review again.

At most **two** fix rounds per video. Whatever remains after that, and any problem with
`"fixable_in_script": false` (a template or pipeline issue), goes in the report; the video
stays in `ready/` as it is and the owner fixes it by hand. Problems you judge harmless (for
example a sticker just touching a label's end) need no fix; mention them in the report.

## 6. Report

```bash
source tools/env.sh && python3 -m pipeline status
```

End with a short summary: whether the video was finished into `ready/` (id, topic, hook), what the
review found and fixed, anything still wrong that needs a manual fix, and any errors with
the exact message.
