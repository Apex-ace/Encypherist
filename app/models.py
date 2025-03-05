from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy import text
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

# ... rest of your models ... 