# Sahayam — ML-Assisted Disaster Coordination Platform

A working prototype built for the Kerala flood-response use case described in the project SRS:
a FastAPI + ML backend doing real request triage and auth, wired live to a single-file React
ops console.

```
sahayam-full/
├── backend/           FastAPI + ML triage engine + auth (REST API, SQLite)
└── frontend/           index.html — the Sahayam Ops React console (citizen / admin / volunteer)
```

## Quick start (both pieces, connected)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open **`http://localhost:8000/`** in a browser. The backend serves `frontend/index.html`
directly at that URL, so the frontend's API calls are same-origin and everything just works —
no separate frontend server, no CORS setup needed.

**Important: don't just double-click `frontend/index.html`.** Opening it directly as a local
file (a `file://` URL) means it has no backend to talk to — the header will show **API OFFLINE**,
login will fail (there's nothing at `/api/auth/login` to reach), and no real hotspots or ML
triage will run. You must run the backend (`uvicorn main:app`, above) and open the page through
`http://localhost:8000/`, not by opening the file itself.

On first load, if the database is empty, the frontend automatically seeds it with an 8-request
demo scenario (posted through the real `POST /api/requests` endpoint, so it runs through the
actual ML triage engine and the real hotspot detector, not canned data — four of the eight seed
requests are a deliberate tight cluster in Aluva so a real hotspot is visible immediately). A
small **API LIVE / API OFFLINE** indicator in the header shows whether the frontend is actually
talking to the backend — check this first if login or hotspots don't seem to work.

### Demo logins

The Admin and Volunteer consoles require signing in (citizen request intake stays open to
everyone — no login to ask for help). Seeded on first run:

| Role      | Username | Password       | Name          |
|-----------|----------|----------------|---------------|
| Admin     | `admin`  | `admin123`     | Admin         |
| Volunteer | `arjun`  | `volunteer123` | Arjun Menon   |
| Volunteer | `divya`  | `volunteer123` | Divya Pillai  |
| Volunteer | `rahul`  | `volunteer123` | Rahul Varma   |

These are seeded straight into the database on first startup (see `DEFAULT_USERS` in
`backend/main.py`) — change or remove them there for anything beyond a demo.

## backend/ — FastAPI + ML triage engine + auth

- `main.py` — FastAPI app. Endpoints:
  - `POST /api/requests` — submit a help request, **open to everyone** (runs ML triage, pushes
    to priority queue)
  - `GET /api/requests` — list requests, priority-ordered, public read
  - `GET /api/requests/next` — pop the highest-priority request and mark it dispatched (admin only)
  - `PATCH /api/requests/{id}` — update a request's `status` / `assigned_to` (**login required**;
    admins can update/reassign anything, volunteers can only update a request already assigned
    to them, and can't reassign it to someone else)
  - `POST /api/requests/{id}/claim` — a **volunteer** self-assigns an unclaimed request to
    themselves; 409 if someone already claimed it first
  - `GET /api/hotspots` — DBSCAN-clustered hotspot zones (real coordinates, public read)
  - `GET /api/stats` — summary counters
  - `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` — session auth
  - `GET /api/volunteers` — volunteer roster (name + base location); **login required**, since
    volunteer identities/locations aren't public
  - also serves `frontend/index.html` as static content at `/`
- `auth.py` — password hashing (PBKDF2-HMAC-SHA256, salted) and an in-memory session-token
  store. Sessions reset on server restart by design — this is a prototype-grade auth layer, not
  production-hardened (no JWT/refresh tokens, no rate limiting); see the code comment for what a
  production version would change.
- `ml_engine.py` — `UrgencyTriageEngine`: TF-IDF + Logistic Regression text-severity classifier,
  rule-based vulnerability scoring (elderly / children / medical need), DBSCAN hotspot
  clustering, and a weighted urgency score (`0.55·text + 0.30·rules + 0.15·hotspot`).
- `priority_queue.py` — max-heap priority queue (`heapq` with negated scores, lazy deletion).
- `database.py` — SQLAlchemy models: `HelpRequest` and `User` (admin/volunteer logins), backed
  by SQLite (`sahayam.db`, created on first run).
- `seed.py` — optional standalone CLI script that posts 8 demo requests to a running API; not
  needed for the normal flow since the frontend seeds itself, but useful for re-seeding via
  `python seed.py` after wiping `sahayam.db`.

Request lifecycle status values used throughout: `pending → assigned → en_route → on_site →
resolved` (the frontend's five-step volunteer workflow; the backend stores whatever string it's
given, so this list is enforced by the frontend, not the database).

## frontend/ — Sahayam Ops

`index.html` is a single-file React 18 app (loaded via CDN + Babel-standalone, no build step).
It talks to the backend over `fetch()`:

- **Citizen intake** — tries the browser's real geolocation first (`navigator.geolocation`) so
  reporters don't have to find themselves on a map; if location access is denied, times out, or
  isn't supported, it falls back to tap-to-pin on the real Kerala district map (also available
  any time to adjust/correct the detected location). Submitting `POST`s straight to
  `/api/requests`; the confirmation screen shows the **real ML-assigned priority and queue
  position** returned by the backend, not a client-side guess (a live text-based estimate is
  shown while typing, for feedback, but the backend's classification is what's actually stored).
- **Admin console** (login required) — live metrics, a priority-ordered request queue polled
  from the backend every 5 seconds, manual request injection (also goes through real ML triage —
  admins pick vulnerability flags, not a priority label), one-click volunteer assignment, and
  district threat-level management (this last piece is frontend-only, see below).
- **Volunteer console** (login required) — two lists: **Nearby Requests** (unclaimed pending
  requests, closest to the signed-in volunteer's base location first, each with a "Claim this
  request" button so volunteers pick their own work) and **My Tasks** (whatever they've claimed
  or been assigned, with one-click status progression `Assigned → En Route → On Site →
  Resolved`, each step `PATCH`ed to the backend immediately). An SMS-payload view replaces task
  cards during the offline-fallback simulation.
- **Real hotspots on the map** — the map overlays the backend's actual DBSCAN-computed hotspot
  clusters (dashed red rings sized by cluster size, polled every 8 seconds from
  `GET /api/hotspots`) on top of the real Kerala district geography, alongside per-district
  severity coloring and live request markers. A hotspot only appears once 3+ open requests fall
  within ~1.5km of each other, so it won't show up on a near-empty database — the auto-seeded
  demo data includes a real 4-request cluster for exactly this reason.
- **Click-to-zoom district map** — on the admin and volunteer maps, clicking a district now
  smoothly zooms the map into that district's shape (computed from its actual SVG bounding box,
  with padding, animated via a CSS transform) instead of just dimming/filtering everything else
  at the same fixed zoom level. Hotspot rings, labels and request markers stay legible at the
  zoomed scale (counter-scaled strokes/text) so a cluster and its critical markers are clearly
  visible up close. Click the "Zoomed — District ✕" chip to animate back out to the full map.
  The citizen tap-to-pin map is unaffected and never zooms.
- **Civic "backwater teal + turmeric" light theme** — the UI is styled to match the original
  Sahayam design system (the same tokens used by the early static prototype's `styles.css`):
  a light, high-legibility palette (`--paper #EEF1E5`, `--brand #14574C`, urgency scale
  `--u-low/medium/high/critical` in green/turmeric/orange/red) built for bright-sunlight,
  low-end-device conditions, set in Manrope (UI) and Noto Sans Malayalam (`[lang="ml"]` /
  `.ml` text). There is a single theme — no dark mode and no theme toggle — replacing an
  earlier dark "monsoon night" ops-console look this file used to ship with.
- **SMS Fallback simulation** — toggling "Online" → "SMS Fallback" tags new submissions with
  `channel: "sms"` (a real field the backend stores and can query on) and switches the
  volunteer view to a simulated SMS payload display — it does not actually disconnect the app
  from the backend, since the point is to demonstrate the channel-tagging UX, not to test
  network failure.
- If the backend can't be reached at all (not running, wrong port), the login screen offers a
  "Continue in offline demo mode" button so the UI can still be demoed standalone (with local
  in-memory data, no real auth), and the header indicator switches to **API OFFLINE**.

To point the frontend at a backend running somewhere other than the same origin, open it with
`?api=http://host:port` in the URL (the backend's CORS is already open to any origin).

## Known simplifications

- **Auth is prototype-grade**: in-memory sessions (reset on server restart), no signup/password
  reset flow, no rate limiting on login attempts. Real password hashing and permission checks
  are in place (see `backend/auth.py` and the role checks in `main.py`'s `PATCH`/`claim`
  endpoints), just not hardened for production.
- **District/zone severity levels** (the admin's "Affected Area Management" panel) live only in
  the frontend's local state — the backend has no districts table. A request's real urgency
  still comes entirely from the backend's ML engine; only the map's decorative district-level
  threat color is client-side.
- **Volunteers are a fixed seeded roster** (3 accounts) rather than a self-service signup flow.
  Assignment is stored on the backend as the volunteer's name in `HelpRequest.assigned_to` (a
  plain string), not a foreign key.
- **SQLite, not PostgreSQL/PostGIS**, and no real SMS/Twilio integration — both called out as
  future work in the SRS.
- Geolocation accuracy depends entirely on the browser/device; in a desktop browser without GPS
  it typically resolves to an IP-based location, not a precise one — tap-to-pin remains
  available to correct it.

This is also documented in the project notes doc saved to the MINI PROJECT workspace.
