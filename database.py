from supabase import create_client, Client
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

# User operations
def get_user_by_id(user_id):
    try:
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting user by ID: {str(e)}")
        return None

def get_user_by_username(username):
    try:
        response = supabase.table('users').select('*').eq('username', username).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting user by username: {str(e)}")
        return None

def create_user(user_data):
    try:
        response = supabase.table('users').insert(user_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating user: {str(e)}")
        return None

def update_user(user_id, user_data):
    try:
        response = supabase.table('users').update(user_data).eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating user: {str(e)}")
        return None

def get_users():
    try:
        response = supabase.table('users').select('*').execute()
        return response.data
    except Exception as e:
        print(f"Error getting users: {str(e)}")
        return []

# Event operations
def get_events(filters=None):
    try:
        query = supabase.table('events').select('*')
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error getting events: {str(e)}")
        return []

def create_event(event_data):
    try:
        response = supabase.table('events').insert(event_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating event: {str(e)}")
        return None

def update_event(event_id, event_data):
    try:
        response = supabase.table('events').update(event_data).eq('id', event_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating event: {str(e)}")
        return None

def delete_event(event_id):
    try:
        response = supabase.table('events').delete().eq('id', event_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting event: {str(e)}")
        return False

# Booking operations
def get_bookings(filters=None):
    try:
        query = supabase.table('bookings').select('*')
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error getting bookings: {str(e)}")
        return []

def create_booking(booking_data):
    try:
        response = supabase.table('bookings').insert(booking_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating booking: {str(e)}")
        return None

def update_booking(booking_id, booking_data):
    try:
        response = supabase.table('bookings').update(booking_data).eq('id', booking_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating booking: {str(e)}")
        return None

def delete_booking(booking_id):
    try:
        response = supabase.table('bookings').delete().eq('id', booking_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting booking: {str(e)}")
        return False

# Notification operations
def get_notifications(filters=None):
    try:
        query = supabase.table('notifications').select('*')
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error getting notifications: {str(e)}")
        return []

def create_notification(notification_data):
    try:
        response = supabase.table('notifications').insert(notification_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating notification: {str(e)}")
        return None

def update_notification(notification_id, notification_data):
    try:
        response = supabase.table('notifications').update(notification_data).eq('id', notification_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating notification: {str(e)}")
        return None

# Message operations
def get_messages(filters=None):
    try:
        query = supabase.table('messages').select('*')
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error getting messages: {str(e)}")
        return []

def create_message(message_data):
    try:
        response = supabase.table('messages').insert(message_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating message: {str(e)}")
        return None

def update_message(message_id, message_data):
    try:
        response = supabase.table('messages').update(message_data).eq('id', message_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating message: {str(e)}")
        return None

# User Activity operations
def get_user_activities(limit=None):
    try:
        query = supabase.table('user_activity').select('*').order('timestamp', desc=True)
        if limit:
            query = query.limit(limit)
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error getting user activities: {str(e)}")
        return []

def log_activity(user_id, activity_type, description, ip_address=None):
    try:
        activity_data = {
            'user_id': user_id,
            'activity_type': activity_type,
            'description': description,
            'ip_address': ip_address
        }
        response = supabase.table('user_activity').insert(activity_data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error logging activity: {str(e)}")
        return None 