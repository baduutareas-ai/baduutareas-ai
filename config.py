"""
GradeScanner - Configuration
Manejo de configuración para diferentes entornos (local y Supabase)
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()


def _build_db_uri():
    """
    Construye la URI de base de datos leyendo desde variables de entorno.
    - En producción (Render): usa DATABASE_URL o SUPABASE_DB_URL.
    - En desarrollo local: si no hay URL configurada, usa SQLite local.
    """
    # DATABASE_URL tiene la mayor prioridad (inyectada por Render en producción)
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        database_url = os.environ.get('SUPABASE_DB_URL', '').strip()

    if not database_url:
        # Fallback a SQLite para desarrollo local
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sqlite_path = os.path.join(base_dir, 'gradescanner.db')
        print(f"[OK] Modo LOCAL: Usando SQLite -> {sqlite_path}")
        return f"sqlite:///{sqlite_path}"

    print("[OK] Conectando a base de datos remota (URL detectada en entorno)")

    # Limpieza agresiva de la URL para evitar errores
    database_url = database_url.replace(' ', '')

    # Corregir doble arroba si existe (error común al copiar)
    while '@@' in database_url:
        database_url = database_url.replace('@@', '@')

    # Requerimiento de SQLAlchemy 2.0+: usar postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


class Config:
    """Configuración base — soporta SQLite local y PostgreSQL/Supabase en producción"""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'gradescanner-secret-key-2024')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    OCR_API_KEY = os.environ.get('OCR_API_KEY', 'helloworld')

    # Determinar entorno
    ENV = os.environ.get('FLASK_ENV', 'development')

    # URI resuelta una sola vez
    SQLALCHEMY_DATABASE_URI = _build_db_uri()

    # Detectar si estamos en modo PostgreSQL/Supabase
    _is_postgres = SQLALCHEMY_DATABASE_URI.startswith('postgresql')
    USE_SUPABASE = _is_postgres

    # Debug: mostrar driver configurado
    _scheme = SQLALCHEMY_DATABASE_URI.split(':')[0]
    print(f"[DEBUG] DB driver activo: {_scheme}")

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # Opciones de conexión: solo aplican para PostgreSQL
    if _is_postgres:
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'connect_args': {
                'connect_timeout': 10,
                'sslmode': 'require'
            }
        }
        # Si estamos usando el puerto 6543 (PgBouncer en modo Transaction)
        if ':6543/' in SQLALCHEMY_DATABASE_URI:
            SQLALCHEMY_ENGINE_OPTIONS['query_cache_size'] = 0
            print("[INFO] Supabase Pooler detectado (puerto 6543). Estabilidad de PgBouncer ajustada.")
    else:
        # SQLite — sin opciones especiales de pool
        SQLALCHEMY_ENGINE_OPTIONS = {}


class DevelopmentConfig(Config):
    """Configuración de desarrollo"""
    DEBUG = True
    ENV = 'development'
    SQLALCHEMY_ECHO = True  # Útil para depurar queries en local


class ProductionConfig(Config):
    """Configuración de producción (Render/Supabase)"""
    DEBUG = False
    ENV = 'production'
    SQLALCHEMY_ECHO = False


class TestingConfig(Config):
    """Configuración de pruebas"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Mapa de configuraciones
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Obtiene la clase de configuración según el entorno"""
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])

