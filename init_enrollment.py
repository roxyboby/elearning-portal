from app import app, db
from models import Enrollment
with app.app_context():
    db.create_all()
    print("Enrollments =", Enrollment.query.count())
