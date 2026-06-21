"""
GradeScanner - Database Configuration
Configuración de la base de datos SQLite o PostgreSQL (Supabase)
"""

import os
from flask_sqlalchemy import SQLAlchemy

# Instancia global de SQLAlchemy
db = SQLAlchemy()



def init_app(app):
    """Inicializa la base de datos con la aplicación Flask"""
    from config import get_config

    cfg = get_config()

    # Verificar que tenemos una URL de base de datos válida
    db_uri = cfg.SQLALCHEMY_DATABASE_URI

    if not db_uri:
        print(f"ERROR: No se ha configurado la base de datos! (URI detectada: '{db_uri}')")
        print(f"Entorno: {os.environ.get('FLASK_ENV', 'N/A')}")
        print(f"DATABASE_URL presente en ENV: {bool(os.environ.get('DATABASE_URL'))}")
        print("Para Supabase: asegúrese de que DATABASE_URL esté definida en Render.")
        raise ValueError(f"DATABASE_URL no configurada correctamente (URI: '{db_uri}')")

    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ECHO'] = getattr(cfg, 'SQLALCHEMY_ECHO', False)

    # Propagar opciones del pool de conexiones si existen (PostgreSQL en producción)
    engine_options = getattr(cfg, 'SQLALCHEMY_ENGINE_OPTIONS', None)
    if engine_options:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options

    db.init_app(app)

    with app.app_context():
        # create_all() NO borra tablas existentes, solo las crea si no existen
        db.create_all()

        # Sembrar usuarios por defecto si no existen
        try:
            from models import User
            if not User.query.first():
                print("  -> Sembrando usuarios por defecto...")
                admin = User(username='admin', role='admin', nombre='Administrador GradeScanner', email='admin@gradescanner.com')
                admin.set_password('admin123')
                
                profesor = User(username='profesor', role='profesor', nombre='Profesor Gómez', email='profesor@gradescanner.com')
                profesor.set_password('profesor123')
                
                estudiante = User(username='estudiante', role='estudiante', nombre='Estudiante Pérez', email='estudiante@gradescanner.com')
                estudiante.set_password('estudiante123')
                
                db.session.add(admin)
                db.session.add(profesor)
                db.session.add(estudiante)
                db.session.commit()
                print("  [OK] Usuarios por defecto sembrados correctamente!")
        except Exception as e:
            print(f"  [WARNING] Error al sembrar usuarios: {str(e)}")

        # Migración: agregar seccion_id a usuarios si no existe
        try:
            from sqlalchemy import inspect as sa_inspect
            inspector = sa_inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('usuarios')]
            if 'seccion_id' not in columns:
                db.engine.execute('ALTER TABLE usuarios ADD COLUMN seccion_id INTEGER REFERENCES secciones(id)')
                print("  [OK] Migración: columna seccion_id agregada a usuarios")
        except Exception as e:
            print(f"  [WARNING] Error en migración: {str(e)}")

        # Verificar que las tablas existen
        inspector = sa_inspect(db.engine)
        tables = inspector.get_table_names()

        driver = db_uri.split(':')[0]
        safe_uri = db_uri.split('@')[0] + '@***' if '@' in db_uri else db_uri

        print(f"[OK] Base de datos [{driver}] conectada -> {safe_uri}")
        if tables:
            print(f"  Tablas encontradas: {', '.join(tables)}")
        else:
            print("  [WARNING] No hay tablas aun -- se acaban de crear.")

    return db
