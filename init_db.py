from app import app, db
from app import User, Event, Booking, Message, Notification, NotificationPreference, Review, UserActivity, SystemBackup
import os

def init_db():
    with app.app_context():
        try:
            # Drop all tables first to ensure clean state
            db.drop_all()
            
            # Create all tables
            db.create_all()
            print("Database tables created successfully!")
            
            # Create admin user if it doesn't exist
            admin = User.query.filter_by(username='admin@gmail.com').first()
            if not admin:
                from werkzeug.security import generate_password_hash
                admin = User(
                    username='admin@gmail.com',
                    password=generate_password_hash('123456789'),
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
                print("Admin user created successfully!")
            
            print("Database initialized successfully!")
            
        except Exception as e:
            print(f"Error initializing database: {str(e)}")
            db.session.rollback()
            raise e

if __name__ == '__main__':
    print("Starting database initialization...")
    print(f"Database URL: {app.config['SQLALCHEMY_DATABASE_URI']}")
    init_db() 