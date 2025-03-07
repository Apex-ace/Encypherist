from app import app, db
from models import User, Event, Booking, Payment, Message, Conversation
import os
from werkzeug.security import generate_password_hash

def init_db():
    print("Starting database initialization...")
    try:
        # Create all tables
        with app.app_context():
            # Drop existing tables to ensure clean state
            db.drop_all()
            print("Dropped existing tables")
            
            # Create all tables
            db.create_all()
            print("Created all tables")
            
            # Create admin user if it doesn't exist
            admin = User.query.filter_by(email='admin@gmail.com').first()
            if not admin:
                admin = User(
                    email='admin@gmail.com',
                    password=generate_password_hash('123456789'),
                    role='admin',
                    name='Admin User'
                )
                db.session.add(admin)
                db.session.commit()
                print("Created admin user")
            
            print("Database initialization completed successfully!")
            
    except Exception as e:
        print(f"Error during database initialization: {str(e)}")
        raise e

if __name__ == '__main__':
    init_db() 