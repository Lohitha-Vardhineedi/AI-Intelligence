# AI Video Intelligence & Real-Time Surveillance Platform

AI engine for the platform designed in [docs/ARCHITECTURE_PROPOSAL.md](docs/ARCHITECTURE_PROPOSAL.md).
Give it a video or a live camera. It detects people and objects, tracks each one with a
stable ID, counts them, and detects when someone crosses the entrance line or enters a
restricted room. When that happens it creates an alert and sends an SMS.

```
Video / camera → frames → YOLO detection → ByteTrack tracking → counting
   → line crossing + zone entry → event → alert rule (cooldown) → SMS
   → annotated video, snapshots, event log
```

## What works today

| Capability | Details |
|---|---|
| Video input | Files (MP4, AVI, MOV, MKV), RTSP/IP cameras with auto-reconnect, webcams |
| Detection | Ultralytics YOLO: people, vehicles, animals, bags (configurable) |
| Tracking | ByteTrack: the same person keeps the same ID across frames |
| Counting | People now, unique people, peak at once, per-object counts |
| Entrance line | IN / OUT counts with direction, anti-jitter |
| Zones | Entry, exit, **restricted-area intrusion**, loitering (dwell time), crowd |
| Alerts | Rule engine (event, zone, object, confidence, schedule) with cooldown and de-duplication |
| SMS | Console (development), **Twilio**, **MSG91**, **AWS SNS**; retries and rate limiting |
| Evidence | Annotated MP4, a snapshot for each intrusion, `events.jsonl`, `summary.json` |

## Quick start (Windows)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

python -m scripts.analyze_video --show
```

On macOS or Linux, activate with `source .venv/bin/activate`.

The first run downloads the default sample video (`vtest.avi`, people walking past a
building) and the YOLO model (`yolo11n.pt`, 5 MB). `--show` opens a live window; press
**Q** to stop. Ctrl+C also stops cleanly.

At the end you get a report like this:

```
 PEOPLE      : 29 different people  (max 8 at the same time)
 OBJECTS     : car 1, truck 1          (the parked car and the white van)
 LINE        : Entrance Line - IN 10, OUT 11
 ZONE        : Room 101 - 29 entries, 26 exits
 ALERTS      : 4
   - [CRITICAL] ... Unauthorized Person Entry track #2  (+22 repeats suppressed)
 SMS         : 2 sent, 0 failed, 0 rate-limited
```

## SMS alerts to your phone

Recipients are set in `.env`, which is git-ignored:

```env
SMS_RECIPIENTS=+919381558756        # comma-separate several numbers
```

`SMS_PROVIDER=console` (the default) prints each SMS in the terminal, so you can test
everything for free. To send **real** SMS, choose a provider and add its credentials to
`.env`. Never put credentials in code or share them.

**Twilio** (quickest to try):
1. Create an account at twilio.com and get a phone number.
2. On a trial account, verify your own mobile number first. Trial accounts can only text
   verified numbers.
3. Set in `.env`:
   ```env
   SMS_PROVIDER=twilio
   SMS_ACCOUNT_SID=AC...
   SMS_AUTH_TOKEN=...
   SMS_FROM_NUMBER=+1...
   ```
4. Check it works: `python -m scripts.send_test_sms`

**MSG91** (Indian provider): set `SMS_PROVIDER=msg91`, `SMS_API_KEY` and
`SMS_TEMPLATE_ID`. The template's variables must be named `severity`, `camera`,
`location`, `event` and `time`.

**AWS SNS:** `pip install boto3`, set `SMS_PROVIDER=aws_sns` and use your standard AWS
credentials.

> Business SMS to Indian numbers falls under TRAI's DLT rules (registered sender ID and
> message templates). Check your provider's current India requirements if messages don't
> arrive.

**Duplicate protection:** once an intrusion alert is sent, more intrusions into the same
zone within `cooldown_seconds` (default 60) are counted on that alert but don't send
another SMS. There is also a per-number limit (`SMS_MAX_PER_HOUR`, default 10).

## Your own video or camera

```powershell
python -m scripts.analyze_video --source C:\Videos\entrance.mp4
python -m scripts.analyze_video --source "rtsp://user:pass@192.168.1.20:554/stream1" --show
python -m scripts.analyze_video --source 0 --show          # laptop webcam
python -m scripts.analyze_video --dry-run                  # never send real SMS
python -m scripts.analyze_video --max-seconds 30 --no-video
```

Camera passwords are removed from every log line.

## Configure "the room" (zones, lines, rules)

Everything about the scene is in [backend/config/scene.yaml](backend/config/scene.yaml):
- the camera name and location
- which objects to detect
- the **Room 101** restricted zone (a polygon)
- the **Entrance Line** (point A → point B)
- the alert rules

Coordinates are fractions of the frame: `0,0` is the top-left corner and `1,1` the
bottom-right. To see where your zones and lines fall, run:

```powershell
python -m scripts.preview_scene --source C:\Videos\entrance.mp4
```

This writes `output/scene_preview.jpg` with the zones, lines and a 10 % grid drawn on a
frame. Adjust the points and run it again.

Example rule (send an SMS when a person enters Room 101, only at night):

```yaml
  - id: room-101-intrusion
    name: Person entering Room 101
    event_types: [INTRUSION_DETECTED]
    zones: [room-101]
    object_classes: [person]
    severity: CRITICAL
    actions: {sms: true, snapshot: true}
    cooldown_seconds: 60
    schedule: {days: [MON, TUE, WED, THU, FRI, SAT, SUN], start: "19:00", end: "07:00"}
```

## Output

Each run writes to `backend/output/<video>_<timestamp>/`:

| File | Contents |
|---|---|
| `annotated.mp4` | Video with boxes, track IDs, labels, confidence, zones, lines, counts and alert banners |
| `snapshots/` | One evidence image per intrusion, loitering or crowd event |
| `events.jsonl` | Every event, one JSON object per line |
| `summary.json` | Counts, alerts and SMS delivery results |

## Project structure

```
backend/
├── app/
│   ├── core/            settings (.env) and logging
│   ├── ai/              DetectionModel (YOLO), ObjectTracker (ByteTrack), model manager
│   ├── video/           sources (file / RTSP / webcam), sampling, pipeline, annotation, writers
│   ├── events/          event types, geometry, line / zone / crowd detectors, rule engine,
│   │                    event processor (event → rule → alert → notification)
│   ├── notifications/   SMSProvider interface + Twilio / MSG91 / AWS SNS / console
│   ├── schemas/         scene configuration models (validated)
│   ├── security/        camera URL redaction
│   └── services/        builds the pipeline from settings + scene
├── config/scene.yaml    camera, zones, lines, alert rules
├── scripts/             analyze_video, preview_scene, send_test_sms
└── tests/               unit + end-to-end pipeline tests
```

The detection, tracking and event code has no web or database dependencies, so the
upcoming API, Celery workers and live stream service can reuse it unchanged.

## Tests

```powershell
cd backend
python -m pytest        # 43 tests
python -m ruff check .
```

The end-to-end test runs the full pipeline with a scripted detector and checks that a
person walking into the room produces exactly one alert and one SMS.

## Notes and limitations

- **Unique counts can be too high.** When someone is fully hidden for more than about
  1.5 s (behind another person or the lamp post in the sample), the tracker can't be sure
  it's the same person and gives them a new ID. "Max at the same time" is not affected.
  A camera mounted higher, looking down at the entrance, gives the most accurate counts.
- **Speed vs accuracy:** on this PC's CPU, the default `yolo11n` model analyses the
  sample (79 s of video) in about 50 s, faster than real time. Setting
  `AI_MODEL_PATH=models/yolo11s.pt` in `.env` is more accurate but runs at about 7 fps.
  An NVIDIA GPU is used automatically when available.
- **False detections:** `yolo11n` sometimes takes the rock on the sample's lawn for a
  "dog". The scene config therefore needs 60 % confidence for animals
  (`class_confidence`). Raise a class's threshold the same way if it gives false alarms
  on your camera.
- **This PC:** Windows Application Control blocks SciPy's DLLs, so the tracker is written
  in NumPy and doesn't need SciPy. No action is needed.
- **Licence:** Ultralytics YOLO is AGPL-3.0, which is fine for personal use. Selling the
  platform or offering it as a service would need Ultralytics' commercial licence, or a
  different model behind the same `DetectionModel` interface.

## Next steps (roadmap)

Following [the architecture proposal](docs/ARCHITECTURE_PROPOSAL.md#i-development-roadmap):
1. PostgreSQL schema and FastAPI backend (auth, cameras, videos, events, alerts API).
2. Celery jobs for uploads; a live stream service for cameras; WebSocket updates.
3. Next.js dashboard: live monitoring, a zone and line editor, alerts, analytics.
