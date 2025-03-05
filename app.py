from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from jinja2.exceptions import TemplateNotFound
import qrcode
from io import BytesIO
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import os
import json
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from urllib.parse import quote_plus
import psycopg2
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy import text, event
import uuid

# Load environment variables
load_dotenv()

# Create Flask app first
app = Flask(__name__)

# Configure app
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# Initialize Flask-Mail after app creation
from flask_mail import Mail, Message
mail = Mail(app)

# Database Configuration
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST')
db_port = os.getenv('DB_PORT')
db_name = os.getenv('DB_NAME')

# Construct database URL with proper encoding
db_url = f"postgresql+psycopg2://{quote_plus(db_user)}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_timeout': 30,
    'pool_recycle': 1800,
    'pool_pre_ping': True,
    'connect_args': {
        'connect_timeout': 10,
        'options': '-c statement_timeout=30000'
    }
}

# Initialize other extensions
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Create upload folders
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'events'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), exist_ok=True)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# Database connection check
def check_db_connection():
    try:
        db.session.execute(text('SELECT 1'))
        return True
    except Exception as e:
        print(f"Database connection error: {str(e)}")
        return False

@app.before_request
def before_request():
    if not check_db_connection():
        return 'Database connection error', 500

# Import models and routes after app initialization
from models import *
from routes import *

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)