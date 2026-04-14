# SQL injection — true negatives (safe patterns)
# no-expect: These should NOT trigger any SQL injection rules

import sqlite3

def safe_parameterized(user_id):
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

def safe_named_params(name, email):
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute(
        "SELECT * FROM users WHERE name = :name AND email = :email",
        {"name": name, "email": email},
    )

def safe_constant():
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute("SELECT count(*) FROM users")

def safe_orm_style(user_id):
    # ORM-style — no raw SQL
    return User.objects.filter(id=user_id).first()
