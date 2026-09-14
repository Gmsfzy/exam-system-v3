from functools import wraps
from flask import redirect, url_for, session, flash

from models.db import get_db


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            with get_db() as conn:
                user = conn.execute('SELECT role FROM users WHERE id = ?',
                                   (session['user_id'],)).fetchone()
            if user['role'] != required_role:
                flash('您没有权限访问此页面', 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator