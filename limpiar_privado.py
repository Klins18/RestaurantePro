"""
Ejecutar UNA SOLA VEZ en D:\RestaurantePro\:
  python limpiar_privado.py

Marca como inactiva la empresa "Privado" de la base de datos.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db, EmpresaTuristica

app = create_app()
with app.app_context():
    privadas = EmpresaTuristica.query.filter(
        EmpresaTuristica.nombre.ilike('privado')
    ).all()
    if not privadas:
        print("No se encontró ninguna empresa llamada 'Privado'. Nada que hacer.")
    for e in privadas:
        e.activo = False
        print(f"Desactivada: {e.nombre} (id={e.id})")
    db.session.commit()
    print("Listo.")
