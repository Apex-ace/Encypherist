from app import app, db
import os
from werkzeug.security import generate_password_hash
import logging
import sys
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def wait_for_db(max_retries=5, delay=2):
    """Wait for database to be ready"""
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {attempt + 1}/{max_retries})...")
            db.engine.connect()
            logger.info("Database connection successful!")
            return True
        except Exception as e:
            logger.warning(f"Database connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Waiting {delay} seconds before next attempt...")
                time.sleep(delay)
            else:
                logger.error("Failed to connect to database after maximum retries")
                return False

def init_db():
    logger.info("Starting database initialization...")
    try:
        # Ensure we're in the correct directory
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        logger.info(f"Working directory set to: {os.getcwd()}")
        
        # Wait for database to be ready
        if not wait_for_db():
            return False
        
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
            
            # Verify tables were created
            logger.info("Verifying table creation...")
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            logger.info(f"Created tables: {tables}")
            
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

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Database URL: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    success = init_db()
    if not success:
        logger.error("Database initialization failed!")
        sys.exit(1) 