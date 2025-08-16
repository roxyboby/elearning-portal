from app import app, db
from models import Enrollment, User, Course
from collections import defaultdict

with app.app_context():
    rows = (
        db.session.query(Enrollment.id, User.email, Course.title, Enrollment.created_at)
        .join(User, Enrollment.user_id == User.id)
        .join(Course, Enrollment.course_id == Course.id)
        .order_by(Enrollment.created_at.desc())
        .all()
    )

    print(f"Total enrollments = {len(rows)}")
    for rid, email, title, created in rows:
        print(f"- #{rid}: {email} -> {title} @ {created}")

    # Check for duplicate pairs (should be none due to unique constraint)
    dup_check = (
        db.session.query(Enrollment.user_id, Enrollment.course_id, db.func.count(Enrollment.id))
        .group_by(Enrollment.user_id, Enrollment.course_id)
        .having(db.func.count(Enrollment.id) > 1)
        .all()
    )
    if dup_check:
        print("\nWARNING: Duplicate (user, course) pairs found:")
        for uid, cid, cnt in dup_check:
            u = User.query.get(uid)
            c = Course.query.get(cid)
            print(f"  {u.email} x {c.title}: {cnt} rows")
    else:
        print("\nNo duplicate (user, course) pairs found.")

