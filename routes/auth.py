from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from werkzeug.security import generate_password_hash, check_password_hash

from models.db import get_db
from models.user import create_user, get_user_by_username

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        hashed_password = generate_password_hash(password)

        try:
            with get_db() as conn:
                create_user(conn, username, hashed_password, role)
            flash('注册成功，请登录', 'success')
            return redirect(url_for('auth.login'))
        except Exception:
            flash('用户名已存在', 'error')

    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = get_user_by_username(username)

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('main.dashboard'))
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


@auth_bp.route('/logout', endpoint='logout')
def logout():
    from utils.decorators import login_required
    session.clear()
    return redirect(url_for('main.index'))