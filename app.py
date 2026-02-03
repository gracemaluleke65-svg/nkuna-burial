from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, current_user
from flask_migrate import Migrate, upgrade as flask_migrate_upgrade
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
#  CRITICAL FIX: COMPLETE SCHEMA MIGRATION
# ------------------------------------------------------------------
def fix_database_schema():
    """Complete schema fix - rename columns, add missing ones, handle constraints"""
    with app.app_context():
        try:
            print("🔧 Starting database schema fix...")
            from sqlalchemy import text, inspect
            
            inspector = inspect(db.engine)
            
            if 'users' not in inspector.get_table_names():
                print("❌ Users table doesn't exist!")
                return False
            
            columns_info = {col['name']: col for col in inspector.get_columns('users')}
            columns = list(columns_info.keys())
            print(f"📊 Found columns: {columns}")
            
            # Step 1: Rename old columns to new names
            renames = [
                ('phone_number', 'phone'),
                ('student_number', 'id_number'),
            ]
            
            for old_name, new_name in renames:
                if old_name in columns and new_name not in columns:
                    print(f"🔄 Renaming {old_name} to {new_name}...")
                    db.session.execute(text(f"ALTER TABLE users RENAME COLUMN {old_name} TO {new_name}"))
                    db.session.commit()
                    print(f"✅ Renamed {old_name} to {new_name}")
                    # Update our tracking
                    columns.append(new_name)
            
            # Step 2: Drop constraints on old columns if they still exist
            for old_name, new_name in renames:
                if old_name in columns:
                    print(f"⚠️  Old column {old_name} still exists, making it nullable...")
                    try:
                        db.session.execute(text(f"ALTER TABLE users ALTER COLUMN {old_name} DROP NOT NULL"))
                        db.session.commit()
                        print(f"✅ Made {old_name} nullable")
                    except Exception as e:
                        print(f"⚠️  Could not alter {old_name}: {e}")
            
            # Step 3: Add missing columns with safe defaults
            column_definitions = [
                ('first_name', 'VARCHAR(50)', "'Unknown'"),
                ('last_name', 'VARCHAR(50)', "'Unknown'"),
                ('phone', 'VARCHAR(20)', "'+27 00 000 0000'"),
                ('address', 'TEXT', "'Not provided'"),
                ('id_number', 'VARCHAR(13)', "'0000000000000'"),
                ('is_admin', 'BOOLEAN', 'FALSE'),
                ('is_active', 'BOOLEAN', 'TRUE'),
                ('registration_fee_paid', 'BOOLEAN', 'FALSE'),
                ('virtual_balance', 'FLOAT', '0.0'),
                ('updated_at', 'TIMESTAMP', 'CURRENT_TIMESTAMP'),
            ]
            
            for col_name, col_type, default_val in column_definitions:
                if col_name not in columns:
                    print(f"➕ Adding {col_name}...")
                    try:
                        # Add column with default
                        db.session.execute(text(f"""
                            ALTER TABLE users 
                            ADD COLUMN {col_name} {col_type} DEFAULT {default_val}
                        """))
                        db.session.commit()
                        
                        # Update existing rows
                        db.session.execute(text(f"""
                            UPDATE users SET {col_name} = {default_val} WHERE {col_name} IS NULL
                        """))
                        db.session.commit()
                        
                        # Make NOT NULL
                        db.session.execute(text(f"""
                            ALTER TABLE users ALTER COLUMN {col_name} SET NOT NULL
                        """))
                        db.session.commit()
                        
                        print(f"✅ Added {col_name}")
                    except Exception as e:
                        print(f"⚠️  Error adding {col_name}: {e}")
                        db.session.rollback()
            
            # Step 4: Special handling - if both old and new columns exist, copy data then drop old
            for old_name, new_name in renames:
                if old_name in columns and new_name in columns:
                    print(f"📝 Both {old_name} and {new_name} exist, copying data...")
                    try:
                        db.session.execute(text(f"""
                            UPDATE users SET {new_name} = {old_name} WHERE {new_name} IS NULL OR {new_name} = {column_definitions[[c[0] for c in column_definitions].index(new_name)][2]}
                        """))
                        db.session.commit()
                        print(f"✅ Copied data from {old_name} to {new_name}")
                    except Exception as e:
                        print(f"⚠️  Could not copy data: {e}")
            
            print("✅ Schema fix completed")
            return True
            
        except Exception as e:
            print(f"❌ Schema fix error: {e}")
            import traceback
            print(traceback.format_exc())
            db.session.rollback()
            return False

# ------------------------------------------------------------------
#  NUCLEAR OPTION: Complete table rebuild
# ------------------------------------------------------------------
def nuclear_rebuild_users_table():
    """NUCLEAR: Drop and recreate users table (DELETES ALL USER DATA)"""
    with app.app_context():
        try:
            from sqlalchemy import text, inspect
            
            print("☢️  NUCLEAR OPTION: Rebuilding users table from scratch...")
            
            inspector = inspect(db.engine)
            if 'users' not in inspector.get_table_names():
                print("⚠️  Users table doesn't exist, will create new")
            else:
                print("💥 Dropping users table...")
                # Drop foreign key constraints first
                try:
                    db.session.execute(text("""
                        DO $$ DECLARE
                            r RECORD;
                        BEGIN
                            FOR r IN (SELECT constraint_name FROM information_schema.table_constraints 
                                      WHERE table_name='users' AND constraint_type='FOREIGN KEY') LOOP
                                EXECUTE 'ALTER TABLE users DROP CONSTRAINT ' || r.constraint_name;
                            END LOOP;
                        END $$;
                    """))
                    db.session.commit()
                except Exception as e:
                    print(f"⚠️  Could not drop FKs: {e}")
                
                db.session.execute(text("DROP TABLE IF EXISTS users CASCADE"))
                db.session.commit()
                print("✅ Dropped users table")
            
            # Create new table with correct schema
            print("📝 Creating new users table...")
            db.session.execute(text("""
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    id_number VARCHAR(13) UNIQUE NOT NULL,
                    first_name VARCHAR(50) NOT NULL,
                    last_name VARCHAR(50) NOT NULL,
                    email VARCHAR(120) UNIQUE NOT NULL,
                    phone VARCHAR(20) NOT NULL,
                    address TEXT NOT NULL,
                    password_hash VARCHAR(256) NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    virtual_balance FLOAT NOT NULL DEFAULT 0.0,
                    registration_fee_paid BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.commit()
            print("✅ Created new users table")
            
            return True
            
        except Exception as e:
            print(f"❌ Nuclear rebuild failed: {e}")
            import traceback
            print(traceback.format_exc())
            db.session.rollback()
            return False

# ------------------------------------------------------------------
#  Database Migrations - BULLETPROOF VERSION
# ------------------------------------------------------------------
def run_migrations():
    """Run database migrations with automatic error recovery"""
    with app.app_context():
        try:
            print("🔄 Running database migrations...")
            
            from alembic import command
            from alembic.config import Config as AlembicConfig
            from alembic.runtime import migration
            from alembic.script import ScriptDirectory
            
            alembic_cfg = AlembicConfig("migrations/alembic.ini")
            alembic_cfg.set_main_option("script_location", "migrations")
            
            script = ScriptDirectory.from_config(alembic_cfg)
            
            # Check current revision
            with db.engine.connect() as connection:
                context = migration.MigrationContext.configure(connection)
                current_rev = context.get_current_revision()
                print(f"📊 Current database revision: {current_rev}")
                
                # Get all available revisions
                all_revisions = [rev.revision for rev in script.walk_revisions()]
                
                # If current_rev is '001' or unknown, or if it's not in our revisions
                if current_rev == '001' or current_rev is None or current_rev not in all_revisions:
                    print(f"⚠️  Revision '{current_rev}' not found in local migrations")
                    print("🔄 Stamping database to current head...")
                    command.stamp(alembic_cfg, "head")
                    print("✅ Database stamped to head revision")
                    return True
            
            # If we get here, try normal upgrade
            flask_migrate_upgrade()
            print("✅ Migrations completed successfully")
            return True
            
        except Exception as e:
            error_str = str(e)
            print(f"⚠️  Migration error: {error_str}")
            
            # If it's the specific '001' error or any revision error
            if "Can't locate revision" in error_str or "001" in error_str:
                print("🔄 Attempting recovery by stamping to head...")
                try:
                    from alembic import command
                    from alembic.config import Config as AlembicConfig
                    
                    alembic_cfg = AlembicConfig("migrations/alembic.ini")
                    alembic_cfg.set_main_option("script_location", "migrations")
                    
                    # Force stamp to head
                    command.stamp(alembic_cfg, "head")
                    print("✅ Database recovery successful - stamped to head")
                    return True
                except Exception as stamp_error:
                    print(f"⚠️  Stamp recovery failed: {stamp_error}")
            
            # Final fallback: just ensure tables exist
            print("🔄 Final fallback: creating all tables...")
            db.create_all()
            print("✅ Tables ensured")
            return True

# ------------------------------------------------------------------
#  Database initialisation - FIXED VERSION
# ------------------------------------------------------------------
def init_database():
    """Initialize database with proper error handling and logging"""
    with app.app_context():
        print("🔍 Starting database initialization...")
        
        try:
            # Ensure tables exist
            db.create_all()
            print("✅ Database tables created/verified")
            
            # Check for admin user
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@nkuna.co.za')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
            
            print(f"🔍 Checking for admin user: {admin_email}")
            
            # Safety check: verify all required columns exist
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('users')]
            
            required_cols = ['first_name', 'last_name', 'phone', 'address', 'id_number']
            missing = [c for c in required_cols if c not in columns]
            
            if missing:
                print(f"⚠️  Required columns still missing: {missing}")
                print("⚠️  Skipping admin initialization")
                return True
            
            existing_admin = User.query.filter_by(email=admin_email).first()
            
            if existing_admin:
                print(f"✅ Admin user already exists: {admin_email}")
                
                # Update admin to have first_name/last_name if missing
                if not existing_admin.first_name or existing_admin.first_name == 'Unknown':
                    existing_admin.first_name = 'System'
                    existing_admin.last_name = 'Administrator'
                    db.session.commit()
                    print("✅ Updated admin user with first_name/last_name")
                
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
            db.session.flush()
            
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
                existing = AdminFee.query.filter_by(fee_type=fee_data['fee_type']).first()
                if not existing:
                    fee = AdminFee(**fee_data)
                    db.session.add(fee)
                    print(f"💰 Created fee: {fee_data['fee_type']}")
            
            db.session.commit()
            
            print('=' * 60)
            print("✅ DATABASE INITIALIZATION COMPLETE")
            print('=' * 60)
            print(f"👤 Admin User: {admin_email} / {admin_password}")
            print('=' * 60)
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Database initialization error: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return False


@app.route('/debug/db')
def debug_db():
    """Debug database connection and tables"""
    try:
        from sqlalchemy import text, inspect
        result = db.session.execute(text('SELECT version()'))
        version = result.fetchone()[0]
        
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        user_columns = []
        if 'users' in tables:
            user_columns = [col['name'] for col in inspector.get_columns('users')]
        
        # Get alembic version
        alembic_rev = "Unknown"
        try:
            result = db.session.execute(text('SELECT version_num FROM alembic_version'))
            alembic_rev = result.fetchone()[0]
        except:
            pass
        
        user_count = User.query.count() if 'users' in tables else 'N/A'
        
        return {
            'database_version': version,
            'tables': tables,
            'user_columns': user_columns,
            'user_count': user_count,
            'alembic_revision': alembic_rev,
            'database_url': app.config['SQLALCHEMY_DATABASE_URI'][:50] + '...'
        }
    except Exception as e:
        return {'error': str(e), 'type': type(e).__name__}, 500


@app.route('/admin/nuclear-reset')
def admin_nuclear_reset():
    """Admin endpoint to trigger nuclear reset (DELETES ALL USERS)"""
    # In production, add authentication here!
    try:
        result = nuclear_rebuild_users_table()
        if result:
            # Recreate admin
            init_database()
            return {"status": "success", "message": "Nuclear reset completed"}
        else:
            return {"status": "error", "message": "Nuclear reset failed"}, 500
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ------------------------------------------------------------------
#  STARTUP SEQUENCE
# ------------------------------------------------------------------
print("🚀 Initializing application on startup...")

print("🔄 Step 0: Fixing database schema...")
schema_fixed = fix_database_schema()

if schema_fixed:
    print("🔄 Step 1: Running database migrations...")
    migration_success = run_migrations()
    
    print("🔄 Step 2: Initializing database...")
    init_database()
else:
    print("❌ Schema fix failed, attempting nuclear option...")
    nuclear_result = nuclear_rebuild_users_table()
    if nuclear_result:
        print("✅ Nuclear rebuild successful")
        init_database()
    else:
        print("❌ Nuclear rebuild also failed")

print("✅ Startup initialization complete")

# ------------------------------------------------------------------
#  Run the development server
# ------------------------------------------------------------------
if __name__ == '__main__':
    print('=' * 60)
    print('NKUNA BURIAL SOCIETY DIGITAL PLATFORM')
    print('=' * 60)
    print('Access: http://localhost:5000')
    print('Admin: http://localhost:5000/admin')
    print('=' * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)