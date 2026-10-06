# AI Video Intelligence & Surveillance Engine

Analyses a video file or a live camera, from a web app or the command line. It detects people and objects, gives each one a
stable track ID, counts them, and detects line crossings, entry into restricted zones,
loitering and crowding. Matching events become alerts, which are sent by SMS and saved
with a snapshot.

```
video / camera -> YOLO detection -> ByteTrack tracking -> counting, line and zone events
               -> alert rules (cooldown, de-duplication) -> SMS, snapshots, annotated video
```

## Features

| Area | What it does |
|---|---|
| Input | Video files (MP4, AVI, MOV, MKV), RTSP/HTTP cameras with auto-reconnect, webcams |
| Detection | Ultralytics YOLO: people, vehicles, animals, bags (configurable) |
| Tracking | ByteTrack (Kalman filter + Hungarian matching) written in NumPy |
| Counting | People now, unique people, peak at once, per-class counts |
| Lines | IN / OUT counts with direction and anti-jitter |
| Zones | Entry, exit, restricted-area intrusion, loitering (dwell time), crowd limit |
| Alerts | Rules on event type, zone, line, class, confidence and schedule, with cooldown |
| SMS | Console (development), Twilio, MSG91, AWS SNS; retries and per-number rate limit |
| Output | Annotated MP4, a snapshot per alert-worthy event, `events.jsonl`, `summary.json` |
| Web app | Upload a video, follow progress live, then review counts, alerts, snapshots and events next to the annotated video |

## Quick start

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS / Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy ..\.env.example ..\.env      # optional: SMS settings

python -m scripts.analyze_video --show
```

The first run downloads the sample video (OpenCV's `vtest.avi`, people walking past a
building) and the `yolo11n.pt` weights (5 MB). `--show` opens a preview window; press
**Q** or Ctrl+C to stop. Both stop cleanly: outputs are finalised and pending SMS sent.

Report for the sample video:

```
 PEOPLE      : 29 different people  (max 8 at the same time)
 OBJECTS     :
   - car            1 detected  (max 1 at once)
   - truck          1 detected  (max 1 at once)
 LINE        : Entrance Line - IN 10, OUT 11
 ZONE        : Room 101 - 29 entries, 26 exits
 ALERTS      : 4
   - [CRITICAL] 10:05:03 @ video   0.4s  Unauthorized Person Entry track #2  (+22 repeats suppressed)
   - [MEDIUM] 10:05:15 @ video  16.6s  Crowd detected in Room 101 (7 people)
   - [MEDIUM] 10:05:27 @ video  31.5s  Loitering in Room 101 track #7  (+2 repeats suppressed)
   - [CRITICAL] 10:05:53 @ video  61.4s  Unauthorized Person Entry track #31  (+5 repeats suppressed)
 SMS         : 2 sent, 0 failed, 0 rate-limited
```

Other sources and options:

```powershell
python -m scripts.analyze_video --source C:\Videos\entrance.mp4
python -m scripts.analyze_video --source "rtsp://user:pass@192.168.1.20:554/stream1" --show
python -m scripts.analyze_video --source 0 --show          # webcam
python -m scripts.analyze_video --dry-run                  # never send real SMS
python -m scripts.analyze_video --max-seconds 30 --no-video
```

## Web app

Upload videos in the browser and review the results.

```
Next.js (React, Redux Toolkit, RTK Query, Tailwind CSS)
   -> FastAPI (REST, /api/v1) -> SQLAlchemy -> PostgreSQL or SQLite
   -> job queue: Celery worker over Redis, or a background thread in the API
   -> the same analysis pipeline as the CLI
```

**1. API** (from `backend`, with the virtual environment active):

```powershell
alembic upgrade head              # creates the database tables
uvicorn app.main:app --reload     # http://localhost:8000/api/docs
```

**2. Frontend** (needs Node.js 20 or newer):

```powershell
cd frontend
npm install
copy .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                       # http://localhost:3000
```

Open http://localhost:3000, click **Add new video** and drop a file. The upload shows its
progress, then the video page follows the analysis live and shows the results when it
finishes. Click any alert or event time to jump the annotated video to that moment.

**Database and job queue.** With the defaults nothing else is needed: data goes to
`backend/storage/app.db` (SQLite), and the API processes uploaded videos itself, one at
a time, on a background thread. For a production setup, set in `.env`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/ai_video
REDIS_URL=redis://localhost:6379/0
```

then run `alembic upgrade head` again and start a worker next to the API:

```powershell
celery -A app.workers.celery_app worker --pool=solo --loglevel=info
```

**API**

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/videos/upload` | Upload a video (multipart, field `file`) |
| `GET /api/v1/videos` · `GET /api/v1/videos/{id}` | List or get videos, with the latest job |
| `POST /api/v1/videos/{id}/process` | Queue an analysis job |
| `GET /api/v1/videos/{id}/annotated` · `/playback` | Annotated or original video (seekable) |
| `DELETE /api/v1/videos/{id}` | Delete a video and its results |
| `GET /api/v1/jobs/{id}` · `POST /api/v1/jobs/{id}/cancel` | Job status and progress; cancel |
| `GET /api/v1/events?job_id=&event_type=` | Events of a job, paginated |
| `GET /api/v1/events/{id}/snapshot` | Evidence image |

Responses use one envelope: `{"success": true, "data": ...}`, with `pagination` for lists,
and `{"success": false, "error": {"code", "message"}}` for errors.

## Configuration

**`.env`** (copy from [.env.example](.env.example)): model, device, thresholds, SMS
provider, credentials and recipients. Settings are read only in `app/core/config.py`.

**[backend/config/scene.yaml](backend/config/scene.yaml)**: the camera, which classes to
detect, zones (polygons), lines and alert rules. Coordinates are fractions of the frame
(`0,0` top-left, `1,1` bottom-right), so they survive a change of resolution. To check
where zones and lines fall:

```powershell
python -m scripts.preview_scene --source C:\Videos\entrance.mp4
```

This writes `output/scene_preview.jpg` with the zones, lines and a 10% grid.

Example rule: SMS when a person enters Room 101, only at night:

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

### SMS

`SMS_PROVIDER=console` (the default) prints each SMS in the terminal. For real messages
set `SMS_RECIPIENTS=+91XXXXXXXXXX` (comma-separated) and one provider:

- **Twilio:** `SMS_PROVIDER=twilio`, `SMS_ACCOUNT_SID`, `SMS_AUTH_TOKEN`, `SMS_FROM_NUMBER`.
  Trial accounts can only text verified numbers.
- **MSG91:** `SMS_PROVIDER=msg91`, `SMS_API_KEY`, `SMS_TEMPLATE_ID`. The DLT template's
  variables must be named `severity`, `camera`, `location`, `event` and `time`.
- **AWS SNS:** `pip install boto3`, `SMS_PROVIDER=aws_sns`, standard AWS credentials.

`python -m scripts.send_test_sms` checks the setup. Business SMS to Indian numbers falls
under TRAI's DLT rules (registered sender ID and templates).

Once an alert is sent, matching events within `cooldown_seconds` are folded into it
instead of sending another SMS. `SMS_MAX_PER_HOUR` caps messages per number.

## Output

Each run writes to `backend/output/<video>_<timestamp>/`:

| File | Contents |
|---|---|
| `annotated.mp4` | Boxes, track IDs, classes, confidence, zones, lines, counts, alert banner |
| `snapshots/` | Evidence image for each intrusion, loitering or crowd event |
| `events.jsonl` | Every event, one JSON object per line |
| `summary.json` | Counts, alerts and SMS delivery results |

## Project structure

```
backend/
├── app/
│   ├── ai/              YOLO adapter, ByteTrack tracker, Kalman filter, assignment
│   ├── events/          track state, counting, line / zone / crowd detectors,
│   │                    rule engine, event processor (event -> rule -> alert -> SMS)
│   ├── notifications/   SMSProvider interface, providers, retries and rate limits
│   ├── video/           sources, pipeline, annotation, privacy masks, writers
│   ├── api/v1/          REST endpoints: videos, jobs, events
│   ├── models/          database tables: videos, video_processing_jobs, events
│   ├── schemas/         scene configuration and API request/response models
│   ├── services/        pipeline wiring, uploads, job runner
│   ├── storage/         file storage (local disk)
│   ├── workers/         Celery app and tasks, local job thread
│   ├── core/            settings, database, errors, logging
│   └── main.py          FastAPI app
├── alembic/             database migrations
├── config/scene.yaml
├── scripts/             analyze_video, preview_scene, send_test_sms
└── tests/               unit, API and end-to-end tests

frontend/src/
├── app/                 pages: /videos, /videos/[id]
├── components/          ui/ (buttons, badges, cards), layout/, videos/
├── services/            RTK Query API (videosApi)
├── store/               Redux store and slices (videoSlice: upload progress)
├── lib/                 config, upload with progress, formatting, errors
└── types/               API and video types
```

The engine (`ai/`, `events/`, `video/`) imports nothing from the web or database code, so
the CLI and the API run exactly the same analysis.

## Design

- **Small interfaces at the edges.** `DetectionModel`, `ObjectTracker`, `VideoSource` and
  `SMSProvider` can each be swapped without touching the pipeline.
  `services/video_analysis.py` is the only place that picks concrete classes.
- **Separate stages.** The event detector only reports what happened in the scene. The
  rule engine is a pure match function. Cooldown and de-duplication live in the event
  processor, and SMS sending in the notification manager.
- **Counting that holds up.** An object is counted only after `min_hits` confident
  detections, and its class is a majority vote over its track, so one bad frame neither
  adds a count nor flips a person into a "dog". Line crossings need the path to cross
  the segment itself and the object to stay on the new side for two frames. Zone entry
  and exit need several frames in a row.
- **Video never waits for SMS.** Messages go out on worker threads with retries and
  exponential backoff.
- **Privacy and secrets.** Credentials come only from `.env`. Camera passwords are
  removed from logs, phone numbers are masked, and privacy masks are applied before a
  frame is analysed, saved or shown.

## Performance

On a CPU (no GPU), `yolo11n` takes about 65 ms per 768x576 frame, roughly 85-90% of
the processing time. The sample video (795 frames, 79 s) is analysed at around 10-12
frames per second, faster than real time. The code around the model is kept cheap:

- **Sampling happens in the source.** A file source skips unwanted frames with `grab()`,
  so they are decoded but never converted to BGR or copied. A camera source keeps only
  the newest frame, so analysis never falls behind live video.
- **Tracking.** One batched Kalman prediction per frame for all tracks, and vectorised
  IoU and class gating.
- **Annotation.** Zone and line geometry is computed once per frame size. The zone tint is
  blended only inside the zones' bounding box, through a mask.
- **Other.** Privacy masks are built once and applied in place. The model is warmed up
  before the first frame. SMS sending runs on background threads.

Measured on the sample video with the detections fixed, so only this code is timed:

| Per frame | Before | After |
|---|---|---|
| Tracking | 1.03 ms | 0.77 ms |
| Events and rules | 0.16 ms | 0.10 ms |
| Annotation | 2.71 ms | 1.48 ms |
| **Total around the model** | **3.9 ms** | **2.4 ms** |

Decoding the sample while analysing every 3rd frame took 1.50 s with `read()` on every
frame and 0.77 s with `grab()` on the skipped ones. On a CPU, end-to-end speed is still
set by YOLO. These savings matter more on a GPU, where inference is only a few
milliseconds.

Settings that matter most for speed: `inference_fps` in `scene.yaml`, `AI_IMAGE_SIZE`,
the model size (`yolo11n.pt` is fastest, `yolo11s.pt` more accurate) and a GPU, which is
used automatically when available.

## Tests

```powershell
cd backend
python -m pytest
python -m ruff check .

cd ..rontend
npm run typecheck
npm run lint
```

The end-to-end test runs the whole pipeline with a scripted detector in place of YOLO
and checks that a person walking into the room produces exactly one alert and one SMS.
The API tests cover upload validation, job control and the job runner against a
temporary SQLite database.

## Limitations

- **No login yet.** The API and web app have no authentication, so run them only on a
  trusted network.
- **Zones are global.** Every uploaded video uses the zones and lines in `scene.yaml`,
  which are drawn for the sample video. Per-video or per-camera zones would need a zone
  editor.
- **Progress is polled.** The video page asks for progress once a second; a WebSocket
  would push it instead.

- **Unique counts can be too high.** If a person is fully hidden for more than about
  1.5 s, the tracker can't be sure it is the same person and gives a new ID. "Max at the
  same time" is not affected. A camera mounted higher gives more accurate counts.
- **Small-model false positives.** `yolo11n` sometimes sees the rock on the sample's lawn
  as a "dog", so the scene config requires 60% confidence for animals
  (`class_confidence`). The same setting fixes other false alarms on a given camera.
- **Licence.** Ultralytics YOLO is AGPL-3.0. A closed-source product or hosted service
  would need an Ultralytics commercial licence, or a different model behind
  `DetectionModel`.
