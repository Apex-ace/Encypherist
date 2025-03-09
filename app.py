from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
import qrcode
from io import BytesIO
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import os
import json
import paypalrestsdk
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging
import time
import sys
from itsdangerous import URLSafeTimedSerializer
from werkzeug.urls import url_parse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///events.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
app.config['ALLOWED_EXTENSIONS'] = os.environ.get(
    'ALLOWED_EXTENSIONS', 'png,jpg,jpeg,gif,pdf'
).split(',')
app.config['SESSION_COOKIE_SECURE'] = os.environ.get(
    'SESSION_COOKIE_SECURE', 'true'
).lower() == 'true'
app.config['REMEMBER_COOKIE_SECURE'] = os.environ.get(
    'REMEMBER_COOKIE_SECURE', 'true'
).lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = int(os.environ.get('PERMANENT_SESSION_LIFETIME', 1800))

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
csrf = CSRFProtect(app)

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    profile_picture = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    activities = db.relationship('UserActivity', backref='user', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)
    preferences = db.relationship(
        'NotificationPreference',
        backref='user',
        lazy=True,
        uselist=False
    )
    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic')
    messages_received = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy='dynamic')
    bookings = db.relationship('Booking', backref='user_profile', lazy='dynamic')
    events = db.relationship('Event', foreign_keys='Event.organizer_id', backref='organizer', lazy='dynamic')

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200))
    price = db.Column(db.Float, nullable=False)
    total_tickets = db.Column(db.Integer, nullable=False)
    remaining_tickets = db.Column(db.Integer, nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    category = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')  # pending, approved, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_group_event = db.Column(db.Boolean, default=False)
    min_group_size = db.Column(db.Integer, default=1)
    max_group_size = db.Column(db.Integer, default=1)
    
    # Relationships
    organizer = db.relationship('User', backref='events')
    bookings = db.relationship('Booking', backref='event', lazy=True)
    notifications = db.relationship('Notification', backref='event', lazy='dynamic')
    messages = db.relationship('Message', backref='event', lazy='dynamic')

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, cancelled
    payment_status = db.Column(db.String(20), default='pending')  # pending, succeeded, failed
    total_price = db.Column(db.Float)
    qr_code = db.Column(db.String(200))  # Path to QR code image
    name = db.Column(db.String(100))
    email = db.Column(db.String(120))
    mobile = db.Column(db.String(20))
    branch = db.Column(db.String(50))
    year = db.Column(db.String(10))
    
    # Relationships
    user_profile = db.relationship('User', backref='bookings')

class UserActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    activity_type = db.Column(db.String(50), nullable=False)  # login, logout, book_event, etc.
    description = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50))

class SystemBackup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    size = db.Column(db.Integer)  # Size in bytes
    status = db.Column(db.String(20), default='completed')  # started, completed, failed

    # Relationships
    user = db.relationship('User', backref=db.backref('backups', lazy=True))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)

    # Relationships
    sender = db.relationship(
        'User',
        foreign_keys=[sender_id],
        backref=db.backref('messages_sent', lazy='dynamic')
    )
    receiver = db.relationship(
        'User',
        foreign_keys=[receiver_id],
        backref=db.backref('messages_received', lazy='dynamic')
    )
    event = db.relationship('Event', backref=db.backref('messages', lazy='dynamic'))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    type = db.Column(db.String(50))  # email, sms, in-app
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    sent = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text, nullable=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))
    event = db.relationship('Event', backref=db.backref('notifications', lazy='dynamic'))

class NotificationPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    email_notifications = db.Column(db.Boolean, default=True)
    sms_notifications = db.Column(db.Boolean, default=True)
    event_updates = db.Column(db.Boolean, default=True)
    event_reminders = db.Column(db.Boolean, default=True)
    messages = db.Column(db.Boolean, default=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('notification_preferences', uselist=False))

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    review_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('reviews', lazy=True))
    event = db.relationship('Event', backref=db.backref('reviews', lazy=True))

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

def wait_for_db(max_retries=5, delay=2):
    """Wait for database to be ready"""
    for attempt in range(max_retries):
        try:
            logger.info(
                f"Attempting to connect to database (attempt {attempt + 1}/{max_retries})..."
            )
            with app.app_context():
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

def ensure_db_ready():
    """Ensure database is ready before starting the application"""
    if not wait_for_db():
        logger.error("Database is not ready. Exiting...")
        return False
    
    try:
        with app.app_context():
            # Test if tables exist
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            if not tables:
                logger.error("No tables found in database. Please run database initialization first.")
                return False
            logger.info(f"Database is ready with tables: {tables}")
            return True
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")
        return False

def create_admin_user(username, password):
    """Create an admin user if it doesn't exist"""
    try:
        with app.app_context():
            # Check if admin user exists
            admin = User.query.filter_by(username=username).first()
            
            if not admin:
                # Create new admin user
                admin = User(
                    username=username,
                    password=generate_password_hash(password),
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
                logger.info(f"Admin user {username} created successfully")
            else:
                # Update existing admin user's password
                admin.password = generate_password_hash(password)
                db.session.commit()
                logger.info(f"Admin user {username} password updated")
    except Exception as e:
        logger.error(f"Error creating/updating admin user: {str(e)}")
        db.session.rollback()

def init_app():
    """Initialize the application and ensure database is ready"""
    logger.info("Initializing application...")
    try:
        with app.app_context():
            # Create database tables
            db.create_all()
            logger.info("Database tables created successfully")
            
            # Create necessary directories
            upload_dirs = ['static/uploads', 'static/images', 'static/posters']
            for dir_path in upload_dirs:
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
                    logger.info(f"Created directory: {dir_path}")
            
            # Create admin user
            create_admin_user(
                username='admin@gmail.com',
                password='admin@123#'
            )
            
            logger.info("Application initialization completed successfully")
            return True
            
    except Exception as e:
        logger.error(f"Error during application initialization: {str(e)}")
        return False

@app.route('/')
def landing():
    # Clean up past events
    now = datetime.utcnow()
    try:
        past_events = Event.query.filter(Event.date < now).all()
        for event in past_events:
            Booking.query.filter_by(event_id=event.id).delete()
            db.session.delete(event)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error cleaning up past events: {str(e)}')
    
    # Get 3 upcoming events for the featured section
    featured_events = Event.query.filter(
        Event.date > now
    ).order_by(Event.date).limit(3).all()
    
    return render_template('landing.html', featured_events=featured_events)

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        if not username or not password or not role:
            flash('Please fill in all fields', 'error')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters long', 'error')
            return redirect(url_for('register'))

        if role not in ['student', 'organizer']:
            flash('Invalid role selected', 'error')
            return redirect(url_for('register'))

        try:
            hashed_password = generate_password_hash(password)
            user = User(username=username, password=hashed_password, role=role)
            db.session.add(user)
            
            # Create notification preferences
            prefs = NotificationPreference(user_id=user.id)
            db.session.add(prefs)
            
            # Log the activity
            activity = UserActivity(
                user_id=user.id,
                activity_type='register',
                description=f'New user registration from {request.remote_addr}',
                ip_address=request.remote_addr
            )
            db.session.add(activity)
            
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            logger.error(f"Error during registration: {str(e)}")
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = bool(request.form.get('remember'))
        
        app.logger.info(f"Login attempt for username: {username}")
        
        user = User.query.filter_by(email=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user, remember=remember)
            app.logger.info(f"Successful login for user: {username}")
            
            # Log the login activity safely
            if not log_user_activity(
                user.id,
                'login',
                f'User logged in from {request.remote_addr}',
                request.remote_addr
            ):
                app.logger.warning(f"Failed to log login activity for user {username}")
            
            next_page = request.args.get('next')
            if not next_page or url_parse(next_page).netloc != '':
                next_page = url_for('home')
            return redirect(next_page)
        
        flash('Invalid username or password', 'error')
        return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/home')
@login_required
def home():
    # Clean up past events
    now = datetime.utcnow()
    try:
        past_events = Event.query.filter(Event.date < now).all()
        for event in past_events:
            Booking.query.filter_by(event_id=event.id).delete()
            db.session.delete(event)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Error cleaning up past events: {str(e)}')
    
    # Get search and filter parameters
    search_query = request.args.get('search', '').strip()
    category = request.args.get('category', 'all')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    sort_by = request.args.get('sort', 'date')  # date, price, popularity
    
    # Base query for future events
    query = Event.query.filter(Event.date > now)
    
    # Apply search filter
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            db.or_(
                Event.title.ilike(search),
                Event.description.ilike(search),
                Event.location.ilike(search)
            )
        )
    
    # Apply category filter
    if category and category != 'all':
        query = query.filter(Event.category == category)
    
    # Apply price range filter
    if min_price is not None:
        query = query.filter(Event.price >= min_price)
    if max_price is not None:
        query = query.filter(Event.price <= max_price)
    
    # Apply date range filter
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Event.date >= start)
        except ValueError:
            pass
    
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d')
            end = end.replace(hour=23, minute=59, second=59)
            query = query.filter(Event.date <= end)
        except ValueError:
            pass
    
    # Apply sorting
    if sort_by == 'price':
        query = query.order_by(Event.price)
    elif sort_by == 'popularity':
        # Count bookings for each event
        subquery = db.session.query(
            Booking.event_id,
            db.func.count(Booking.id).label('booking_count')
        ).group_by(Booking.event_id).subquery()
        
        query = query.outerjoin(
            subquery, Event.id == subquery.c.event_id
        ).order_by(db.desc(subquery.c.booking_count.nullsfirst()))
    else:  # sort by date
        query = query.order_by(Event.date)
    
    # Get distinct categories for filter dropdown
    categories = db.session.query(Event.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    # Execute query
    events = query.all()
    
    return render_template(
        'home.html',
        events=events,
        now=now,
        search_query=search_query,
        selected_category=category,
        min_price=min_price,
        max_price=max_price,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        categories=categories
    )

@app.route('/create_event', methods=['GET', 'POST'])
@login_required
def create_event():
    try:
        if current_user.role != 'organizer':
            flash('Only organizers can create events', 'error')
            return redirect(url_for('home'))

        if request.method == 'POST':
            # Get form data with validation
            title = request.form.get('title')
            description = request.form.get('description')
            location = request.form.get('location')
            price = request.form.get('price')
            date_str = request.form.get('date')
            total_tickets = request.form.get('total_tickets')
            category = request.form.get('category')
            is_group_event = 'is_group_event' in request.form

            # Validate required fields
            if not all([title, description, location, price, date_str, total_tickets, category]):
                flash('Please fill in all required fields', 'error')
                return redirect(url_for('create_event'))

            # Convert and validate numeric fields
            try:
                price = float(price)
                total_tickets = int(total_tickets)
                if price < 0 or total_tickets < 1:
                    flash('Price and total tickets must be positive numbers', 'error')
                    return redirect(url_for('create_event'))
            except ValueError:
                flash('Invalid price or ticket quantity', 'error')
                return redirect(url_for('create_event'))

            # Parse and validate date
            try:
                event_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
                if event_date < datetime.now():
                    flash('Event date must be in the future', 'error')
                    return redirect(url_for('create_event'))
            except ValueError:
                flash('Invalid date format', 'error')
                return redirect(url_for('create_event'))

            # Handle group event settings
            min_group_size = 1
            max_group_size = 1
            if is_group_event:
                try:
                    min_group_size = int(request.form.get('min_group_size', 2))
                    max_group_size = int(request.form.get('max_group_size', 10))
                    if min_group_size < 2 or max_group_size < min_group_size:
                        flash('Invalid group size settings', 'error')
                        return redirect(url_for('create_event'))
                except ValueError:
                    flash('Invalid group size values', 'error')
                    return redirect(url_for('create_event'))

            # Create event
            event = Event(
                title=title,
                description=description,
                location=location,
                price=price,
                date=event_date,
                organizer_id=current_user.id,
                total_tickets=total_tickets,
                remaining_tickets=total_tickets,
                is_group_event=is_group_event,
                min_group_size=min_group_size,
                max_group_size=max_group_size,
                category=category,
                status='pending',
                created_at=datetime.utcnow()
            )
            
            # Create activity log
            activity = UserActivity(
                user_id=current_user.id,
                activity_type='create_event',
                description=f'Created event: {title}',
                ip_address=request.remote_addr
            )
            
            db.session.add(event)
            db.session.add(activity)
            db.session.commit()
            
            flash('Event created successfully!', 'success')
            return redirect(url_for('organizer_profile'))

        return render_template('create_event.html')

    except Exception as e:
        logger.error(f"Error creating event: {str(e)}")
        db.session.rollback()
        flash('An error occurred while creating the event', 'error')
        return redirect(url_for('create_event'))

@app.route('/delete_event/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    if current_user.role != 'organizer':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        flash('You can only delete your own events')
        return redirect(url_for('home'))
    
    # Delete associated bookings
    Booking.query.filter_by(event_id=event_id).delete()
    # Delete the event
    db.session.delete(event)
    db.session.commit()
    
    flash('Event deleted successfully')
    return redirect(url_for('home'))

@app.route('/book_event/<int:event_id>', methods=['GET', 'POST'])
@login_required
def book_event(event_id):
    try:
        if current_user.role != 'student':
            flash('Only students can book events', 'error')
            return redirect(url_for('home'))
        
        event = Event.query.get_or_404(event_id)
        
        # Check if event has started
        if datetime.utcnow() >= event.date:
            flash('Registration closed: Event has already started', 'warning')
            return redirect(url_for('home'))
        
        # Check if event is sold out
        if event.remaining_tickets <= 0:
            flash('Event is sold out!', 'warning')
            return redirect(url_for('home'))

        # Check if user has already booked this event
        existing_booking = Booking.query.filter_by(
            user_id=current_user.id,
            event_id=event.id
        ).first()
        
        if existing_booking:
            flash('You have already booked this event', 'warning')
            return redirect(url_for('home'))
        
        return render_template('booking_form.html', event=event)
        
    except Exception as e:
        logger.error(f"Error in book_event: {str(e)}")
        flash('An error occurred while processing your booking request', 'error')
        return redirect(url_for('home'))

@app.route('/submit_booking/<int:event_id>', methods=['POST'])
@login_required
def submit_booking(event_id):
    try:
        if current_user.role != 'student':
            flash('Only students can book events', 'error')
            return redirect(url_for('home'))
        
        event = Event.query.get_or_404(event_id)
        
        # Validate event availability
        if event.remaining_tickets <= 0:
            flash('Event is sold out!', 'error')
            return redirect(url_for('home'))
        
        # Validate form data
        required_fields = ['name', 'email', 'mobile', 'branch', 'year']
        if not all(request.form.get(field) for field in required_fields):
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('book_event', event_id=event_id))
        
        # Create booking
        booking = Booking(
            user_id=current_user.id,
            event_id=event.id,
            name=request.form['name'],
            email=request.form['email'],
            mobile=request.form['mobile'],
            branch=request.form['branch'],
            year=request.form['year'],
            status='confirmed',
            booking_date=datetime.utcnow(),
            total_price=event.price
        )
        
        # Update ticket count
        event.remaining_tickets -= 1
        
        # Create activity log
        activity = UserActivity(
            user_id=current_user.id,
            activity_type='book_event',
            description=f'Booked event: {event.title}',
            ip_address=request.remote_addr
        )
        
        db.session.add(booking)
        db.session.add(activity)
        db.session.commit()
        
        flash('Booking successful!', 'success')
        return redirect(url_for('view_ticket', booking_id=booking.id))
        
    except Exception as e:
        logger.error(f"Error in submit_booking: {str(e)}")
        db.session.rollback()
        flash('An error occurred while processing your booking', 'error')
        return redirect(url_for('home'))

@app.route('/view_ticket/<int:booking_id>')
@login_required
def view_ticket(booking_id):
    try:
        booking = Booking.query.options(
            db.joinedload(Booking.event),
            db.joinedload(Booking.user_profile)
        ).get_or_404(booking_id)
        
        if booking.user_id != current_user.id:
            flash('Unauthorized access', 'error')
            return redirect(url_for('home'))
        
        if booking.status != 'confirmed':
            flash('Booking not confirmed', 'warning')
            return redirect(url_for('student_profile'))
        
        return render_template('ticket.html', booking=booking, event=booking.event)
        
    except Exception as e:
        logger.error(f"Error viewing ticket: {str(e)}")
        flash('An error occurred while viewing the ticket', 'error')
        return redirect(url_for('home'))

@app.route('/event_details/<int:event_id>')
def event_details(event_id):
    try:
        event = Event.query.options(
            db.joinedload(Event.organizer),
            db.joinedload(Event.bookings)
        ).get_or_404(event_id)
        
        return render_template(
            'event_details.html',
            event=event,
            now=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Error viewing event details: {str(e)}")
        flash('An error occurred while viewing the event details', 'error')
        return redirect(url_for('home'))

@app.route('/download_registrations/<int:event_id>')
@login_required
def download_registrations(event_id):
    try:
        # Check if user is the organizer of this event
        event = Event.query.get_or_404(event_id)
        if current_user.role != 'organizer' or event.organizer_id != current_user.id:
            flash('Unauthorized access', 'danger')
            return redirect(url_for('home'))
        
        # Get all bookings for this event with user details
        bookings = Booking.query.filter_by(event_id=event_id).all()
        
        # Create PDF
        output = BytesIO()
        c = canvas.Canvas(output, pagesize=letter)
        
        # Title
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 750, f"Registered Students - {event.title}")
        c.setFont("Helvetica", 12)
        c.drawString(50, 730, f"Date: {event.date.strftime('%B %d, %Y')}")
        c.drawString(50, 710, f"Total Registrations: {len(bookings)}")
        
        # Headers
        y = 670
        headers = ['Name', 'Email', 'Mobile', 'Branch', 'Year', 'Booking Date']
        x_positions = [50, 150, 300, 400, 480, 530]
        
        for i, header in enumerate(headers):
            c.drawString(x_positions[i], y, header)
        
        # Draw a line under headers
        y -= 15
        c.line(50, y, 550, y)
        y -= 20
        
        # Add registrations
        for booking in bookings:
            # Check if we need a new page
            if y < 50:
                c.showPage()
                y = 750
                
            c.drawString(x_positions[0], y, booking.name)
            c.drawString(x_positions[1], y, booking.email)
            c.drawString(x_positions[2], y, booking.mobile)
            c.drawString(x_positions[3], y, booking.branch)
            c.drawString(x_positions[4], y, booking.year)
            c.drawString(x_positions[5], y, booking.booking_date.strftime('%Y-%m-%d'))
            y -= 20
        
        c.save()
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'registrations_{event.title}_{datetime.now().strftime("%Y%m%d")}.pdf'
        )
        
    except Exception as e:
        app.logger.error(f"Error downloading registrations: {str(e)}")
        flash('An error occurred while downloading registrations', 'danger')
        return redirect(url_for('organizer_profile'))

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    try:
        if request.method == 'POST':
            # Handle profile updates
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    current_user.profile_picture = filename

            # Log the activity
            activity = UserActivity(
                user_id=current_user.id,
                activity_type='edit_profile',
                description=f'Profile updated from {request.remote_addr}',
                ip_address=request.remote_addr
            )
            db.session.add(activity)
            db.session.commit()

            flash('Profile updated successfully!', 'success')
            return redirect(url_for(
                'organizer_profile' if current_user.role == 'organizer' else 'student_profile'
            ))

        return render_template('edit_profile.html', user=current_user)

    except Exception as e:
        logger.error(f"Error in edit_profile: {str(e)}")
        db.session.rollback()
        flash('An error occurred while updating your profile', 'error')
        return redirect(url_for(
            'organizer_profile' if current_user.role == 'organizer' else 'student_profile'
        ))

@app.route('/organizer_profile')
@login_required
def organizer_profile():
    try:
        if current_user.role != 'organizer':
            flash('Access denied. Only organizers can view this page.', 'error')
            return redirect(url_for('home'))

        # Get all events organized by the user
        now = datetime.utcnow()
        upcoming_events = Event.query.filter(
            Event.organizer_id == current_user.id,
            Event.date > now
        ).order_by(Event.date).all()

        past_events = Event.query.filter(
            Event.organizer_id == current_user.id,
            Event.date <= now
        ).order_by(Event.date.desc()).all()

        # Calculate statistics
        total_events = len(upcoming_events) + len(past_events)
        total_bookings = sum(
            len(event.bookings) 
            for event in upcoming_events + past_events
        )
        total_revenue = sum(
            event.price * (event.total_tickets - event.remaining_tickets)
            for event in past_events
        )

        return render_template(
            'organizer_profile.html',
            user=current_user,
            upcoming_events=upcoming_events,
            past_events=past_events,
            total_events=total_events,
            total_bookings=total_bookings,
            total_revenue=total_revenue
        )

    except Exception as e:
        logger.error(f"Error in organizer_profile: {str(e)}")
        flash('An error occurred while loading your profile', 'error')
        return redirect(url_for('home'))

@app.route('/messages')
@login_required
def messages():
    # Get all messages for the current user
    received_messages = Message.query.filter_by(
        receiver_id=current_user.id
    ).order_by(Message.timestamp.desc()).all()
    
    sent_messages = Message.query.filter_by(
        sender_id=current_user.id
    ).order_by(Message.timestamp.desc()).all()

    # Mark unread messages as read
    for message in received_messages:
        if not message.read:
            message.read = True
    db.session.commit()

    return render_template(
        'messages.html',
        received_messages=received_messages,
        sent_messages=sent_messages
    )

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(username=email).first()
        
        if user:
            # Generate reset token
            token = generate_reset_token(user)
            
            # Send reset email
            try:
                send_reset_email(user, token)
                flash('Password reset instructions have been sent to your email.', 'success')
                return redirect(url_for('login'))
            except Exception as e:
                logger.error(f"Error sending reset email: {str(e)}")
                flash('Error sending reset email. Please try again later.', 'error')
        else:
            # Don't reveal if user exists
            flash('If an account exists with this email, you will receive password reset instructions.', 'info')
        
        return redirect(url_for('forgot_password'))
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
        email = serializer.loads(token, salt='password-reset-salt', max_age=3600)  # Token valid for 1 hour
        user = User.query.filter_by(username=email).first()
        
        if not user:
            flash('Invalid or expired reset link.', 'error')
            return redirect(url_for('login'))
        
        if request.method == 'POST':
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
            
            if not password or not confirm_password:
                flash('Please fill in all fields.', 'error')
            elif password != confirm_password:
                flash('Passwords do not match.', 'error')
            elif len(password) < 6:
                flash('Password must be at least 6 characters long.', 'error')
            else:
                user.password = generate_password_hash(password)
                db.session.commit()
                flash('Your password has been reset successfully.', 'success')
                return redirect(url_for('login'))
                
        return render_template('reset_password.html')
        
    except Exception as e:
        logger.error(f"Error in reset_password: {str(e)}")
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('login'))

@app.route('/user_notifications')
@login_required
def user_notifications():
    """Handle user notifications"""
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.timestamp.desc()).all()
    return render_template('notifications.html', notifications=notifications)

def log_user_activity(user_id, activity_type, description, ip_address=None):
    try:
        user = User.query.get(user_id)
        if not user:
            app.logger.error(f"Failed to log activity: User {user_id} not found")
            return False
        
        activity = UserActivity(
            user_id=user_id,
            activity_type=activity_type,
            description=description,
            ip_address=ip_address
        )
        db.session.add(activity)
        db.session.commit()
        return True
    except Exception as e:
        app.logger.error(f"Error logging user activity: {str(e)}")
        db.session.rollback()
        return False

# Initialize the application
init_app()

@app.route('/health')
def health_check():
    """Health check endpoint to verify database connectivity"""
    try:
        with app.app_context():
            # Test database connection
            db.engine.connect()
            # Check if tables exist
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            if not tables:
                return jsonify({"status": "error", "message": "No tables found"}), 503
            return jsonify({"status": "healthy", "tables": tables}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 503

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def generate_reset_token(user):
    # Generate a secure token for password reset
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    return serializer.dumps(user.email, salt='password-reset-salt')

def send_reset_email(user, token):
    # Implement email sending functionality
    # This is a placeholder - you'll need to implement actual email sending
    pass

if __name__ == '__main__':
    app.run(debug=True)