# AI Video Intelligence & Real-Time Surveillance Platform
## Architecture Proposal

| | |
|---|---|
| **Project** | Personal project |
| **Status** | Draft for approval. No code has been written yet |
| **Version / date** | 0.2 · 5 October 2026 |
| **Responds to** | Requirements brief §74–§75. This document covers Steps 1–2 of §69 (analyse requirements, create architecture) |
| **Next step** | Your approval, then Step 3 (repository structure) |

Section references such as "§23" point to the requirements brief.

---

## 0. Executive summary

The platform takes in uploaded videos and live CCTV/RTSP/IP camera streams. It detects people and objects, tracks each one with a stable ID, counts them and works out how they move. From that it detects line crossings, zone entry and exit, intrusion, crowding and loitering. It then evaluates configurable alert rules and notifies users in real time through the dashboard, browser notifications and SMS. Evidence, analytics, reports, multi-tenancy, RBAC and audit trails are included.

**The system has three planes:**

- **Control plane:** Next.js frontend, FastAPI REST API and WebSocket gateway, PostgreSQL, Redis and object storage.
- **Processing plane:**
  - Python workers run the vision pipeline: video → frames → detection → tracking → event detection.
  - Events flow through Redis to a separate event processor. It stores them, evaluates rules, creates alerts and hands notifications to the notification service.
  - The vision code never sends SMS itself (§64).
- **Media plane:** MediaMTX pulls each camera stream and serves it to browsers over WebRTC, with HLS as a fallback. Bounding boxes, track IDs, zones and lines are drawn over the video in the browser.

### 0.1 Design decisions

Most decisions implement the brief as written. Where the brief leaves something open, or a specified approach would not work in practice, the last column says so.

| # | Area | Decision | Relation to brief |
|---|---|---|---|
| **D1** | Object detection | **Ultralytics YOLO** (PyTorch) behind a `DetectionModel` interface. Optional ONNX/OpenVINO export for faster CPU inference | As specified (§7) |
| **D2** | Tracking | **ByteTrack** behind an `ObjectTracker` interface; BoT-SORT as an alternative | As specified (§7, §11) |
| **D3** | Video input | **OpenCV** (FFmpeg backend) behind a `VideoSource` interface, with reconnection and timeouts | As specified (§7–§9) |
| **D4** | Background processing | **Celery + Redis** for uploaded-video jobs, exports and reports. A **long-running stream service** for live cameras | Extends §45: Celery is built for jobs that finish, while live camera processing runs continuously |
| **D5** | Event flow | **Redis Streams** carry events from workers to the event processor. **Redis Pub/Sub** fans updates out to WebSocket clients | Implements §27 and §64 |
| **D6** | Detection storage | The `detections` table stores per-frame results for **uploaded videos**. **Live cameras** store tracks, sampled track points, events and per-minute counts, not every frame | Refines §10 and §23: storing every frame of every live camera grows the database by millions of rows a day |
| **D7** | Browser playback | **MediaMTX**: RTSP → WebRTC, with HLS fallback; overlays drawn on a canvas | Implements §5 ("HLS/WebRTC") |
| **D8** | Multi-tenancy | `tenant_id` on every tenant-owned table from the first migration, enforced in repositories **and** PostgreSQL Row-Level Security. Tenant admin screens arrive in Phase 4 | Implements §24. Building it in from the start avoids a costly retrofit |
| **D9** | Authentication | Registration creates an organisation and its admin. Short-lived JWT access token plus rotating refresh token in an httpOnly cookie. Argon2id password hashing. RBAC with the 5 roles in §25 | As specified (§25, §61) |
| **D10** | Frontend state | **Redux Toolkit** with the slice structure from §42 for client and real-time state. **RTK Query** (part of Redux Toolkit) for server data | Interprets "React Query where appropriate" (§5) and avoids two competing caches |
| **D11** | Notifications | `SMSProvider` interface with **Twilio, MSG91 and AWS SNS** adapters, chosen by `SMS_PROVIDER`. A console provider for development | As specified (§20) |
| **D12** | Privacy | No facial recognition. Privacy masks, configurable retention, evidence permissions and audit logs | As specified (§50) |

---

## 1. Requirements analysis

### 1.1 Gaps the brief leaves open, and how this design fills them

1. **Reaching the cameras.**
   - **Issue:** CCTV cameras sit on private networks.
   - **Approach:** run the stack on the same network as the cameras (your PC or a home or office server).
   - **Cloud (Phase 5):** a cloud-hosted backend needs either a VPN or a small on-site service that relays the stream. The stream service is designed so it can run on-site later.
2. **Live processing and Celery.** Celery suits finite jobs such as processing an uploaded video. A live camera pipeline runs indefinitely and needs supervision, reconnection and failover. Live cameras therefore run in a dedicated stream service (D4).
3. **Detection volume.**
   - **Issue:** 10 cameras × 5 inferred frames per second × 10 objects is about 43 million rows a day.
   - **Uploaded videos:** these are finite, so their per-frame detections are stored in full.
   - **Live cameras:** these store tracks, events and aggregated counts (D6).
4. **Browsers cannot play RTSP.** MediaMTX converts each camera stream to WebRTC and HLS (D7).
5. **Password reset needs email.** `/forgot-password` (§29) requires sending emails. Emails go through an SMTP email provider. In development, a local mail catcher (Mailpit) captures them.
6. **Counting accuracy is not defined.** An evaluation script measures count error and line-crossing accuracy on labelled sample clips. Thresholds can then be tuned with evidence instead of by eye.
7. **"Today" depends on the time zone.** All timestamps are stored in UTC. Each site has a time zone (default `Asia/Kolkata`), and daily counts use the site's local day.
8. **Video evidence needs footage from before the event.** Each live camera keeps a short rolling buffer, so an event clip can include the seconds before the event as well as after.
9. **Annotated video must play in browsers.** OpenCV's default MP4 codec does not play in browsers.
   - **Playback:** the original video plays with boxes drawn live by the browser from stored detections, so labels can be toggled.
   - **Export:** an annotated MP4 export is encoded as H.264 with FFmpeg.
10. **Duplicate SMS when track IDs change.** If a person is briefly hidden, the tracker may give them a new ID, so cooldown per track alone would still send repeat SMS. The default cooldown is therefore per rule and zone (§22, see §E.4).
11. **SMS to Indian numbers.** Under TRAI's DLT framework, business SMS to Indian numbers generally needs a registered sender ID and pre-approved message templates. Check your chosen provider's current India rules. The console provider lets every feature be built and tested without sending real SMS.
12. **Naming.**
    - `CROWD_THRESHOLD_EXCEEDED` (§16) and `CROWD_DETECTED` (§19) refer to the same event and are unified as `CROWD_DETECTED`.
    - WebSocket message types are lower-case event names (§27).
13. **Ultralytics licence.** Ultralytics YOLO is licensed under AGPL-3.0. This is fine for personal and open-source use. Selling the platform as closed-source software, or offering it as a service, would require Ultralytics' commercial licence. The `DetectionModel` interface (§7) allows a swap to a permissively licensed model if that becomes relevant.

### 1.2 Assumptions (I will proceed on these unless you correct them)

- **Development:** on your Windows 11 machine with Docker Desktop. The non-Docker setup also supports macOS and Linux.
- **Hardware:** a GPU is optional. Without one, the system runs on CPU with a small model and a lower inference frame rate.
- **Scale:** a handful of cameras at first. The architecture scales horizontally to more (Phase 5).
- **Cameras:** provide RTSP in H.264 or H.265, ideally with a lower-resolution sub-stream. An RTSP simulator (a looping sample video) stands in for real cameras in development.
- **Users and tenants:** each user belongs to one organisation (tenant). `SUPER_ADMIN` is a platform-level user.
- **Versions:** Python 3.12, current Node.js LTS, PostgreSQL 17 and Redis 7. Exact versions are pinned in Step 3.

---

## A. System architecture

### A.1 Layered view

```
 CLIENT       Next.js web app ──REST──────┐ ──WebSocket────┐ ──WebRTC / HLS─────┐
                                          ▼                ▼                    ▼
 EDGE         Reverse proxy (nginx): TLS · single origin · upload limits · rate limits
                                          │                │                    │
 CONTROL      FastAPI API ────────────────┴── WS gateway ──┘             MediaMTX (media relay)
 PLANE          auth · RBAC · tenancy · CRUD · uploads · analytics            ▲         │
                │                                                             │         │ RTSP
 DATA         PostgreSQL            Redis                             Object storage    │
 LAYER        (system of record)    Celery broker · Streams ·         local / S3 /      │
                ▲                   Pub/Sub · cache · locks           MinIO / Azure     │
                │                     ▲            │                    ▲               │
 PROCESSING     │                     │            ▼                    │               ▼
 PLANE        Event processor ◄───────┤        Job workers (Celery) ────┤        CCTV / IP cameras
              store → rules →         │        uploaded videos, exports,│               │
              alerts → notify         │        reports, retention       │               │
                │                     │                                 │               │
                │                     └──── Stream service ─────────────┘◄──────────────┘
                │                           read → sample → detect → track → event detection
                ▼
 EXTERNAL     SMS provider (Twilio / MSG91 / AWS SNS) · SMTP (email)
```

### A.2 Components

| Component | Responsibility | Technology |
|---|---|---|
| **Web app** | Dashboard, live monitoring, zone and line editor, video analysis, alerts, analytics, admin | Next.js (App Router), TypeScript, Tailwind CSS, Redux Toolkit, Recharts |
| **Reverse proxy** | Serves frontend, API, WebSocket and media on **one origin** (cookies work and no cross-origin setup is needed); TLS; upload size limits | nginx |
| **API service** | REST API, validation, authentication, RBAC, tenant isolation, uploads, analytics queries, WebSocket gateway, OpenAPI docs | FastAPI, Pydantic, SQLAlchemy 2 (async), Alembic |
| **Media relay** | Pulls each camera **once**; serves WebRTC/HLS to browsers and RTSP to the stream service. Many cameras allow only a few simultaneous connections, so sharing one connection matters. Checks viewer permissions with the API | MediaMTX |
| **Stream service** | Long-running pipeline per live camera. Detects, tracks and analyses events, then publishes events, live overlay data, snapshots and health heartbeats | Python, OpenCV, PyTorch / Ultralytics YOLO, ByteTrack, NumPy |
| **Job workers** | Uploaded-video processing, annotated export, camera connection tests, report generation, retention clean-up | Celery + Redis |
| **Event processor** | Reads events from Redis Streams. Stores them, evaluates alert rules, creates alerts and queues notifications, all in one database transaction. Then pushes real-time updates and sends notifications | Python asyncio, Redis Streams consumer groups |
| **PostgreSQL** | System of record: normalised tables, UUID keys, time-partitioned high-volume tables, Row-Level Security | PostgreSQL 17 |
| **Redis** | Celery broker, event streams, Pub/Sub, alert cooldowns, rate limits, camera assignment, caching | Redis 7 (AOF persistence on) |
| **Object storage** | Videos, snapshots, clips, annotated exports, reports | `StorageProvider`: local filesystem, AWS S3, MinIO, Azure Blob |
| **Notification service** | SMS (and email for account flows) through provider adapters, with retries and delivery tracking | Twilio / MSG91 / AWS SNS; SMTP |

### A.3 Key decisions explained

**D1 — Detection.**
- The application depends only on `DetectionModel.detect(frames) -> list[list[Detection]]` (§7).
- The default implementation wraps Ultralytics YOLO:
  - nano/small variants for CPU
  - small/medium for GPU
  - weights downloaded by a setup script
- `ModelManager` selects the device (CUDA if available, otherwise CPU), warms up the model, and records the model name and version on every job and event.
- Another model can be added by writing one adapter class.

**D2 — Tracking.**
- `ObjectTracker.update(detections) -> list[TrackedObject]` (§7).
- ByteTrack is the default. It is fast, reliable at typical CCTV frame rates, and keeps tracking independent of the detector.
- BoT-SORT can be enabled for scenes with heavy occlusion.
- Each camera or video gets its own tracker instance.

**D4 — Stream service.**
- Each live camera is assigned to one stream-service process through a **lease**: a Redis key with an expiry, renewed by heartbeat.
- If a process stops, its leases expire and another process takes over those cameras. This is what makes horizontal scaling (Phase 5) possible.
- Start, stop and configuration changes (for example, editing a zone) reach the stream service as commands on a Redis channel and take effect without a restart.

**D5 — Event consistency.**
- Each event gets a time-ordered UUID **in the worker**, so every downstream component refers to the same ID.
- The event processor writes the event, any alert and the queued notifications in **one transaction**. Inserts are idempotent, so a redelivered event is never stored twice.
- A sweeper resends notifications left pending after a crash.

**D7 — Live overlays.**
- The browser plays the camera stream and draws boxes on a `<canvas>` from WebSocket messages stamped with the frame time.
- Overlay data is published only while someone is watching that camera.
- Snapshots used as evidence are rendered on the server, so they are always exact.

**D8 — Tenancy.**
- The tenant is always taken from the logged-in user's token, never from request data.
- Repositories add the tenant filter automatically. PostgreSQL Row-Level Security blocks any query that misses it.
- A request for another tenant's record returns `404`.

**D9 — Authentication.**
- The access token lasts about 15 minutes and is held in browser memory.
- The refresh token rotates on every use and is stored hashed. Reusing an old refresh token revokes the whole session.
- WebSocket connections use a one-time ticket, so tokens never appear in URLs.
- Public registration can be switched off with `ALLOW_REGISTRATION=false` when the app is exposed to the internet.

---

## B. Folder structure

```
ai-video-intelligence/
├── README.md
├── docker-compose.yml              # full dev stack (§K.1)
├── docker-compose.gpu.yml          # override: NVIDIA GPU for workers
├── .env.example                    # every variable documented; no real values
├── .gitignore  .gitattributes  .editorconfig  .pre-commit-config.yaml
├── .github/workflows/ci.yml        # lint · type-check · tests · image build
├── docs/
│   ├── ARCHITECTURE.md  API.md  DATABASE.md  AI_PIPELINE.md
│   ├── DEPLOYMENT.md  SECURITY.md  DEVELOPMENT.md
│   └── adr/                        # architecture decision records (D1–D12)
│
├── backend/
│   ├── pyproject.toml  uv.lock
│   ├── requirements.txt  requirements-ai.txt  requirements-dev.txt
│   ├── Dockerfile                  # targets: api | worker-cpu | worker-gpu
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py                 # app factory, middleware, routers, error handlers
│   │   ├── api/
│   │   │   ├── deps.py             # current user, tenant session, permission checks, pagination
│   │   │   └── v1/
│   │   │       ├── router.py
│   │   │       ├── auth.py  users.py  roles.py  tenants.py  sites.py
│   │   │       ├── cameras.py  zones.py  lines.py
│   │   │       ├── videos.py  jobs.py  detections.py  tracks.py
│   │   │       ├── events.py  alert_rules.py  alerts.py  notification_channels.py
│   │   │       ├── analytics.py  reports.py  settings.py  audit_logs.py
│   │   │       └── webhooks.py  health.py
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings: the only place env vars are read
│   │   │   ├── security.py         # password hashing (Argon2id), JWT, refresh tokens
│   │   │   ├── database.py         # async engine, sessions with tenant context
│   │   │   ├── logging.py          # structured JSON logs with request/tenant/user IDs
│   │   │   ├── errors.py           # error codes, exception classes, handlers
│   │   │   └── responses.py        # success / paginated response envelopes
│   │   ├── security/
│   │   │   ├── rbac.py  permissions.py   # roles, permissions, route guards
│   │   │   ├── encryption.py       # camera credential encryption (AES-256-GCM)
│   │   │   ├── url_guard.py        # camera URL validation and log redaction
│   │   │   └── rate_limit.py
│   │   ├── models/                 # SQLAlchemy ORM models
│   │   ├── schemas/                # Pydantic request/response schemas
│   │   ├── repositories/           # data access; tenant-scoped base repository
│   │   ├── services/               # business logic: auth, users, cameras, videos, zones,
│   │   │                           #   rules, alerts, analytics, reports, audit
│   │   ├── storage/                # StorageProvider: base, local, s3 (+MinIO), azure_blob
│   │   │
│   │   │   # ── AI engine: no web or database imports (enforced in CI, §63) ──
│   │   ├── video/
│   │   │   ├── sources/            # base.py, file.py, rtsp.py, http.py (IP camera)
│   │   │   ├── reader.py           # threaded reader, reconnect, latest-frame buffer
│   │   │   ├── processor.py        # frame sampling, resizing, privacy masks
│   │   │   ├── pipeline.py         # read → detect → track → detect events
│   │   │   └── writer.py           # snapshots, annotated MP4, event clips
│   │   ├── ai/
│   │   │   ├── types.py            # Frame, Detection, TrackedObject
│   │   │   ├── detector.py         # DetectionModel interface + YOLO implementation
│   │   │   ├── tracker.py          # ObjectTracker interface + ByteTrack implementation
│   │   │   ├── classifier.py       # extension point (vehicle type, PPE, …)
│   │   │   └── model_manager.py    # model loading, device selection, warm-up
│   │   ├── events/
│   │   │   ├── types.py            # EventType, Severity, Event
│   │   │   ├── geometry.py         # line intersection, side test, point-in-polygon
│   │   │   ├── detectors/          # counting, line_crossing, zones, crowd, loitering
│   │   │   ├── detector.py         # EventDetector: runs all detectors per frame
│   │   │   ├── rules.py            # RuleEngine: matches events to alert rules (§18)
│   │   │   └── processor.py        # EventProcessor: store → rules → alerts → notify queue
│   │   │   # ─────────────────────────────────────────────────────────────
│   │   ├── notifications/
│   │   │   ├── sms.py              # SMSProvider interface + provider factory
│   │   │   ├── providers/          # twilio.py, msg91.py, aws_sns.py, console.py
│   │   │   ├── email.py            # SMTP for account emails
│   │   │   ├── templates.py        # message templates (§21)
│   │   │   └── manager.py          # dispatch, retries, rate limits, delivery status
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   ├── tasks/              # video_processing, export, camera_test, reports, retention
│   │   │   ├── stream_service.py   # live camera pipelines, leases, commands
│   │   │   └── event_worker.py     # runs EventProcessor and notification dispatcher
│   │   ├── websocket/
│   │   │   ├── manager.py  routes.py  topics.py
│   │   └── analytics/              # aggregation queries, report builders (CSV/PDF)
│   ├── scripts/                    # create_superadmin.py, seed_demo.py, download_models.py,
│   │                               #   analyze_video.py (CLI), benchmark.py, evaluate.py
│   └── tests/
│       ├── unit/                   # ai/, events/, rules/, notifications/, security/
│       ├── integration/            # database, Redis, storage, workers
│       ├── api/                    # endpoints, auth, RBAC, tenant isolation
│       └── fixtures/               # sample clips, images, synthetic tracks
│
├── frontend/
│   ├── package.json  next.config.ts  tsconfig.json  tailwind config
│   ├── Dockerfile
│   ├── src/
│   │   ├── app/
│   │   │   ├── (auth)/login  register  forgot-password  reset-password
│   │   │   ├── (app)/layout.tsx    # shell: sidebar, top bar, critical-alert banner
│   │   │   ├── (app)/dashboard  monitoring  cameras  cameras/[id]  cameras/[id]/configure
│   │   │   ├── (app)/videos  videos/[id]  events  events/[id]  alerts
│   │   │   ├── (app)/alert-rules  alert-rules/[id]  analytics  reports
│   │   │   ├── (app)/users  users/[id]  settings/[section]
│   │   │   └── (platform)/tenants  # super admin only
│   │   ├── components/
│   │   │   ├── ui/                 # buttons, inputs, tables, badges, dialogs, cards
│   │   │   ├── layout/  dashboard/  monitoring/  cameras/  videos/
│   │   │   ├── events/  alerts/  analytics/  zones/
│   │   ├── features/               # per-feature hooks and logic (keeps components thin)
│   │   ├── services/               # API layer (RTK Query endpoints), WebSocket client, player
│   │   ├── store/
│   │   │   ├── index.ts  hooks.ts
│   │   │   └── slices/             # authSlice, cameraSlice, videoSlice, detectionSlice,
│   │   │                           #   eventSlice, alertSlice, analyticsSlice,
│   │   │                           #   notificationSlice, uiSlice   (as §42)
│   │   ├── hooks/  types/  utils/  constants/  lib/  styles/
│   └── tests/                      # Vitest + Testing Library; Playwright end-to-end
│
├── infra/
│   ├── nginx/nginx.conf
│   ├── mediamtx/mediamtx.yml
│   ├── postgres/init.sql           # database roles for Row-Level Security
│   ├── rtsp-simulator/             # streams a sample video as an RTSP "camera"
│   └── monitoring/                 # Prometheus and Grafana (Phase 5)
└── models/                         # git-ignored; AI weights downloaded by script
```

**Notes**

- This follows §43–§44. A few folders are added:
  - `storage/`, `security/` and `analytics/` (named in §6)
  - `events/detectors/` (keeps files small, §70)
  - `scripts/`
- `video/`, `ai/` and the event detectors **do not import FastAPI or the database**. A CI check enforces this, so the AI engine stays independent of the web application (§63) and can be tested on its own.
- **Redux (§42):** the slice files are exactly the ones listed in the brief.
  - Data fetched from the API is cached by RTK Query in `services/`.
  - The slices hold session data, live WebSocket data (camera status, live counts, event and alert feeds), upload progress, filters and UI state.
  - High-frequency overlay boxes go straight from the WebSocket client to the canvas without passing through Redux. Updating Redux 8–10 times a second per camera would re-render the whole page.

---

## C. Database ER design

### C.1 Conventions

- **Keys:** UUID primary keys, time-ordered (UUIDv7) for index efficiency.
- **Timestamps:** `created_at` and `updated_at` in UTC.
- **Tenancy:** `tenant_id` on every tenant-owned table, with a Row-Level Security policy on each.
- **Soft delete:** configuration records (users, cameras, zones, lines, rules) use `deleted_at`, so past events keep valid references. Footage and evidence are permanently deleted by retention jobs.
- **Partitioning:** high-volume tables are partitioned by month: `detections`, `track_points`, `events`, `count_aggregates` and `audit_logs`. Old data is removed by dropping whole partitions.
- **Coordinates:** zone and line coordinates are stored **normalised to 0–1** of the frame size, so they stay correct if camera resolution changes.

### C.2 Relationships

Legend: `─<` one-to-many, `─1` one-to-one, `>─<` many-to-many through a join table.

```
tenants ─┬─< users >─< user_roles >── roles >─< role_permissions >── permissions
         │     ├─< user_camera_access >── cameras
         │     ├─< refresh_tokens
         │     ├─< password_reset_tokens
         │     └─< notification_channels  (a user's SMS number / email)
         │
         ├─< sites (Building → Room hierarchy)
         │     └─< cameras ─┬─1 camera_credentials
         │                  ├─< camera_streams        (main / sub stream)
         │                  ├─< zones ─< zone_points
         │                  ├─< lines
         │                  └─< privacy_masks
         │
         ├─< videos ─< video_processing_jobs ─< detections
         │
         ├─< object_tracks ─< track_points           (track belongs to a camera or a job)
         │
         ├─< events ─┬─< event_snapshots              (snapshots and clips)
         │           └─< alerts >── alert_rules >─< alert_rule_channels >── notification_channels
         │                 └─< notification_logs
         │
         ├─< count_aggregates                         (per minute, for analytics)
         ├─< report_jobs
         ├─< system_settings                          (tenant_id NULL = platform default)
         └─< audit_logs
```

### C.3 Tables

All the tables suggested in §23 are kept. The additions are marked *(added)*.

**Users and access**

| Table | Main columns | Notes |
|---|---|---|
| `tenants` *(added)* | id, name, slug, status, timezone | One organisation (§24) |
| `users` | id, tenant_id, email, password_hash, full_name, phone, status (`ACTIVE`/`INACTIVE`), last_login_at | Email unique (case-insensitive) |
| `roles` | id, tenant_id (NULL = system role), name, is_system | Seeded: SUPER_ADMIN, TENANT_ADMIN, SECURITY_MANAGER, OPERATOR, VIEWER |
| `permissions` | id, code (e.g. `camera:manage`), description | Seeded (§D.3) |
| `role_permissions` *(added)* | role_id, permission_id | Links roles to permissions |
| `user_roles` | user_id, role_id | |
| `user_camera_access` *(added)* | user_id, camera_id | "Assign camera access" (§40). No rows = all cameras |
| `refresh_tokens` *(added)* | id, user_id, token_hash, family_id, expires_at, revoked_at | Refresh token rotation |
| `password_reset_tokens` *(added)* | id, user_id, token_hash, purpose (`RESET`/`ACTIVATION`), expires_at, used_at | Forgot password and new-user activation |

**Cameras**

| Table | Main columns | Notes |
|---|---|---|
| `sites` *(added)* | id, tenant_id, parent_id, name, timezone | "Building A / Room 101" (§3) |
| `cameras` | id, tenant_id, site_id, name, protocol (`RTSP`/`HTTP`), status (`ONLINE`/`OFFLINE`/`DISABLED`/`UNKNOWN`), monitoring_enabled, fps, resolution, frame_skip, confidence_threshold, iou_threshold, detection_classes, last_seen_at | Analysis settings from §9 per camera |
| `camera_credentials` | camera_id, username_encrypted, password_encrypted, key_version | Encrypted; never returned by the API (§49) |
| `camera_streams` | id, camera_id, kind (`MAIN`/`SUB`), host, port, path, transport | The full RTSP URL is built only inside the worker |
| `privacy_masks` *(added)* | id, tenant_id, camera_id, points jsonb | Regions blacked out before storage and display (§50) |

**Zones and lines**

| Table | Main columns | Notes |
|---|---|---|
| `zones` | id, tenant_id, camera_id, name, zone_type (`RESTRICTED`/`SAFE`/`ENTRY`/`EXIT`/`PARKING`/`CROWDED`/`CUSTOM`), allowed_classes, max_people, max_dwell_seconds, severity, colour, enabled | §14–§17, §34 |
| `zone_points` | id, zone_id, point_order, x, y | Polygon vertices; replaced as a set when a zone is edited |
| `lines` | id, tenant_id, camera_id, name, start_x, start_y, end_x, end_y, direction (`IN`/`OUT`/`BOTH`), counts_occupancy, enabled | §13, §35. IN means crossing from the left of A→B to its right; the UI shows an arrow |

**Videos and processing**

| Table | Main columns | Notes |
|---|---|---|
| `videos` | id, tenant_id, camera_id (optional), filename, storage_key, size_bytes, checksum, format, codec, duration_seconds, fps, width, height, status, uploaded_by | The file lives in object storage (§47) |
| `video_processing_jobs` | id, tenant_id, video_id, status (`QUEUED`/`PROCESSING`/`COMPLETED`/`FAILED`/`CANCELLED`), progress_percent, frames_processed, total_frames, processing_fps, started_at, completed_at, error_code, error_message, settings_snapshot jsonb, model_version, annotated_video_key, summary jsonb | §46. The settings snapshot makes results reproducible |
| `detections` | id, tenant_id, job_id, frame_number, timestamp_ms, track_id, class, confidence, bbox_x, bbox_y, bbox_w, bbox_h | Per-frame results for **uploaded videos** (§10). Bulk-inserted. Index (job_id, frame_number) |

**Tracking**

| Table | Main columns | Notes |
|---|---|---|
| `object_tracks` | id, tenant_id, camera_id or job_id, tracker_track_id, object_class, first_seen_at, last_seen_at, best_confidence, best_bbox, direction, status (`ACTIVE`/`ENDED`) | One row per tracked object (§11). Tracker IDs restart each run, so each track also gets a UUID |
| `track_points` | id, track_id, tenant_id, timestamp, x, y, zone_id | Trajectory sampled about once per second (configurable). Short retention |
| `count_aggregates` *(added)* | tenant_id, camera_id, minute, object_class, max_visible, avg_visible, unique_objects, entries, exits | Per-minute counts behind analytics and reports. Holds no personal data |

**Events, alerts and notifications**

| Table | Main columns | Notes |
|---|---|---|
| `events` | id, tenant_id, camera_id, job_id, event_type, severity, occurred_at, video_timestamp_ms, track_id, zone_id, line_id, object_class, confidence, bbox, direction, details jsonb, model_version | Indexes: (tenant_id, occurred_at), (camera_id, occurred_at), (event_type, occurred_at), (track_id) |
| `event_snapshots` | id, tenant_id, event_id, kind (`SNAPSHOT`/`CLIP`), storage_key, checksum, captured_at, expires_at | Evidence (§15, §37). Every view is audited |
| `alert_rules` | id, tenant_id, name, enabled, event_types, camera_ids, zone_ids, line_ids, object_classes, threshold, min_duration_seconds, days_of_week, start_time, end_time, severity, create_snapshot, cooldown_seconds, dedup_scope | Every rule field listed in §18 |
| `notification_channels` | id, tenant_id, user_id (optional), type (`SMS`/`EMAIL`), name, destination, verified_at, enabled | Registered SMS recipients (§3, §40) |
| `alert_rule_channels` *(added)* | rule_id, channel_id | Which recipients a rule notifies |
| `alerts` | id, tenant_id, event_id, rule_id, camera_id, severity, status (`OPEN`/`ACKNOWLEDGED`/`RESOLVED`), occurrence_count, last_occurred_at, acknowledged_by, acknowledged_at, resolved_by, resolved_at, note | §36. Index (tenant_id, status, severity, created_at) |
| `notification_logs` | id, tenant_id, alert_id, channel_id, provider, destination_masked, message, status (`PENDING`/`SENT`/`DELIVERED`/`FAILED`/`SUPPRESSED`), attempts, provider_message_id, error, sent_at | Delivery history; also the queue of pending notifications |

**System**

| Table | Main columns | Notes |
|---|---|---|
| `system_settings` | id, tenant_id (NULL = platform default), section, value jsonb | AI defaults, camera defaults, notifications, retention, security (§41) |
| `report_jobs` *(added)* | id, tenant_id, report_type, parameters, format (`CSV`/`PDF`), status, storage_key, requested_by | §39 |
| `audit_logs` | id, tenant_id, user_id, action, entity_type, entity_id, changes jsonb, ip_address, user_agent, request_id, created_at | Append-only; secrets redacted |

### C.4 Default retention (configurable per organisation, §50)

| Data | Default |
|---|---|
| Uploaded videos and their detections | 30 days |
| Snapshots and clips | 30 days |
| Track points | 14 days |
| Events | 180 days |
| Alerts and notification logs | 365 days |
| Per-minute counts | 2 years (aggregated, no personal data) |
| Audit logs | 365 days |

---

## D. API architecture

### D.1 Conventions

- REST under `/api/v1` (§26). OpenAPI documentation is generated automatically at `/api/docs`.
- **Responses** follow §53–§54 exactly:
  - `{ success, data }` for single results.
  - `{ success, data, pagination }` for lists.
  - `{ success:false, error:{ code, message } }` for errors, which never include stack traces.
- **Filtering:** `?camera_id=&event_type=&severity=&status=&from=&to=&page=&page_size=`
- **Tenant scope:** every endpoint requires a permission and is limited to the caller's organisation.

### D.2 Endpoints

All endpoints listed in §26 are included; the rest are additions.

| Area | Endpoints |
|---|---|
| **Auth** | `POST /auth/register` · `POST /auth/login` · `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me` · `POST /auth/forgot-password` · `POST /auth/reset-password` · `POST /auth/ws-ticket` |
| **Users and roles** | `GET, POST /users` · `GET, PUT /users/{id}` · `POST /users/{id}/deactivate` · `PUT /users/{id}/roles` · `PUT /users/{id}/camera-access` · `GET /roles` |
| **Organisations** (super admin) | `GET, POST /tenants` · `GET, PUT /tenants/{id}` |
| **Sites** | `GET, POST /sites` · `GET, PUT, DELETE /sites/{id}` |
| **Cameras** | `GET, POST /cameras` · `GET, PUT, DELETE /cameras/{id}` · `POST /cameras/test-connection` · `POST /cameras/{id}/test-connection` · `POST /cameras/{id}/start-monitoring` · `POST /cameras/{id}/stop-monitoring` · `GET /cameras/{id}/snapshot` · `GET /cameras/{id}/stream` (short-lived playback URLs) · `GET /cameras/{id}/statistics` |
| **Zones and lines** | `GET, POST /zones` · `GET, PUT, DELETE /zones/{id}` · `GET, POST /lines` · `GET, PUT, DELETE /lines/{id}` · `GET, PUT /cameras/{id}/privacy-masks` |
| **Videos** | `POST /videos/upload` · `GET /videos` · `GET, DELETE /videos/{id}` · `POST /videos/{id}/process` → `{ job_id }` · `GET /videos/{id}/playback` · `GET /videos/{id}/annotated` · `GET /videos/{id}/summary` |
| **Jobs** | `GET /jobs/{id}` · `POST /jobs/{id}/cancel` |
| **Detections and tracks** | `GET /detections?job_id=&from_frame=&to_frame=` · `GET /tracks` · `GET /tracks/{id}` |
| **Events** | `GET /events` · `GET /events/{id}` · `GET /events/{id}/snapshots` (short-lived signed URLs) |
| **Alert rules** | `GET, POST /alert-rules` · `GET, PUT, DELETE /alert-rules/{id}` · `POST /alert-rules/{id}/test` |
| **Alerts** | `GET /alerts` · `GET /alerts/{id}` · `POST /alerts/{id}/acknowledge` · `POST /alerts/{id}/resolve` |
| **Notification channels** | `GET, POST /notification-channels` · `PUT, DELETE /notification-channels/{id}` · `POST /notification-channels/{id}/test` · `GET /notification-logs` |
| **Analytics** | `GET /analytics/overview` · `/analytics/people-count` · `/analytics/entries-exits` · `/analytics/occupancy` · `/analytics/object-distribution` · `/analytics/events` · `/analytics/peak-hours`. Parameters: `from`, `to`, `granularity` (hour/day/week/month), `camera_id`, `site_id` |
| **Reports** | `POST /reports` → `{ report_id }` · `GET /reports` · `GET /reports/{id}/download` |
| **Settings and audit** | `GET, PUT /settings/{section}` · `GET /audit-logs` |
| **System** | `GET /health` · `GET /ready` · `GET /metrics` (internal) · `POST /webhooks/sms/{provider}` (delivery receipts, signature-verified) |

**WebSocket — `/ws?ticket=…` (§27)**
- The client subscribes to topics: `alerts`, `events`, `cameras`, `camera.{id}.live`, `job.{id}.progress`.
- Message types:
  - `person_detected`, `person_entered`, `person_exited`
  - `intrusion_detected`, `crowd_detected`
  - `camera_online`, `camera_offline`
  - `alert_created`, `alert_updated`
  - `processing_progress`, `processing_completed`
- Users can subscribe only to cameras they are allowed to see.
- After a reconnect, the client reloads recent data over REST.

**Error codes (initial set):** `AUTH_INVALID_CREDENTIALS`, `AUTH_TOKEN_EXPIRED`, `PERMISSION_DENIED`, `NOT_FOUND`, `VALIDATION_ERROR`, `RATE_LIMITED`, `CAMERA_CONNECTION_FAILED`, `CAMERA_URL_NOT_ALLOWED`, `VIDEO_FORMAT_UNSUPPORTED`, `VIDEO_TOO_LARGE`, `JOB_ALREADY_RUNNING`, `SMS_PROVIDER_ERROR`, `INTERNAL_ERROR`.

### D.3 Roles and permissions (§25)

| Permission | SUPER_ADMIN | TENANT_ADMIN | SECURITY_MANAGER | OPERATOR | VIEWER |
|---|:-:|:-:|:-:|:-:|:-:|
| Organisation management | ✓ | | | | |
| User management | ✓ | ✓ | | | |
| Camera management (incl. zones and lines) | ✓ | ✓ | ✓ | | |
| Live monitoring | ✓ | ✓ | ✓ | ✓ | |
| Video upload and processing | ✓ | ✓ | ✓ | ✓ | |
| View events | ✓ | ✓ | ✓ | ✓ | ✓ |
| View evidence (snapshots, clips) | ✓ | ✓ | ✓ | ✓ | |
| Rule management | ✓ | ✓ | ✓ | | |
| Alert management (acknowledge, resolve) | ✓ | ✓ | ✓ | ✓ | |
| Reports and analytics | ✓ | ✓ | ✓ | ✓ | ✓ |
| System settings | ✓ | ✓ | | | |
| Audit logs | ✓ | ✓ | ✓ | | |

Roles and permissions are database records, so the table can be changed without code changes.

---

## E. AI pipeline and event architecture

### E.1 Pipeline

```
 Video source    Stream reader       Frame sampling    Preprocessing       Detection           Tracking
 file / RTSP / ─► decode (OpenCV) ─► target FPS,    ─► resize, privacy ─► YOLO: class,    ─► ByteTrack:
 IP camera        reconnect,          frame skip        masks               confidence, box     stable track IDs
                  latest frame only                                                              │
                                                                                                 ▼
 Outputs      ◄────────────── Event detection ◄──────────────── Counting ◄──────────── Track state
 • events → Redis Stream        line crossing, zone entry/exit,   visible now, unique,   trajectory, direction,
 • live overlay → WebSocket     intrusion, crowd, loitering       entries, exits,        current zone, dwell
 • snapshots → storage                                            occupancy
 • per-minute counts
```

### E.2 Stages

**1. Video source and reader** (§8, §9)
- `VideoSource` implementations: `FileSource` (MP4, AVI, MOV, MKV), `RtspSource` and `HttpSource` (IP camera). New source types plug into the same interface (§8D).
- The reader runs in its own thread using OpenCV's FFmpeg backend, with TCP transport and connection and read timeouts.
- **Live cameras:** only the newest frame is kept. If inference is slower than the camera, frames are skipped rather than falling behind real time.
- **Files:** every frame is read in order.
- **Lost connection:** the reader retries with increasing delay (1 s up to 30 s). `CAMERA_OFFLINE` is raised after a configurable grace period (default 30 s), and `CAMERA_ONLINE` on recovery.
- If the camera offers a lower-resolution sub-stream, analysis uses it. Decoding is then much cheaper, and the main stream is kept for evidence.

**2. Frame sampling and preprocessing**
- Settings are configurable per camera (§9): FPS, frame skip, resolution, confidence threshold, IoU threshold and detection classes.
- The default inference rate for live cameras is 8 frames per second.
- Privacy masks are applied before analysis or storage.

**3. Detection**
- Each detection carries class, confidence, bounding box, frame number, timestamp and camera ID (§10).
- Default classes: person, bicycle, car, motorcycle, bus, truck, dog, cat, backpack, handbag, suitcase.
- *Vehicle* is available as a group (car, truck, bus, motorcycle).

**4. Tracking** (§11)
- ByteTrack assigns the same ID to the same object across frames, which prevents double counting.
- A track counts only after it has been confirmed over several frames, which filters one-frame false detections.
- Each track records:
  - first seen and last seen
  - current and previous position
  - trajectory
  - class (majority vote over the track's history, so it does not flicker)
  - current zone
  - direction
  - status
- Position is measured at the **bottom-centre of the box**, where a person or vehicle meets the ground. This makes line and zone checks match what you draw on the floor.

**5. Counting** (§12)
- **Visible now** per class.
- **Unique objects** per class over a period.
- **Entries and exits** from line crossings.
- **Occupancy** = entries − exits since the daily reset, never below zero, with a manual reset option.
- Per-minute totals are written to `count_aggregates`.

**6. Line crossing** (§13)
- A crossing is recorded when the movement between two consecutive positions **intersects the drawn line segment**.
- The direction (IN or OUT) comes from which side of A→B the object moved to.
- **Anti-jitter:** the object must stay on the new side for 2 samples and move beyond a small tolerance. Someone standing on the line does not trigger repeated counts.
- Each track–line pair remembers its last crossing, so the same crossing is never counted twice.
- Output: `LINE_CROSSED` with direction, plus `PERSON_ENTERED` or `PERSON_EXITED` for people.

**7. Zones** (§14–§17)
- **Point-in-polygon** test on the track's position.
- **Entry and exit:** an object counts as entered after being inside for a few consecutive samples. It counts as exited after being outside for a few samples, or after being lost for a set time.
- **Intrusion:** a class not allowed in a `RESTRICTED` zone enters it → `INTRUSION_DETECTED`, once per visit.
- **Dwell and loitering:** time inside exceeds `max_dwell_seconds` → `LOITERING_DETECTED`, once per visit.
- **Crowd:** people in the zone or frame exceed `max_people` for a minimum duration → `CROWD_DETECTED`, once per episode. It re-arms only after the count drops back below the threshold, so a count hovering near the limit does not trigger repeatedly.
- `OBJECT_COUNT_THRESHOLD` applies the same logic to any class.

### E.3 Event types (§19) and default severity (§65)

| Event | When | Default severity |
|---|---|---|
| `PERSON_DETECTED` / `OBJECT_DETECTED` | A new confirmed track appears (once per track, not every frame) | INFO |
| `LINE_CROSSED` | A track crosses a line | INFO |
| `PERSON_ENTERED` / `PERSON_EXITED` | A person crosses an entry line IN / OUT | LOW |
| `ZONE_ENTERED` / `ZONE_EXITED` | An object enters or leaves a zone | LOW |
| `INTRUSION_DETECTED` | A restricted zone is entered | HIGH (CRITICAL when the zone is set to critical) |
| `CROWD_DETECTED` | The people threshold is exceeded | MEDIUM |
| `LOITERING_DETECTED` | Dwell time is exceeded | MEDIUM |
| `OBJECT_COUNT_THRESHOLD` | An object count is exceeded | MEDIUM |
| `CAMERA_OFFLINE` / `CAMERA_ONLINE` | The stream is lost / restored | HIGH / INFO |
| `PROCESSING_STARTED` / `_COMPLETED` / `_FAILED` | Video job lifecycle | INFO / INFO / MEDIUM |

### E.4 Event → rule → alert → notification (§18, §22, §64)

```
 Stream service / job worker                Event worker
 ───────────────────────────                ─────────────────────────────────────────────────────
 EventDetector ─► Event ──► Redis Stream ──► EventProcessor   (one database transaction)
 (knows nothing about rules or SMS)            1. store event (idempotent)
                                               2. RuleEngine: find matching active rules
                                               3. cooldown / duplicate check (Redis)
                                               4. create alert, or add to the open one
                                               5. queue notifications (notification_logs = PENDING)
                                             then:
                                               • push alert_created / event over WebSocket
                                               • NotificationManager ─► SMSProvider.send_sms()
                                                   retry temporary failures; record SENT / FAILED
                                                   provider delivery receipt ─► DELIVERED
```

**Alert rules (§18)** are structured forms, not code:

```
WHEN   event type           e.g. INTRUSION_DETECTED
IF     camera, zone, line, object type, threshold, minimum duration, days, time window
THEN   create alert (severity) · capture snapshot · notify channels (SMS, dashboard)
WITH   cooldown period and duplicate scope
```

**Preventing duplicate SMS (§22)** works at three levels:

1. **Event level:** intrusion, loitering and zone entry are raised once per visit, and crowd once per episode.
2. **Alert level:**
   - A cooldown key per rule and scope (track, zone or camera; default **zone**) blocks repeats within the cooldown period (default 60 s).
   - While an alert is open, repeat matches **increase its occurrence count** instead of creating new alerts.
3. **Notification level:** a per-recipient hourly SMS limit guards against alert storms. Messages blocked by the limit are logged as `SUPPRESSED`.

**Result:** the same person, camera, zone and event within 60 seconds produces **one SMS**, and the dashboard shows how many times it occurred.

**SMS (§20–§21)**
- `SMSProvider.send_sms(phone_number, message)` is implemented for Twilio, MSG91, AWS SNS and a console provider for development, chosen by `SMS_PROVIDER`.
- Provider credentials exist only in backend environment variables.
- Phone numbers are validated in international format and masked in logs and the UI (`+91XXXXXX1234`).
- The default template follows §21:

```
AI Surveillance Alert
Severity: CRITICAL
Camera: Camera 01
Location: Room 101
Event: Unauthorized Person Entry
Time: 10:42 AM
Please check the surveillance dashboard.
```

### E.5 Uploaded videos (§62)

- They use the same pipeline as live cameras, but every frame is read.
- Progress is pushed about once a second over WebSocket (§46): percentage, frames processed and total, FPS, elapsed time and estimated time remaining.
- Cancellation takes effect between frame batches.
- Outputs:
  - detections
  - tracks
  - events with their position in the video
  - a count summary
  - an annotated MP4 (H.264)

### E.6 Performance (§51)

- **Capacity needed** = cameras × inference FPS. For example, 4 cameras at 8 FPS need 32 detections per second.
- A benchmark script (Step 8) measures what your hardware can actually sustain on CPU and GPU.
- **Levers:**
  - sub-streams
  - frame skipping
  - smaller models on CPU
  - GPU with half precision
  - **batching frames from several cameras** into one GPU call (Step 23)
- **Live metrics:**
  - inference FPS
  - detection latency
  - dropped frames
  - end-to-end delay from frame to alert
- **Targets, to be verified in Steps 12–14:** under 2 seconds from event to dashboard, and under 5 seconds from event to SMS hand-off to the provider. Carrier delivery time is outside the system's control.

### E.7 Extension points (§67)

- New AI capabilities plug in as a `FrameAnalyzer` stage in the pipeline without changing the rest of the system. Examples: pose, PPE/helmet, fire/smoke, licence plates, face blurring, fall detection.
- Some future rules reuse existing building blocks:
  - *Wrong-direction detection* is a line crossing in a disallowed direction.
  - *Abandoned object* is a stationary bag with no person nearby for a set time.

---

## F. Frontend page map (§29–§41)

| Route | Purpose | Main contents |
|---|---|---|
| `/login`, `/register`, `/forgot-password`, `/reset-password` | Authentication | Accessible forms, validation, clear error messages |
| `/dashboard` | What is happening right now | Total, online and offline cameras; people now; vehicles now; current occupancy; today's entries and exits; open critical alerts; recent events; system health |
| `/monitoring` | Live camera grid | 1/4/9/16 layouts; LIVE/OFFLINE badges; overlays for boxes, track IDs, labels, confidence, zones, lines and alerts (each toggleable); a tile flashes on alert; click to enlarge |
| `/cameras` | Camera list | Status, location, last seen, monitoring on/off; **Add camera** wizard: details → connection → test → save |
| `/cameras/[id]` | Camera details | Information, live stream, connection status, resolution, FPS, location, zones, lines, detection statistics, recent events |
| `/cameras/[id]/configure` | Zone and line editor (§34–§35) | Draw, move, resize, delete and rename polygons; set zone type and alert; draw line A→B with IN/OUT/BOTH; privacy masks; detection settings |
| `/videos` | Video upload and list | Drag-and-drop upload with progress; processing status |
| `/videos/[id]` | Video analysis (§32–§33) | Original and annotated playback; detection timeline; object counts; events (click to jump to that moment) |
| `/events`, `/events/[id]` | Event timeline and details (§37) | Filterable timeline. Details: snapshot, video evidence, track path, camera, zone, time, alert history |
| `/alerts` | Alert management (§36) | Severity, event, camera, location, time, status, acknowledged by; filters; acknowledge and resolve |
| `/alert-rules`, `/alert-rules/[id]` | Rule builder (§18) | WHEN / IF / THEN form; schedule; SMS recipients; cooldown; test |
| `/analytics` | Charts (§38) | People per hour, entries vs exits, occupancy, object distribution, events by type and camera, peak hours, daily/weekly/monthly trends |
| `/reports` | Reports (§39) | Daily, weekly, monthly, camera, incident and people-count reports; CSV and PDF export |
| `/users`, `/users/[id]` | User management (§40) | Create, edit, deactivate; assign role, camera access and notification number |
| `/settings/[section]` | System settings (§41) | Organisation, users, AI configuration, detection thresholds, camera defaults, notifications, SMS provider (status and test message), alert settings, security, audit logs |
| `/tenants` | Organisations (super admin) | Create and manage organisations |

**Design (§28, §71)**
- A dark-first security-operations style with a light theme option.
- Severity colours are used only for severity: CRITICAL red, HIGH orange, MEDIUM amber, LOW blue, INFO grey.
- Critical alerts show in a **persistent banner** until acknowledged, with an optional browser notification.
- Every alert answers *what, where, when, how severe and what to do*.

**Accessibility (§72)**
- WCAG 2.2 AA target.
- Full keyboard navigation.
- ARIA labels, plus live announcements for new critical alerts.
- Severity is shown with text and an icon, never colour alone.
- Accessible tables and forms.

---

## G. User workflows

### G.1 End-to-end workflow (§61)

```
REGISTER ─────────────── organisation + admin account created · audit: user.register
LOGIN ────────────────── access token (memory) + refresh cookie
DASHBOARD ────────────── empty-state checklist guides setup
ADD CAMERA ───────────── name, site (Building A / Room 101), RTSP details · credentials encrypted
TEST CAMERA CONNECTION ─ worker connects (15 s timeout) → codec, resolution, FPS, preview frame
VIEW LIVE STREAM ─────── MediaMTX → WebRTC player
CONFIGURE ZONE ───────── draw "Room 101" polygon, type RESTRICTED, allowed objects: none
CONFIGURE LINE ───────── draw "Entrance Line" A→B, direction IN
CREATE ALERT RULE ────── WHEN INTRUSION_DETECTED · IF Camera 01 + Room 101 + person
                         THEN CRITICAL alert + snapshot + SMS · cooldown 60 s
SELECT SMS RECIPIENT ─── add +91XXXXXXXXXX · send test SMS
START MONITORING ─────── stream service picks up the camera → CAMERA_ONLINE
AI DETECTION ─────────── person detected
OBJECT TRACKING ──────── Track ID 101 assigned and followed
EVENT DETECTION ──────── LINE_CROSSED (IN) · PERSON_ENTERED · INTRUSION_DETECTED + snapshot
RULE MATCH ───────────── rule matched · cooldown free
ALERT CREATED ────────── CRITICAL alert stored
SMS SENT ─────────────── via configured provider · delivery status recorded
EVENT STORED ─────────── events, snapshots, track stored
DASHBOARD UPDATED ────── WebSocket → banner, monitoring tile flash, browser notification
AUDIT LOG CREATED ────── e.g. alert.acknowledge, evidence.view when the operator responds
```

### G.2 Video upload workflow (§62)

```
UPLOAD ──► VALIDATE (extension, size, file signature, FFprobe: format, codec, duration)
       ──► STORE (StorageProvider) ──► CREATE JOB (QUEUED) ──► API returns { job_id }
       ──► WORKER PICKS JOB (PROCESSING) ──► OPEN VIDEO ──► READ FRAME ──► DETECT ──► TRACK
       ──► UPDATE COUNTS ──► CHECK ZONES ──► CHECK LINES ──► CHECK RULES ──► CREATE EVENTS
       ──► STORE METADATA ──► GENERATE ANNOTATED VIDEO ──► COMPLETED ──► DISPLAY RESULTS
           (progress streamed to the browser throughout; FAILED / CANCELLED handled)
```

### G.3 Status lifecycles

```
Alert:   OPEN ──acknowledge──► ACKNOWLEDGED ──resolve──► RESOLVED
         (repeats while OPEN raise occurrence_count; CAMERA_ONLINE auto-resolves CAMERA_OFFLINE)

Job:     QUEUED ──► PROCESSING ──► COMPLETED | FAILED | CANCELLED

Camera:  UNKNOWN ──test──► monitoring started ──► ONLINE ⇄ OFFLINE (auto-reconnect) ──► DISABLED
```

---

## H. MVP and future scope

### H.1 MVP — the five phases in §68

| Phase | Capabilities | Delivered in steps |
|---|---|---|
| **1** | Authentication, dashboard, video upload, object and person detection, tracking, people counting, video annotation, event detection | 4–10, 15, 16, 18 |
| **2** | RTSP cameras, live monitoring, zone detection, line crossing, entry/exit | 7, 8, 11, 17 |
| **3** | Alert rules, SMS, WebSocket, real-time dashboard | 12–14, 16 |
| **4** | Analytics, reports, multi-tenancy, RBAC, audit logs | 4–6 (built into the foundations), 19 |
| **5** | Docker, cloud deployment, GPU processing, horizontal scaling, monitoring | 21–24 |

When all five phases are complete, every success criterion in §76 is met.

### H.2 Future scope (designed for, not built now)

| Item | Extension point |
|---|---|
| Pose, vehicle classification, licence plates, face detection and **face blurring**, fall, fire/smoke, PPE/helmet, abandoned object, wrong direction, unusual activity (§67) | `FrameAnalyzer` stage and `classifier.py` |
| BoT-SORT with re-identification; tracking across cameras | `ObjectTracker` interface |
| Email, WhatsApp, push and voice alert channels; escalation rules | Notification channel types |
| ONVIF camera discovery, PTZ control, NVR integration | `VideoSource` interface |
| On-site edge service for cloud deployments (cameras on private networks) | Stream service already runs separately |
| Two-factor authentication and single sign-on | Auth service |
| Native mobile apps | REST and WebSocket APIs |

**Not planned:** facial recognition or identity matching (§50).

---

## I. Development roadmap (§69)

The roadmap follows the 24-step sequence in your brief, one module at a time. Each step builds on the previous one and ends with a short demo, after which I wait for your go-ahead.

**Two practical points:**
- **Tests and Docker are not left to the end.** Each step includes its own tests. Step 20 adds full integration and end-to-end coverage. A basic `docker-compose.yml` for PostgreSQL, Redis and Mailpit exists from Step 3, because development needs them; Step 21 completes containerisation.
- **No UI before Step 15.** The frontend starts at Step 15, as in your sequence, so Steps 5–14 are demonstrated through the interactive API docs (`/api/docs`), command-line scripts and tests.

| Step | Module | Deliverables | Done when |
|---|---|---|---|
| 1 | Analyse requirements | §1 of this document | ✅ Done |
| 2 | Architecture | This document | ✅ On your approval |
| 3 | Repository structure | Monorepo layout (§B); tooling (uv, Ruff, mypy, pytest; npm, ESLint, Prettier, Vitest); pre-commit; CI; `.env.example`; basic Compose (PostgreSQL, Redis, Mailpit); docs skeleton | Empty test suites pass; `docker compose up postgres redis` works |
| 4 | Database schema | SQLAlchemy models and first Alembic migration for every table in §C; tenant isolation policies; partitions; indexes; seeded roles and permissions | `alembic upgrade head` and `downgrade` work; tenant-isolation test passes |
| 5 | Backend foundation | FastAPI app; configuration; database sessions with tenant context; repository base; response envelopes; error handling; structured logging; `/health`, `/ready`; CORS; security headers; rate limiting | Errors match §53; logs are JSON with request IDs |
| 6 | Authentication | Register, login, refresh, logout, profile, forgot/reset password (email via Mailpit); RBAC checks; audit logging; super-admin creation script | Auth, RBAC and cross-tenant tests pass |
| 7 | Camera and video management | Sites; camera CRUD with encrypted credentials; URL validation; connection test; storage providers (local, S3/MinIO); video upload and validation; Celery; processing jobs, status, cancel | Camera tested against the RTSP simulator; upload → job → completed |
| 8 | AI detection engine | `DetectionModel` + YOLO adapter; ModelManager (CPU/GPU); video sources, reader, processor, pipeline; stream service (start/stop monitoring, reconnect, online/offline); `analyze_video.py` CLI; benchmark | CLI prints detections for a sample clip; live pipeline runs on the simulator; benchmark FPS recorded |
| 9 | Tracking engine | `ObjectTracker` + ByteTrack; track state; counting; storage of detections, tracks and track points; annotated MP4 export | A person keeps one ID across frames; correct counts; annotated MP4 plays in a browser |
| 10 | Event engine | Event types; EventDetector; event processor (Redis Streams → database); snapshots; crowd and object-count thresholds | Events and snapshots stored for a sample clip; a redelivered event is not duplicated |
| 11 | Zones and lines | Zone and line APIs; line crossing with direction; entry/exit and occupancy; zone entry/exit; intrusion; loitering | Geometry edge cases tested; IN/OUT counts on a sample clip match a manual count |
| 12 | Alert engine | Alert rule API; rule engine (filters, thresholds, days and hours, severity); cooldown and duplicate control; alert acknowledge/resolve | One matching event creates exactly one alert; schedule and cooldown tests pass |
| 13 | SMS integration | Notification channels; `SMSProvider` with Twilio, MSG91, AWS SNS and console; templates; retries; rate limits; delivery webhooks; test SMS | 20 matching events in 60 s → 1 SMS; a real SMS reaches your phone |
| 14 | WebSocket system | Tickets; connection manager; topics; Redis fan-out; job progress; live counts and overlay; alert events | A test client receives events and progress live; topic permissions enforced |
| 15 | Frontend foundation | Next.js app; Tailwind theme (dark/light); UI components; layout; auth pages; Redux store and §42 slices; API layer; WebSocket client; route protection | Register → login → app shell; silent token refresh; viewers blocked from admin pages |
| 16 | Dashboard | KPI cards; live alert feed; recent events; system health; alerts page; events pages; rule builder; critical banner; browser notifications | Dashboard updates live, without a refresh, when an event fires |
| 17 | Live monitoring | MediaMTX integration; WebRTC/HLS player; camera grid with overlays; camera list and details; add-camera wizard; zone and line editor; privacy masks | Success criteria 2–9 and 19 in §76 work end to end in the UI |
| 18 | Video analysis UI | Upload with progress; status; original and annotated playback; detection timeline; counts; events list | §32 page complete for a sample clip |
| 19 | Analytics | Per-minute aggregates; analytics API; charts; CSV and PDF reports; user, settings and audit-log pages; retention jobs; organisation management | Charts match raw event counts; exports download correctly |
| 20 | Tests | Integration suite (real PostgreSQL and Redis); API coverage; Playwright end-to-end run of the §76 flow; accuracy evaluation script; CI quality gates | Full §76 flow passes automatically |
| 21 | Dockerise | Production images (API, worker CPU/GPU, frontend); full Compose with nginx, MediaMTX, RTSP simulator and optional MinIO; GPU override | Fresh clone → `docker compose up` → working app |
| 22 | Security review | OWASP checklist; dependency, image and secret scans; RBAC and tenant-isolation review; fixes | No open high-severity findings |
| 23 | Performance | GPU processing; multi-camera batching; frame-rate tuning; caching; query and index review; load test with simulated cameras; multiple stream-service instances | Capacity documented for your hardware |
| 24 | Documentation | README, ARCHITECTURE, API, DATABASE, AI_PIPELINE, DEPLOYMENT (local + cloud), SECURITY, DEVELOPMENT; Prometheus/Grafana monitoring | A new developer can set up and run everything from the docs |

**What you will need along the way**

| Item | Needed by |
|---|---|
| A few short sample videos (people walking through a doorway, cars). You can record your own | Step 8 |
| An IP/CCTV camera with RTSP, or a phone camera app that streams RTSP (the simulator covers development) | Step 17 |
| An SMS provider account (Twilio, MSG91 or AWS SNS) | Step 13 |
| An NVIDIA GPU (optional; CPU works for development) | Step 23 |

---

## J. Security and privacy architecture (§48–§50)

### J.1 Threats and controls

| Threat | Controls |
|---|---|
| One organisation seeing another's data | Tenant taken from the token only; filtered repositories; PostgreSQL Row-Level Security; isolation tests on every endpoint |
| Camera credential theft | AES-256-GCM encryption with a key from environment variables (a cloud key vault in production); never returned by the API (§49); decrypted only inside the worker; RTSP URLs removed from logs and error messages |
| Session theft | 15-minute access tokens; rotating refresh tokens with reuse detection; httpOnly, Secure, SameSite cookies; one-time WebSocket tickets |
| Password guessing | Rate limits per IP and account; Argon2id hashing; generic login errors |
| Abuse of the camera URL field (making the server call internal addresses) | Allowed schemes only (`rtsp`, `rtsps`, `http`, `https`); loopback and cloud-metadata addresses blocked; optional allowed-network list |
| Malicious video files | Size limits; file-signature and FFprobe checks; processing in a locked-down container (non-root, read-only filesystem) |
| Evidence leakage | Private storage; short-lived signed URLs; evidence permission; every view and download audited |
| Fake SMS delivery callbacks | Provider signature verification |
| Vulnerable dependencies | Lock files; automated update PRs; `pip-audit`, `npm audit`; container image scanning; secret scanning in CI |
| Web attacks (XSS, clickjacking) | React escaping; Content Security Policy; HSTS; framing disabled; CORS limited to the app's own origin |
| Information leaks in errors | Central error handler with no stack traces; phone numbers masked; no tokens, passwords or URLs in logs |

Secrets live only in `.env`, which is git-ignored, or in a secret manager. `.env.example` contains placeholders only (§48, §57).

### J.2 Privacy controls (§50)

- **No facial recognition.** Track IDs are temporary and never linked to a person's identity.
- **Privacy masks** black out sensitive areas before anything is stored or shown.
- **Minimal recording:** there is no continuous recording by default; only event snapshots and short clips are kept.
- **Retention:** configurable retention with automatic deletion (§C.4). Deletions are logged.
- **Access control:**
  - role-based permissions
  - camera-level access per user
  - a separate evidence permission
  - audit logs of who viewed what
- **Legal advice:** if the platform is ever deployed for an organisation or offered commercially, get legal advice on data protection obligations (in India, the Digital Personal Data Protection Act, 2023).

---

## K. Deployment architecture

### K.1 Local development — `docker compose up` (§56, §58)

| Service | Purpose |
|---|---|
| `nginx` | Single entry point for the frontend, API, WebSocket and video |
| `frontend` | Next.js with hot reload |
| `backend` | FastAPI with auto-reload |
| `worker` | Celery job worker |
| `stream-service` | Live camera processing |
| `event-worker` | Event processor and notification dispatcher |
| `postgres`, `redis` | Database and message broker |
| `mediamtx` | Camera stream relay |
| `rtsp-simulator` | Streams a sample video as a fake camera |
| `mailpit` | Captures password-reset emails in development |
| `minio` *(optional)* | S3-compatible storage for testing the S3 provider; the local filesystem is the default |

- `docker-compose.gpu.yml` enables an NVIDIA GPU for the workers.
- **Without Docker,** `DEVELOPMENT.md` documents:
  - `uv run uvicorn …` (API)
  - `uv run celery …` (worker)
  - `npm run dev` (frontend)
  - PostgreSQL and Redis from Docker or a local install
- **Windows note:** Celery's default process pool does not support Windows, so non-Docker Windows development uses `--pool=solo`. Docker Desktop avoids this.

### K.2 Single-server deployment

```
Same network as the cameras
┌───────────────────────────────────────────────────────────────────┐
│ nginx (TLS) · frontend · backend · event-worker                   │
│ postgres (daily backups) · redis (persistence on)                 │
│ mediamtx · stream-service · worker      (GPU used if present)     │
│ object storage: local disk or S3                                  │
│ Cameras ──RTSP──► mediamtx                                        │
└───────────────────────────────────────────────────────────────────┘
Remote access through a VPN or secure tunnel. Cameras are never exposed to the internet.
```

### K.3 Cloud deployment (Phase 5)

```
Camera site                                 Cloud (AWS or Azure)
┌──────────────────────────────┐           ┌───────────────────────────────────────────┐
│ Cameras ─► on-site service   │ outbound  │ Load balancer ─► frontend, backend        │
│   mediamtx + stream-service  │ TLS only  │ event-worker · workers (GPU instances)    │
│   (AI runs on site)          │──────────►│ managed PostgreSQL · managed Redis        │
│                              │ events,   │ S3 / Azure Blob · secrets manager         │
│                              │ snapshots,│ Prometheus / Grafana or cloud monitoring  │
│                              │ live view │                                           │
└──────────────────────────────┘           └───────────────────────────────────────────┘
```

- **Horizontal scaling:**
  - API: more backend instances behind the load balancer.
  - Live cameras: more stream-service instances, which share cameras automatically through leases.
  - Uploaded videos: more Celery workers.
  - Database: PostgreSQL scales up, with a read replica for analytics.
- **Monitoring (§52):** structured logs, plus Prometheus metrics for:
  - CPU, RAM and GPU
  - camera status
  - queue length
  - inference FPS
  - detection latency
  - API latency
  - failed jobs
  - SMS failures

---

## L. Risks and open questions

### L.1 Risks

| Risk | Mitigation |
|---|---|
| Counting is less accurate on real cameras (angle, occlusion, low light, night IR) | Camera placement guidance; evaluation script on your own footage; confirmed-track filtering; anti-jitter; adjustable thresholds |
| False alerts and unnecessary SMS | Minimum durations; cooldowns; occurrence counts; SMS rate limits |
| CPU-only hardware is too slow for several cameras | Small models; sub-streams; lower inference FPS; benchmark early (Step 8) |
| Camera variety (H.265, authentication types, vendor-specific RTSP behaviour) | FFmpeg-based reading; early testing with your actual camera (Step 17) |
| SMS delivery rules for Indian numbers | Console provider during development; check your chosen provider's current India rules before Step 13 |
| Large overall scope | Step-by-step delivery with a demo and approval after each step |

### L.2 Questions for you

1. **Hardware:** does your machine have an NVIDIA GPU? If so, which one? This sets the default model size and frame rate.
2. **Cameras:** do you have an RTSP/IP camera to test with? Which make and model?
3. **SMS:** which provider do you prefer (Twilio, MSG91 or AWS SNS), and will recipients be Indian numbers?
4. **Frontend timing:** keep your sequence (UI from Step 15), or start the frontend right after Step 6 so you can see screens sooner?
5. **Phase 5 target:** AWS, Azure, or local/self-hosted only?

**If these stay open, I will use these defaults:**
- CPU development with GPU support ready.
- The RTSP simulator in place of a real camera.
- The console SMS provider, plus Twilio as the first real provider.
- Your step order as written.
- A provider-neutral setup for Phase 5.

---

## Appendix — Main third-party components

| Component | Use | Licence |
|---|---|---|
| FastAPI, Pydantic, SQLAlchemy, Alembic | Backend | MIT |
| Celery | Background jobs | BSD-3-Clause |
| PostgreSQL | Database | PostgreSQL Licence |
| Redis | Broker, streams, cache | Free for self-hosted use (7.2: BSD; 7.4+: RSALv2/SSPLv1; 8.x adds an AGPLv3 option) |
| OpenCV | Video and image processing | Apache-2.0 |
| PyTorch | Deep learning runtime | BSD-3-Clause |
| Ultralytics YOLO | Object detection | AGPL-3.0 (a commercial licence is available) |
| ByteTrack | Multi-object tracking | MIT |
| MediaMTX | RTSP → WebRTC/HLS relay | MIT |
| FFmpeg | Encoding the annotated MP4 | LGPL/GPL depending on build |
| Next.js, React, Redux Toolkit, Tailwind CSS, Recharts | Frontend | MIT |
| hls.js | HLS playback | Apache-2.0 |
| MinIO (optional) | S3-compatible development storage | AGPL-3.0 |
| Mailpit | Development email capture | MIT |

Licences matter mainly if you publish or sell the platform. For personal use, every component above is free to use.
