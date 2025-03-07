from app import app, db
import os
from werkzeug.security import generate_password_hash
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    logger.info("Starting database initialization...")
    try:
        # Create all tables
        with app.app_context():
            # Drop all tables first to ensure clean state
            logger.info("Dropping existing tables...")
            db.drop_all()
            logger.info("Dropped existing tables")
            
            # Create all tables
            logger.info("Creating tables...")
            db.create_all()
            logger.info("Created all tables")
            
            # Import models after tables are created
            from app import User, Event, Booking, Payment, Message, Conversation
            
            # Create admin user if it doesn't exist
            logger.info("Checking for admin user...")
            admin = User.query.filter_by(email='admin@gmail.com').first()
            if not admin:
                logger.info("Creating admin user...")
                admin = User(
                    email='admin@gmail.com',
                    password=generate_password_hash('123456789'),
                    role='admin',
                    name='Admin User'
                )
                db.session.add(admin)
                db.session.commit()
                logger.info("Created admin user")
            else:
                logger.info("Admin user already exists")
            
            # Create necessary directories if they don't exist
            logger.info("Creating necessary directories...")
            upload_dirs = ['static/uploads', 'static/images', 'static/posters']
            for dir_path in upload_dirs:
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
                    logger.info(f"Created directory: {dir_path}")
            
            logger.info("Database initialization completed successfully!")
            return True
            
    except Exception as e:
        logger.error(f"Error during database initialization: {str(e)}")
        logger.exception("Full traceback:")
        return False

if __name__ == '__main__':
    success = init_db()
    if not success:
        logger.error("Database initialization failed!")
        exit(1) 