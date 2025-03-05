from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user, login_user, logout_user
from app.models import User, Event, Booking
from app import db
from datetime import datetime, timezone

main = Blueprint('main', __name__)

@main.route('/')
def index():
    featured_events = Event.query.filter_by(status='active').limit(6).all()
    return render_template('index.html', featured_events=featured_events)

# ... rest of your routes ... 