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
from flask_mail import Mail

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# Configure SQLAlchemy for Supabase transaction pooler
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

# Theme configuration for Encypherist
app.config['THEME'] = {
    'primary_color': '#00FF00',  # Bright green
    'secondary_color': '#000000',  # Black
    'accent_color': '#1a1a1a',  # Dark gray
    'text_color': '#FFFFFF',  # White
    'background_color': '#0a0a0a',  # Very dark gray
    'brand_name': 'Encypherist'
}

# Initialize CSRF protection
csrf = CSRFProtect(app)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Enable UUID extension
with app.app_context():
    db.session.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    db.session.commit()

# Test database connection
try:
    with app.app_context():
        db.create_all()
except Exception as e:
    print(f"Error connecting to database: {e}")
    raise

# Add these configurations after your existing app configs
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create upload folders if they don't exist
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'events'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Database Models
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    profile_picture = db.Column(db.String(200))
    created_at = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    
    # Relationships
    events = db.relationship('Event', backref='organizer', lazy='dynamic', cascade='all, delete-orphan')
    bookings = db.relationship('Booking', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic', cascade='all, delete-orphan')
    messages_received = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy='dynamic', cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    notification_preferences = db.relationship('NotificationPreference', backref='user', uselist=False, cascade='all, delete-orphan')
    reviews = db.relationship('Review', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    activities = db.relationship('UserActivity', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    system_backups = db.relationship('SystemBackup', backref='created_by_user', lazy='dynamic', foreign_keys='SystemBackup.created_by')

class Event(db.Model):
    __tablename__ = 'event'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    date = db.Column(TIMESTAMP(timezone=True), nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    payment_qr = db.Column(db.String(500))
    total_tickets = db.Column(db.Integer, default=0)
    remaining_tickets = db.Column(db.Integer, default=0)
    is_group_event = db.Column(db.Boolean, default=False)
    min_group_size = db.Column(db.Integer, default=1)
    max_group_size = db.Column(db.Integer, default=1)
    group_discount_percentage = db.Column(db.Float, default=0)
    category = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    poster_image = db.Column(db.String(200))
    
    # Relationships
    bookings = db.relationship('Booking', backref='event', lazy='dynamic', cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='event', lazy='dynamic', cascade='all, delete-orphan')
    messages = db.relationship('Message', backref='event', lazy='dynamic', cascade='all, delete-orphan')
    reviews = db.relationship('Review', backref='event', lazy='dynamic', cascade='all, delete-orphan')

    # Indexes
    __table_args__ = (
        db.Index('idx_event_date', date),
        db.Index('idx_event_category', category),
        db.Index('idx_event_status', status),
        db.Index('idx_event_created_at', created_at),
    )

class Booking(db.Model):
    __tablename__ = 'booking'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id', ondelete='CASCADE'), nullable=False)
    booking_date = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    payment_status = db.Column(db.String(20), default='pending')
    payment_id = db.Column(db.String(100), unique=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    branch = db.Column(db.String(50), nullable=False)
    year = db.Column(db.String(10), nullable=False)
    
    # Relationships
    group_booking = db.relationship('GroupBooking', backref='booking', uselist=False, cascade='all, delete-orphan')
    
    # Indexes
    __table_args__ = (
        db.Index('idx_booking_user', user_id),
        db.Index('idx_booking_event', event_id),
        db.Index('idx_booking_date', booking_date),
    )

class GroupBooking(db.Model):
    __tablename__ = 'group_booking'
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id', ondelete='CASCADE'), nullable=False)
    group_size = db.Column(db.Integer, nullable=False)
    group_members = db.Column(JSONB, nullable=False)
    discount_applied = db.Column(db.Float, default=0)
    created_at = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))

class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id', ondelete='SET NULL'))
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    read = db.Column(db.Boolean, default=False)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_message_sender', sender_id),
        db.Index('idx_message_receiver', receiver_id),
        db.Index('idx_message_timestamp', timestamp),
    )

class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id', ondelete='SET NULL'))
    type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    sent = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text)
    
    # Indexes
    __table_args__ = (
        db.Index('idx_notification_user', user_id),
        db.Index('idx_notification_timestamp', timestamp),
    )

class NotificationPreference(db.Model):
    __tablename__ = 'notification_preference'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True)
    email_notifications = db.Column(db.Boolean, default=True)
    sms_notifications = db.Column(db.Boolean, default=True)
    event_updates = db.Column(db.Boolean, default=True)
    event_reminders = db.Column(db.Boolean, default=True)
    messages = db.Column(db.Boolean, default=True)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))

class Review(db.Model):
    __tablename__ = 'review'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text)
    created_at = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    
    # Indexes
    __table_args__ = (
        db.Index('idx_review_event', event_id),
        db.CheckConstraint('rating BETWEEN 1 AND 5', name='check_rating_range'),
    )

class UserActivity(db.Model):
    __tablename__ = 'user_activity'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    timestamp = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    ip_address = db.Column(db.String(50))

class SystemBackup(db.Model):
    __tablename__ = 'system_backup'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    created_at = db.Column(TIMESTAMP(timezone=True), server_default=text('CURRENT_TIMESTAMP'))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    size = db.Column(db.Integer)
    status = db.Column(db.String(20), default='completed')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def landing():
    # Clean up past events
    now = datetime.now(timezone.utc)
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
    
    return render_template('index.html', featured_events=featured_events, now=now)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        if not username or not password or not role:
            flash('Please fill in all fields')
            return redirect(url_for('register'))

        if not username.endswith('@gmail.com'):
            flash('Please use a Gmail address')
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
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please provide both username and password', 'error')
            return redirect(url_for('login'))
            
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            # Log failed admin login attempts
            if username == 'admin@gmail.com' and not check_password_hash(user.password, password):
                log_user_activity(
                    user.id if user else None,
                    'failed_admin_login',
                    f'Failed admin login attempt from IP: {request.remote_addr}',
                    request.remote_addr
                )
                flash('Invalid admin credentials', 'error')
                return redirect(url_for('login'))

            login_user(user, remember=True)
            next_page = request.args.get('next')
            
            # Log successful login
            log_user_activity(
                user.id,
                'login',
                f'User logged in successfully from IP: {request.remote_addr}',
                request.remote_addr
            )
            
            flash('Logged in successfully!', 'success')
            
            # Redirect admin users to admin dashboard
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            
            return redirect(next_page) if next_page else redirect(url_for('home'))
        
        flash('Invalid username or password', 'error')
        return redirect(url_for('login'))
        
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))

@app.route('/home')
@login_required
def home():
    try:
        # Clean up past events
        now = datetime.now(timezone.utc)
        past_events = Event.query.filter(Event.date < now).all()
        for event in past_events:
            Booking.query.filter_by(event_id=event.id).delete()
            db.session.delete(event)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error cleaning up past events: {str(e)}")
    
    # Get search and filter parameters
    search_query = request.args.get('search', '').strip()
    category = request.args.get('category', 'all')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    sort_by = request.args.get('sort', 'date')
    
    # Base query for approved future events
    query = Event.query.filter(
        Event.date > now,
        Event.status == 'approved'
    )
    
    # Apply filters
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            db.or_(
                Event.title.ilike(search),
                Event.description.ilike(search),
                Event.location.ilike(search)
            )
        )
    
    if category and category != 'all':
        query = query.filter(Event.category == category)
    
    if min_price is not None:
        query = query.filter(Event.price >= min_price)
    if max_price is not None:
        query = query.filter(Event.price <= max_price)
    
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
        subquery = db.session.query(
            Booking.event_id,
            db.func.count(Booking.id).label('booking_count')
        ).group_by(Booking.event_id).subquery()
        
        query = query.outerjoin(
            subquery, Event.id == subquery.c.event_id
        ).order_by(db.desc(subquery.c.booking_count.nullsfirst()))
    else:
        query = query.order_by(Event.date)
    
    # Get categories for filter
    categories = db.session.query(Event.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]
    
    # Execute query with debug print
    events = query.all()
    print(f"Found {len(events)} events matching criteria")
    
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
            location = request.form.get('venue')  # Changed from location to venue
            price = request.form.get('price')
            date = request.form.get('date')
            time = request.form.get('time')
            category = request.form.get('category')
            is_group_event = 'group_booking' in request.form
            total_tickets = request.form.get('total_tickets', 0)
            payment_qr = request.form.get('payment_qr', '')

            # Debug logging
            print(f"Received event data: Title={title}, Location={location}, Date={date}, Time={time}")

            # Validate required fields
            if not all([title, description, location, price, date, time, category]):
                missing_fields = [field for field, value in {
                    'title': title, 'description': description, 'venue': location,
                    'price': price, 'date': date, 'time': time,
                    'category': category
                }.items() if not value]
                flash(f'Please fill in all required fields. Missing: {", ".join(missing_fields)}')
                return redirect(url_for('create_event'))

            # Convert and validate numeric fields
            try:
                price = float(price)
                total_tickets = int(total_tickets)
                if price < 0:
                    flash('Price must be a positive number')
                    return redirect(url_for('create_event'))
            except ValueError:
                flash('Invalid price value')
                return redirect(url_for('create_event'))

            # Parse date and time with timezone awareness
            try:
                naive_date = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                event_date = naive_date.replace(tzinfo=timezone.utc)
                if event_date < datetime.now(timezone.utc):
                    flash('Event date must be in the future')
                    return redirect(url_for('create_event'))
            except ValueError:
                flash('Invalid date or time format')
                return redirect(url_for('create_event'))

            # Handle payment QR code upload
            if 'payment_qr_file' in request.files:
                qr_file = request.files['payment_qr_file']
                if qr_file and qr_file.filename:
                    # Ensure the filename is secure
                    filename = secure_filename(qr_file.filename)
                    # Add timestamp to filename to make it unique
                    filename = f"qr_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{filename}"
                    
                    # Create uploads directory if it doesn't exist
                    uploads_dir = os.path.join(app.root_path, 'static', 'uploads', 'qr')
                    os.makedirs(uploads_dir, exist_ok=True)
                    
                    # Save the file
                    qr_file.save(os.path.join(uploads_dir, filename))
                    payment_qr = filename

            # Handle poster image upload
            if 'poster' in request.files:
                poster = request.files['poster']
                if poster and allowed_file(poster.filename):
                    filename = secure_filename(f"event_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{poster.filename}")
                    poster_path = os.path.join('uploads', 'events', filename)
                    poster.save(os.path.join('static', poster_path))
                    event.poster_image = poster_path

            # Create event
            event = Event(
                title=title,
                description=description,
                location=location,
                price=price,
                date=event_date,
                organizer_id=current_user.id,
                payment_qr=payment_qr,
                total_tickets=total_tickets,
                remaining_tickets=total_tickets,
                is_group_event=is_group_event,
                min_group_size=request.form.get('min_group_size', 1, type=int),
                max_group_size=request.form.get('max_group_size', 1, type=int),
                group_discount_percentage=request.form.get('group_discount', 0, type=float),
                category=category,
                status='pending'
            )
            
            db.session.add(event)
            db.session.commit()
            
            # Log event creation
            log_user_activity(
                current_user.id,
                'create_event',
                f'Created event: {event.title}',
                request.remote_addr
            )
            
            flash('Event created successfully! Waiting for admin approval.')
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
    try:
        event = Event.query.get_or_404(event_id)
        
        if request.method == 'POST':
            if event.remaining_tickets <= 0:
                flash('Sorry, this event is sold out!')
                return redirect(url_for('event_details', event_id=event_id))

            # Create booking
            booking = Booking(
                user_id=current_user.id,
                event_id=event_id,
                booking_date=datetime.now(timezone.utc),
                payment_status='pending',
                name=request.form.get('name'),
                email=request.form.get('email'),
                mobile=request.form.get('mobile'),
                branch=request.form.get('branch'),
                year=request.form.get('year')
            )
            
            # Update ticket count
            event.remaining_tickets -= 1
            
            try:
                db.session.add(booking)
                db.session.commit()
                
                # Send confirmation email
                send_booking_confirmation_email(booking.email, event, booking)
                
                flash('Booking successful!')
                return redirect(url_for('booking_confirmation', booking_id=booking.id))
            except Exception as e:
                db.session.rollback()
                flash(f'Error creating booking: {str(e)}')
                return redirect(url_for('event_details', event_id=event_id))
                
        return render_template('book_event.html', event=event)
    except Exception as e:
        flash(f'Error accessing event: {str(e)}')
        return redirect(url_for('home'))

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
            
            # Update booking status
            booking.payment_status = 'succeeded'
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
    # Enhanced admin access check
    if not current_user.is_authenticated or current_user.role != 'admin':
        log_user_activity(
            current_user.id if current_user.is_authenticated else None,
            'unauthorized_admin_access',
            f'Unauthorized admin access attempt from IP: {request.remote_addr}',
            request.remote_addr
        )
        flash('Unauthorized access. This incident will be logged.', 'error')
        return redirect(url_for('home'))
    
    try:
        # Get analytics data
        now = datetime.utcnow()
        total_users = User.query.count()
        total_events = Event.query.count()
        total_bookings = Booking.query.count()
        pending_events = Event.query.filter_by(status='pending').count()
        
        # User activity statistics
        recent_activities = UserActivity.query.order_by(
            UserActivity.timestamp.desc()
        ).limit(10).all()
    
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
        
        # Log admin dashboard access
        log_user_activity(
            current_user.id,
            'admin_dashboard_access',
            'Admin accessed dashboard',
            request.remote_addr
        )
    
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
    except Exception as e:
        log_user_activity(
            current_user.id,
            'admin_dashboard_error',
            f'Error in admin dashboard: {str(e)}',
            request.remote_addr
        )
        flash('An error occurred while loading the dashboard', 'error')
        return redirect(url_for('home'))

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
    
    try:
        # Get all events with their organizers using a join
        events = db.session.query(Event, User).join(
            User, Event.organizer_id == User.id
        ).order_by(Event.created_at.desc()).all()
        
        # Debug logging
        print(f"Found {len(events)} events in admin panel")
        for event, organizer in events:
            print(f"Event: {event.title}, Organizer: {organizer.username}, Status: {event.status}")
        
        return render_template('admin/events.html', events=events)
    except Exception as e:
        print(f"Error in admin events: {str(e)}")
        db.session.rollback()
        flash('Error loading events. Please check the logs.')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/approve_event/<int:event_id>', methods=['POST'])
@login_required
def approve_event(event_id):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    try:
        event = Event.query.get_or_404(event_id)
        
        # Debug logging
        print(f"Approving event: {event.title}, Current status: {event.status}")
        
        # Only allow approval of pending events
        if event.status != 'pending':
            flash('Only pending events can be approved')
            return redirect(url_for('admin_events'))
        
        event.status = 'approved'
        db.session.commit()
        
        # Debug logging
        print(f"Event approved: {event.title}, New status: {event.status}")
        
        # Log approval
        log_user_activity(
            current_user.id,
            'approve_event',
            f'Approved event: {event.title}',
            request.remote_addr
        )
        
        # Notify organizer
        try:
            send_notification(
                event.organizer_id,
                'Event Approved',
                f'Your event "{event.title}" has been approved and is now visible to users.',
                'event_approval',
                event.id
            )
        except Exception as e:
            print(f"Error sending notification: {str(e)}")
            # Don't rollback the approval if notification fails
        
        flash('Event approved successfully')
    except Exception as e:
        db.session.rollback()
        flash(f'Error approving event: {str(e)}')
        return redirect(url_for('admin_events'))

@app.route('/admin/reject_event/<int:event_id>', methods=['POST'])
@login_required
def reject_event(event_id):
    if current_user.role != 'admin':
        flash('Unauthorized access')
        return redirect(url_for('home'))
    
    try:
        event = Event.query.get_or_404(event_id)
        event.status = 'rejected'
        db.session.commit()
        
        # Log rejection
        log_user_activity(
            current_user.id,
            'reject_event',
            f'Rejected event: {event.title}',
            request.remote_addr
        )
        
        # Notify organizer
        send_notification(
            event.organizer_id,
            'Event Rejected',
            f'Your event "{event.title}" has been rejected by the admin.',
            'event_rejection'
        )
    
        flash('Event rejected successfully')
    except Exception as e:
        db.session.rollback()
        flash(f'Error rejecting event: {str(e)}')
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

# Add activity logging function
def log_user_activity(user_id, activity_type, description, ip_address=None):
    try:
        activity = UserActivity(
            user_id=user_id,
            activity_type=activity_type,
            description=description,
            ip_address=ip_address
        )
        db.session.add(activity)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error logging activity: {str(e)}")

# Notification and messaging functions
def send_notification(user_id, title, content, notification_type, event_id=None):
    try:
        notification = Notification(
            user_id=user_id,
            event_id=event_id,
            type=notification_type,
            title=title,
            content=content
        )
        db.session.add(notification)
        
        # Get user preferences
        prefs = NotificationPreference.query.filter_by(user_id=user_id).first()
        if not prefs:
            prefs = NotificationPreference(user_id=user_id)
            db.session.add(prefs)
        
        # Send email if enabled
        if notification_type == 'email' and prefs.email_notifications and prefs.email:
            send_email(prefs.email, title, content)
            notification.sent = True
        
        # Send SMS if enabled
        if notification_type == 'sms' and prefs.sms_notifications and prefs.phone:
            send_sms(prefs.phone, content)
            notification.sent = True
        
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error sending notification: {str(e)}")
        return False

def send_event_update(event_id, title, content):
    event = Event.query.get(event_id)
    if not event:
        return False
    
    # Get all bookings for this event
    bookings = Booking.query.filter_by(event_id=event_id).all()
    
    for booking in bookings:
        # Send in-app notification
        send_notification(booking.user_id, title, content, 'in-app', event_id)
        
        # Send email notification
        send_notification(booking.user_id, title, content, 'email', event_id)
        
        # Send SMS notification
        send_notification(booking.user_id, title, content, 'sms', event_id)
    
    return True

def send_event_reminder():
    # Get events happening in the next 24 hours
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    events = Event.query.filter(
        Event.date > now,
        Event.date <= tomorrow
    ).all()
    
    for event in events:
        bookings = Booking.query.filter_by(event_id=event.id).all()
        for booking in bookings:
            title = f"Reminder: {event.title} is tomorrow!"
            content = f"Don't forget! {event.title} is happening tomorrow at {event.date.strftime('%I:%M %p')} at {event.location}."
            send_notification(booking.user_id, title, content, 'email', event.id)
            send_notification(booking.user_id, title, content, 'sms', event.id)

@app.route('/messages')
@login_required
def messages():
    try:
        # Get the other user's ID from query parameters
        other_user_id = request.args.get('user_id', type=int)
        
        # Get all conversations for the current user
        conversations = {}
        sent_messages = Message.query.filter_by(sender_id=current_user.id).all()
        received_messages = Message.query.filter_by(receiver_id=current_user.id).all()
        
        # Combine all messages and get unique conversations
        all_messages = sent_messages + received_messages
        for message in all_messages:
            other_id = message.receiver_id if message.sender_id == current_user.id else message.sender_id
            other_user = User.query.get(other_id)
            
            if other_id not in conversations:
                conversations[other_id] = {
                    'user': other_user,
                    'last_message': message,
                    'unread': Message.query.filter_by(
                        sender_id=other_id,
                        receiver_id=current_user.id,
                        read=False
                    ).count()
                }
        
        # If a specific conversation is selected, get those messages
        messages = None
        other_user = None
        if other_user_id:
            other_user = User.query.get_or_404(other_user_id)
            messages = Message.query.filter(
                ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user_id)) |
                ((Message.sender_id == other_user_id) & (Message.receiver_id == current_user.id))
            ).order_by(Message.timestamp.asc()).all()
            
            # Mark messages as read
            for message in messages:
                if message.receiver_id == current_user.id and not message.read:
                    message.read = True
            
            db.session.commit()
        
        return render_template('messages.html', 
                             conversations=conversations,
                             messages=messages,
                             other_user=other_user)
                             
    except Exception as e:
        print(f"Error in messages route: {str(e)}")
        db.session.rollback()
        flash('An error occurred while loading messages')
        return redirect(url_for('home'))

@app.route('/send_message/<int:user_id>', methods=['POST'])
@login_required
def send_message(user_id):
    try:
        data = request.get_json()
        content = data.get('content')
        
        if not content:
            return jsonify({'error': 'Message cannot be empty'}), 400
            
        message = Message(
            sender_id=current_user.id,
            receiver_id=user_id,
            content=content,
            timestamp=datetime.now(timezone.utc)
        )
        
        db.session.add(message)
        db.session.commit()
        
        return jsonify({
            'id': message.id,
            'content': message.content,
            'timestamp': message.timestamp.isoformat(),
            'sender_name': current_user.username
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/notifications')
@login_required
def notifications():
    page = request.args.get('page', 1, type=int)
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(
        Notification.timestamp.desc()
    ).paginate(page=page, per_page=20)
    
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
        flash('Notification preferences updated successfully')
        return redirect(url_for('notification_preferences'))
    
    return render_template('notification_preferences.html', preferences=prefs)

# Helper functions for sending notifications
def send_email(to_email, subject, content):
    # TODO: Implement email sending using your preferred email service
    # For example, using Flask-Mail or a third-party service like SendGrid
    pass

def send_sms(phone_number, message):
    # TODO: Implement SMS sending using your preferred SMS service
    # For example, using Twilio or a similar service
    pass

def send_booking_confirmation_email(email, event, booking):
    try:
        msg = Message(
            'Booking Confirmation',
            sender=app.config['MAIL_DEFAULT_SENDER'],
            recipients=[email]
        )
        msg.body = f'''
        Thank you for booking {event.title}!
        
        Booking Details:
        - Event: {event.title}
        - Date: {event.date.strftime('%B %d, %Y at %I:%M %p')}
        - Location: {event.location}
        - Booking ID: {booking.id}
        
        Please keep this email for your records.
        '''
        mail.send(msg)
    except Exception as e:
        print(f"Error sending confirmation email: {str(e)}")

@app.route('/profile')
@login_required
def profile():
    try:
        now = datetime.now(timezone.utc)
        
        if current_user.role == 'organizer':
            events = Event.query.filter_by(organizer_id=current_user.id)\
                .order_by(Event.date.desc())\
                .all()
            return render_template('organizer_profile.html',
                                user=current_user,
                                events=events,
                                now=now)
        else:
            bookings = Booking.query.filter_by(user_id=current_user.id)\
                .join(Event)\
                .order_by(Booking.booking_date.desc())\
                .all()
            return render_template('student_profile.html',
                                user=current_user,
                                bookings=bookings,
                                now=now)
    except Exception as e:
        flash(f'Error loading profile: {str(e)}')
        return redirect(url_for('home'))

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        try:
            # Handle profile picture upload
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename:
                    # Ensure the filename is secure
                    filename = secure_filename(file.filename)
                    # Add timestamp to filename to make it unique
                    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
                    
                    # Create uploads directory if it doesn't exist
                    uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
                    os.makedirs(uploads_dir, exist_ok=True)
                    
                    # Save the file
                    file.save(os.path.join(uploads_dir, filename))
                    
                    # Delete old profile picture if it exists
                    if current_user.profile_picture:
                        try:
                            old_file = os.path.join(uploads_dir, current_user.profile_picture)
                            if os.path.exists(old_file):
                                os.remove(old_file)
                        except Exception as e:
                            print(f"Error deleting old profile picture: {str(e)}")
                    
                    current_user.profile_picture = filename
            
            db.session.commit()
            flash('Profile updated successfully')
            return redirect(url_for('profile'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {str(e)}')
            return redirect(url_for('edit_profile'))
    
    return render_template('edit_profile.html', user=current_user)

@app.route('/reset_password', methods=['GET', 'POST'])
@login_required
def reset_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not current_password or not new_password or not confirm_password:
            flash('Please fill in all fields')
            return redirect(url_for('reset_password'))
        
        if not check_password_hash(current_user.password, current_password):
            flash('Current password is incorrect')
            return redirect(url_for('reset_password'))
        
        if new_password != confirm_password:
            flash('New passwords do not match')
            return redirect(url_for('reset_password'))
        
        if len(new_password) < 6:
            flash('New password must be at least 6 characters long')
            return redirect(url_for('reset_password'))
        
        try:
            current_user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password updated successfully')
            return redirect(url_for('profile'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating password: {str(e)}')
            return redirect(url_for('reset_password'))
    
    return render_template('reset_password.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash('Please enter your email address')
            return redirect(url_for('forgot_password'))
        
        user = User.query.filter_by(username=email).first()
        if not user:
            flash('No account found with that email address')
            return redirect(url_for('forgot_password'))
        
        # Generate password reset token
        reset_token = generate_password_hash(str(datetime.utcnow()))
        user.reset_token = reset_token
        user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        
        # Send password reset email
        reset_url = url_for('reset_password_token', token=reset_token, _external=True)
        send_notification(
            user.id,
            'Password Reset Request',
            f'Click the following link to reset your password: {reset_url}\nThis link will expire in 1 hour.',
            'email'
        )
        
        flash('Password reset instructions have been sent to your email')
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        flash('Invalid or expired password reset link')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not new_password or not confirm_password:
            flash('Please fill in all fields')
            return redirect(url_for('reset_password_token', token=token))
        
        if new_password != confirm_password:
            flash('Passwords do not match')
            return redirect(url_for('reset_password_token', token=token))
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long')
            return redirect(url_for('reset_password_token', token=token))
        
        try:
            user.password = generate_password_hash(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            flash('Password has been reset successfully. Please login with your new password.')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error resetting password: {str(e)}')
            return redirect(url_for('reset_password_token', token=token))
    
    return render_template('reset_password_token.html')

@app.route('/submit_review/<int:event_id>', methods=['POST'])
@login_required
def submit_review(event_id):
    if current_user.role != 'student':
        flash('Only students can submit reviews')
        return redirect(url_for('home'))
    
    try:
        event = Event.query.get_or_404(event_id)
        booking = Booking.query.filter_by(
            user_id=current_user.id,
            event_id=event_id
        ).first()
        
        if not booking:
            flash('You can only review events you have booked')
            return redirect(url_for('profile'))
            
        # Check if user has already reviewed this event
        existing_review = Review.query.filter_by(
            user_id=current_user.id,
            event_id=event_id
        ).first()
        
        if existing_review:
            flash('You have already reviewed this event')
            return redirect(url_for('profile'))
        
        rating = request.form.get('rating')
        review_text = request.form.get('review_text')
        
        if not rating or not rating.isdigit() or int(rating) < 1 or int(rating) > 5:
            flash('Please provide a valid rating (1-5 stars)')
            return redirect(url_for('profile'))
        
        review = Review(
            user_id=current_user.id,
            event_id=event_id,
            rating=int(rating),
            review_text=review_text
        )
        
        db.session.add(review)
        db.session.commit()
        
        flash('Review submitted successfully!')
        return redirect(url_for('profile'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error submitting review: {str(e)}')
        return redirect(url_for('profile'))

@app.route('/event_reviews/<int:event_id>')
def event_reviews(event_id):
    event = Event.query.get_or_404(event_id)
    reviews = Review.query.filter_by(event_id=event_id).order_by(Review.created_at.desc()).all()
    
    # Calculate average rating
    avg_rating = db.session.query(db.func.avg(Review.rating)).filter(Review.event_id == event_id).scalar()
    
    return jsonify({
        'reviews': [{
            'username': review.user.username,
            'rating': review.rating,
            'review_text': review.review_text,
            'created_at': review.created_at.strftime('%B %d, %Y')
        } for review in reviews],
        'average_rating': float(avg_rating) if avg_rating else 0,
        'total_reviews': len(reviews)
    })

@app.route('/book_group/<int:event_id>', methods=['GET', 'POST'])
@login_required
def book_group(event_id):
    event = Event.query.get_or_404(event_id)
    
    if not event.is_group_event:
        flash('This event does not support group bookings.', 'error')
        return redirect(url_for('event_details', event_id=event_id))
    
    if request.method == 'POST':
        try:
            group_size = int(request.form.get('group_size'))
            
            # Validate group size
            if group_size < event.min_group_size or group_size > event.max_group_size:
                flash('Invalid group size.', 'error')
                return redirect(url_for('book_group', event_id=event_id))
            
            # Check ticket availability
            if event.remaining_tickets < group_size:
                flash('Not enough tickets available for the group.', 'error')
                return redirect(url_for('book_group', event_id=event_id))
            
            # Calculate total price with discount
            price_per_person = event.price
            discount = event.group_discount_percentage / 100
            total_price = price_per_person * group_size * (1 - discount)
            
            # Create the main booking
            booking = Booking(
                user_id=current_user.id,
                event_id=event_id,
                ticket_count=group_size,
                total_amount=total_price,
                status='confirmed'
            )
            db.session.add(booking)
            
            # Create group booking entry
            group_members = []
            for i in range(group_size):
                member = {
                    'name': request.form.get(f'member_name_{i}'),
                    'email': request.form.get(f'member_email_{i}'),
                    'mobile': request.form.get(f'member_mobile_{i}'),
                    'branch': request.form.get(f'member_branch_{i}'),
                    'year': request.form.get(f'member_year_{i}')
                }
                group_members.append(member)
            
            group_booking = GroupBooking(
                booking_id=booking.id,
                group_size=group_size,
                group_members=json.dumps(group_members),
                discount_applied=event.group_discount_percentage
            )
            db.session.add(group_booking)
            
            # Update event ticket count
            event.remaining_tickets -= group_size
            
            db.session.commit()
            
            # Send confirmation emails to all group members
            for member in group_members:
                send_booking_confirmation_email(
                    member['email'],
                    event,
                    booking,
                    is_group_member=True
                )
            
            flash('Group booking successful! Confirmation emails have been sent to all members.', 'success')
            return redirect(url_for('booking_confirmation', booking_id=booking.id))
            
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while processing your booking. Please try again.', 'error')
            print(f"Error in group booking: {str(e)}")
            return redirect(url_for('book_group', event_id=event_id))
    
    # Add group booking form context
    min_size = event.min_group_size
    max_size = event.max_group_size
    discount = event.group_discount_percentage if hasattr(event, 'group_discount_percentage') else 0
    
    return render_template('group_booking.html', 
                         event=event,
                         min_size=min_size,
                         max_size=max_size,
                         discount=discount)

# Add this route after your other routes
@app.route('/event/<int:event_id>')
def event_details(event_id):
    try:
        event = Event.query.get_or_404(event_id)
        return render_template('event_details.html', event=event)
    except Exception as e:
        flash('Error loading event details')
        return redirect(url_for('home'))

# Create views
def create_views():
    with app.app_context():
        # Create upcoming_events view
        db.session.execute(text("""
            CREATE OR REPLACE VIEW upcoming_events AS
            SELECT *
            FROM event
            WHERE date > CURRENT_TIMESTAMP
            AND status = 'approved'
            ORDER BY date ASC;
        """))
        
        # Create event_statistics view
        db.session.execute(text("""
            CREATE OR REPLACE VIEW event_statistics AS
            SELECT 
                e.id,
                e.title,
                e.date,
                COUNT(DISTINCT b.id) AS booking_count,
                AVG(r.rating) AS average_rating,
                COUNT(DISTINCT r.id) AS review_count
            FROM event e
            LEFT JOIN booking b ON e.id = b.event_id
            LEFT JOIN review r ON e.id = r.event_id
            GROUP BY e.id, e.title, e.date;
        """))
        
        db.session.commit()

# Create functions
def create_functions():
    with app.app_context():
        # Function to create notifications for new events
        db.session.execute(text("""
            CREATE OR REPLACE FUNCTION notify_event_creation()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO notification (user_id, event_id, type, title, content)
                SELECT u.id, NEW.id, 'new_event', 'New Event: ' || NEW.title, 
                       'A new event has been created: ' || NEW.title || ' on ' || NEW.date
                FROM "user" u
                JOIN notification_preference np ON np.user_id = u.id
                WHERE np.event_updates = TRUE;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        
        # Function to log user activity
        db.session.execute(text("""
            CREATE OR REPLACE FUNCTION log_user_activity(
                p_user_id INTEGER,
                p_activity_type VARCHAR(50),
                p_description TEXT,
                p_ip_address VARCHAR(50)
            )
            RETURNS VOID AS $$
            BEGIN
                INSERT INTO user_activity (user_id, activity_type, description, ip_address)
                VALUES (p_user_id, p_activity_type, p_description, p_ip_address);
            END;
            $$ LANGUAGE plpgsql;
        """))
        
        db.session.commit()

# Create triggers
def create_triggers():
    with app.app_context():
        # Trigger for event creation notification
        db.session.execute(text("""
            DROP TRIGGER IF EXISTS after_event_insert ON event;
            CREATE TRIGGER after_event_insert
            AFTER INSERT ON event
            FOR EACH ROW
            EXECUTE FUNCTION notify_event_creation();
        """))
        
        db.session.commit()

# Initialize database schema
def init_db():
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Create admin user if not exists
        admin = User.query.filter_by(username='admin@gmail.com').first()
        if not admin:
            admin = User(
                username='admin@gmail.com',
                password=generate_password_hash('admin@123#'),
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully!")
        
        # Create views, functions, and triggers
        create_views()
        create_functions()
        create_triggers()

# Initialize database on startup
if __name__ == '__main__':
    with app.app_context():
        # Drop all views first
        db.session.execute(text('DROP VIEW IF EXISTS event_statistics CASCADE;'))
        db.session.execute(text('DROP VIEW IF EXISTS upcoming_events CASCADE;'))
        db.session.commit()
        
        db.drop_all()
        db.create_all()
        
        # Create views after tables are created
        create_views()
        create_functions()
        create_triggers()
        
        # Create admin user if not exists
        admin = User.query.filter_by(username='admin@gmail.com').first()
        if not admin:
            admin = User(
                username='admin@gmail.com',
                password=generate_password_hash('admin@123#'),
                role='admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully!")
        
    app.run(debug=True)

@app.route('/booking_confirmation/<int:booking_id>')
@login_required
def booking_confirmation(booking_id):
    try:
        booking = Booking.query.get_or_404(booking_id)
        if booking.user_id != current_user.id:
            flash('Unauthorized access')
            return redirect(url_for('home'))
            
        return render_template('booking_confirmation.html', booking=booking)
    except Exception as e:
        flash(f'Error accessing booking confirmation: {str(e)}')
        return redirect(url_for('home'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

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