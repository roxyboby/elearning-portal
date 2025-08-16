from app import app, db
from models import *
with app.app_context():
    db.create_all()
    print("DB initialized: tables created (if not present).")
