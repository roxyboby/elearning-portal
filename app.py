"""
app.py — E-Learning Portal (Raspberry Pi)
-----------------------------------------
Single-file Flask app with:
- Config & DB setup
- Auth (register/login/logout)
- Admin guard + admin pages (dashboard, courses)
- Enrollment + My Courses
- File upload for page HTMLs (admin New/Edit Page)
- Insert/renumber Sections to place between existing ones
- Active users tracking and session timeout management
- Hero image upload functionality
- Minimal, readable structure with comments for each section
"""


import os, time
from functools import wraps
from flask import Flask, render_template, redirect, url_for, request, flash, abort, session, jsonify, send_from_directory
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import uuid
from PIL import Image
import json
import glob
import psutil
import os
from datetime import datetime





# -----------------------------------------------------------------------------
# 0) Load environment variables (.env) early
# -----------------------------------------------------------------------------
load_dotenv()

# -----------------------------------------------------------------------------
# 1) Flask application (single-file style)
# -----------------------------------------------------------------------------
app = Flask(__name__)

# --- Security & upload limits (added by patch) ---
import os
secret = os.getenv('SECRET_KEY') or 'dev-only-not-secure'
app.secret_key = secret
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
# Optional session hardening when behind HTTPS (Cloudflare):
# app.config['SESSION_COOKIE_SECURE'] = True
# app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# --- end patch ---

app.secret_key = os.getenv('SECRET_KEY', 'fallback_secret')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, 'portal.db')

# Root folder for course HTML pages (kept inside the project)
CONTENT_ROOT = os.path.join(BASE_DIR, 'content')
PAGES_DIR = os.path.join(CONTENT_ROOT, 'pages')
os.makedirs(CONTENT_ROOT, exist_ok=True)
os.makedirs(PAGES_DIR, exist_ok=True)

COVERS_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'covers')
os.makedirs(COVERS_DIR, exist_ok=True)

# Hero image upload configuration
HERO_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'hero')
HERO_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
HERO_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
os.makedirs(HERO_UPLOAD_FOLDER, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_BINDS'] = {'trends': f'sqlite:///{os.path.join(INSTANCE_DIR, "market_intelligence.db")}'}

# Session timeout configuration (10 minutes)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

# -----------------------------------------------------------------------------
# 2) Active Users Tracking and Session Management
# -----------------------------------------------------------------------------
# In-memory store for active users (user_id -> last_activity_timestamp)
active_users = {}

def update_user_activity(user_id):
    """Update the last activity time for a user"""
    if user_id:
        active_users[user_id] = datetime.utcnow()

def cleanup_inactive_users():
    """Remove users inactive for more than 10 minutes"""
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    inactive_users = [uid for uid, last_activity in active_users.items() if last_activity < cutoff]
    for uid in inactive_users:
        del active_users[uid]

def get_active_users_count():
    """Get count of currently active users"""
    cleanup_inactive_users()
    return len(active_users)

def get_active_users_list():
    """Get list of active users with details"""
    cleanup_inactive_users()
    from models import User
    user_ids = list(active_users.keys())
    if not user_ids:
        return []
    
    users = User.query.filter(User.id.in_(user_ids)).all()
    result = []
    for user in users:
        last_activity = active_users.get(user.id)
        if last_activity:
            result.append({
                'id': user.id,
                'email': user.email,
                'last_activity': last_activity,
                'minutes_ago': int((datetime.utcnow() - last_activity).total_seconds() / 60)
            })
    return result

@app.before_request
def before_request():
    """Handle session timeout and user activity tracking"""
    # Make session permanent to use PERMANENT_SESSION_LIFETIME
    session.permanent = True
    
    # Check if user is logged in
    if current_user.is_authenticated:
        # Update user activity
        update_user_activity(current_user.id)
        
        # Check session timeout
        if 'last_activity' in session:
            last_activity = datetime.fromisoformat(session['last_activity'])
            if datetime.utcnow() - last_activity > app.config['PERMANENT_SESSION_LIFETIME']:
                # Session expired
                logout_user()
                session.clear()
                flash('Your session has expired due to inactivity. Please log in again.', 'warning')
                return redirect(url_for('login'))
        
        # Update last activity in session
        session['last_activity'] = datetime.utcnow().isoformat()
    else:
        # Clean up session data for non-authenticated users
        if 'last_activity' in session:
            del session['last_activity']

# -----------------------------------------------------------------------------
# 3) Database + Models (import after app creation)
# -----------------------------------------------------------------------------
from models import db, User, Course, Section, Page, Enrollment  # noqa: E402
db.init_app(app)

# One-time migration: ensure 'cover_image' column exists on 'course'
with app.app_context():
    try:
        from sqlalchemy import text
        cols = db.session.execute(text("PRAGMA table_info(course)")).fetchall()
        names = {c[1] for c in cols}
        if 'cover_image' not in names:
            db.session.execute(text("ALTER TABLE course ADD COLUMN cover_image VARCHAR(255)"))
            db.session.commit()
    except Exception as _e:
        # Non-fatal in case DB isn't initialized yet
        pass

# -----------------------------------------------------------------------------
# 4) Login manager
# -----------------------------------------------------------------------------
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))



#------------------------------------------------------------
# Server Health Monitoring Functions
#------------------------------------------------------------
def get_system_metrics():
    """Get system resource metrics"""
    memory = psutil.virtual_memory()
    memory_data = {
        'total': round(memory.total / (1024**3), 2),
        'used': round(memory.used / (1024**3), 2),
        'available': round(memory.available / (1024**3), 2),
        'percent': memory.percent
    }
    
    disk = psutil.disk_usage('/')
    disk_data = {
        'total': round(disk.total / (1024**3), 2),
        'used': round(disk.used / (1024**3), 2),
        'free': round(disk.free / (1024**3), 2),
        'percent': round((disk.used / disk.total) * 100, 1)
    }
    
    cpu_percent = psutil.cpu_percent(interval=1)
    
    # Load average (Linux/Unix systems)
    try:
        load_avg = os.getloadavg()
        load_data = {
            '1min': round(load_avg[0], 2),
            '5min': round(load_avg[1], 2),
            '15min': round(load_avg[2], 2)
        }
    except (OSError, AttributeError):
        load_data = {'1min': 0, '5min': 0, '15min': 0}
    
    return {
        'memory': memory_data,
        'disk': disk_data,
        'cpu_percent': cpu_percent,
        'load_average': load_data,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


def get_database_health():
    """Get database health metrics"""
    try:
        # Count total records in main tables
        user_count = User.query.count()
        course_count = Course.query.count()
        page_count = Page.query.count()
        feedback_count = CourseFeedback.query.count()
        
        # Get database file size (SQLite)
        db_path = 'instance/portal.db'  # Adjust path if different
        if os.path.exists(db_path):
            db_size = round(os.path.getsize(db_path) / (1024**2), 2)  # MB
        else:
            db_size = 0
        
        # Test database connectivity with a simple query
        db_responsive = True
        try:
            db.session.execute(db.text('SELECT 1')).fetchone()
        except:
            db_responsive = False
            
        return {
            'tables': {
                'users': user_count,
                'courses': course_count,
                'pages': page_count,
                'feedback': feedback_count
            },
            'database_size_mb': db_size,
            'responsive': db_responsive,
            'connection_pool_size': 5,  # Default SQLite doesn't use pools, but we can show this
            'active_connections': 1     # SQLite typically has 1 connection
        }
    except Exception as e:
        return {
            'tables': {'error': str(e)},
            'database_size_mb': 0,
            'responsive': False,
            'connection_pool_size': 0,
            'active_connections': 0
        }



def get_health_status(metrics):
    """Determine overall health status based on metrics"""
    warnings = []
    critical = []
    
    # Memory warnings (adjusted for 8GB Pi)
    if metrics['memory']['percent'] > 85:
        critical.append(f"Critical: RAM usage at {metrics['memory']['percent']}%")
    elif metrics['memory']['percent'] > 70:
        warnings.append(f"Warning: RAM usage at {metrics['memory']['percent']}%")
    
    # Disk warnings (critical for 16GB SD card)
    if metrics['disk']['percent'] > 90:
        critical.append(f"Critical: Disk usage at {metrics['disk']['percent']}%")
    elif metrics['disk']['percent'] > 80:
        warnings.append(f"Warning: Disk usage at {metrics['disk']['percent']}%")
    
    # CPU warnings
    if metrics['cpu_percent'] > 90:
        critical.append(f"Critical: CPU usage at {metrics['cpu_percent']}%")
    elif metrics['cpu_percent'] > 80:
        warnings.append(f"Warning: CPU usage at {metrics['cpu_percent']}%")
    
    # Overall status
    if critical:
        status = 'critical'
    elif warnings:
        status = 'warning'
    else:
        status = 'healthy'
    
    return {
        'status': status,
        'warnings': warnings,
        'critical': critical
    }






# -----------------------------------------------------------------------------
# 5) Admin guard decorator
# -----------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            abort(403)
        return f(*args, **kwargs)
    return wrapper

# -----------------------------------------------------------------------------
# Helper: renumber sections (10, 20, 30 ...)
# -----------------------------------------------------------------------------
def renumber_sections(course_id: int):
    secs = (Section.query
            .filter_by(course_id=course_id)
            .order_by(Section.position, Section.id)
            .all())
    pos = 10
    for s in secs:
        s.position = pos
        pos += 10
    db.session.commit()

ALLOWED_COVER_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

def save_cover_file(upload_file):
    """
    Save uploaded cover file into static/uploads/covers and return
    a relative path like 'uploads/covers/<name>.ext' or None if invalid.
    """
    if not upload_file or not getattr(upload_file, "filename", ""):
        return None
    fname = secure_filename(upload_file.filename.strip())
    if not fname:
        return None
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ALLOWED_COVER_EXTS:
        return None

    covers_dir = os.path.join(app.static_folder, "uploads", "covers")
    os.makedirs(covers_dir, exist_ok=True)
    unique_name = f"{int(time.time())}_{fname}"
    dest_path = os.path.join(covers_dir, unique_name)
    upload_file.save(dest_path)
    # return the path relative to /static so templates can url_for('static', filename=...)
    return f"uploads/covers/{unique_name}"

def allowed_hero_file(filename):
    """Check if hero image file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in HERO_ALLOWED_EXTENSIONS

def resize_hero_image(image_path, max_width=1920, max_height=1080, quality=85):
    """Resize and optimize uploaded hero image"""
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (for JPEG saving)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # Calculate new dimensions while maintaining aspect ratio
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            # Save optimized image
            img.save(image_path, 'JPEG', quality=quality, optimize=True)
            return True
    except Exception as e:
        print(f"Error resizing hero image: {e}")
        return False

# -----------------------------------------------------------------------------
# 6) Public routes
# -----------------------------------------------------------------------------

@app.route('/')
def home():
    # Update user activity if logged in
    if current_user.is_authenticated:
        update_user_activity(current_user.id)
    
    # Get hero image - check for existing uploaded images
    hero_image = None
    
    # Look for the most recent hero image file
    import glob
    hero_files = glob.glob(os.path.join(HERO_UPLOAD_FOLDER, 'hero_*.jpg'))
    hero_files.extend(glob.glob(os.path.join(HERO_UPLOAD_FOLDER, 'hero_*.jpeg')))
    hero_files.extend(glob.glob(os.path.join(HERO_UPLOAD_FOLDER, 'hero_*.png')))
    hero_files.extend(glob.glob(os.path.join(HERO_UPLOAD_FOLDER, 'hero_*.gif')))
    hero_files.extend(glob.glob(os.path.join(HERO_UPLOAD_FOLDER, 'hero_*.webp')))
    
    if hero_files:
        # Get the most recent file
        latest_file = max(hero_files, key=os.path.getctime)
        filename = os.path.basename(latest_file)
        hero_image = f"/static/uploads/hero/{filename}"
    
    return render_template('index.html', hero_image=hero_image)


@app.route('/catalog')
def catalog():
    courses = Course.query.filter_by(published=True).order_by(Course.id.desc()).all()
    return render_template('catalog.html', courses=courses)

@app.route('/course/<int:course_id>')
def course_public(course_id: int):
    course = Course.query.get_or_404(course_id)
    if not course.published and not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        abort(404)

    sections = (Section.query
                .filter_by(course_id=course.id)
                .order_by(Section.position, Section.id)
                .all())
    section_ids = [s.id for s in sections]
    pages_by_section = {}
    if section_ids:
        pages = (Page.query
                 .filter(Page.section_id.in_(section_ids))
                 .order_by(Page.section_id, Page.position, Page.id)
                 .all())
        for p in pages:
            pages_by_section.setdefault(p.section_id, []).append(p)

    is_enrolled = False
    if current_user.is_authenticated:
        is_enrolled = Enrollment.query.filter_by(
            user_id=current_user.id, course_id=course.id
        ).first() is not None

    # Session-based progress (no DB changes)
    total_pages = sum(len(pages_by_section.get(s.id, [])) for s in sections)
    visited = set()
    if current_user.is_authenticated:
        key = f"progress_{current_user.id}_{course.id}"
        visited = set(session.get(key, []))
    done_pages = len(visited)
    pct = int((done_pages / total_pages) * 100) if total_pages else 0

    return render_template('course_public.html', course=course, sections=sections, pages_by_section=pages_by_section, is_enrolled=is_enrolled, progress_total=total_pages, progress_done=done_pages, progress_pct=pct)

@app.route('/page/<int:page_id>')
def page_view(page_id: int):
    page = Page.query.get_or_404(page_id)
    section = Section.query.get_or_404(page.section_id)
    course = Course.query.get_or_404(section.course_id)

    is_admin = current_user.is_authenticated and getattr(current_user, "is_admin", False)
    is_enrolled = False
    if current_user.is_authenticated:
        is_enrolled = Enrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first() is not None

    allowed = page.is_free or is_admin or is_enrolled
    if not allowed:
        flash('This lesson is locked. Please enroll to access.', 'error')
        return redirect(url_for('course_public', course_id=course.id))

    # Safe path resolution
    safe_rel = os.path.normpath(page.filename).lstrip(os.sep)
    abs_path = os.path.abspath(os.path.join(CONTENT_ROOT, safe_rel))
    root = os.path.abspath(CONTENT_ROOT)
    if not (abs_path == root or abs_path.startswith(root + os.sep)):
        abort(404)
    if not os.path.exists(abs_path):
        flash('Content file is missing.', 'error')
        return redirect(url_for('course_public', course_id=course.id))

    with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    # Mark this page as visited for the current user (session-based progress)
    if current_user.is_authenticated:
        key = f"progress_{current_user.id}_{course.id}"
        visited = set(session.get(key, []))
        visited.add(page.id)
        session[key] = list(visited)

    # Build ordered list of all pages in this course (by section and page order)
    pages_all = (Page.query.join(Section, Page.section_id == Section.id)
                   .filter(Section.course_id == course.id)
                   .order_by(Section.position, Section.id, Page.position, Page.id)
                   .all())
    first_id = pages_all[0].id if pages_all else None
    prev_id = next_id = None
    for i, p in enumerate(pages_all):
        if p.id == page.id:
            if i > 0:
                prev_id = pages_all[i-1].id
            if i < len(pages_all) - 1:
                next_id = pages_all[i+1].id
            break

    return render_template('page_viewer.html',
                           course=course, page=page, html=html,
                           prev_id=prev_id, next_id=next_id, first_id=first_id)

@app.route("/healthz")
def healthz():
    return "OK", 200

# -----------------------------------------------------------------------------
# 7) Auth (Register / Login / Logout)
# -----------------------------------------------------------------------------
from flask import request, render_template, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, current_user
from sqlalchemy.exc import IntegrityError

@app.route('/register', methods=['GET', 'POST'])
def register():
    # GET → show form
    if request.method == 'GET':
        return render_template('register.html')

    # POST → process form
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    password2 = request.form.get('password2') or ''

    if not email or not password:
        flash('Email and password are required.', 'error')
        return redirect(url_for('register'))
    if password != password2:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('register'))

    if User.query.filter_by(email=email).first():
        flash('That email is already registered. Please log in.', 'error')
        return redirect(url_for('login'))

    hashed = generate_password_hash(password)
    user = User(email=email, password_hash=hashed, is_admin=False)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('This email is already registered. Please log in.', 'error')
        return redirect(url_for('login'))

    login_user(user)
    flash('Registration successful. You are now logged in.', 'success')
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in and trying to access login page, redirect based on user type
    if current_user.is_authenticated:
        if getattr(current_user, "is_admin", False):
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('my_courses'))

    if request.method == 'GET':
        return render_template('login.html')

    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''

    if not email or not password:
        flash('Email and password are required.', 'error')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        flash('Invalid email or password.', 'error')
        return redirect(url_for('login'))

    login_user(user)
    # Initialize user activity tracking
    update_user_activity(user.id)
    session['last_activity'] = datetime.utcnow().isoformat()
    flash('Welcome back!', 'success')
    
    # Redirect based on user type
    if getattr(user, "is_admin", False):
        return redirect(url_for('admin'))
    else:
        return redirect(url_for('my_courses'))




@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        # Remove user from active users tracking
        user_id = current_user.id
        if user_id in active_users:
            del active_users[user_id]
        logout_user()
        session.clear()
        flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

# -----------------------------------------------------------------------------
# 8) Enrollment + My Courses
# -----------------------------------------------------------------------------
@app.route('/enroll/<int:course_id>', methods=['POST'])
@login_required
def enroll(course_id: int):
    course = Course.query.get_or_404(course_id)

    existing = Enrollment.query.filter_by(
        user_id=current_user.id, course_id=course.id
    ).first()
    if existing:
        flash('You are already enrolled in this course.', 'info')
        return redirect(url_for('course_public', course_id=course.id))

    e = Enrollment(user_id=current_user.id, course_id=course.id)
    db.session.add(e)
    db.session.commit()
    flash('Enrolled successfully!', 'success')
    return redirect(url_for('course_public', course_id=course.id))

@app.route('/my-courses')
@login_required
def my_courses():
    courses = (
        Course.query
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(Enrollment.user_id == current_user.id)
        .order_by(Enrollment.created_at.desc())
        .all()
    )
    return render_template('my_courses.html', courses=courses)

# -----------------------------------------------------------------------------
# 9) Admin-only routes
# -----------------------------------------------------------------------------
@app.route('/admin', strict_slashes=False)
@login_required
@admin_required
def admin():
    # Get active users statistics
    active_count = get_active_users_count()
    active_users_list = get_active_users_list()
    
    return render_template('admin_dashboard.html', 
                         active_users_count=active_count,
                         active_users_list=active_users_list)

@app.route('/admin/active-users')
@login_required
@admin_required
def admin_active_users():
    """Dedicated page for viewing active users"""
    active_users_list = get_active_users_list()
    active_count = len(active_users_list)
    
    return render_template('admin_active_users.html',
                         active_users_list=active_users_list,
                         active_users_count=active_count)

@app.route('/admin/courses')
@login_required
@admin_required
def admin_courses():
    courses = Course.query.order_by(Course.id.desc()).all()
    return render_template('admin_courses.html', courses=courses)


@app.route('/admin/trends')
@login_required
@admin_required
def admin_trends():
    """Admin view for market intelligence trends"""
    from trends_models import TrendData
    
    github_trends = TrendData.query.filter_by(source='github').order_by(TrendData.trend_score.desc()).all()
    
    total_trends = len(github_trends)
    top_language = github_trends[0].keyword if github_trends else "No data"
    
    return render_template('admin_trends.html', 
                         trends=github_trends,
                         total_trends=total_trends,
                         top_language=top_language)






@app.route('/admin/courses/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_courses_new():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        short_desc = (request.form.get('short_desc') or '').strip()
        price_raw = (request.form.get('price') or '0').strip()
        published = bool(request.form.get('published'))

        # Cover upload handling using helper
        cover = request.files.get('cover')
        cover_rel = save_cover_file(cover)

        # Create and save course
        c = Course(
            title=title,
            short_desc=short_desc,
            price=price_raw,
            published=published,
            cover_image=cover_rel
        )
        db.session.add(c)
        db.session.commit()
        flash('Course created.', 'success')
        return redirect(url_for('admin_courses'))

    # GET: show form
    return render_template('admin_course_form.html', course=None)

@app.route('/admin/courses/<int:course_id>')
@login_required
@admin_required
def admin_course_detail(course_id: int):
    course = Course.query.get_or_404(course_id)
    sections = (
        Section.query
        .filter_by(course_id=course.id)
        .order_by(Section.position, Section.id)
        .all()
    )
    section_ids = [s.id for s in sections]
    pages_by_section = {}
    if section_ids:
        pages = (
            Page.query
            .filter(Page.section_id.in_(section_ids))
            .order_by(Page.section_id, Page.position, Page.id)
            .all()
        )
        for p in pages:
            pages_by_section.setdefault(p.section_id, []).append(p)

    return render_template('admin_course_detail.html',
                           course=course,
                           sections=sections,
                           pages_by_section=pages_by_section)

@app.route('/admin/courses/<int:course_id>/cover', methods=['POST'])
@login_required
@admin_required
def admin_course_cover(course_id: int):
    course = Course.query.get_or_404(course_id)
    file = request.files.get('cover')
    path = save_cover_file(file)
    if not path:
        flash('Please upload a valid image (jpg, png, gif, or webp).', 'error')
        return redirect(url_for('admin_course_detail', course_id=course.id))
    course.cover_image = path
    db.session.commit()
    flash('Cover image updated.', 'success')
    return redirect(url_for('admin_course_detail', course_id=course.id))

@app.route('/admin/courses/<int:course_id>/sections/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_sections_new(course_id: int):
    course = Course.query.get_or_404(course_id)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        pos_raw = (request.form.get('position') or '').strip()
        try:
            position = int(pos_raw) if pos_raw else 0
        except Exception:
            position = 0

        if not title:
            flash('Section title is required.', 'error')
            return redirect(url_for('admin_sections_new', course_id=course.id))

        s = Section(course_id=course.id, title=title, position=position)
        db.session.add(s)
        db.session.commit()

        renumber_sections(course.id)

        flash('Section created.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course.id))

    default_pos = request.args.get('position', type=int)
    return render_template('admin_section_form.html', course=course, initial_position=default_pos)

@app.route('/admin/sections/<int:section_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_section_edit(section_id: int):
    section = Section.query.get_or_404(section_id)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        pos_raw = (request.form.get('position') or '').strip() or '0'
        try:
            position = int(pos_raw)
        except Exception:
            position = 0
        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('admin_section_edit', section_id=section.id))
        section.title = title
        section.position = position
        db.session.commit()
        renumber_sections(section.course_id)
        flash('Section updated.', 'success')
        return redirect(url_for('admin_course_detail', course_id=section.course_id))
    return render_template('admin_section_form.html', section=section)

@app.route('/admin/sections/<int:section_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_section_delete(section_id: int):
    section = Section.query.get_or_404(section_id)
    course_id = section.course_id
    Page.query.filter_by(section_id=section.id).delete(synchronize_session=False)
    db.session.delete(section)
    db.session.commit()
    renumber_sections(course_id)
    flash('Section deleted.', 'success')
    return redirect(url_for('admin_course_detail', course_id=course_id))

@app.route('/admin/sections/<int:section_id>/pages/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_pages_new(section_id: int):
    section = Section.query.get_or_404(section_id)
    course = Course.query.get_or_404(section.course_id)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        rel_filename = (request.form.get('filename') or '').strip()
        is_free = bool(request.form.get('is_free'))
        pos_raw = (request.form.get('position') or '').strip()

        upload = request.files.get('file')
        if upload and upload.filename:
            name = secure_filename(upload.filename)
            ext = os.path.splitext(name)[1].lower()
            if ext not in {'.html', '.htm'}:
                flash('Only .html or .htm files are allowed.', 'error')
                return redirect(url_for('admin_pages_new', section_id=section.id))
            unique = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{name}"
            abs_path_upload = os.path.join(PAGES_DIR, unique)
            upload.save(abs_path_upload)
            rel_filename = f"pages/{unique}"

# Process resource files if uploaded
            resource_files = request.files.getlist('resources')
            auto_fix_links = bool(request.form.get('auto_fix_links'))
            
            if resource_files and auto_fix_links:
                # Read the HTML content to fix resource links
                with open(abs_path_upload, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                # Replace /resources/ with /download/ in the HTML
                updated_content = html_content.replace('/resources/', '/download/')
                
                # Write back the updated content
                with open(abs_path_upload, 'w', encoding='utf-8') as f:
                    f.write(updated_content)


# Save uploaded resource files
            for resource_file in resource_files:
                if resource_file and resource_file.filename:
                    safe_resource_name = secure_filename(resource_file.filename)
                    resource_path = os.path.join(RESOURCES_DIR, safe_resource_name)
                    resource_file.save(resource_path)
                    
                    # Record in database (we'll add this after creating the page)
                    # Will be added after page creation below







        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('admin_pages_new', section_id=section.id))
        if not rel_filename:
            flash('Please provide a filename or upload an HTML file.', 'error')
            return redirect(url_for('admin_pages_new', section_id=section.id))

        safe_rel = os.path.normpath(rel_filename).lstrip(os.sep)
        abs_path = os.path.abspath(os.path.join(CONTENT_ROOT, safe_rel))
        if not abs_path.startswith(os.path.abspath(CONTENT_ROOT) + os.sep) and abs_path != os.path.abspath(CONTENT_ROOT):
            flash('Invalid filename/path.', 'error')
            return redirect(url_for('admin_pages_new', section_id=section.id))

        try:
            position = int(pos_raw) if pos_raw else None
        except Exception:
            position = None
        if position is None:
            last = (Page.query.filter_by(section_id=section.id)
                             .order_by(Page.position.desc(), Page.id.desc())
                             .first())
            position = (last.position + 1) if last else 1

        if not os.path.exists(abs_path):
            flash('Note: file not found on disk yet. You can add it later under content/.', 'info')

        p = Page(section_id=section.id, title=title, filename=safe_rel, is_free=is_free, position=position)
        db.session.add(p)
        db.session.commit()



# Save resource file records to database if any were uploaded
        if 'resource_files' in locals():
            for resource_file in resource_files:
                if resource_file and resource_file.filename:
                    safe_resource_name = secure_filename(resource_file.filename)
                    file_size = os.path.getsize(os.path.join(RESOURCES_DIR, safe_resource_name))
                    file_ext = os.path.splitext(safe_resource_name)[1].lower()
                    
                    # Create database record
                    from models import PageResource  # We'll need to add this model
                    resource_record = PageResource(
                        page_id=p.id,
                        original_filename=resource_file.filename,
                        stored_filename=safe_resource_name,
                        file_size=file_size,
                        file_type=file_ext
                    )
                    db.session.add(resource_record)
            
            db.session.commit()






        flash('Page created.', 'success')
        return redirect(url_for('admin_course_detail', course_id=course.id))
    return render_template('admin_page_form.html', course=course, section=section)

@app.route('/admin/pages/<int:page_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_page_edit(page_id: int):
    page = Page.query.get_or_404(page_id)
    section = Section.query.get_or_404(page.section_id)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        new_filename = (request.form.get('filename') or '').strip()
        is_free = bool(request.form.get('is_free'))
        pos_raw = (request.form.get('position') or '').strip() or '0'

        upload = request.files.get('file')
        if upload and upload.filename:
            name = secure_filename(upload.filename)
            ext = os.path.splitext(name)[1].lower()
            if ext not in {'.html', '.htm'}:
                flash('Only .html or .htm files are allowed.', 'error')
                return redirect(url_for('admin_page_edit', page_id=page.id))
            unique = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{name}"
            abs_path_upload = os.path.join(PAGES_DIR, unique)
            upload.save(abs_path_upload)
            new_filename = f"pages/{unique}"

        try:
            position = int(pos_raw)
        except Exception:
            position = 0
        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('admin_page_edit', page_id=page.id))
        if not new_filename:
            flash('Filename is required.', 'error')
            return redirect(url_for('admin_page_edit', page_id=page.id))

        safe_rel = os.path.normpath(new_filename).lstrip(os.sep)
        abs_path = os.path.abspath(os.path.join(CONTENT_ROOT, safe_rel))
        if not abs_path.startswith(os.path.abspath(CONTENT_ROOT) + os.sep) and abs_path != os.path.abspath(CONTENT_ROOT):
            flash('Invalid filename/path.', 'error')
            return redirect(url_for('admin_page_edit', page_id=page.id))

        page.title = title
        page.filename = safe_rel
        page.is_free = is_free
        page.position = position
        db.session.commit()
        flash('Page updated.', 'success')
        return redirect(url_for('admin_course_detail', course_id=section.course_id))
    return render_template('admin_page_form.html', page=page, section=section, course=Course.query.get(section.course_id))

@app.route('/admin/pages/<int:page_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_page_delete(page_id: int):
    page = Page.query.get_or_404(page_id)
    section = Section.query.get_or_404(page.section_id)
    course_id = section.course_id
    db.session.delete(page)
    db.session.commit()
    flash('Page deleted.', 'success')
    return redirect(url_for('admin_course_detail', course_id=course_id))

@app.route('/admin/courses/<int:course_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_course_delete(course_id: int):
    course = Course.query.get_or_404(course_id)

    Enrollment.query.filter_by(course_id=course.id).delete(synchronize_session=False)

    sections = Section.query.filter_by(course_id=course.id).all()
    section_ids = [s.id for s in sections]
    if section_ids:
        Page.query.filter(Page.section_id.in_(section_ids)).delete(synchronize_session=False)
        Section.query.filter(Section.id.in_(section_ids)).delete(synchronize_session=False)

    db.session.delete(course)
    db.session.commit()

    flash('Course deleted.', 'success')
    return redirect(url_for('admin_courses'))




# -----------------------------------------------------------------------------
# NEW ROUTES FOR COURSE EDIT/DELETE - Added for course title management
# -----------------------------------------------------------------------------

@app.route('/admin/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_course_edit(course_id: int):
    """
    NEW ROUTE: Edit course title and details
    Added to allow admins to rename courses
    """
    course = Course.query.get_or_404(course_id)
    
    if request.method == 'POST':
        # Get form data
        title = (request.form.get('title') or '').strip()
        short_desc = (request.form.get('short_desc') or '').strip()
        price_raw = (request.form.get('price') or '0').strip()
        published = bool(request.form.get('published'))
        
        # Validate title
        if not title:
            flash('Course title is required.', 'error')
            return redirect(url_for('admin_course_edit', course_id=course_id))
        
        # Check for duplicate title (excluding current course)
        existing = Course.query.filter(
            Course.title == title,
            Course.id != course_id
        ).first()
        if existing:
            flash('A course with this title already exists.', 'error')
            return redirect(url_for('admin_course_edit', course_id=course_id))
        
        # Handle cover image upload if provided
        cover = request.files.get('cover')
        if cover and cover.filename:
            cover_rel = save_cover_file(cover)
            if cover_rel:
                course.cover_image = cover_rel
        
        # Update course details
        course.title = title
        course.short_desc = short_desc
        try:
            course.price = int(price_raw) if price_raw else 0
        except ValueError:
            course.price = 0
        course.published = published
        
        # Save changes
        db.session.commit()
        flash(f'Course "{title}" has been updated successfully.', 'success')
        return redirect(url_for('admin_courses'))
    
    # GET request - show edit form
    return render_template('admin_course_form.html', course=course, edit_mode=True)

@app.route('/admin/courses/<int:course_id>/delete-confirm')
@login_required
@admin_required
def admin_course_delete_confirm(course_id: int):
    """
    NEW ROUTE: Show confirmation page before deleting a course
    Added for safer deletion with proper warning
    """
    course = Course.query.get_or_404(course_id)
    
    # Get statistics about what will be deleted
    sections = Section.query.filter_by(course_id=course.id).all()
    section_ids = [s.id for s in sections]
    
    total_sections = len(sections)
    total_pages = 0
    if section_ids:
        total_pages = Page.query.filter(Page.section_id.in_(section_ids)).count()
    
    total_enrollments = Enrollment.query.filter_by(course_id=course.id).count()
    
    return render_template('admin_course_delete_confirm.html',
                         course=course,
                         total_sections=total_sections,
                         total_pages=total_pages,
                         total_enrollments=total_enrollments)



# Add this right after the admin_course_delete_confirm route (around line 920)
# and before the "Hero Image Upload Routes" comment



# -----------------------------------------------------------------------------
# SERVER HEALTH MONITORING ROUTES - Admin system monitoring
# -----------------------------------------------------------------------------

@app.route('/admin/server-health')
@login_required
@admin_required
def admin_server_health():
    """Server health monitoring dashboard"""
    try:
        # Get system metrics
        system_metrics = get_system_metrics()
        
        # Get database health
        db_health = get_database_health()
        
        # Get health status and warnings
        health_status = get_health_status(system_metrics)
        
        return render_template('admin_server_health.html',
                             system_metrics=system_metrics,
                             db_health=db_health,
                             health_status=health_status)
    
    except Exception as e:
        flash(f'Error retrieving server health data: {str(e)}', 'error')
        return redirect(url_for('admin'))




# -----------------------------------------------------------------------------
# ADMIN FEEDBACK MANAGEMENT ROUTES - View user feedback and analytics
# -----------------------------------------------------------------------------

@app.route('/admin/feedback')
@login_required
@admin_required
def admin_feedback_dashboard():
    """Main feedback dashboard showing overview and user list"""
    # Get all users who have submitted feedback with their feedback counts
    users_with_feedback_query = (db.session.query(
        User.id,
        User.email,
        db.func.count(CourseFeedback.id).label('feedback_count'),
        db.func.max(CourseFeedback.created_at).label('latest_feedback')
    )
    .join(CourseFeedback, User.id == CourseFeedback.user_id)
    .group_by(User.id, User.email)
    .all())
    
    # Convert to list of dictionaries for easier template access
    users_with_feedback = []
    for user_data in users_with_feedback_query:
        users_with_feedback.append({
            'id': user_data.id,
            'email': user_data.email,
            'feedback_count': user_data.feedback_count,
            'latest_feedback': user_data.latest_feedback
        })
    
    # Get feedback statistics
    total_feedback = CourseFeedback.query.count()
    unique_users = len(users_with_feedback)
    
    # Get feedback by trigger type
    feedback_by_trigger = {}
    for trigger in ['chapter_2', 'mid_course', 'completion']:
        count = CourseFeedback.query.filter_by(trigger_type=trigger).count()
        feedback_by_trigger[trigger] = count
    
    return render_template('admin_feedback_dashboard.html',
                         users_with_feedback=users_with_feedback,
                         total_feedback=total_feedback,
                         unique_users=unique_users,
                         feedback_by_trigger=feedback_by_trigger)




@app.route('/admin/feedback/user/<int:user_id>')
@login_required
@admin_required
def admin_user_feedback(user_id):
    """View specific user's feedback across all their courses"""
    user = User.query.get_or_404(user_id)
    
    # Get all courses this user has feedback for
    courses_with_feedback = (db.session.query(Course)
                            .join(CourseFeedback, Course.id == CourseFeedback.course_id)
                            .filter(CourseFeedback.user_id == user_id)
                            .distinct()
                            .all())
    
    # Get all feedback for this user organized by course
    feedback_by_course = {}
    for course in courses_with_feedback:
        feedback_entries = (CourseFeedback.query
                           .filter_by(user_id=user_id, course_id=course.id)
                           .order_by(CourseFeedback.created_at.desc())
                           .all())
        feedback_by_course[course.id] = feedback_entries
    
    return render_template('admin_user_feedback.html',
                         user=user,
                         courses_with_feedback=courses_with_feedback,
                         feedback_by_course=feedback_by_course)





# -----------------------------------------------------------------------------
# MARKET INTELLIGENCE INTEGRATION - Job Market API Client and Routes
# -----------------------------------------------------------------------------

import requests
from datetime import datetime, timedelta
import json

class MarketIntelligenceClient:
    """Client to interact with the job market intelligence API"""
    
    def __init__(self, api_base_url="https://api.wiabtech.in"):
        self.api_base_url = api_base_url
    
    def get_skills_data(self):
        """Fetch skills data from external API"""
        try:
            response = requests.get(f"{self.api_base_url}/api/job-market/skills", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching skills data: {e}")
            return {"skills": []}
    
    def get_course_recommendations(self):
        """Fetch course recommendations"""
        try:
            response = requests.get(f"{self.api_base_url}/api/job-market/course-recommendations", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching recommendations: {e}")
            return {"course_recommendations": []}
    
    def get_market_summary(self):
        """Generate market summary statistics"""
        skills_data = self.get_skills_data()
        recommendations_data = self.get_course_recommendations()
        
        if not skills_data.get("skills"):
            return {
                "total_skills": 0,
                "high_priority": 0,
                "niche_opportunities": 0,
                "low_priority": 0,
                "top_skill": "No data available",
                "last_updated": "N/A"
            }
        
        skills = skills_data["skills"]
        recommendations = recommendations_data.get("course_recommendations", [])
        
        # Categorize by priority
        high_priority = len([r for r in recommendations if r.get("priority") == "HIGH_PRIORITY"])
        niche_opportunities = len([r for r in recommendations if r.get("priority") == "NICHE_OPPORTUNITY"])
        low_priority = len([r for r in recommendations if r.get("priority") == "LOW_PRIORITY"])
        
        # Find top skill
        top_skill = "No data"
        if skills:
            top_skill_data = max(skills, key=lambda x: x.get("demand", 0))
            job_count = top_skill_data.get('demand', 0)
            job_display = f"{job_count}+" if job_count == 30 else str(job_count)
            top_skill = f"{top_skill_data.get('skill', 'Unknown')} ({job_display} jobs)"


        
        return {
            "total_skills": len(skills),
            "high_priority": high_priority,
            "niche_opportunities": niche_opportunities,
            "low_priority": low_priority,
            "top_skill": top_skill,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "skills": skills[:10],  # Top 10 for dashboard display
            "recommendations": recommendations[:5]  # Top 5 recommendations
        }

# Initialize the market intelligence client
market_client = MarketIntelligenceClient()

@app.route('/admin/market-intelligence')
@login_required
@admin_required
def admin_market_intelligence():
    """Enhanced market intelligence dashboard"""
    try:
        # Get comprehensive market data
        market_summary = market_client.get_market_summary()
        skills_data = market_client.get_skills_data()
        recommendations_data = market_client.get_course_recommendations()
        
        # Process data for charts and widgets
        skills = skills_data.get("skills", [])
        recommendations = recommendations_data.get("course_recommendations", [])
        
        # Prepare chart data
        priority_distribution = {
            "HIGH_PRIORITY": len([r for r in recommendations if r.get("priority") == "HIGH_PRIORITY"]),
            "NICHE_OPPORTUNITY": len([r for r in recommendations if r.get("priority") == "NICHE_OPPORTUNITY"]),
            "LOW_PRIORITY": len([r for r in recommendations if r.get("priority") == "LOW_PRIORITY"])
        }
        
        # Top skills for display
        top_skills = sorted(skills, key=lambda x: x.get("demand", 0), reverse=True)[:10]
        
        # Skills to avoid (low demand)
        avoid_skills = [s for s in skills if s.get("demand", 0) <= 2]
        
        return render_template('admin_market_intelligence.html',
                             market_summary=market_summary,
                             top_skills=top_skills,
                             avoid_skills=avoid_skills,
                             priority_distribution=priority_distribution,
                             recommendations=recommendations)
    
    except Exception as e:
        flash(f'Error loading market intelligence data: {str(e)}', 'error')
        return redirect(url_for('admin'))

@app.route('/api/admin/market-summary')
@login_required
@admin_required
def api_admin_market_summary():
    """API endpoint for real-time market summary data"""
    try:
        summary = market_client.get_market_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/refresh-market-data')
@login_required
@admin_required
def api_refresh_market_data():
    """Refresh market intelligence data"""
    try:
        # Force refresh by creating new client instance
        global market_client
        market_client = MarketIntelligenceClient()
        summary = market_client.get_market_summary()
        return jsonify({
            "success": True, 
            "message": "Market data refreshed successfully",
            "summary": summary
        })
    except Exception as e:
        return jsonify({
            "success": False, 
            "message": f"Error refreshing data: {str(e)}"
        }), 500






# Add these new routes to your app.py file after the existing market intelligence routes

@app.route('/api/admin/skills-by-priority/<priority>')
@login_required
@admin_required
def api_skills_by_priority(priority):
    """Get skills filtered by priority level"""
    try:
        recommendations_data = market_client.get_course_recommendations()
        recommendations = recommendations_data.get("course_recommendations", [])
        
        # Filter by priority
        filtered_skills = [r for r in recommendations if r.get("priority") == priority]
        
        # Sort by job demand
        filtered_skills.sort(key=lambda x: x.get("job_demand", 0), reverse=True)
        
        return jsonify({
            "priority": priority,
            "count": len(filtered_skills),
            "skills": filtered_skills
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/all-skills-data')
@login_required
@admin_required
def api_all_skills_data():
    """Get all skills with detailed breakdown"""
    try:
        skills_data = market_client.get_skills_data()
        recommendations_data = market_client.get_course_recommendations()
        
        skills = skills_data.get("skills", [])
        recommendations = recommendations_data.get("course_recommendations", [])
        
        # Create comprehensive data structure
        all_skills_with_priority = []
        
        for skill in skills:
            # Find matching recommendation to get priority
            matching_rec = next((r for r in recommendations if r.get("skill") == skill.get("skill")), None)
            priority = matching_rec.get("priority", "UNKNOWN") if matching_rec else "UNKNOWN"
            
            all_skills_with_priority.append({
                "skill": skill.get("skill"),
                "demand": skill.get("demand", 0),
                "source": skill.get("source"),
                "priority": priority
            })
        
        # Sort by demand
        all_skills_with_priority.sort(key=lambda x: x.get("demand", 0), reverse=True)
        
        return jsonify({
            "total_skills": len(all_skills_with_priority),
            "skills": all_skills_with_priority
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500








# -----------------------------------------------------------------------------
# Hero Image Upload Routes (Admin Only)
# -----------------------------------------------------------------------------
@app.route('/upload-hero-image', methods=['POST'])
@login_required
@admin_required
def upload_hero_image():
    """Handle hero image upload (Admin only)"""
    # Check if file is present in request
    if 'heroImage' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    
    file = request.files['heroImage']
    
    # Check if file is selected
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning
    
    if file_size > HERO_MAX_FILE_SIZE:
        return jsonify({'success': False, 'message': 'File too large. Maximum size is 5MB'}), 400
    
    if file and allowed_hero_file(file.filename):
        try:
            # Generate unique filename
            file_extension = secure_filename(file.filename).rsplit('.', 1)[1].lower()
            unique_filename = f"hero_{uuid.uuid4().hex[:8]}.{file_extension}"
            file_path = os.path.join(HERO_UPLOAD_FOLDER, unique_filename)
            
            # Save the file
            file.save(file_path)
            
            # Resize and optimize the image
            if resize_hero_image(file_path):
                # Remove old hero image if exists
                old_hero = session.get('hero_image')
                if old_hero and old_hero.startswith('/static/uploads/hero/'):
                    old_path = old_hero[1:]  # Remove leading slash
                    old_full_path = os.path.join(BASE_DIR, old_path)
                    if os.path.exists(old_full_path) and 'hero_' in old_path:
                        try:
                            os.remove(old_full_path)
                        except:
                            pass  # Ignore if file doesn't exist
                
                # Store new hero image path in session
                hero_image_url = f"/static/uploads/hero/{unique_filename}"
                # Don't store in session anymore since we auto-detect files
                pass

                
                return jsonify({
                    'success': True, 
                    'message': 'Hero image uploaded successfully!',
                    'image_url': hero_image_url
                })
            else:
                # Remove file if resize failed
                if os.path.exists(file_path):
                    os.remove(file_path)
                return jsonify({'success': False, 'message': 'Error processing image'}), 500
                
        except Exception as e:
            return jsonify({'success': False, 'message': f'Upload failed: {str(e)}'}), 500
    
    return jsonify({'success': False, 'message': 'Invalid file type. Please upload PNG, JPG, JPEG, GIF, or WebP files.'}), 400

@app.route('/delete-hero-image', methods=['POST'])
@login_required
@admin_required
def delete_hero_image():
    """Delete current hero image (Admin only)"""
    try:
        # Get current hero image
        current_hero = session.get('hero_image')
        if current_hero and current_hero.startswith('/static/uploads/hero/'):
            file_path = current_hero[1:]  # Remove leading slash
            full_path = os.path.join(BASE_DIR, file_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        
        # Remove from session
        session.pop('hero_image', None)
        
        return jsonify({'success': True, 'message': 'Hero image deleted successfully!'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Delete failed: {str(e)}'}), 500

# -----------------------------------------------------------------------------
# 10) Error handlers
# -----------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(_e):
    return render_template('403.html'), 403


# -----------------------------------------------------------------------------
# API ENDPOINTS FOR FEEDBACK SYSTEM - Added for user progress tracking
# -----------------------------------------------------------------------------
# These routes handle AJAX requests from the frontend to track user progress
# and determine when to trigger feedback popups based on milestones:
# - chapter_2: After completing 2 pages/chapters
# - mid_course: After completing 50% of course content
# - completion: After completing 100% of course content
# 
# The system prevents duplicate feedback requests using milestone tracking
# stored in the user_progress table with JSON arrays for completed pages
# and feedback triggers already shown to each user per course.
# -----------------------------------------------------------------------------

@app.route('/api/update_progress', methods=['POST'])
@login_required
def update_progress():
    """API endpoint to update user progress and check feedback triggers"""
    data = request.get_json()
    page_id = data.get('page_id')
    course_id = data.get('course_id')
    
    if not page_id or not course_id:
        return jsonify({'error': 'Missing page_id or course_id'}), 400
    
    # Update user progress
    pages_completed = update_user_progress(current_user.id, course_id, page_id)
    
    # Check if feedback should be triggered
    trigger_type = None
    if should_show_feedback(current_user.id, course_id, "chapter_2"):
        trigger_type = "chapter_2"
    elif should_show_feedback(current_user.id, course_id, "mid_course"):
        trigger_type = "mid_course"
    elif should_show_feedback(current_user.id, course_id, "completion"):
        trigger_type = "completion"
    
    return jsonify({
        'pages_completed': pages_completed,
        'show_feedback': trigger_type is not None,
        'trigger_type': trigger_type
    })



@app.route('/api/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    """API endpoint to submit user feedback for courses"""
    data = request.get_json()
    
    course_id = data.get('course_id')
    page_id = data.get('page_id')
    trigger_type = data.get('trigger_type')
    content_quality = data.get('content_quality_rating')
    difficulty = data.get('difficulty_rating')
    career_relevance = data.get('career_relevance_rating')
    technical_issues = data.get('technical_issues_rating')
    comments = data.get('comments', '').strip()
    
    if not course_id or not trigger_type:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    try:
        # Create feedback record
        feedback = CourseFeedback(
            user_id=current_user.id,
            course_id=course_id,
            page_id=page_id,
            trigger_type=trigger_type,
            content_quality_rating=content_quality,
            difficulty_rating=difficulty,
            career_relevance_rating=career_relevance,
            technical_issues_rating=technical_issues,
            comments=comments if comments else None
        )
        
        db.session.add(feedback)
        
        # Mark this feedback trigger as completed
        mark_feedback_trigger_completed(current_user.id, course_id, trigger_type)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Feedback submitted successfully!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'message': f'Error saving feedback: {str(e)}'
        }), 500




# File Download Routes
RESOURCES_DIR = os.path.join(os.getcwd(), 'content', 'pages', 'resources')


@app.route('/download/<filename>')
@login_required
def download_file(filename):
    """Serve downloadable resource files from organized structure"""
    try:
        safe_filename = secure_filename(filename)
        
        # Search through all course/page directories for the file
        for course_dir in os.listdir(RESOURCES_DIR):
            course_path = os.path.join(RESOURCES_DIR, course_dir)
            if not os.path.isdir(course_path) or not course_dir.startswith('course_'):
                continue
                
            for page_dir in os.listdir(course_path):
                page_path = os.path.join(course_path, page_dir)
                if not os.path.isdir(page_path):
                    continue
                    
                file_path = os.path.join(page_path, safe_filename)
                if os.path.exists(file_path):
                    print(f"Serving file: {file_path}")
                    return send_from_directory(
                        page_path,
                        safe_filename,
                        as_attachment=True,
                        download_name=safe_filename
                    )
        
        # Fallback: check root resources directory for legacy files
        root_file_path = os.path.join(RESOURCES_DIR, safe_filename)
        if os.path.exists(root_file_path):
            print(f"Serving legacy file: {root_file_path}")
            return send_from_directory(
                RESOURCES_DIR,
                safe_filename,
                as_attachment=True,
                download_name=safe_filename
            )
        
        print(f"File not found: {safe_filename}")
        abort(404)
        
    except Exception as e:
        print(f"Download error: {e}")
        abort(404)




@app.route('/api/resources')
@login_required
def list_resources():
    """List all available resource files"""
    try:
        if not os.path.exists(RESOURCES_DIR):
            return jsonify({'resources': []})
        
        files = []
        for filename in os.listdir(RESOURCES_DIR):
            file_path = os.path.join(RESOURCES_DIR, filename)
            if os.path.isfile(file_path):
                files.append({
                    'filename': filename,
                    'download_url': f'/download/{filename}',
                    'size': os.path.getsize(file_path)
                })
        
        return jsonify({'resources': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500







# -----------------------------------------------------------------------------
# 11) Entry point (dev only)
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=8000)


# -----------------------------------------------------------------------------
# NEW FEEDBACK SYSTEM FUNCTIONS - Added for milestone tracking
# -----------------------------------------------------------------------------

import json
from models import UserProgress, CourseFeedback

def get_or_create_user_progress(user_id, course_id):
    """Get existing progress or create new progress record for user/course"""
    progress = UserProgress.query.filter_by(user_id=user_id, course_id=course_id).first()
    if not progress:
        progress = UserProgress(
            user_id=user_id,
            course_id=course_id,
            pages_completed='[]',
            feedback_triggers_shown='[]'
        )
        db.session.add(progress)
        db.session.commit()
    return progress



def update_user_progress(user_id, course_id, page_id):
    """Update user progress when they complete a page"""
    progress = get_or_create_user_progress(user_id, course_id)
    
    # Parse completed pages
    completed_pages = json.loads(progress.pages_completed or '[]')
    
    # Add page if not already completed
    if page_id not in completed_pages:
        completed_pages.append(page_id)
        progress.pages_completed = json.dumps(completed_pages)
        progress.updated_at = datetime.utcnow()
        db.session.commit()
    
    return len(completed_pages)





def should_show_feedback(user_id, course_id, trigger_type):
    """Check if user should see feedback popup for this milestone"""
    progress = get_or_create_user_progress(user_id, course_id)
    
    # Parse completed triggers
    completed_triggers = json.loads(progress.feedback_triggers_shown or '[]')
    
    # Check if this trigger was already shown
    if trigger_type in completed_triggers:
        return False
    
    # Parse completed pages
    completed_pages = json.loads(progress.pages_completed or '[]')
    pages_count = len(completed_pages)
    
    # Check milestone requirements
    if trigger_type == "chapter_2" and pages_count >= 2:
        return True
    elif trigger_type == "mid_course":
        # Get total pages in course to calculate percentage
        course = Course.query.get(course_id)
        sections = Section.query.filter_by(course_id=course_id).all()
        section_ids = [s.id for s in sections]
        total_pages = Page.query.filter(Page.section_id.in_(section_ids)).count() if section_ids else 0
        completion_pct = (pages_count / total_pages * 100) if total_pages > 0 else 0
        return completion_pct >= 50
    elif trigger_type == "completion":
        # Check if course is 100% complete
        course = Course.query.get(course_id)
        sections = Section.query.filter_by(course_id=course_id).all()
        section_ids = [s.id for s in sections]
        total_pages = Page.query.filter(Page.section_id.in_(section_ids)).count() if section_ids else 0
        return pages_count >= total_pages
    
    return False




def mark_feedback_trigger_completed(user_id, course_id, trigger_type):
    """Mark a feedback trigger as completed for this user/course"""
    progress = get_or_create_user_progress(user_id, course_id)
    
    # Parse completed triggers
    completed_triggers = json.loads(progress.feedback_triggers_shown or '[]')
    
    # Add trigger if not already marked
    if trigger_type not in completed_triggers:
        completed_triggers.append(trigger_type)
        progress.feedback_triggers_shown = json.dumps(completed_triggers)
        progress.updated_at = datetime.utcnow()
        db.session.commit()
