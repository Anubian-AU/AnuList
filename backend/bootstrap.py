import getpass
import sys
from storage import init, transaction, uid
from security import password_hash

def main():
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        raise SystemExit("Usage: python backend/bootstrap.py your@email.com")
    init()
    with transaction() as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise SystemExit("Accounts already exist. Create household invitations in AnuList.")
        pw = getpass.getpass("Choose password (12+ characters): ")
        if pw != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords differ")
        user, household, shopping = uid(), uid(), uid()
        db.execute("INSERT INTO users(id,email,name,password_hash) VALUES(?,?,?,?)",
                   (user, sys.argv[1].strip().lower(), "Owner", password_hash(pw)))
        db.execute("INSERT INTO households VALUES(?,?)", (household, "Our Household"))
        db.execute("INSERT INTO members VALUES(?,?,?)", (user, household, "owner"))
        db.execute("INSERT INTO lists(id,household_id,name,kind) VALUES(?,?,?,?)",
                   (shopping, household, "Shopping", "shopping"))
    print("Initial household created successfully.")

if __name__ == "__main__":
    main()
