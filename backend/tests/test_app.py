import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

directory = tempfile.TemporaryDirectory()
os.environ["ANULIST_DB"] = str(Path(directory.name) / "test.db")
os.environ["ANULIST_MEDIA"] = str(Path(directory.name) / "media")
os.environ["COOKIE_SECURE"] = "false"

from storage import transaction, uid
from security import password_hash
from app import app

client = TestClient(app)

def seed():
    with transaction() as db:
        user, home, lst = uid(), uid(), uid()
        db.execute("INSERT INTO users(id,email,name,password_hash) VALUES(?,?,?,?)",
                   (user, "owner@example.test", "Owner", password_hash("test-password-1234")))
        db.execute("INSERT INTO households VALUES(?,?)", (home, "Test Home"))
        db.execute("INSERT INTO members VALUES(?,?,?)", (user, home, "owner"))
        db.execute("INSERT INTO lists(id,household_id,name,kind) VALUES(?,?,?,?)",
                   (lst, home, "Shopping", "shopping"))
        return lst

def mutate(method, url, data=None):
    from urllib.parse import unquote
    csrf = unquote(client.cookies.get("anulist_csrf", ""))
    return client.request(method, url, json=data, headers={"X-CSRF-Token": csrf})

def test_household_workflow():
    list_id = seed()
    assert client.get("/api/lists").status_code == 401
    assert client.post("/api/auth/login", json={"email":"owner@example.test","password":"test-password-1234"}).status_code == 200
    assert client.get("/api/auth/me").json()["role"] == "owner"
    assert client.post("/api/lists", json={"name":"Unprotected"}).status_code == 403
    assert mutate("POST", f"/api/lists/{list_id}/entries", {"name":"Beef Mince","quantity":"500g","note":"5-star lean"}).status_code == 200
    items = client.get(f"/api/lists/{list_id}/entries").json()
    assert len(items) == 1
    assert items[0]["quantity"] == "500g"
    assert mutate("PATCH", "/api/entries/" + items[0]["id"], {"checked":True,"version":1}).status_code == 200
    assert mutate("PATCH", "/api/entries/" + items[0]["id"], {"checked":False,"version":1}).status_code == 409
    assert mutate("POST", f"/api/lists/{list_id}/entries", {"name":"beef mince"}).json()["note"] == "5-star lean"
    assert len(mutate("POST", f"/api/lists/{list_id}/bulk", {"text":"2L Milk\nBread"}).json()) == 2
    recipe = mutate("POST","/api/recipes",{"title":"Test","ingredients":[{"name":"Rice","quantity":"200g"}]}).json()
    assert mutate("POST",f"/api/recipes/{recipe['id']}/add",{"list_id":list_id}).status_code == 200
    invite = mutate("POST","/api/household/invite").json()["code"]
    assert invite
    assert mutate("POST","/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401

def test_cross_household_isolation():
    with transaction() as db:
        other, home, lst = uid(), uid(), uid()
        db.execute("INSERT INTO users(id,email,name,password_hash) VALUES(?,?,?,?)",
                   (other, "other@example.test", "Other", password_hash("other-password-1234")))
        db.execute("INSERT INTO households VALUES(?,?)", (home, "Other Home"))
        db.execute("INSERT INTO members VALUES(?,?,?)", (other, home, "owner"))
        db.execute("INSERT INTO lists(id,household_id,name,kind) VALUES(?,?,?,?)",
                   (lst, home, "Other List", "shopping"))
    assert client.post("/api/auth/login",json={"email":"other@example.test","password":"other-password-1234"}).status_code == 200
    assert mutate("POST", "/api/lists/" + client.get("/api/lists").json()[0]["id"] + "/entries", {"name":"Private"}).status_code == 200
    with transaction() as db:
        чужой = db.execute("SELECT id FROM lists WHERE name='Shopping'").fetchone()["id"]
    assert client.get(f"/api/lists/{чужой}/entries").status_code == 404
