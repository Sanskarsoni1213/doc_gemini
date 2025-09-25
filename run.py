# This Flask application serves as the backend for the Doctor-Patient Queue System.
# It handles user authentication, queue management, and provides analytics.

# To run this, you will need to install Flask, Flask-SQLAlchemy, and Flask-CORS.
# pip install Flask Flask-SQLAlchemy Flask-CORS

import os
import uuid
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS # Import CORS
from datetime import datetime, timedelta
import time
import random

# --- Configuration ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app) # Enable CORS for the application

db = SQLAlchemy(app)

# --- Database Models ---
class User(db.Model):
    """Represents a user (patient or doctor) in the system."""
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False) # In a real app, use hashed passwords
    role = db.Column(db.String(20), nullable=False) # 'patient', 'doctor', 'admin'
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    specialty = db.Column(db.String(50)) # For doctors

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'specialty': self.specialty
        }

class Queue(db.Model):
    """Represents a patient in a doctor's waiting queue."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    doctor_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_emergency = db.Column(db.Boolean, default=False)

    user = db.relationship('User', foreign_keys=[user_id], backref='queue_entries')
    doctor = db.relationship('User', foreigns_keys=[doctor_id], backref='doctor_queues')

class Consultation(db.Model):
    """Records historical consultation data for analytics and AI estimation."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(36), db.ForeignKey('user.id'))
    doctor_id = db.Column(db.String(36), db.ForeignKey('user.id'))
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    duration_minutes = db.Column(db.Integer)

# --- Routes ---

# Helper function to fast-track emergency patients
def sort_queue(queue_list):
    """Sorts the queue with emergency patients at the top."""
    # A more complex system would handle real-time changes
    return sorted(queue_list, key=lambda x: (x.is_emergency, x.joined_at))

# AI-based wait time estimation
def estimate_wait_time(doctor_id):
    """
    Estimates the wait time for a doctor.
    This is a simplified AI model using historical data. In a real-world scenario,
    this would be a trained model.
    """
    # Fetch historical consultation durations for the doctor
    historical_durations = db.session.query(Consultation.duration_minutes).filter_by(doctor_id=doctor_id).all()
    
    if not historical_durations:
        # Fallback to a default average if no data exists
        return 15 # Default 15 minutes
    
    durations = [d[0] for d in historical_durations if d[0] is not None]
    if not durations:
        return 15

    avg_duration = sum(durations) / len(durations)
    
    # Get the current queue length for the doctor
    queue_length = db.session.query(Queue).filter_by(doctor_id=doctor_id).count()
    
    estimated_time = queue_length * avg_duration
    return int(estimated_time)

@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user (patient or doctor)."""
    data = request.json
    # Validate data (simplified)
    if not all(k in data for k in ('email', 'password', 'role')):
        return jsonify({'message': 'Missing required fields'}), 400

    # In a real app, hash the password
    new_user = User(
        email=data['email'],
        password=data['password'],
        role=data['role'],
        first_name=data.get('firstName', ''),
        last_name=data.get('lastName', ''),
        specialty=data.get('specialty', '')
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'User registered successfully', 'user_id': new_user.id}), 201

@app.route('/api/login', methods=['POST'])
def login():
    """Login a user and return their role and user ID."""
    data = request.json
    user = User.query.filter_by(email=data['email'], password=data['password']).first()
    if user:
        # A real system would use JWT tokens for authentication
        return jsonify({
            'message': 'Login successful',
            'user_id': user.id,
            'role': user.role
        }), 200
    else:
        return jsonify({'message': 'Invalid credentials'}), 401

@app.route('/api/doctors', methods=['GET'])
def get_doctors():
    """Returns a list of all doctors in the system."""
    doctors = User.query.filter_by(role='doctor').all()
    return jsonify([d.to_dict() for d in doctors]), 200

@app.route('/api/queue/join', methods=['POST'])
def join_queue():
    """Patient joins a specific doctor's queue."""
    data = request.json
    user_id = data.get('user_id')
    doctor_id = data.get('doctor_id')
    is_emergency = data.get('is_emergency', False)

    # Check if user is already in a queue
    existing_queue = Queue.query.filter_by(user_id=user_id).first()
    if existing_queue:
        return jsonify({'message': 'You are already in a queue'}), 409

    new_queue_entry = Queue(user_id=user_id, doctor_id=doctor_id, is_emergency=is_emergency)
    db.session.add(new_queue_entry)
    db.session.commit()
    return jsonify({'message': 'Successfully joined the queue'}), 201

@app.route('/api/queue/position/<user_id>', methods=['GET'])
def get_queue_position(user_id):
    """Returns a patient's current position in the queue."""
    queue_entry = Queue.query.filter_by(user_id=user_id).first()
    if not queue_entry:
        return jsonify({'message': 'Not in a queue'}), 404

    doctor_queue = Queue.query.filter_by(doctor_id=queue_entry.doctor_id).order_by(Queue.joined_at).all()
    position = doctor_queue.index(queue_entry) + 1
    
    estimated_wait = estimate_wait_time(queue_entry.doctor_id)
    
    return jsonify({
        'position': position,
        'doctor_id': queue_entry.doctor_id,
        'estimated_wait_minutes': estimated_wait
    }), 200

@app.route('/api/doctor/queue/<doctor_id>', methods=['GET'])
def get_doctor_queue(doctor_id):
    """Returns the list of patients in a doctor's queue."""
    queue_entries = Queue.query.filter_by(doctor_id=doctor_id).all()
    # Apply sorting with emergency patients first
    sorted_entries = sorted(queue_entries, key=lambda x: (not x.is_emergency, x.joined_at))

    patients = []
    for entry in sorted_entries:
        user = User.query.get(entry.user_id)
        if user:
            patients.append({
                'queue_id': entry.id,
                'user_id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'joined_at': entry.joined_at,
                'is_emergency': entry.is_emergency
            })
    return jsonify(patients), 200

@app.route('/api/doctor/complete_consultation', methods=['POST'])
def complete_consultation():
    """Marks a consultation as complete and updates historical data."""
    data = request.json
    queue_id = data.get('queue_id')
    
    queue_entry = Queue.query.get(queue_id)
    if not queue_entry:
        return jsonify({'message': 'Queue entry not found'}), 404

    # Record the consultation duration
    now = datetime.utcnow()
    duration = (now - queue_entry.joined_at).seconds // 60
    
    new_consultation = Consultation(
        patient_id=queue_entry.user_id,
        doctor_id=queue_entry.doctor_id,
        start_time=queue_entry.joined_at,
        end_time=now,
        duration_minutes=duration if duration > 0 else 1 # Ensure duration is at least 1 minute
    )
    db.session.add(new_consultation)
    db.session.delete(queue_entry)
    db.session.commit()

    return jsonify({'message': 'Consultation completed successfully'}), 200

@app.route('/api/admin/analytics', methods=['GET'])
def get_analytics():
    """Provides analytics data for the admin dashboard."""
    total_patients = User.query.filter_by(role='patient').count()
    total_doctors = User.query.filter_by(role='doctor').count()

    # Calculate average consultation time
    avg_consultation_time = db.session.query(db.func.avg(Consultation.duration_minutes)).scalar()
    avg_consultation_time = round(avg_consultation_time, 2) if avg_consultation_time else 0

    # Simulate peak hours data
    peak_hours = [
        {'hour': '9-10 AM', 'count': random.randint(30, 60)},
        {'hour': '12-1 PM', 'count': random.randint(50, 80)},
        {'hour': '3-4 PM', 'count': random.randint(40, 70)},
    ]

    # No-show rates - a simple random value for demonstration
    no_show_rate = random.uniform(5, 15)

    return jsonify({
        'total_patients': total_patients,
        'total_doctors': total_doctors,
        'avg_consultation_time': avg_consultation_time,
        'peak_hours': peak_hours,
        'no_show_rate': round(no_show_rate, 2)
    }), 200

if __name__ == '__main__':
    # Create the database and tables if they don't exist
    with app.app_context():
        db.create_all()
    # The app will run on http://127.0.0.1:5000 by default.
    app.run(debug=True)
