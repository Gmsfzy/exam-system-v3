from models.db import get_db


def create_user(conn, username, hashed_password, role):
    conn.execute(
        'INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
        (username, hashed_password, role)
    )
    conn.commit()


def get_user_by_username(username):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()


def get_user_role(user_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT role FROM users WHERE id = ?', (user_id,)
        ).fetchone()