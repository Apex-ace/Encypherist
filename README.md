# Encypherist - Event Management System

A modern event management system built with Flask, featuring user authentication, event creation, booking management, and real-time messaging.

## Features

- User Authentication (Student/Organizer)
- Event Creation and Management
- Ticket Booking System
- Real-time Messaging
- Profile Management
- Responsive Design with Modern UI
- Secure Payment Integration

## Tech Stack

- Python 3.8+
- Flask
- SQLAlchemy
- Flask-Login
- Flask-WTF
- SQLite (Development) / PostgreSQL (Production)
- HTML5, CSS3, JavaScript
- TailwindCSS

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git

## Local Development Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/encypherist.git
cd encypherist
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the root directory:
```env
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///encypherist.db
```

5. Initialize the database:
```bash
flask db init
flask db migrate
flask db upgrade
```

6. Run the development server:
```bash
flask run
```

The application will be available at `http://localhost:5000`

## Deployment on Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure the following settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Environment Variables:
     ```
     FLASK_APP=app.py
     FLASK_ENV=production
     SECRET_KEY=your-secret-key
     DATABASE_URL=your-postgresql-url
     ```

## Project Structure

```
encypherist/
├── app/
│   ├── __init__.py
│   ├── models/
│   ├── routes/
│   ├── static/
│   └── templates/
├── migrations/
├── .env
├── .gitignore
├── app.py
├── config.py
├── requirements.txt
└── README.md
```

## Contributing

1. Fork the repository
2. Create a new branch (`git checkout -b feature/improvement`)
3. Make your changes
4. Commit your changes (`git commit -am 'Add new feature'`)
5. Push to the branch (`git push origin feature/improvement`)
6. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support, please open an issue in the GitHub repository or contact the maintainers. 