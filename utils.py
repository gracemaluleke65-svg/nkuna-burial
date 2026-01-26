from datetime import datetime
import random
import string
import os
from models import db, SystemLog

def generate_transaction_id(prefix='TXN'):
    """Generate unique transaction ID"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_str = ''.join(random.choices(string.digits, k=4))
    return f"{prefix}{timestamp}{random_str}"


def generate_policy_number():
    """Generate unique policy number"""
    timestamp = datetime.now().strftime('%y%m%d')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"POL{timestamp}{random_str}"


def generate_claim_number():
    """Generate unique claim number"""
    timestamp = datetime.now().strftime('%y%m%d')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"CLM{timestamp}{random_str}"


def calculate_age_premium(age):
    """Calculate premium based on age band"""
    from config import Config
    
    if age <= 18:
        return Config.AGE_BANDS['0-18']
    elif age <= 30:
        return Config.AGE_BANDS['19-30']
    elif age <= 45:
        return Config.AGE_BANDS['31-45']
    elif age <= 60:
        return Config.AGE_BANDS['46-60']
    elif age <= 75:
        return Config.AGE_BANDS['61-75']
    else:
        return Config.AGE_BANDS['76+']


def log_activity(user_id, action, details=None, ip_address=None):
    """Log system activity"""
    log = SystemLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip_address
    )
    
    try:
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Don't fail if logging fails
        pass


def allowed_file(filename):
    """Check if file extension is allowed"""
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def format_currency(amount):
    """Format amount as South African Rand"""
    return f"R{amount:,.2f}"


def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def validate_sa_id(id_number):
    """Validate South African ID number"""
    # Check length
    if len(id_number) != 13 or not id_number.isdigit():
        return False
    
    return True


def save_uploaded_file(file, folder):
    """Save uploaded file securely"""
    if file and allowed_file(file.filename):
        # Create secure filename
        filename = datetime.now().strftime('%Y%m%d_%H%M%S_') + file.filename
        filepath = os.path.join(folder, filename)
        file.save(filepath)
        return filename
    return None