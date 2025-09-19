from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Map Python attribute 'password_hash' to the existing DB column named 'password'
    password_hash = db.Column('password', db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

class Course(db.Model):
    __tablename__ = 'course'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    short_desc = db.Column(db.Text, nullable=True)
    price = db.Column(db.Integer, default=0, nullable=False)
    published = db.Column(db.Boolean, default=False, nullable=False)
    cover_image = db.Column(db.String(255), nullable=True)  # path under /static

class Section(db.Model):
    __tablename__ = 'section'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)

class Page(db.Model):
    __tablename__ = 'page'
    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(1024), nullable=False)  # relative to content root
    is_free = db.Column(db.Boolean, default=False, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)

class Enrollment(db.Model):
    __tablename__ = 'enrollment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class UserProgress(db.Model):
    __tablename__ = 'user_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    pages_completed = db.Column(db.Text, nullable=True)  # JSON array of page IDs
    feedback_triggers_shown = db.Column(db.Text, nullable=True)  # JSON array of trigger types
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class CourseFeedback(db.Model):
    __tablename__ = 'course_feedback'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False, index=True)
    page_id = db.Column(db.Integer, db.ForeignKey('page.id'), nullable=True, index=True)
    trigger_type = db.Column(db.String(50), nullable=False)  # 'chapter_2', 'mid_course', 'completion', 'manual'
    content_quality_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    difficulty_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    career_relevance_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    technical_issues_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class PageResource(db.Model):
    __tablename__ = 'page_resources'
    
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('page.id'), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(50))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    page = db.relationship('Page', backref=db.backref('resources', lazy=True, cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<PageResource {self.original_filename}>'
