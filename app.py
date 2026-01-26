from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from datetime import datetime, timedelta
import os
import json
from dotenv import load_dotenv
from functools import wraps

# Load environment variables
load_dotenv()

# Import models and config
from models import db
from config import Config

# Determine environment
env = os.environ.get('FLASK_ENV', 'development')
config_class = {
    'production': 'config.ProductionConfig',
    'development': 'config.DevelopmentConfig',
    'testing': 'config.TestingConfig'
}.get(env, 'config.DevelopmentConfig')

# ------------------------------------------------------------------
#  Flask application factory
# ------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(config_class)

# ------------------------------------------------------------------
#  FIX: register the missing Jinja2 filter
# ------------------------------------------------------------------
app.jinja_env.filters['fromjson'] = json.loads

# ------------------------------------------------------------------
#  Initialise extensions
# ------------------------------------------------------------------
db.init_app(app)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Flask-Migrate - IMPORTANT for PostgreSQL
migrate = Migrate(app, db)

# ------------------------------------------------------------------
#  Register blueprints
# ------------------------------------------------------------------
from auth import auth_bp
from routes import main_bp
from admin_routes import admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)

# ------------------------------------------------------------------
#  Flask-Login user loader
# ------------------------------------------------------------------
from models import User, Policy, CoveredMember, Claim, Transaction, AdminFee, SystemLog

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ------------------------------------------------------------------
#  Error handlers
# ------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

@app.errorhandler(500)
def internal_server_error(e):
    db.session.rollback()
    return render_template('errors/500.html'), 500

# ------------------------------------------------------------------
#  Context processor
# ------------------------------------------------------------------
@app.context_processor
def inject_app_info():
    from config import Config
    from datetime import datetime
    return dict(
        app_name=Config.APP_NAME,
        app_slogan=Config.APP_SLOGAN,
        current_year=datetime.now().year,
        timedelta=timedelta
    )

# ------------------------------------------------------------------
#  Pre-request hook
# ------------------------------------------------------------------
@app.before_request
def before_request():
    if current_user.is_authenticated and not current_user.is_active:
        from flask_login import logout_user
        logout_user()
        flash('Your account has been deactivated', 'danger')
        return redirect(url_for('auth.login'))

# ------------------------------------------------------------------
#  Shell context
# ------------------------------------------------------------------
@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Policy': Policy,
        'CoveredMember': CoveredMember,
        'Claim': Claim,
        'Transaction': Transaction,
        'AdminFee': AdminFee,
        'SystemLog': SystemLog
    }

# ------------------------------------------------------------------
#  Database initialisation - FIXED VERSION
# ------------------------------------------------------------------
def init_database():
    """Initialize database with proper error handling and logging"""
    with app.app_context():
        print("🔍 Starting database initialization...")
        
        try:
            # Create all tables (safe to run multiple times)
            db.create_all()
            print("✅ Database tables created/verified")
            
            # Check for admin user
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@nkuna.co.za')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
            
            print(f"🔍 Checking for admin user: {admin_email}")
            
            existing_admin = User.query.filter_by(email=admin_email).first()
            
            if existing_admin:
                print(f"✅ Admin user already exists: {admin_email}")
                print(f"   Admin ID: {existing_admin.id}")
                print(f"   Is Active: {existing_admin.is_active}")
                print(f"   Is Admin: {existing_admin.is_admin}")
                
                # Verify password hash is valid
                if existing_admin.check_password(admin_password):
                    print("✅ Admin password hash is valid")
                else:
                    print("⚠️  Admin password hash mismatch - resetting password")
                    existing_admin.set_password(admin_password)
                    db.session.commit()
                    print("✅ Admin password reset successfully")
                
                return True
            
            print("📝 Creating default admin user...")
            admin = User(
                id_number='0000000000000',
                first_name='System',
                last_name='Administrator',
                email=admin_email,
                phone='+27 11 123 4567',
                address='Administration Office',
                is_admin=True,
                is_active=True,
                virtual_balance=0.0,
                registration_fee_paid=True
            )
            admin.set_password(admin_password)
            
            db.session.add(admin)
            db.session.flush()  # Get the ID without committing
            
            print(f"👤 Admin user created with ID: {admin.id}")
            
            # Create default fees
            fees = [
                {
                    'fee_type': 'service_fee',
                    'description': 'Monthly service fee on deposits',
                    'percentage': Config.SERVICE_FEE_PERCENT,
                    'minimum': Config.SERVICE_FEE_MIN,
                    'is_active': True
                },
                {
                    'fee_type': 'claim_processing_fee',
                    'description': 'Claim processing fee',
                    'percentage': Config.CLAIM_FEE_PERCENT,
                    'minimum': Config.CLAIM_FEE_MIN,
                    'is_active': True
                },
                {
                    'fee_type': 'late_payment_fee',
                    'description': 'Late payment penalty',
                    'fixed_amount': Config.LATE_FEE,
                    'is_active': True
                },
                {
                    'fee_type': 'registration_fee',
                    'description': 'One-time registration fee',
                    'fixed_amount': Config.REGISTRATION_FEE,
                    'is_active': True
                }
            ]
            
            for fee_data in fees:
                # Check if fee already exists
                existing = AdminFee.query.filter_by(fee_type=fee_data['fee_type']).first()
                if not existing:
                    fee = AdminFee(**fee_data)
                    db.session.add(fee)
                    print(f"💰 Created fee: {fee_data['fee_type']}")
                else:
                    print(f"⏭️  Fee already exists: {fee_data['fee_type']}")
            
            db.session.commit()
            
            print('=' * 60)
            print("✅ DATABASE INITIALIZATION COMPLETE")
            print('=' * 60)
            print(f"👤 Admin User Created:")
            print(f"   Email: {admin_email}")
            print(f"   Password: {admin_password}")
            print(f"   ID: {admin.id}")
            print('=' * 60)
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ CRITICAL ERROR during database initialization: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return False


@app.route('/debug/db')
def debug_db():
    """Debug database connection and tables"""
    try:
        # Test connection
        from sqlalchemy import text
        result = db.session.execute(text('SELECT version()'))
        version = result.fetchone()[0]
        
        # Check if tables exist
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        # Check users table
        user_count = User.query.count() if 'users' in tables else 'N/A'
        
        return {
            'database_version': version,
            'tables': tables,
            'user_count': user_count,
            'database_url': app.config['SQLALCHEMY_DATABASE_URI'][:50] + '...'  # masked
        }
    except Exception as e:
        return {'error': str(e), 'type': type(e).__name__}, 500


# ------------------------------------------------------------------
#  CRITICAL FIX: Initialize database on startup (not just in __main__)
# ------------------------------------------------------------------
print("🚀 Initializing database on application startup...")
init_database()
print("✅ Startup initialization complete")

# ------------------------------------------------------------------
#  Run the development server
# ------------------------------------------------------------------
if __name__ == '__main__':
    print('=' * 60)
    print('NKUNA BURIAL SOCIETY DIGITAL PLATFORM')
    print('=' * 60)

    print('\nStarting application...')
    print('Access the application at: http://localhost:5000')
    print('Admin dashboard: http://localhost:5000/admin')
    print('\nPress CTRL+C to stop the server')
    print('=' * 60)

    app.run(debug=True, host='0.0.0.0', port=5000)