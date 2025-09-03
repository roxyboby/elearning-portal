#!/usr/bin/env python3
"""
Database migration script to add feedback system tables
Run this once to create UserProgress and CourseFeedback tables
"""

from app import app, db
from models import UserProgress, CourseFeedback

def create_feedback_tables():
    with app.app_context():
        try:
            # Create the new tables
            db.create_all()
            print("SUCCESS: Feedback tables created successfully!")
            print("- user_progress table created")
            print("- course_feedback table created")
            
        except Exception as e:
            print(f"ERROR: {e}")
            print("Tables may already exist or there's a configuration issue")

if __name__ == "__main__":
    create_feedback_tables()
