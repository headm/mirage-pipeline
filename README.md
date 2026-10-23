# Mirage TikTok pipeline

Makes one short TikTok video a day of an AI avatar of me recommending
[Aria Payments](https://ariapayments.biz/) to small-business owners, in the Paper II
collage style. A scheduled Claude Code cloud agent runs it; I review each finished video
on my phone and upload it to TikTok by hand.

## Architecture

```mermaid
flowchart LR
    routine["Routine<br/>daily, 6am PT"]
    github["GitHub repo<br/>code, instructions"]

    subgraph cloud["Claude Code cloud session"]
        direction TB
        agent["Claude agent (Sonnet 5.5)<br/>follows ROUTINE.md, writes script"]
        voice["Voice step<br/>script to my cloned voice"]
        avatar["Avatar step<br/>voice + reference clip to video"]
        matte["Matte (Robust Video Matting)<br/>cuts me out, runs on CPU"]
        edit["Edit (Mirage Tesseract CLI)<br/>Paper II template to MP4"]
        deliver["Package and deliver<br/>queue, then oldest to ready/"]
        agent --> voice --> avatar --> matte --> edit --> deliver
    end

    eleven["ElevenLabs<br/>text to speech"]
    mirage["Mirage API<br/>Avatar X render"]
    drive[("Google Drive, via rclone<br/>topics.csv, assets,<br/>reference clip,<br/>videos, queue, ready")]
    me["Me (phone)<br/>review in Drive"]
    tiktok["TikTok<br/>manual upload"]

    routine --> cloud
    github --> cloud
    voice <--> eleven
    avatar <--> mirage
    cloud <--> drive
    drive --> me --> tiktok

    classDef inCloud fill:#EEEDFE,stroke:#534AB7,color:#3C3489
    classDef external fill:#E1F5EE,stroke:#0F6E56,color:#085041
    classDef person fill:#F1EFE8,stroke:#5F5E5A,color:#444441
    class agent,voice,avatar,matte,edit,deliver inCloud
    class github,eleven,mirage,drive external
    class routine,me,tiktok person
```

Nothing persists between cloud sessions, so everything the pipeline remembers lives in
Google Drive. API keys and the Drive token are environment variables in the Claude cloud
environment, never in this repo.

## Where things are

| Path | What it is |
|---|---|
| `ROUTINE.md` | The daily instructions the cloud agent follows |
| `instructions/script_writer.md` | Persona, approved claims, disclosure, script and on-screen text rules |
| `pipeline/` | The pipeline: `plan`, `produce`, `deliver`, `status`, `fetch-assets` |
| `pipeline/paper2.py` | The Paper II edit template |
| `scripts/cloud_setup.sh` | Prepares a fresh cloud session (pinned, checksum-verified downloads) |
| `scripts/build_paper2_assets.py` | Rebuilds the sticker, photo, circle and paper library |
| `templates/topics.csv` | Starter topic list (the live list is `topics.csv` in Drive) |
| `brand/` | Brand settings, fonts, logo; `brand/paper2/CREDITS.csv` lists image sources |

## Running it by hand

```bash
python3 -m pipeline status
python3 -m pipeline plan            # pick the next topic; prints what needs a script
python3 -m pipeline produce <id>    # after writing script.json for that video
python3 -m pipeline deliver         # move the oldest finished video into ready/
```

Settings come from `.env` locally (see `.env.example`).
