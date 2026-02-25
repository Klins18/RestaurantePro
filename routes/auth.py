from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import Usuario, registrar_auditoria, db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = Usuario.query.filter_by(username=username, activo=True).first()
        if user and user.check_password(password):
            login_user(user)
            registrar_auditoria(user.id, 'LOGIN', ip=request.remote_addr)
            db.session.commit()
            return redirect(url_for('main.dashboard'))
        flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    registrar_auditoria(current_user.id, 'LOGOUT', ip=request.remote_addr)
    db.session.commit()
    logout_user()
    return redirect(url_for('auth.login'))
