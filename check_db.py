import os
import sys

# Add your project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User

def check_database():
    """Check what's in the database"""
    with app.app_context():
        print("🔍 Checking database contents...")
        
        users = User.query.all()
        print(f"\n📊 Found {len(users)} users:")
        
        for user in users:
            print(f"\n👤 User ID: {user.id}")
            print(f"   Email: {user.email}")
            print(f"   Name: {user.first_name} {user.last_name}")
            print(f"   Is Admin: {user.is_admin}")
            print(f"   Is Active: {user.is_active}")
            print(f"   Registration Paid: {user.registration_fee_paid}")
            print(f"   Virtual Balance: R{user.virtual_balance}")
            print(f"   Password Hash Exists: {bool(user.password_hash)}")
        
        # Test password for admin
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@nkuna.co.za')
        admin = User.query.filter_by(email=admin_email).first()
        
        if admin:
            print(f"\n🔑 Testing admin password...")
            test_password = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
            if admin.check_password(test_password):
                print("✅ Admin password is correct!")
            else:
                print("❌ Admin password is incorrect!")
                print(f"   Expected: {test_password}")
                print("   Hash doesn't match")

if __name__ == '__main__':
    check_database()