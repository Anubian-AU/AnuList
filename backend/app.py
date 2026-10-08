import io
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from storage import MEDIA_PATH, init, transaction, uid
from security import authenticate, clear_session, expiry, hashed, password_check, password_hash, set_session

init()
app = FastAPI(title="AnuList", version="0.1.0", docs_url=None, redoc_url=None)
login_attempts = defaultdict(deque)

@app.middleware("http")
async def headers(request, call_next):
    result = await call_next(request)
    result.headers["X-Content-Type-Options"] = "nosniff"
    result.headers["Referrer-Policy"] = "no-referrer"
    result.headers["X-Frame-Options"] = "DENY"
    result.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/"):
        result.headers["Cache-Control"] = "no-store"
    return result

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

class Registration(Credentials):
    name: str = Field(min_length=1, max_length=100)
    invitation: str = Field(min_length=20, max_length=200)

class Named(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = "general"

class ItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    quantity: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=80)

class BulkInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)

class EditEntry(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    quantity: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=80)
    checked: bool | None = None
    version: int = Field(ge=1)

class CatalogueEdit(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    quantity: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=80)

class IngredientInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    quantity: str = Field(default="", max_length=60)

class RecipeInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    servings: int = Field(default=4, ge=1, le=100)
    instructions: str = Field(default="", max_length=20000)
    source_url: str = Field(default="", max_length=1000)
    ingredients: list[IngredientInput] = Field(default_factory=list, max_length=150)

class AddRecipe(BaseModel):
    list_id: str
    ingredient_ids: list[str] | None = None

def text(value):
    return value.strip()

def one(db, sql, params=(), status=404):
    row = db.execute(sql, params).fetchone()
    if not row:
        raise HTTPException(status, "Not found")
    return dict(row)

def rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params).fetchall()]

def ctx(request, db):
    user, member, session = authenticate(request, db)
    return user, member["household_id"], member["role"], session

def owned_list(db, household, list_id):
    return one(db, "SELECT * FROM lists WHERE id=? AND household_id=?", (list_id, household))

def owned_catalogue(db, household, item_id):
    return one(db, "SELECT * FROM catalogue WHERE id=? AND household_id=?", (item_id, household))

def owned_recipe(db, household, recipe_id):
    return one(db, "SELECT * FROM recipes WHERE id=? AND household_id=?", (recipe_id, household))

def owned_entry(db, household, entry_id):
    return one(db, """SELECT e.* FROM entries e JOIN lists l ON l.id=e.list_id
                     WHERE e.id=? AND l.household_id=?""", (entry_id, household))

def catalogue_match(db, household, name):
    row = db.execute("SELECT * FROM catalogue WHERE household_id=? AND name=? COLLATE NOCASE",
                     (household, name)).fetchone()
    return dict(row) if row else None

def add_entry(db, user_id, household, list_id, item):
    name = text(item.name)
    if not name:
        raise HTTPException(422, "Item name required")
    template = catalogue_match(db, household, name)
    if not template:
        cat_id = uid()
        db.execute("INSERT INTO catalogue(id,household_id,name,quantity,note,category) VALUES(?,?,?,?,?,?)",
                   (cat_id, household, name, text(item.quantity), text(item.note), text(item.category)))
        template = one(db, "SELECT * FROM catalogue WHERE id=?", (cat_id,))
    ident = uid()
    # A blank field inherits the household default, but a supplied value overrides it.
    db.execute("""INSERT INTO entries
       (id,list_id,catalogue_id,name,quantity,note,category,added_by)
       VALUES(?,?,?,?,?,?,?,?)""",
       (ident, list_id, template["id"], template["name"],
        text(item.quantity) or template["quantity"],
        text(item.note) or template["note"],
        text(item.category) or template["category"], user_id))
    return one(db, "SELECT * FROM entries WHERE id=?", (ident,))

def enforce_rate(request, email):
    key = (request.client.host if request.client else "unknown", email)
    now = time.monotonic()
    attempts = login_attempts[key]
    while attempts and attempts[0] < now - 60:
        attempts.popleft()
    if len(attempts) >= 8:
        raise HTTPException(429, "Too many sign-in attempts. Wait a minute.")
    attempts.append(now)

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}

@app.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response):
    email = body.email.strip().lower()
    enforce_rate(request, email)
    with transaction() as db:
        record = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not record or not password_check(record["password_hash"], body.password):
            raise HTTPException(401, "Incorrect email or password")
        set_session(db, response, record["id"])
        return {"name": record["name"]}

@app.post("/api/auth/register")
def register(body: Registration, response: Response):
    invitation = text(body.invitation)
    with transaction() as db:
        record = db.execute("SELECT * FROM invitations WHERE code_hash=?", (hashed(invitation),)).fetchone()
        if not record or record["used_at"] or datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(400, "Invitation invalid or expired")
        if db.execute("SELECT 1 FROM users WHERE email=?", (body.email.lower().strip(),)).fetchone():
            raise HTTPException(409, "Email already registered")
        user_id = uid()
        db.execute("INSERT INTO users(id,email,name,password_hash) VALUES(?,?,?,?)",
                   (user_id, body.email.strip().lower(), text(body.name), password_hash(body.password)))
        db.execute("INSERT INTO members VALUES(?,?,?)", (user_id, record["household_id"], "member"))
        db.execute("UPDATE invitations SET used_at=? WHERE code_hash=?",
                   (datetime.now(timezone.utc).isoformat(), record["code_hash"]))
        set_session(db, response, user_id)
    return {"ok": True}

@app.get("/api/auth/me")
def me(request: Request):
    with transaction() as db:
        user, household, role, _ = ctx(request, db)
        return {**user, "household_id": household, "role": role,
                "household": one(db, "SELECT name FROM households WHERE id=?", (household,))["name"]}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    with transaction() as db:
        _, _, _, session = ctx(request, db)
        db.execute("DELETE FROM sessions WHERE token_hash=?", (session["token_hash"],))
        clear_session(response)
    return {"ok": True}

@app.post("/api/household/invite")
def invite(request: Request):
    with transaction() as db:
        _, household, role, _ = ctx(request, db)
        if role != "owner":
            raise HTTPException(403, "Only household owners can invite")
        code = secrets.token_urlsafe(32)
        db.execute("INSERT INTO invitations VALUES(?,?,?,NULL)", (hashed(code), household, expiry(1)))
        return {"code": code, "expires_in_hours": 24}

@app.get("/api/household/members")
def members(request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        return rows(db, """SELECT u.name,u.email,m.role FROM users u JOIN members m ON m.user_id=u.id
                           WHERE m.household_id=? ORDER BY u.name""", (household,))

@app.get("/api/lists")
def lists(request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        return rows(db, """SELECT l.*, COUNT(e.id) AS total,
                           COALESCE(SUM(CASE WHEN e.checked=0 THEN 1 ELSE 0 END),0) AS remaining
                           FROM lists l LEFT JOIN entries e ON e.list_id=l.id
                           WHERE l.household_id=? GROUP BY l.id ORDER BY l.created_at,l.name""", (household,))

@app.post("/api/lists")
def create_list(body: Named, request: Request):
    if body.kind not in ("shopping", "general", "travel", "medication", "takeaway"):
        raise HTTPException(422, "Unsupported list type")
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        ident = uid()
        db.execute("INSERT INTO lists(id,household_id,name,kind) VALUES(?,?,?,?)",
                   (ident, household, text(body.name), body.kind))
        return one(db, "SELECT * FROM lists WHERE id=?", (ident,))

@app.patch("/api/lists/{list_id}")
def rename_list(list_id: str, body: Named, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_list(db, household, list_id)
        db.execute("UPDATE lists SET name=? WHERE id=?", (text(body.name), list_id))
        return owned_list(db, household, list_id)

@app.delete("/api/lists/{list_id}")
def delete_list(list_id: str, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_list(db, household, list_id)
        db.execute("DELETE FROM lists WHERE id=?", (list_id,))
        return {"ok": True}

@app.get("/api/lists/{list_id}/entries")
def entries(list_id: str, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_list(db, household, list_id)
        return rows(db, """SELECT e.*, c.image_key FROM entries e
                          LEFT JOIN catalogue c ON c.id=e.catalogue_id
                          WHERE e.list_id=? ORDER BY e.checked,e.category COLLATE NOCASE,e.created_at""", (list_id,))

@app.post("/api/lists/{list_id}/entries")
def create_entry(list_id: str, body: ItemInput, request: Request):
    with transaction() as db:
        user, household, _, _ = ctx(request, db)
        owned_list(db, household, list_id)
        return add_entry(db, user["id"], household, list_id, body)

quantity_pattern = re.compile(r"^\s*((?:\d+(?:\.\d+)?)\s*(?:kg|g|ml|l|pack|packs|x))\s+(.+)$", re.I)
end_quantity_pattern = re.compile(r"^(.+?)\s+(\d+(?:\.\d+)?\s*(?:kg|g|ml|l|pack|packs))$", re.I)

def split_item(line):
    match = quantity_pattern.match(line)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    match = end_quantity_pattern.match(line)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return line.strip(), ""

@app.post("/api/lists/{list_id}/bulk")
def bulk_add(list_id: str, body: BulkInput, request: Request):
    lines = [line.strip(" \t•-*") for line in body.text.splitlines() if line.strip(" \t•-*")]
    if len(lines) > 150:
        raise HTTPException(422, "Maximum 150 items at a time")
    with transaction() as db:
        user, household, _, _ = ctx(request, db)
        owned_list(db, household, list_id)
        result = []
        for line in lines:
            name, quantity = split_item(line[:220])
            result.append(add_entry(db, user["id"], household, list_id, ItemInput(name=name, quantity=quantity)))
        return result

@app.patch("/api/entries/{entry_id}")
def edit_entry(entry_id: str, body: EditEntry, request: Request):
    with transaction() as db:
        user, household, _, _ = ctx(request, db)
        entry = owned_entry(db, household, entry_id)
        if body.version != entry["version"]:
            raise HTTPException(409, "Item changed on another device. Refresh and retry.")
        updates = body.model_dump(exclude_unset=True, exclude={"version"})
        if not updates:
            return entry
        if "checked" in updates:
            updates["checked"] = int(updates["checked"])
            updates["checked_by"] = user["id"] if updates["checked"] else None
        for key in ("name", "quantity", "note", "category"):
            if key in updates:
                updates[key] = text(updates[key])
        if "name" in updates and not updates["name"]:
            raise HTTPException(422, "Item name required")
        columns = ", ".join(key + "=?" for key in updates)
        db.execute("UPDATE entries SET " + columns + ", version=version+1 WHERE id=?",
                   [*updates.values(), entry_id])
        return owned_entry(db, household, entry_id)

@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: str, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_entry(db, household, entry_id)
        db.execute("DELETE FROM entries WHERE id=?", (entry_id,))
    return {"ok": True}

@app.get("/api/catalogue")
def catalogue(request: Request, q: str = ""):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        # Escape LIKE wildcards so user input is treated literally.
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:100]
        return rows(db, """SELECT * FROM catalogue WHERE household_id=? AND name LIKE ? ESCAPE '\'
                          ORDER BY name COLLATE NOCASE LIMIT 100""", (household, "%" + term + "%"))

@app.put("/api/catalogue/{item_id}")
def update_catalogue(item_id: str, body: CatalogueEdit, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_catalogue(db, household, item_id)
        try:
            db.execute("""UPDATE catalogue SET name=?,quantity=?,note=?,category=? WHERE id=?""",
                       (text(body.name), text(body.quantity), text(body.note), text(body.category), item_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "An item with this name already exists")
        return owned_catalogue(db, household, item_id)

@app.post("/api/catalogue/{item_id}/photo")
async def upload_photo(item_id: str, request: Request, file: UploadFile = File(...)):
    contents = await file.read(8 * 1024 * 1024 + 1)
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(413, "Photo maximum size is 8 MB")
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "JPEG, PNG and WebP only")
    try:
        Image.MAX_IMAGE_PIXELS = 25_000_000
        source = Image.open(io.BytesIO(contents))
        source.verify()
        image = Image.open(io.BytesIO(contents))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1600, 1600))
        converted = image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "Invalid image")
    filename = uid() + ".jpg"
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        item = owned_catalogue(db, household, item_id)
        converted.save(MEDIA_PATH / filename, "JPEG", quality=84, optimize=True)
        db.execute("UPDATE catalogue SET image_key=? WHERE id=?", (filename, item_id))
        previous = item["image_key"]
    if previous and previous != filename:
        (MEDIA_PATH / previous).unlink(missing_ok=True)
    return {"ok": True}

@app.get("/api/catalogue/{item_id}/photo")
def get_photo(item_id: str, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        item = owned_catalogue(db, household, item_id)
        if not item["image_key"]:
            raise HTTPException(404, "No photo")
        filename = MEDIA_PATH / item["image_key"]
        if not filename.is_file():
            raise HTTPException(404, "Missing file")
        return FileResponse(filename, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

@app.get("/api/recipes")
def recipes(request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        return rows(db, "SELECT * FROM recipes WHERE household_id=? ORDER BY title COLLATE NOCASE", (household,))

def load_recipe(db, recipe_id):
    recipe = one(db, "SELECT * FROM recipes WHERE id=?", (recipe_id,))
    recipe["ingredients"] = rows(db, "SELECT * FROM ingredients WHERE recipe_id=? ORDER BY position", (recipe_id,))
    return recipe

def replace_ingredients(db, recipe_id, ingredients):
    db.execute("DELETE FROM ingredients WHERE recipe_id=?", (recipe_id,))
    for i, ing in enumerate(ingredients):
        if not ing.name.strip():
            continue
        db.execute("INSERT INTO ingredients(id,recipe_id,name,quantity,position) VALUES(?,?,?,?,?)",
                   (uid(), recipe_id, text(ing.name), text(ing.quantity), i))

@app.post("/api/recipes")
def create_recipe(body: RecipeInput, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        recipe_id = uid()
        db.execute("""INSERT INTO recipes(id,household_id,title,servings,instructions,source_url)
                      VALUES(?,?,?,?,?,?)""",
                   (recipe_id, household, text(body.title), body.servings, body.instructions, text(body.source_url)))
        replace_ingredients(db, recipe_id, body.ingredients)
        return load_recipe(db, recipe_id)

@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_recipe(db, household, recipe_id)
        return load_recipe(db, recipe_id)

@app.put("/api/recipes/{recipe_id}")
def update_recipe(recipe_id: str, body: RecipeInput, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_recipe(db, household, recipe_id)
        db.execute("""UPDATE recipes SET title=?,servings=?,instructions=?,source_url=? WHERE id=?""",
                   (text(body.title), body.servings, body.instructions, text(body.source_url), recipe_id))
        replace_ingredients(db, recipe_id, body.ingredients)
        return load_recipe(db, recipe_id)

@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: str, request: Request):
    with transaction() as db:
        _, household, _, _ = ctx(request, db)
        owned_recipe(db, household, recipe_id)
        db.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
    return {"ok": True}

@app.post("/api/recipes/{recipe_id}/add")
def recipe_to_list(recipe_id: str, body: AddRecipe, request: Request):
    with transaction() as db:
        user, household, _, _ = ctx(request, db)
        owned_recipe(db, household, recipe_id)
        owned_list(db, household, body.list_id)
        ingredients = rows(db, "SELECT * FROM ingredients WHERE recipe_id=? ORDER BY position", (recipe_id,))
        allowed = set(body.ingredient_ids) if body.ingredient_ids is not None else None
        if allowed is not None and not allowed.issubset({i["id"] for i in ingredients}):
            raise HTTPException(422, "Unrecognised ingredient")
        result = []
        for ingredient in ingredients:
            if allowed is None or ingredient["id"] in allowed:
                result.append(add_entry(db, user["id"], household, body.list_id,
                                        ItemInput(name=ingredient["name"], quantity=ingredient["quantity"])))
        return result

frontend = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
