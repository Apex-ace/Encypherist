from app import app, db
from app import User, Event, Booking, Message, Notification, NotificationPreference, Review, UserActivity, SystemBackup

def init_db():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Create admin user if it doesn't exist
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            from werkzeug.security import generate_password_hash
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully!")
        
        print("Database initialized successfully!")

if __name__ == '__main__':
    init_db() 