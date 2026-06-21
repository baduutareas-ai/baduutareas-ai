"""
GradeScanner - Flask Application (Simplified)
Sistema simplificado de examenes con plantillas
Solo examenes: permite registrar plantillas (opcion multiple y opcion libre)
"""

import os
import json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for, abort
from flask_cors import CORS

from database import db, init_app
from config import get_config
from models import Examen, Plantilla, Pregunta, Configuracion, Seccion, User
from ocr_engine import OCREngine

# Crear aplicación con configuración
app = Flask(__name__)
config = get_config()
app.config.from_object(config)

# Habilitar CORS
CORS(app)

# Configuración de uploads
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

# Inicializar base de datos
init_app(app)

# Asegurar que existe la carpeta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Inicializar motor OCR
ocr_engine = OCREngine()


def allowed_file(filename):
    """Verifica si el archivo tiene una extensión permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# Decoradores de Autenticación y Autorización
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'No autorizado. Inicie sesión.'}), 401
            return redirect(url_for('login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_role' not in session or session['user_role'] not in roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Permiso denegado. No tiene el rol requerido.'}), 403
                return render_template('unauthorized.html'), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== RUTAS DE AUTENTICACIÓN ====================

@app.route('/login', methods=['GET'])
def login_page():
    """Página de inicio de sesión"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """API de inicio de sesión"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': 'Debe ingresar usuario y contraseña.'}), 400
        
    user = User.query.filter_by(username=username, activo=True).first()
    
    if not user or not user.check_password(password):
        return jsonify({'error': 'Usuario o contraseña incorrectos.'}), 401
        
    # Iniciar sesión
    session['user_id'] = user.id
    session['username'] = user.username
    session['user_role'] = user.role
    session['user_name'] = user.nombre
    
    return jsonify({
        'message': 'Sesión iniciada correctamente',
        'user': user.to_dict()
    }), 200


@app.route('/logout')
def logout():
    """Cerrar sesión"""
    session.clear()
    return redirect(url_for('login_page'))


# ==================== RUTAS PRINCIPALES ====================

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')


@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard principal"""
    return render_template('dashboard.html')


@app.route('/scan')
@login_required
@role_required(['admin', 'profesor'])
def scan_page():
    """Página de escaneo"""
    return render_template('scan.html')


@app.route('/secciones')
@login_required
@role_required(['admin', 'profesor'])
def secciones_page():
    """Página de gestión de secciones"""
    return render_template('secciones.html')


@app.route('/exams')
@login_required
def exams_page():
    """Página de exámenes"""
    return render_template('exams.html')


@app.route('/templates')
@login_required
@role_required(['admin', 'profesor'])
def templates_page():
    """Página de plantillas"""
    return render_template('templates.html')


@app.route('/users')
@login_required
@role_required(['admin'])
def users_page():
    """Página de gestión de usuarios (exclusiva de admin)"""
    return render_template('users.html')


@app.route('/estudiantes')
@login_required
@role_required(['admin', 'profesor'])
def estudiantes_page():
    """Página de gestión de estudiantes"""
    return render_template('estudiantes.html')



# ==================== API: SECCIONES ====================

@app.route('/api/secciones', methods=['GET'])
@login_required
def get_secciones():
    """Obtiene todas las secciones"""
    if session.get('user_role') == 'estudiante':
        student_name = session.get('user_name', '')
        student_username = session.get('username', '')
        seccion_ids = db.session.query(Examen.seccion_id).filter(
            db.or_(
                Examen.nombre_estudiante.ilike(f"%{student_name}%"),
                Examen.nombre_estudiante.ilike(f"%{student_username}%")
            )
        ).distinct().all()
        ids = [sid[0] for sid in seccion_ids if sid[0] is not None]
        secciones = Seccion.query.filter(Seccion.id.in_(ids), Seccion.activo == True).all() if ids else []
    else:
        secciones = Seccion.query.filter_by(activo=True).all()
    return jsonify([s.to_dict() for s in secciones])


@app.route('/api/secciones', methods=['POST'])
@login_required
@role_required(['admin', 'profesor'])
def create_seccion():
    """Crea una nueva sección"""
    data = request.get_json()
    
    seccion = Seccion(
        asignatura=data['asignatura'],
        grado=data['grado'],
        letra=data['letra'],
        lapso=data.get('lapso', ''),
        profesor=data.get('profesor', '')
    )
    
    db.session.add(seccion)
    db.session.commit()
    
    return jsonify(seccion.to_dict()), 201


@app.route('/api/secciones/<int:id>', methods=['GET'])
@login_required
def get_seccion(id):
    """Obtiene una sección por ID"""
    seccion = Seccion.query.get_or_404(id)
    if session.get('user_role') == 'estudiante':
        student_name = session.get('user_name', '')
        student_username = session.get('username', '')
        has_exam = Examen.query.filter(
            Examen.seccion_id == id,
            db.or_(
                Examen.nombre_estudiante.ilike(f"%{student_name}%"),
                Examen.nombre_estudiante.ilike(f"%{student_username}%")
            )
        ).first()
        if not has_exam:
            return jsonify({'error': 'Permiso denegado. No tiene exámenes en esta sección.'}), 403
    return jsonify(seccion.to_dict())


@app.route('/api/secciones/<int:id>', methods=['PUT'])
@login_required
@role_required(['admin', 'profesor'])
def update_seccion(id):
    """Actualiza una sección"""
    seccion = Seccion.query.get_or_404(id)
    data = request.get_json()
    
    seccion.asignatura = data.get('asignatura', seccion.asignatura)
    seccion.grado = data.get('grado', seccion.grado)
    seccion.letra = data.get('letra', seccion.letra)
    seccion.lapso = data.get('lapso', seccion.lapso)
    seccion.profesor = data.get('profesor', seccion.profesor)
    
    db.session.commit()
    return jsonify(seccion.to_dict())


@app.route('/api/secciones/<int:id>', methods=['DELETE'])
@login_required
@role_required(['admin', 'profesor'])
def delete_seccion(id):
    """Elimina (desactiva) una sección"""
    seccion = Seccion.query.get_or_404(id)
    seccion.activo = False
    db.session.commit()
    return jsonify({'message': 'Sección eliminada'})


# ==================== API: PLANTILLAS ====================

@app.route('/api/plantillas', methods=['GET'])
@login_required
@role_required(['admin', 'profesor'])
def get_plantillas():
    """Obtiene todas las plantillas"""
    seccion_id = request.args.get('seccion_id', type=int)
    
    query = Plantilla.query.filter_by(activa=True)
    
    if seccion_id:
        query = query.filter_by(seccion_id=seccion_id)
    
    plantillas = query.all()
    return jsonify([p.to_dict() for p in plantillas])


@app.route('/api/plantillas', methods=['POST'])
@login_required
@role_required(['admin', 'profesor'])
def create_plantilla():
    """Crea una nueva plantilla"""
    data = request.get_json()
    
    # Solo opción múltiple
    respuestas = json.dumps(data.get('respuestas_correctas', []))
    
    plantilla = Plantilla(
        nombre=data['nombre'],
        descripcion=data.get('descripcion', ''),
        seccion_id=data.get('seccion_id'),
        tipo_examen='multiple_choice',
        respuestas_correctas=respuestas,
        puntaje_total=data.get('puntaje_total', 10)
    )
    
    db.session.add(plantilla)
    db.session.commit()
    
    return jsonify(plantilla.to_dict()), 201


@app.route('/api/plantillas/<int:id>', methods=['GET'])
@login_required
@role_required(['admin', 'profesor'])
def get_plantilla(id):
    """Obtiene una plantilla por ID"""
    plantilla = Plantilla.query.get_or_404(id)
    return jsonify(plantilla.to_dict())


@app.route('/api/plantillas/<int:id>', methods=['PUT'])
@login_required
@role_required(['admin', 'profesor'])
def update_plantilla(id):
    """Actualiza una plantilla"""
    plantilla = Plantilla.query.get_or_404(id)
    data = request.get_json()
    
    plantilla.nombre = data.get('nombre', plantilla.nombre)
    plantilla.descripcion = data.get('descripcion', plantilla.descripcion)
    if 'seccion_id' in data:
        plantilla.seccion_id = data['seccion_id']
    
    if 'respuestas_correctas' in data:
        plantilla.respuestas_correctas = json.dumps(data.get('respuestas_correctas', []))
    
    if 'puntaje_total' in data:
        plantilla.puntaje_total = data['puntaje_total']
    
    db.session.commit()
    return jsonify(plantilla.to_dict())


@app.route('/api/plantillas/<int:id>', methods=['DELETE'])
@login_required
@role_required(['admin', 'profesor'])
def delete_plantilla(id):
    """Elimina (desactiva) una plantilla"""
    plantilla = Plantilla.query.get_or_404(id)
    plantilla.activa = False
    db.session.commit()
    return jsonify({'message': 'Plantilla eliminada'})


# ==================== API: EXÁMENES Y ESCANEO ====================

@app.route('/api/ocr/status', methods=['GET'])
@login_required
@role_required(['admin', 'profesor'])
def ocr_status():
    """Verifica el estado del motor OCR"""
    status = ocr_engine.check_tesseract()
    
    # Agregar información adicional de diagnóstico
    status['api_key_configured'] = bool(ocr_engine.api_key and ocr_engine.api_key != '')
    status['api_key_prefix'] = ocr_engine.api_key[:4] + '...' if ocr_engine.api_key and len(ocr_engine.api_key) > 4 else 'N/A'
    status['api_url'] = ocr_engine.api_url
    status['language'] = ocr_engine.language
    status['last_error'] = getattr(ocr_engine, 'last_error', None)
    
    return jsonify(status), 200


@app.route('/api/ocr/test', methods=['POST'])
@login_required
@role_required(['admin', 'profesor'])
def ocr_test():
    """Endpoint de prueba para verificar el OCR con una imagen de prueba"""
    if 'file' not in request.files:
        return jsonify({'error': 'No se recibió ningún archivo'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    
    if file:
        # Guardar temporalmente
        import tempfile
        import uuid
        
        suffix = '.' + file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            # Probar OCR
            result = ocr_engine.extract_text_with_confidence(tmp_path)
            return jsonify(result)
        finally:
            # Limpiar
            import os
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    return jsonify({'error': 'Tipo de archivo no permitido'}), 400


@app.route('/api/scan', methods=['POST'])
@login_required
@role_required(['admin', 'profesor'])
def scan_examen():
    """Escanea un examen desde una imagen (soporta bubble sheets y texto)"""
    if 'file' not in request.files:
        return jsonify({'error': 'No se recibió ningún archivo'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    
    if file and allowed_file(file.filename):
        # Usar archivo temporal que se eliminará al terminar (NO se guarda permanentemente)
        import tempfile
        suffix = '.' + file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else '.jpg'
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        filepath = tmp.name
        tmp.close()
        file.save(filepath)
        
        titulo = request.form.get('titulo', 'Evaluación sin título')
        nombre_estudiante = request.form.get('nombre_estudiante', '').strip()
        seccion_id = request.form.get('seccion_id', type=int)
        plantilla_id = request.form.get('plantilla_id', type=int)
        
        # Modo de detección: 'auto', 'bubble', 'text'
        detection_mode = request.form.get('detection_mode', 'auto')
        
        # Opciones personalizadas (ej: "A,B,C,D" o "A,B,C,D,E")
        custom_options = request.form.get('options', '')
        options = [x.strip().upper() for x in custom_options.split(',') if x.strip()] if custom_options else None
        
        # Número de preguntas esperado (opcional)
        num_questions = request.form.get('num_questions', type=int)
        
        try:
            # Obtener plantilla si existe
            plantilla = Plantilla.query.get(plantilla_id) if plantilla_id else None
            
            # Determinar opciones desde plantilla si no se especificaron
            if not options and plantilla and plantilla.respuestas_correctas:
                try:
                    correct = json.loads(plantilla.respuestas_correctas)
                    if correct:
                        all_opts = set(c.get('respuesta', '').upper() for c in correct if c.get('respuesta'))
                        if all_opts:
                            max_opt = max(all_opts)
                            options = [chr(c) for c in range(ord('A'), ord(max_opt) + 1)]
                        if not num_questions:
                            num_questions = len(correct)
                except:
                    pass
            
            # Determinar force_mode basado en detection_mode
            force_mode = None
            if detection_mode == 'bubble':
                force_mode = 'bubble'
            elif detection_mode == 'text':
                force_mode = 'text'
            
            # Usar el método híbrido de procesamiento
            result = ocr_engine.process_image(
                filepath,
                force_mode=force_mode,
                num_questions=num_questions,
                options=options
            )
            
            # Verificar si hay error
            if result.get('error') and not result.get('answers'):
                return jsonify({
                    'error': f'Error de procesamiento: {result["error"]}',
                    'details': 'La imagen no pudo ser procesada. Verifica que la imagen sea legible.',
                    'method': result.get('method', 'none'),
                    'image_type': result.get('image_type', 'unknown')
                }), 500
            
            # Verificar que se encontraron respuestas o texto
            if not result.get('answers') and not result.get('text'):
                return jsonify({
                    'error': 'No se detectaron respuestas ni texto en la imagen',
                    'details': 'La imagen puede ser ilegible o no contener un formato reconocible. Intenta con una imagen más clara o selecciona el modo de detección correcto.',
                    'method': result.get('method', 'none'),
                    'image_type': result.get('image_type', 'unknown')
                }), 500
            
            extracted_answers = result.get('answers', [])
            
            # Crear examen en la base de datos (sin ruta de imagen)
            examen = Examen(
                titulo=titulo,
                nombre_estudiante=nombre_estudiante or None,
                seccion_id=seccion_id,
                plantilla_id=plantilla_id,
                imagen_path=None,  # No se guarda la imagen permanentemente
                texto_ocr=result.get('text', ''),
                confianza_ocr=result.get('confidence', 0),
                estado='procesado' if plantilla else 'pendiente'
            )
            
            db.session.add(examen)
            db.session.commit()
            
            # Calificar si hay plantilla
            grade_result = None
            if plantilla:
                correct_answers = json.loads(plantilla.respuestas_correctas) if plantilla.respuestas_correctas else []
                grade_result = ocr_engine.grade_answers(extracted_answers, correct_answers)
                
                examen.nota_final = grade_result['nota']
                examen.estado = 'revisado'
                
                # Crear preguntas
                for r in grade_result['resultados']:
                    pregunta = Pregunta(
                        examen_id=examen.id,
                        plantilla_id=plantilla_id,
                        numero=r['pregunta'],
                        tipo='multiple_choice',
                        respuesta_estudiante=r.get('respuesta_estudiante'),
                        respuesta_correcta=r.get('respuesta_correcta'),
                        puntos=r['puntos'],
                        puntos_obtenidos=r['puntos_obtenidos']
                    )
                    db.session.add(pregunta)
                
                db.session.commit()
            
            return jsonify({
                'examen': examen.to_dict(),
                'ocr': {
                    'text': result.get('text', ''),
                    'confidence': result.get('confidence', 0),
                    'words': result.get('words', 0),
                    'error': result.get('error'),
                    'method': result.get('method', 'unknown'),
                    'image_type': result.get('image_type', 'unknown')
                },
                'extracted_answers': extracted_answers,
                'grade': grade_result
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Error al procesar: {str(e)}'}), 500
        
        finally:
            # Siempre eliminar el archivo temporal
            if os.path.exists(filepath):
                os.remove(filepath)
    
    return jsonify({'error': 'Tipo de archivo no permitido'}), 400


@app.route('/api/scan/bubble-test', methods=['POST'])
@login_required
@role_required(['admin', 'profesor'])
def scan_bubble_test():
    """Endpoint de prueba para verificar detección de burbujas"""
    if 'file' not in request.files:
        return jsonify({'error': 'No se recibió ningún archivo'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    
    if file:
        import tempfile
        
        suffix = '.' + file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            # Probar detección de tipo
            image_type = ocr_engine.detect_image_type(tmp_path)
            
            # Probar procesamiento completo
            result = ocr_engine.process_image(tmp_path, force_mode='bubble')
            
            return jsonify({
                'image_type': image_type,
                'method': result.get('method', 'none'),
                'answers': result.get('answers', []),
                'confidence': result.get('confidence', 0),
                'text': result.get('text', ''),
                'error': result.get('error')
            })
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    return jsonify({'error': 'Tipo de archivo no permitido'}), 400


@app.route('/api/examenes', methods=['GET'])
@login_required
def get_examenes():
    """Obtiene todos los exámenes"""
    seccion_id = request.args.get('seccion_id', type=int)
    plantilla_id = request.args.get('plantilla_id', type=int)
    estado = request.args.get('estado')
    
    query = Examen.query
    
    if seccion_id:
        query = query.filter_by(seccion_id=seccion_id)
    if plantilla_id:
        query = query.filter_by(plantilla_id=plantilla_id)
    if estado:
        query = query.filter_by(estado=estado)
        
    # Filtrado por rol estudiante
    if session.get('user_role') == 'estudiante':
        student_name = session.get('user_name', '')
        student_username = session.get('username', '')
        query = query.filter(
            db.or_(
                Examen.nombre_estudiante.ilike(f"%{student_name}%"),
                Examen.nombre_estudiante.ilike(f"%{student_username}%")
            )
        )
    
    examenes = query.order_by(Examen.fecha_escaneo.desc()).all()
    return jsonify([e.to_dict() for e in examenes])


@app.route('/api/examenes/<int:id>', methods=['GET'])
@login_required
def get_examen(id):
    """Obtiene un examen por ID"""
    examen = Examen.query.get_or_404(id)
    
    # Restricción de acceso para estudiantes
    if session.get('user_role') == 'estudiante':
        student_name = session.get('user_name', '').lower()
        student_username = session.get('username', '').lower()
        exam_student = (examen.nombre_estudiante or '').lower()
        if student_name not in exam_student and student_username not in exam_student:
            return jsonify({'error': 'No tiene permisos para ver este examen.'}), 403
            
    # Obtener preguntas del examen
    preguntas = Pregunta.query.filter_by(examen_id=id).all()
    
    result = examen.to_dict()
    result['preguntas'] = [p.to_dict() for p in preguntas]
    
    return jsonify(result)


@app.route('/api/examenes', methods=['POST'])
@login_required
@role_required(['admin', 'profesor'])
def create_examen():
    """Crea un examen manualmente con sus respuestas y notas"""
    data = request.get_json() or {}
    
    titulo = data.get('titulo', 'Evaluación Manual')
    nombre_estudiante = data.get('nombre_estudiante', '').strip()
    seccion_id = data.get('seccion_id')
    plantilla_id = data.get('plantilla_id')
    observaciones = data.get('observaciones', '')
    estado = data.get('estado', 'revisado')
    
    # Crear examen
    examen = Examen(
        titulo=titulo,
        nombre_estudiante=nombre_estudiante or None,
        seccion_id=seccion_id,
        plantilla_id=plantilla_id,
        estado=estado,
        observaciones=observaciones,
        confianza_ocr=100.0,  # es manual
        texto_ocr='Creado manualmente'
    )
    db.session.add(examen)
    db.session.commit()
    
    # Crear preguntas y respuestas si vienen dadas
    respuestas = data.get('respuestas', [])
    suma_puntos_obtenidos = 0.0
    for r in respuestas:
        pregunta = Pregunta(
            examen_id=examen.id,
            plantilla_id=plantilla_id,
            numero=r['numero'],
            tipo='multiple_choice',
            respuesta_estudiante=r.get('respuesta_estudiante'),
            respuesta_correcta=r.get('respuesta_correcta'),
            puntos=r.get('puntos', 1.0),
            puntos_obtenidos=r.get('puntos_obtenidos', 0.0)
        )
        suma_puntos_obtenidos += float(r.get('puntos_obtenidos', 0.0))
        db.session.add(pregunta)
    
    # Calcular nota si no viene dada
    if 'nota_final' in data:
        examen.nota_final = data['nota_final']
    else:
        plantilla = Plantilla.query.get(plantilla_id) if plantilla_id else None
        if plantilla and plantilla.puntaje_total:
            examen.nota_final = round((suma_puntos_obtenidos / plantilla.puntaje_total) * 20.0, 2)
        else:
            examen.nota_final = suma_puntos_obtenidos
            
    db.session.commit()
    return jsonify(examen.to_dict()), 201


@app.route('/api/examenes/<int:id>', methods=['PUT'])
@login_required
@role_required(['admin', 'profesor'])
def update_examen(id):
    """Actualiza un examen (estudiante, respuestas, nota manual, observaciones)"""
    examen = Examen.query.get_or_404(id)
    data = request.get_json() or {}
    
    if 'titulo' in data:
        examen.titulo = data['titulo']
    if 'nombre_estudiante' in data:
        examen.nombre_estudiante = data['nombre_estudiante'] or None
    if 'seccion_id' in data:
        examen.seccion_id = data['seccion_id']
    if 'plantilla_id' in data:
        examen.plantilla_id = data['plantilla_id']
    if 'observaciones' in data:
        examen.observaciones = data['observaciones']
    if 'estado' in data:
        examen.estado = data['estado']
        if data['estado'] == 'revisado':
            examen.fecha_revision = datetime.utcnow()
            
    # Actualizar preguntas/respuestas si vienen
    if 'respuestas' in data:
        Pregunta.query.filter_by(examen_id=id).delete()
        
        suma_puntos_obtenidos = 0.0
        for r in data['respuestas']:
            pregunta = Pregunta(
                examen_id=id,
                plantilla_id=examen.plantilla_id,
                numero=r['numero'],
                tipo='multiple_choice',
                respuesta_estudiante=r.get('respuesta_estudiante'),
                respuesta_correcta=r.get('respuesta_correcta'),
                puntos=r.get('puntos', 1.0),
                puntos_obtenidos=r.get('puntos_obtenidos', 0.0)
            )
            suma_puntos_obtenidos += float(r.get('puntos_obtenidos', 0.0))
            db.session.add(pregunta)
        
        if 'nota_final' in data:
            examen.nota_final = data['nota_final']
        else:
            plantilla = Plantilla.query.get(examen.plantilla_id) if examen.plantilla_id else None
            if plantilla and plantilla.puntaje_total:
                examen.nota_final = round((suma_puntos_obtenidos / plantilla.puntaje_total) * 20.0, 2)
            else:
                examen.nota_final = suma_puntos_obtenidos
    elif 'nota_final' in data:
        examen.nota_final = data['nota_final']
    
    db.session.commit()
    return jsonify(examen.to_dict())


@app.route('/api/examenes/<int:id>', methods=['DELETE'])
@login_required
@role_required(['admin', 'profesor'])
def delete_examen(id):
    """Elimina un examen"""
    examen = Examen.query.get_or_404(id)
    db.session.delete(examen)
    db.session.commit()
    return jsonify({'message': 'Examen eliminado'})


# ==================== API: PREGUNTAS ====================

@app.route('/api/preguntas/examen/<int:examen_id>', methods=['GET'])
@login_required
def get_preguntas_examen(examen_id):
    """Obtiene las preguntas de un examen"""
    examen = Examen.query.get_or_404(examen_id)
    
    # Restricción de acceso para estudiantes
    if session.get('user_role') == 'estudiante':
        student_name = session.get('user_name', '').lower()
        student_username = session.get('username', '').lower()
        exam_student = (examen.nombre_estudiante or '').lower()
        if student_name not in exam_student and student_username not in exam_student:
            return jsonify({'error': 'No tiene permisos para ver las preguntas de este examen.'}), 403
            
    preguntas = Pregunta.query.filter_by(examen_id=examen_id).order_by(Pregunta.numero).all()
    return jsonify([p.to_dict() for p in preguntas])


# ==================== API: ESTADÍSTICAS ====================

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Obtiene estadísticas del sistema"""
    is_student = session.get('user_role') == 'estudiante'
    
    if is_student:
        student_name = session.get('user_name', '')
        student_username = session.get('username', '')
        exam_filter = db.or_(
            Examen.nombre_estudiante.ilike(f"%{student_name}%"),
            Examen.nombre_estudiante.ilike(f"%{student_username}%")
        )
        
        # Contar exámenes del estudiante
        total_examenes = Examen.query.filter(exam_filter).count()
        
        # Exámenes por estado del estudiante
        examen_estados = db.session.query(
            Examen.estado, 
            db.func.count(Examen.id)
        ).filter(exam_filter).group_by(Examen.estado).all()
        
        # Promedio de notas del estudiante
        notas_promedio = db.session.query(
            db.func.avg(Examen.nota_final)
        ).filter(exam_filter, Examen.nota_final.isnot(None)).scalar() or 0
        
        # Exámenes recientes del estudiante
        examenes_recientes = Examen.query.filter(exam_filter).order_by(
            Examen.fecha_escaneo.desc()
        ).limit(10).all()
        
        # Para estudiantes, las secciones y plantillas se filtran por sus exámenes
        seccion_ids = db.session.query(Examen.seccion_id).filter(exam_filter).distinct().all()
        ids_secciones = [sid[0] for sid in seccion_ids if sid[0] is not None]
        total_secciones = Seccion.query.filter(Seccion.id.in_(ids_secciones), Seccion.activo == True).count() if ids_secciones else 0
        
        plantilla_ids = db.session.query(Examen.plantilla_id).filter(exam_filter).distinct().all()
        ids_plantillas = [pid[0] for pid in plantilla_ids if pid[0] is not None]
        total_plantillas = Plantilla.query.filter(Plantilla.id.in_(ids_plantillas), Plantilla.activa == True).count() if ids_plantillas else 0
    else:
        # Contar secciones
        total_secciones = Seccion.query.filter_by(activo=True).count()
        
        # Contar plantillas
        total_plantillas = Plantilla.query.filter_by(activa=True).count()
        
        # Contar exámenes
        total_examenes = Examen.query.count()
        
        # Exámenes por estado
        examen_estados = db.session.query(
            Examen.estado, 
            db.func.count(Examen.id)
        ).group_by(Examen.estado).all()
        
        # Promedio de notas
        notas_promedio = db.session.query(
            db.func.avg(Examen.nota_final)
        ).filter(Examen.nota_final.isnot(None)).scalar() or 0
        
        # Exámenes recientes
        examenes_recientes = Examen.query.order_by(
            Examen.fecha_escaneo.desc()
        ).limit(10).all()
    
    return jsonify({
        'total_secciones': total_secciones,
        'total_plantillas': total_plantillas,
        'total_examenes': total_examenes,
        'examenes_por_estado': {e[0]: e[1] for e in examen_estados},
        'nota_promedio': round(float(notas_promedio), 2),
        'examenes_recientes': [e.to_dict() for e in examenes_recientes]
    })


# ==================== API: GESTIÓN DE USUARIOS ====================

@app.route('/api/users', methods=['GET'])
@login_required
@role_required(['admin', 'profesor'])
def get_users():
    """Obtiene todos los usuarios (Admin ve todos, Profesor ve estudiantes)"""
    if session.get('user_role') == 'profesor':
        users = User.query.filter_by(role='estudiante').all()
    else:
        users = User.query.all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/estudiantes', methods=['GET'])
@login_required
@role_required(['admin', 'profesor'])
def get_estudiantes():
    """Obtiene todos los estudiantes con estadísticas académicas"""
    estudiantes = User.query.filter_by(role='estudiante').all()
    result = []
    for est in estudiantes:
        # Buscamos exámenes que coincidan con su nombre o usuario
        exam_filter = db.or_(
            Examen.nombre_estudiante.ilike(f"%{est.nombre}%"),
            Examen.nombre_estudiante.ilike(f"%{est.username}%")
        )
        examenes = Examen.query.filter(exam_filter).all()
        count = len(examenes)
        promedio = 0.0
        if count > 0:
            notas = [e.nota_final for e in examenes if e.nota_final is not None]
            promedio = round(sum(notas) / len(notas), 2) if notas else 0.0
        
        d = est.to_dict()
        d['total_examenes'] = count
        d['promedio_notas'] = promedio
        result.append(d)
    return jsonify(result)



@app.route('/api/users', methods=['POST'])
@login_required
@role_required(['admin'])
def create_user():
    """Crea un nuevo usuario (Solo Admin)"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'profesor')
    nombre = data.get('nombre', '').strip()
    email = data.get('email', '').strip()
    seccion_id = data.get('seccion_id')
    
    if not username or not password or not nombre:
        return jsonify({'error': 'Faltan campos obligatorios (usuario, contraseña, nombre).'}), 400
        
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'El nombre de usuario ya está registrado.'}), 400
        
    user = User(username=username, role=role, nombre=nombre, email=email, seccion_id=seccion_id)
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify(user.to_dict()), 201


@app.route('/api/users/<int:id>', methods=['PUT'])
@login_required
@role_required(['admin'])
def update_user(id):
    """Actualiza un usuario (Solo Admin)"""
    user = User.query.get_or_404(id)
    data = request.get_json() or {}
    
    if 'nombre' in data:
        user.nombre = data['nombre'].strip()
    if 'email' in data:
        user.email = data['email'].strip()
    if 'seccion_id' in data:
        user.seccion_id = data['seccion_id']
    if 'role' in data:
        if user.id == session.get('user_id') and data['role'] != 'admin':
            return jsonify({'error': 'No puede quitarse el rol de administrador a sí mismo.'}), 400
        user.role = data['role']
    if 'activo' in data:
        if user.id == session.get('user_id') and not data['activo']:
            return jsonify({'error': 'No puede desactivar su propia cuenta.'}), 400
        user.activo = data['activo']
    if 'password' in data and data['password']:
        user.set_password(data['password'])
        
    db.session.commit()
    return jsonify(user.to_dict())


@app.route('/api/users/<int:id>', methods=['DELETE'])
@login_required
@role_required(['admin'])
def delete_user(id):
    """Elimina un usuario (Solo Admin)"""
    user = User.query.get_or_404(id)
    if user.id == session.get('user_id'):
        return jsonify({'error': 'No puede eliminar su propia cuenta.'}), 400
    
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'Usuario eliminado correctamente.'})


@app.route('/api/users/change-password', methods=['POST'])
@login_required
def change_own_password():
    """Permite a cualquier usuario cambiar su propia contraseña"""
    data = request.get_json() or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Debe ingresar la contraseña actual y la nueva contraseña.'}), 400
        
    user = User.query.get(session['user_id'])
    if not user or not user.check_password(current_password):
        return jsonify({'error': 'La contraseña actual es incorrecta.'}), 400
        
    user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Contraseña actualizada correctamente.'})


# ==================== API: SALUD ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint de verificación de salud"""
    return jsonify({
        'status': 'ok',
        'environment': config.ENV,
        'database': 'supabase' if config.USE_SUPABASE else 'sqlite'
    })


# ==================== ARCHIVOS ESTÁTICOS ====================

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Recurso no encontrado'}), 404
