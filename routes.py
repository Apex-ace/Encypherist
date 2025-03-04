from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user, login_user, logout_user
from models import db, User, Event, Announcement

main = Blueprint('main', __name__)

@main.route('/')
def index():
    featured_events = Event.query.filter_by(is_featured=True).order_by(Event.date.asc()).limit(3).all()
    announcements = Announcement.query.filter_by(is_active=True).order_by(Announcement.priority.desc(), Announcement.created_at.desc()).all()
    return render_template('index.html', featured_events=featured_events, announcements=announcements)

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(username=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('main.index'))
        flash('Invalid email or password')
    return render_template('login.html')

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'student')  # Default to student if no role selected

        # Validation
        if not email or not password:
            flash('Please fill in all fields')
            return redirect(url_for('main.register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters long')
            return redirect(url_for('main.register'))

        if role not in ['student', 'organizer']:
            flash('Invalid role selected')
            return redirect(url_for('main.register'))

        if User.query.filter_by(username=email).first():
            flash('Email already registered')
            return redirect(url_for('main.register'))

        try:
            user = User(username=email, role=role)  # Using email as username
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.')
            return redirect(url_for('main.register'))

    return render_template('register.html') 