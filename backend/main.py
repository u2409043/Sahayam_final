from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import init_db, get_db, HelpRequest, User
from ml_engine import engine as ml_engine, find_hotspots, hotspot_boost_for_point
from priority_queue import queue
from auth import hash_password, verify_password, create_session, get_user_id_for_token, destroy_session

app = FastAPI(title="Sahayam API", description="ML-assisted disaster coordination platform for Kerala")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Seeded demo accounts -- documented in the README. A real deployment would
# have a signup/admin-provisioning flow instead of hardcoded seed logins.
DEFAULT_USERS = [
    dict(username="admin", password="admin123", role="admin", name="Admin", lat=None, lng=None),
    dict(username="arjun", password="volunteer123", role="volunteer", name="Arjun Menon", lat=10.1075, lng=76.3516),
    dict(username="divya", password="volunteer123", role="volunteer", name="Divya Pillai", lat=9.9816, lng=76.2999),
    dict(username="rahul", password="volunteer123", role="volunteer", name="Rahul Varma", lat=9.3833, lng=76.4333),
]


@app.on_event("startup")
def on_startup():
    init_db()
    from database import SessionLocal
    db = SessionLocal()
    try:
        # rebuild the in-memory priority queue from any existing open requests
        open_requests = db.query(HelpRequest).filter(
            HelpRequest.status.in_(["pending", "assigned", "en_route", "on_site", "in_progress"])
        ).all()
        for r in open_requests:
            queue.push(r.id, r.urgency_score, r.created_at.timestamp())

        # seed default admin + volunteer accounts if the users table is empty
        if db.query(User).count() == 0:
            for u in DEFAULT_USERS:
                db.add(User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    name=u["name"],
                    lat=u["lat"],
                    lng=u["lng"],
                ))
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    user_id = get_user_id_for_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user


def require_role(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {' or '.join(roles)}")
        return user
    return _dep


def serialize_user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "name": u.name, "lat": u.lat, "lng": u.lng}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RequestCreate(BaseModel):
    name: str | None = None
    phone: str | None = None
    channel: str = Field(default="app", description="app | whatsapp | ivr | sms")
    language: str = Field(default="ml", description="ml | en")
    description: str
    category: str = "general"
    has_elderly: bool = False
    has_children: bool = False
    has_medical_need: bool = False
    lat: float | None = None
    lng: float | None = None
    location_text: str | None = None


class StatusUpdate(BaseModel):
    status: str | None = None
    assigned_to: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session(user.id)
    return {"token": token, "user": serialize_user(user)}


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        destroy_session(authorization.split(" ", 1)[1].strip())
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return serialize_user(user)


@app.get("/api/volunteers")
def list_volunteers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Admin/volunteer only -- volunteers' names and base locations are not public."""
    vols = db.query(User).filter(User.role == "volunteer").all()
    return [serialize_user(v) for v in vols]


def serialize(r: HelpRequest) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "phone": r.phone,
        "channel": r.channel,
        "language": r.language,
        "description": r.description,
        "category": r.category,
        "has_elderly": bool(r.has_elderly),
        "has_children": bool(r.has_children),
        "has_medical_need": bool(r.has_medical_need),
        "lat": r.lat,
        "lng": r.lng,
        "location_text": r.location_text,
        "urgency_score": r.urgency_score,
        "urgency_label": r.urgency_label,
        "ml_confidence": r.ml_confidence,
        "status": r.status,
        "assigned_to": r.assigned_to,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Request intake + triage
# ---------------------------------------------------------------------------
@app.post("/api/requests")
def create_request(payload: RequestCreate, db: Session = Depends(get_db)):
    # current open requests, for hotspot detection
    open_points = [
        {"id": r.id, "lat": r.lat, "lng": r.lng}
        for r in db.query(HelpRequest).filter(
            HelpRequest.status.in_(["pending", "assigned", "en_route", "on_site", "in_progress"])
        ).all()
    ]
    hotspots = find_hotspots(open_points)
    boost = hotspot_boost_for_point(payload.lat, payload.lng, hotspots)

    result = ml_engine.classify(
        description=payload.description,
        has_elderly=payload.has_elderly,
        has_children=payload.has_children,
        has_medical_need=payload.has_medical_need,
        hotspot_boost=boost,
    )

    r = HelpRequest(
        name=payload.name,
        phone=payload.phone,
        channel=payload.channel,
        language=payload.language,
        description=payload.description,
        category=payload.category,
        has_elderly=int(payload.has_elderly),
        has_children=int(payload.has_children),
        has_medical_need=int(payload.has_medical_need),
        lat=payload.lat,
        lng=payload.lng,
        location_text=payload.location_text,
        urgency_score=result.urgency_score,
        urgency_label=result.urgency_label,
        ml_confidence=result.ml_confidence,
        status="pending",
    )
    db.add(r)
    db.commit()
    db.refresh(r)

    queue.push(r.id, r.urgency_score, r.created_at.timestamp())

    return {
        **serialize(r),
        "triage_breakdown": {
            "text_severity": result.text_severity,
            "rule_score": result.rule_score,
            "hotspot_boost": result.hotspot_boost,
        },
    }


@app.get("/api/requests")
def list_requests(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(HelpRequest)
    if status:
        q = q.filter(HelpRequest.status == status)
    requests = q.all()
    by_id = {r.id: r for r in requests}

    ordered_open_ids = [rid for rid in queue.ordered_ids() if rid in by_id]
    rest_ids = [r.id for r in requests if r.id not in set(ordered_open_ids)]
    ordered = [by_id[i] for i in ordered_open_ids] + [by_id[i] for i in rest_ids]

    return [serialize(r) for r in ordered]


@app.get("/api/requests/next")
def next_request(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Pop the single highest-urgency open request off the dispatch queue."""
    rid = queue.pop()
    if rid is None:
        raise HTTPException(status_code=404, detail="Queue is empty")
    r = db.query(HelpRequest).filter(HelpRequest.id == rid).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    r.status = "assigned"
    r.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(r)
    return serialize(r)


@app.patch("/api/requests/{request_id}")
def update_status(
    request_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Requires login. Admins can update any request's status and reassign
    it to anyone. Volunteers can only update the status of a request already
    assigned to them, and cannot reassign it to someone else -- that's what
    the /claim endpoint is for."""
    r = db.query(HelpRequest).filter(HelpRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")

    if user.role == "volunteer":
        if r.assigned_to != user.name:
            raise HTTPException(status_code=403, detail="This request is not assigned to you")
        if payload.assigned_to is not None and payload.assigned_to != user.name:
            raise HTTPException(status_code=403, detail="Volunteers cannot reassign requests")

    if payload.status is not None:
        r.status = payload.status
    if payload.assigned_to is not None:
        r.assigned_to = payload.assigned_to
    r.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(r)

    if payload.status in ("resolved",):
        queue.remove(request_id)

    return serialize(r)


@app.post("/api/requests/{request_id}/claim")
def claim_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("volunteer")),
):
    """A volunteer picks an unclaimed request to attend to themselves."""
    r = db.query(HelpRequest).filter(HelpRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    if r.assigned_to is not None:
        raise HTTPException(status_code=409, detail=f"Already claimed by {r.assigned_to}")
    r.assigned_to = user.name
    r.status = "assigned"
    r.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(r)
    return serialize(r)


@app.get("/api/hotspots")
def hotspots(db: Session = Depends(get_db)):
    open_points = [
        {"id": r.id, "lat": r.lat, "lng": r.lng}
        for r in db.query(HelpRequest).filter(
            HelpRequest.status.in_(["pending", "assigned", "en_route", "on_site", "in_progress"])
        ).all()
    ]
    return find_hotspots(open_points)


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    all_reqs = db.query(HelpRequest).all()
    total = len(all_reqs)
    by_label = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    by_status = {"pending": 0, "assigned": 0, "in_progress": 0, "resolved": 0}
    for r in all_reqs:
        by_label[r.urgency_label] = by_label.get(r.urgency_label, 0) + 1
        by_status[r.status] = by_status.get(r.status, 0) + 1
    return {
        "total": total,
        "by_urgency": by_label,
        "by_status": by_status,
        "queue_length": len(queue),
    }


# ---------------------------------------------------------------------------
# Frontend static files (served from the same app for a one-command demo)
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
