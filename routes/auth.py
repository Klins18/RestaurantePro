from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import Usuario, registrar_auditoria, db
from models import LoginAttempt, now_peru
from datetime import timedelta
from flask import session

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        ip = (request.remote_addr or 'unknown')[:45]
        now = now_peru()
        LoginAttempt.query.filter(LoginAttempt.ventana_inicio < now - timedelta(days=1)).delete(
            synchronize_session=False
        )
        intento = LoginAttempt.query.filter_by(username=username[:80], ip=ip).with_for_update().first()
        if intento and intento.bloqueado_hasta and intento.bloqueado_hasta > now:
            flash('Usuario o contraseña incorrectos', 'error')
            return render_template('login.html'), 429
        user = Usuario.query.filter_by(username=username, activo=True).first()
        if user and user.check_password(password):
            if intento:
                db.session.delete(intento)
            session.pop('_csrf_token', None)
            login_user(user)
            registrar_auditoria(user.id, 'LOGIN', ip=request.remote_addr)
            db.session.commit()
            return redirect(url_for('main.dashboard'))
        if not intento:
            intento = LoginAttempt(username=username[:80], ip=ip, intentos=0, ventana_inicio=now)
            db.session.add(intento)
        if now - intento.ventana_inicio > timedelta(minutes=15):
            intento.intentos = 0
            intento.ventana_inicio = now
            intento.bloqueado_hasta = None
        intento.intentos += 1
        if intento.intentos >= 5:
            intento.bloqueado_hasta = now + timedelta(minutes=15)
        db.session.commit()
        flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    registrar_auditoria(current_user.id, 'LOGOUT', ip=request.remote_addr)
    db.session.commit()
    logout_user()
    return redirect(url_for('auth.login'))
