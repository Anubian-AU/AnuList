import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException, Request, Response
from storage import uid

hasher = PasswordHasher()
SECURE_COOKIE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
SESSION_AGE = 14 * 86400

def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()

def password_hash(value):
    if not 12 <= len(value) <= 128:
        raise HTTPException(422, "Password must be 12–128 characters")
    return hasher.hash(value)

def password_check(stored, supplied):
    try:
        return hasher.verify(stored, supplied)
    except (VerificationError, VerifyMismatchError):
        return False

def expiry(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

def set_session(db, response: Response, user_id):
    token, csrf = secrets.token_urlsafe(36), secrets.token_urlsafe(30)
    db.execute("INSERT INTO sessions VALUES (?,?,?,?)",
               (hashed(token), hashed(csrf), user_id, expiry(14)))
    response.set_cookie("anulist_session", token, max_age=SESSION_AGE, httponly=True,
                        secure=SECURE_COOKIE, samesite="lax", path="/")
    response.set_cookie("anulist_csrf", csrf, max_age=SESSION_AGE, httponly=False,
                        secure=SECURE_COOKIE, samesite="lax", path="/")

def clear_session(response: Response):
    response.delete_cookie("anulist_session", path="/")
    response.delete_cookie("anulist_csrf", path="/")

def authenticate(request: Request, db):
    token = request.cookies.get("anulist_session")
    if not token:
        raise HTTPException(401, "Please sign in")
    session = db.execute("SELECT * FROM sessions WHERE token_hash=?", (hashed(token),)).fetchone()
    if not session or datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent, cookie = request.headers.get("X-CSRF-Token", ""), request.cookies.get("anulist_csrf", "")
        if not sent or not cookie or not secrets.compare_digest(sent, cookie) or not secrets.compare_digest(hashed(sent), session["csrf_hash"]):
            raise HTTPException(403, "Invalid CSRF token")
    user = db.execute("SELECT id,email,name FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not user:
        raise HTTPException(401, "Account not found")
    membership = db.execute("SELECT * FROM members WHERE user_id=?", (user["id"],)).fetchone()
    if not membership:
        raise HTTPException(403, "No household")
    return dict(user), dict(membership), session
