from app import app, db
from app import User, Event, Booking, Message, Notification, NotificationPreference, Review, UserActivity, SystemBackup
import os
import sys

def init_db():
    print("Starting database initialization...")
    print(f"Database URL: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python version: {sys.version}")
    
    with app.app_context():
        try:
            # Drop all tables first to ensure clean state
            print("Dropping all tables...")
            db.drop_all()
            print("Tables dropped successfully")
            
            # Create all tables
            print("Creating all tables...")
            db.create_all()
            print("Database tables created successfully!")
            
            # Create admin user if it doesn't exist
            print("Checking for admin user...")
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
            else:
                print("Admin user already exists")
            
            # Verify tables were created
            print("\nVerifying table creation:")
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            for table in tables:
                print(f"- {table}")
            
            print("\nDatabase initialized successfully!")
            
        except Exception as e:
            print(f"\nError initializing database: {str(e)}")
            print(f"Error type: {type(e).__name__}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            db.session.rollback()
            raise e

if __name__ == '__main__':
    try:
        init_db()
    except Exception as e:
        print(f"Failed to initialize database: {str(e)}")
        sys.exit(1) 