# Encypherist - Event Management System

A modern event management system built with Flask, featuring user roles, event creation, booking management, and real-time notifications.

## Features

- User Authentication (Admin, Organizer, Student)
- Event Creation and Management
- Ticket Booking System
- Group Booking Support
- Real-time Notifications
- Messaging System
- Review and Rating System
- Admin Dashboard
- Profile Management

## Tech Stack

- Python 3.11
- Flask
- SQLAlchemy
- PostgreSQL
- Gunicorn
- Flask-Login
- Flask-WTF
- QR Code Generation
- PDF Generation

## Local Development Setup

1. Clone the repository:
```bash
git clone https://github.com/Apex-ace/Encypherist.git
cd Encypherist
```

2. Create and activate virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Initialize the database:
```bash
python init_db.py
```

6. Run the development server:
```bash
python app.py
```

## Deployment on Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure the following:
   - Build Command: `pip install -r requirements.txt && python init_db.py`
   - Start Command: `gunicorn app:app`
   - Python Version: 3.11.0

4. Add Environment Variables:
   - `FLASK_ENV`: production
   - `FLASK_DEBUG`: 1
   - `SQLALCHEMY_ECHO`: true
   - `SECRET_KEY`: (Generate a secure key)
   - `DATABASE_URL`: (Will be automatically added by Render)

5. Create a PostgreSQL Database:
   - Name: encypherist_db
   - Database: encypherist
   - User: encypherist
   - Plan: Free

## Default Admin Credentials

- Email: admin@gmail.com
- Password: 123456789

## License

This project is licensed under the MIT License - see the LICENSE file for details. 