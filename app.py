from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
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
app.config['ALLOWED_EXTENSIONS'] = os.environ.get('ALLOWED_EXTENSIONS', 'png,jpg,jpeg,gif,pdf').split(',')
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
app.config['REMEMBER_COOKIE_SECURE'] = os.environ.get('REMEMBER_COOKIE_SECURE', 'true').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = os.environ.get('SESSION_COOKIE_HTTPONLY', 'true').lower() == 'true'
app.config['REMEMBER_COOKIE_HTTPONLY'] = os.environ.get('REMEMBER_COOKIE_HTTPONLY', 'true').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = int(os.environ.get('PERMANENT_SESSION_LIFETIME', 1800))

# Initialize CSRF protection
csrf = CSRFProtect(app)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    profile_picture = db.Column(db.String(200))  # Store profile picture filename
    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic')
    messages_received = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    notification_preferences = db.relationship('NotificationPreference', backref='user', uselist=False)
    bookings = db.relationship('Booking', backref='user', lazy='dynamic')
    events = db.relationship('Event', foreign_keys='Event.organizer_id', backref='organizer', lazy='dynamic')

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    payment_qr = db.Column(db.String(500))  # Store payment QR code
    total_tickets = db.Column(db.Integer, nullable=False, default=0)
    remaining_tickets = db.Column(db.Integer, nullable=False, default=0)
    is_group_event = db.Column(db.Boolean, default=False)  # Whether event accepts group registrations
    min_group_size = db.Column(db.Integer, default=1)  # Minimum participants per group
    max_group_size = db.Column(db.Integer, default=1)  # Maximum participants per group
    category = db.Column(db.String(50), nullable=True)  # Add category field
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notifications = db.relationship('Notification', backref='event', lazy='dynamic')
    messages = db.relationship('Message', backref='event', lazy='dynamic')

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    payment_status = db.Column(db.String(20), default='pending')
    payment_id = db.Column(db.String(100), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    branch = db.Column(db.String(50), nullable=False)
    year = db.Column(db.String(10), nullable=False)
    
    # Add relationship to Event
    event = db.relationship('Event', backref='bookings', lazy='joined')

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

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)

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

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    review_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Add relationships to User and Event models
    user = db.relationship('User', backref='reviews')
    event = db.relationship('Event', backref='reviews')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def wait_for_db(max_retries=5, delay=2):
    """Wait for database to be ready"""
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {attempt + 1}/{max_retries})...")
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
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        if not username or not password or not role:
            flash('Please fill in all fields')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters long')
            return redirect(url_for('register'))

        if role not in ['student', 'organizer']:
            flash('Invalid role selected')
            return redirect(url_for('register'))

        try:
            hashed_password = generate_password_hash(password)
            user = User(username=username, password=hashed_password, role=role)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            remember = request.form.get('remember') == 'on'
            
            logger.info(f"Login attempt for username: {username}")
            
            if not username or not password:
                logger.warning("Login attempt with missing credentials")
                flash('Please provide both username and password', 'error')
                return redirect(url_for('login'))
            
            try:
                user = User.query.filter_by(username=username).first()
                
                if user and check_password_hash(user.password, password):
                    login_user(user, remember=remember)
                    logger.info(f"Successful login for user: {username}")
                    flash('Logged in successfully!', 'success')
                    
                    # Redirect based on user role
                    if user.role == 'admin':
                        return redirect(url_for('admin_dashboard'))
                    return redirect(url_for('home'))
                
                logger.warning(f"Failed login attempt for username: {username}")
                flash('Invalid username or password', 'error')
                return redirect(url_for('login'))
                
            except Exception as e:
                logger.error(f"Database error during login: {str(e)}")
                flash('An error occurred during login. Please try again.', 'error')
                return redirect(url_for('login'))
        
        return render_template('login.html')
        
    except Exception as e:
        logger.error(f"Unexpected error in login route: {str(e)}")
        flash('An unexpected error occurred. Please try again.', 'error')
        return redirect(url_for('login'))

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))

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
    if current_user.role != 'organizer':
        flash('Only organizers can create events')
        return redirect(url_for('home'))

    if request.method == 'POST':
        try:
            # Get form data with validation
            title = request.form.get('title')
            description = request.form.get('description')
            location = request.form.get('location')
            price = request.form.get('price')
            date_str = request.form.get('date')
            total_tickets = request.form.get('total_tickets')
            category = request.form.get('category')  # Get category from form
            is_group_event = 'is_group_event' in request.form

            # Validate required fields
            if not all([title, description, location, price, date_str, total_tickets, category]):  # Add category to required fields
                flash('Please fill in all required fields')
                return redirect(url_for('create_event'))

            # Convert and validate numeric fields
            try:
                price = float(price)
                total_tickets = int(total_tickets)
                if price < 0 or total_tickets < 1:
                    flash('Price and total tickets must be positive numbers')
                    return redirect(url_for('create_event'))
            except ValueError:
                flash('Invalid price or ticket quantity')
                return redirect(url_for('create_event'))

            # Parse and validate date
            try:
                event_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
                if event_date < datetime.now():
                    flash('Event date must be in the future')
                    return redirect(url_for('create_event'))
            except ValueError:
                flash('Invalid date format')
                return redirect(url_for('create_event'))

            # Handle group event settings
            min_group_size = 1
            max_group_size = 1
            if is_group_event:
                try:
                    min_group_size = int(request.form.get('min_group_size', 2))
                    max_group_size = int(request.form.get('max_group_size', 10))
                    if min_group_size < 2 or max_group_size < min_group_size:
                        flash('Invalid group size settings')
                        return redirect(url_for('create_event'))
                except ValueError:
                    flash('Invalid group size values')
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
                category=category,  # Save category to event
                status='pending',
                created_at=datetime.utcnow()
            )
            
            db.session.add(event)
            db.session.commit()
            flash('Event created successfully!')
            return redirect(url_for('home'))

        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred while creating the event: {str(e)}')
            return redirect(url_for('create_event'))

    return render_template('create_event.html')

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
    if current_user.role != 'student':
        flash('Only students can book events')
        return redirect(url_for('home'))
    
    event = Event.query.get_or_404(event_id)
    
    # Check if event has started
    if datetime.utcnow() >= event.date:
        flash('Registration closed: Event has already started')
        return redirect(url_for('home'))
    
    # Check if event is sold out
    if event.remaining_tickets <= 0:
        flash('Event is sold out!')
        return redirect(url_for('home'))

    # Check if user has already booked this event
    existing_booking = Booking.query.filter_by(
        user_id=current_user.id,
        event_id=event.id
    ).first()
    
    if existing_booking:
        flash('You have already booked this event')
        return redirect(url_for('home'))
    
    return render_template('booking_form.html', event=event)

@app.route('/payment/<int:event_id>', methods=['GET', 'POST'])
@login_required
def payment(event_id):
    if current_user.role != 'student':
        flash('Only students can book events')
        return redirect(url_for('home'))
    
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        # Validate form data
        name = request.form.get('name')
        email = request.form.get('email')
        mobile = request.form.get('mobile')
        branch = request.form.get('branch')
        year = request.form.get('year')

        if not all([name, email, mobile, branch, year]):
            flash('Please fill in all fields')
            return redirect(url_for('book_event', event_id=event_id))

        try:
            # Create booking
            booking = Booking(
                user_id=current_user.id,
                event_id=event.id,
                name=name,
                email=email,
                mobile=mobile,
                branch=branch,
                year=year,
                payment_status='pending',
                payment_id='booking_' + str(datetime.utcnow().timestamp()),
                booking_date=datetime.utcnow()
            )
            
            # Update ticket count
            if event.remaining_tickets <= 0:
                flash('Sorry, this event is now sold out')
                return redirect(url_for('home'))
                
            event.remaining_tickets -= 1
            
            db.session.add(booking)
            db.session.commit()
            
            # For now, we'll directly mark the payment as succeeded
            booking.payment_status = 'succeeded'
            db.session.commit()
            
            flash('Booking successful!')
            return redirect(url_for('ticket', event_id=event_id))
            
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during booking. Please try again.')
            return redirect(url_for('book_event', event_id=event_id))
    
    # GET request - show payment page or redirect to booking
    return redirect(url_for('submit_booking', event_id=event_id))

@app.route('/submit_booking/<int:event_id>', methods=['POST'])
@login_required
def submit_booking(event_id):
    if current_user.role != 'student':
        flash('Only students can book events')
        return redirect(url_for('home'))
    
    try:
        event = Event.query.get_or_404(event_id)
        
        if event.remaining_tickets <= 0:
            flash('Event is sold out!')
            return redirect(url_for('home'))
        
        # Create a new booking with user information
        booking = Booking(
            user_id=current_user.id,
            event_id=event.id,
            name=request.form['name'],
            email=request.form['email'],
            mobile=request.form['mobile'],
            branch=request.form['branch'],
            year=request.form['year'],
            payment_status='succeeded',
            payment_id='direct_booking_' + str(datetime.utcnow().timestamp()),
            booking_date=datetime.utcnow()
        )
        
        # Update ticket count
        event.remaining_tickets -= 1
        
        # Debug print
        print(f"Creating booking for user {current_user.username} for event {event.title}")
        
        db.session.add(booking)
        db.session.commit()
        
        print(f"Booking created successfully with ID: {booking.id}")
        flash('Booking successful!')
        
        return redirect(url_for('ticket', event_id=event_id))
        
    except Exception as e:
        print(f"Error in submit_booking: {str(e)}")
        db.session.rollback()
        flash('An error occurred while processing your booking')
        return redirect(url_for('home'))

@app.route('/process_payment/<int:event_id>')
@login_required
def process_payment(event_id):
    if current_user.role != 'student':
        return redirect(url_for('home'))

    event = Event.query.get_or_404(event_id)
    
    if event.remaining_tickets <= 0:
        flash('Event is sold out!')
        return redirect(url_for('home'))

    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    
    if not payment_id or not payer_id:
        flash('Payment failed')
        return redirect(url_for('home'))

    try:
        payment = paypalrestsdk.Payment.find(payment_id)
        if payment.execute({"payer_id": payer_id}):
            # Check if user already has a booking
            existing_booking = Booking.query.filter_by(
                user_id=current_user.id,
                event_id=event.id
            ).first()
            
            if existing_booking and existing_booking.payment_status == 'succeeded':
                flash('You have already booked this event')
                return redirect(url_for('home'))
            
            # Create or update booking with current timestamp
            if existing_booking:
                booking = existing_booking
            else:
                booking = Booking(
                    user_id=current_user.id,
                    event_id=event.id,
                    payment_status='pending',
                    payment_id=payment_id,
                    booking_date=datetime.utcnow()
                )
                db.session.add(booking)
            
            # Update booking and ticket count
            booking.payment_status = 'succeeded'
            event.remaining_tickets -= 1
            db.session.commit()
            
            return redirect(url_for('ticket', event_id=event_id))
        else:
            flash('Payment failed')
            return redirect(url_for('home'))

    except Exception as e:
        db.session.rollback()
        flash(f'Payment failed: {str(e)}')
        return redirect(url_for('home'))

@app.route('/ticket/<int:event_id>')
@login_required
def ticket(event_id):
    event = Event.query.get_or_404(event_id)
    booking = Booking.query.filter_by(event_id=event_id, user_id=current_user.id).first_or_404()

    if booking.payment_status != 'succeeded':
        flash('Payment not completed')
        return redirect(url_for('payment', event_id=event_id))

    # Generate QR code with structured data
    ticket_data = {
        'booking_id': booking.id,
        'event_title': event.title,
        'event_date': event.date.strftime('%Y-%m-%d %H:%M'),
        'booking_date': booking.booking_date.strftime('%Y-%m-%d %H:%M'),
        'attendee': {
            'name': booking.name,
            'email': booking.email,
            'mobile': booking.mobile,
            'branch': booking.branch,
            'year': booking.year
        },
        'payment_status': booking.payment_status,
        'payment_id': booking.payment_id
    }

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(json.dumps(ticket_data))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    # Convert QR code to base64 for display
    buffered = BytesIO()
    qr_img.save(buffered, format="PNG")
    qr_code = f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"

    # Generate PDF ticket with more details
    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=letter)
    c.drawString(100, 750, f"Event: {event.title}")
    c.drawString(100, 730, f"Date: {event.date.strftime('%B %d, %Y')}")
    c.drawString(100, 710, f"Time: {event.date.strftime('%I:%M %p')}")
    c.drawString(100, 690, f"Booking ID: {booking.id}")
    c.drawString(100, 670, f"Booking Date: {booking.booking_date.strftime('%B %d, %Y %I:%M %p')}")
    c.drawString(100, 650, f"Attendee: {booking.name}")
    c.drawString(100, 630, f"Email: {booking.email}")
    c.drawString(100, 610, f"Mobile: {booking.mobile}")
    c.drawString(100, 590, f"Branch: {booking.branch}")
    c.drawString(100, 570, f"Year: {booking.year}")
    c.drawString(100, 550, f"Payment Status: {booking.payment_status}")
    c.drawString(100, 530, f"Payment ID: {booking.payment_id}")
    c.save()

    # Save PDF to static folder
    os.makedirs(os.path.join(app.root_path, 'static'), exist_ok=True)
    pdf_filename = f"ticket_{booking.id}.pdf"
    pdf_path = os.path.join(app.static_folder, pdf_filename)
    with open(pdf_path, 'wb') as f:
        f.write(pdf_buffer.getvalue())

    return render_template('ticket.html',
                          event=event,
                          booking=booking,
                          qr_code=qr_code,
                          ticket_pdf_url=url_for('static', filename=pdf_filename))

@app.route('/clear_database', methods=['POST'])
@login_required
def clear_database():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
        
    try:
        # Delete all bookings first (due to foreign key constraints)
        Booking.query.delete()
        # Delete all events
        Event.query.delete()
        # Delete all non-admin users
        User.query.filter(User.role != 'admin').delete()
        
        # Commit the changes
        db.session.commit()
        flash('Database cleared successfully!')
    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing database: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    # Get analytics data
    now = datetime.utcnow()
    total_users = User.query.count()
    total_events = Event.query.count()
    total_bookings = Booking.query.count()
    pending_events = Event.query.filter_by(status='pending').count()
    
    # User activity statistics
    recent_activities = UserActivity.query.order_by(UserActivity.timestamp.desc()).limit(10).all()
    
    # Event statistics
    events_by_category = db.session.query(
        Event.category, 
        db.func.count(Event.id)
    ).group_by(Event.category).all()
    
    # Booking statistics
    bookings_by_date = db.session.query(
        db.func.date(Booking.booking_date),
        db.func.count(Booking.id)
    ).group_by(db.func.date(Booking.booking_date)).all()
    
    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        total_events=total_events,
        total_bookings=total_bookings,
        pending_events=pending_events,
        recent_activities=recent_activities,
        events_by_category=events_by_category,
        bookings_by_date=bookings_by_date
    )

@app.route('/admin/users')
@login_required
def admin_users():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    if current_user.id == user_id:
        flash('Cannot delete your own admin account')
        return redirect(url_for('admin_users'))
    
    user = User.query.get_or_404(user_id)
    
    # Delete user's bookings
    Booking.query.filter_by(user_id=user_id).delete()
    # Delete user's events
    Event.query.filter_by(organizer_id=user_id).delete()
    # Delete user
    db.session.delete(user)
    db.session.commit()
    
    flash('User deleted successfully')
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_event/<int:event_id>', methods=['POST'])
@login_required
def admin_delete_event(event_id):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    event = Event.query.get_or_404(event_id)
    
    try:
        # Delete associated bookings first (due to foreign key constraints)
        Booking.query.filter_by(event_id=event_id).delete()
        # Delete the event
        db.session.delete(event)
        db.session.commit()
        flash('Event deleted successfully')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting event: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/events')
@login_required
def admin_events():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template('admin/events.html', events=events)

@app.route('/admin/approve_event/<int:event_id>', methods=['POST'])
@login_required
def approve_event(event_id):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    event = Event.query.get_or_404(event_id)
    event.status = 'approved'
    db.session.commit()
    
    log_user_activity(
        current_user.id,
        'approve_event',
        f'Approved event: {event.title}'
    )
    
    flash('Event approved successfully')
    return redirect(url_for('admin_events'))

@app.route('/admin/reject_event/<int:event_id>', methods=['POST'])
@login_required
def reject_event(event_id):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    event = Event.query.get_or_404(event_id)
    event.status = 'rejected'
    db.session.commit()
    
    log_user_activity(
        current_user.id,
        'reject_event',
        f'Rejected event: {event.title}'
    )
    
    flash('Event rejected successfully')
    return redirect(url_for('admin_events'))

@app.route('/admin/activity_log')
@login_required
def activity_log():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    page = request.args.get('page', 1, type=int)
    activities = UserActivity.query.order_by(
        UserActivity.timestamp.desc()
    ).paginate(page=page, per_page=20)
    
    return render_template('admin/activity_log.html', activities=activities)

@app.route('/admin/generate_report')
@login_required
def generate_report():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    report_type = request.args.get('type', 'events')
    
    if report_type == 'events':
        events = Event.query.all()
        output = BytesIO()
        c = canvas.Canvas(output, pagesize=letter)
        
        # Generate PDF report
        y = 750
        c.drawString(100, y, "Events Report")
        y -= 20
        
        for event in events:
            c.drawString(100, y, f"Event: {event.title}")
            y -= 15
            c.drawString(120, y, f"Date: {event.date}")
            y -= 15
            c.drawString(120, y, f"Status: {event.status}")
            y -= 15
            c.drawString(120, y, f"Tickets: {event.remaining_tickets}/{event.total_tickets}")
            y -= 20
            
            if y < 50:
                c.showPage()
                y = 750
        
        c.save()
        output.seek(0)
        
        log_user_activity(
            current_user.id,
            'generate_report',
            'Generated events report'
        )
        
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='events_report.pdf'
        )

@app.route('/admin/backup')
@login_required
def create_backup():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    try:
        # Create backup directory if it doesn't exist
        backup_dir = os.path.join(app.root_path, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Generate backup filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = f'backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_file)
        
        # Create backup
        with open(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', ''), 'rb') as src, \
             open(backup_path, 'wb') as dst:
            dst.write(src.read())
        
        # Record backup in database
        backup = SystemBackup(
            filename=backup_file,
            created_by=current_user.id,
            size=os.path.getsize(backup_path)
        )
        db.session.add(backup)
        db.session.commit()
        
        log_user_activity(
            current_user.id,
            'create_backup',
            f'Created system backup: {backup_file}'
        )
        
        flash('Backup created successfully')
    except Exception as e:
        flash(f'Error creating backup: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/restore/<filename>')
@login_required
def restore_backup(filename):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    try:
        backup_path = os.path.join(app.root_path, 'backups', filename)
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        
        # Restore from backup
        with open(backup_path, 'rb') as src, \
             open(db_path, 'wb') as dst:
            dst.write(src.read())
        
        log_user_activity(
            current_user.id,
            'restore_backup',
            f'Restored system from backup: {filename}'
        )
        
        flash('System restored successfully')
    except Exception as e:
        flash(f'Error restoring system: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        
        if not password:
            flash('Please provide the admin password', 'error')
            return redirect(url_for('admin_login'))
            
        # Use fixed admin email
        admin_email = 'admin@gmail.com'
        user = User.query.filter_by(username=admin_email).first()

        if user and check_password_hash(user.password, password) and user.role == 'admin':
            login_user(user, remember=True)
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        
        flash('Invalid admin password', 'error')
        return redirect(url_for('admin_login'))
        
    return render_template('admin/login.html')

@app.route('/admin/logout', methods=['POST'])
@login_required
def admin_logout():
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    logout_user()
    return redirect(url_for('admin_login'))

@app.route('/messages')
@login_required
def messages():
    # Get all messages for the current user
    received_messages = Message.query.filter_by(receiver_id=current_user.id).order_by(Message.timestamp.desc()).all()
    sent_messages = Message.query.filter_by(sender_id=current_user.id).order_by(Message.timestamp.desc()).all()
    
    # Mark messages as read
    for message in received_messages:
        if not message.read:
            message.read = True
    db.session.commit()
    
    # Get all users and events for the message form
    users = User.query.filter(User.id != current_user.id).all()
    events = Event.query.all()
    
    return render_template('messages.html', 
                         received_messages=received_messages,
                         sent_messages=sent_messages,
                         users=users,
                         events=events)

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    receiver_id = request.form.get('receiver_id')
    content = request.form.get('content')
    event_id = request.form.get('event_id')
    
    if not receiver_id or not content:
        flash('Please provide both receiver and message content')
        return redirect(url_for('messages'))
    
    try:
        message = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            event_id=event_id,
            content=content
        )
        db.session.add(message)
        db.session.commit()
        flash('Message sent successfully!')
    except Exception as e:
        db.session.rollback()
        flash('Error sending message. Please try again.')
    
    return redirect(url_for('messages'))

@app.route('/conversation/<int:user_id>')
@login_required
def conversation(user_id):
    other_user = User.query.get_or_404(user_id)
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    
    # Mark messages as read
    for message in messages:
        if message.receiver_id == current_user.id and not message.read:
            message.read = True
    db.session.commit()
    
    return render_template('conversation.html', other_user=other_user, messages=messages)

@app.route('/profile')
@login_required
def profile():
    if current_user.role == 'student':
        return redirect(url_for('student_profile'))
    elif current_user.role == 'organizer':
        return redirect(url_for('organizer_profile'))
    return redirect(url_for('home'))

@app.route('/student_profile')
@login_required
def student_profile():
    if current_user.role != 'student':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    reviews = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).all()
    
    return render_template('student_profile.html', bookings=bookings, reviews=reviews)

@app.route('/organizer_profile')
@login_required
def organizer_profile():
    if current_user.role != 'organizer':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    total_events = len(events)
    total_bookings = sum(event.bookings.count() for event in events)
    total_revenue = sum(event.price * (event.total_tickets - event.remaining_tickets) for event in events)
    
    return render_template('organizer_profile.html',
                         events=events,
                         total_events=total_events,
                         total_bookings=total_bookings,
                         total_revenue=total_revenue)

@app.route('/notifications')
@login_required
def notifications():
    page = request.args.get('page', 1, type=int)
    notifications = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.timestamp.desc())\
        .paginate(page=page, per_page=10)
    return render_template('notifications.html', notifications=notifications)

@app.route('/notification_preferences', methods=['GET', 'POST'])
@login_required
def notification_preferences():
    prefs = NotificationPreference.query.filter_by(user_id=current_user.id).first()
    if not prefs:
        prefs = NotificationPreference(user_id=current_user.id)
        db.session.add(prefs)
        db.session.commit()
    
    if request.method == 'POST':
        prefs.email_notifications = 'email_notifications' in request.form
        prefs.sms_notifications = 'sms_notifications' in request.form
        prefs.event_updates = 'event_updates' in request.form
        prefs.event_reminders = 'event_reminders' in request.form
        prefs.messages = 'messages' in request.form
        prefs.email = request.form.get('email')
        prefs.phone = request.form.get('phone')
        
        db.session.commit()
        flash('Notification preferences updated successfully!')
        return redirect(url_for('notification_preferences'))
    
    return render_template('notification_preferences.html', preferences=prefs)

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        try:
            # Handle profile picture upload
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    current_user.profile_picture = filename
            
            # Update other fields
            current_user.name = request.form.get('name')
            current_user.email = request.form.get('email')
            current_user.phone = request.form.get('phone')
            
            db.session.commit()
            flash('Profile updated successfully!')
            return redirect(url_for('profile'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error updating profile. Please try again.')
    
    return render_template('edit_profile.html')

@app.route('/reset_password', methods=['GET', 'POST'])
@login_required
def reset_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not check_password_hash(current_user.password, current_password):
            flash('Current password is incorrect')
            return redirect(url_for('reset_password'))
        
        if new_password != confirm_password:
            flash('New passwords do not match')
            return redirect(url_for('reset_password'))
        
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Password updated successfully!')
        return redirect(url_for('profile'))
    
    return render_template('reset_password.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Generate password reset token
            token = generate_reset_token(user)
            # Send password reset email
            send_reset_email(user, token)
            flash('Password reset instructions have been sent to your email')
            return redirect(url_for('login'))
        
        flash('Email address not found')
        return redirect(url_for('forgot_password'))
    
    return render_template('forgot_password.html')

@app.route('/google_login')
def google_login():
    # Implement Google OAuth login
    return redirect(url_for('login'))

@app.route('/event/<int:event_id>')
def event(event_id):
    event = Event.query.get_or_404(event_id)
    return render_template('event_details.html', event=event)

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