from app import app, db
import os
from werkzeug.security import generate_password_hash

def init_db():
    print("Starting database initialization...")
    try:
        # Create all tables
        with app.app_context():
            # Drop all tables first to ensure clean state
            db.drop_all()
            print("Dropped existing tables")
            
            # Create all tables
            db.create_all()
            print("Created all tables")
            
            # Import models after tables are created
            from app import User, Event, Booking, Payment, Message, Conversation
            
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
            
            # Create necessary directories if they don't exist
            upload_dirs = ['static/uploads', 'static/images', 'static/posters']
            for dir_path in upload_dirs:
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
                    print(f"Created directory: {dir_path}")
            
            print("Database initialization completed successfully!")
            
    except Exception as e:
        print(f"Error during database initialization: {str(e)}")
        # Don't raise the exception, just log it
        return False
    
    return True

if __name__ == '__main__':
    success = init_db()
    if not success:
        print("Database initialization failed!")
        exit(1) 