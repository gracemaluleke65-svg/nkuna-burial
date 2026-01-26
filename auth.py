from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
import os
from datetime import datetime

from models import db, User, Transaction, SystemLog
from forms import LoginForm, RegistrationForm, ProfileUpdateForm
from utils import generate_transaction_id, log_activity, validate_sa_id

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact admin.', 'danger')
                return redirect(url_for('auth.login'))
            
            login_user(user, remember=form.remember.data)
            log_activity(user.id, 'login', f'User logged in from {request.remote_addr}')
            
            next_page = request.args.get('next')
            
            # FIXED: Redirect admin users to admin dashboard
            if user.is_admin:
                return redirect(next_page or url_for('admin.admin_dashboard'))
            else:
                return redirect(next_page or url_for('main.dashboard'))
        
        flash('Invalid email or password', 'danger')
    
    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # Validate ID number
        if not validate_sa_id(form.id_number.data):
            flash('Invalid ID number format', 'danger')
            return redirect(url_for('auth.register'))
        
        # Check if user already exists
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('auth.register'))
        
        if User.query.filter_by(id_number=form.id_number.data).first():
            flash('ID number already registered', 'danger')
            return redirect(url_for('auth.register'))
        
        # Create new user
        user = User(
            id_number=form.id_number.data,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data,
            phone=form.phone.data,
            address=form.address.data,
            is_admin=False,
            is_active=True,
            registration_fee_paid=False,
            virtual_balance=0.0
        )
        user.set_password(form.password.data)
        
        try:
            db.session.add(user)
            db.session.commit()
            
            log_activity(user.id, 'registration', 'New user registered')
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('auth.login'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Registration error: {str(e)}')
            flash('An error occurred during registration. Please try again.', 'danger')
    
    return render_template('auth/register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    log_activity(current_user.id, 'logout', 'User logged out')
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile management"""
    form = ProfileUpdateForm(obj=current_user)
    
    if form.validate_on_submit():
        # Update user details
        current_user.first_name = form.first_name.data
        current_user.last_name = form.last_name.data
        current_user.email = form.email.data
        current_user.phone = form.phone.data
        current_user.address = form.address.data
        
        # Update password if provided
        if form.current_password.data and form.new_password.data:
            if current_user.check_password(form.current_password.data):
                current_user.set_password(form.new_password.data)
                flash('Password updated successfully', 'success')
            else:
                flash('Current password is incorrect', 'danger')
                return redirect(url_for('auth.profile'))
        
        try:
            db.session.commit()
            log_activity(current_user.id, 'profile_update', 'Profile updated')
            flash('Profile updated successfully', 'success')
            return redirect(url_for('auth.profile'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Profile update error: {str(e)}')
            flash('An error occurred. Please try again.', 'danger')
    
    return render_template('auth/profile.html', form=form)


@auth_bp.route('/pay-registration-fee')
@login_required
def pay_registration_fee():
    """Pay registration fee for new users"""
    if current_user.registration_fee_paid:
        flash('Registration fee already paid', 'info')
        return redirect(url_for('main.dashboard'))
    
    from config import Config
    fee_amount = Config.REGISTRATION_FEE
    
    if current_user.virtual_balance < fee_amount:
        flash(f'Insufficient balance. Please deposit at least R{fee_amount:.2f}', 'warning')
        return redirect(url_for('main.deposit'))
    
    # Deduct fee
    current_user.virtual_balance -= fee_amount
    current_user.registration_fee_paid = True
    
    # Create transaction record
    transaction = Transaction(
        transaction_id=generate_transaction_id('FEE'),
        user_id=current_user.id,
        transaction_type='registration_fee',
        amount=fee_amount,
        service_fee=0,
        net_amount=-fee_amount,
        reference='Registration Fee',
        status='completed'
    )
    
    try:
        db.session.add(transaction)
        db.session.commit()
        
        log_activity(current_user.id, 'registration_fee_paid', f'Paid registration fee of R{fee_amount:.2f}')
        flash('Registration fee paid successfully. You can now create policies.', 'success')
        return redirect(url_for('main.dashboard'))
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Registration fee payment error: {str(e)}')
        flash('Payment failed. Please try again.', 'danger')
        return redirect(url_for('main.dashboard'))


# DEBUG ROUTES - REMOVE THESE IN PRODUCTION
@auth_bp.route('/debug-users')
def debug_users():
    """Debug route to check all users"""
    users = User.query.all()
    output = []
    for user in users:
        output.append(f"""
        <div style='border: 1px solid #ccc; margin: 10px; padding: 10px;'>
            <p><strong>ID:</strong> {user.id}</p>
            <p><strong>Email:</strong> {user.email}</p>
            <p><strong>Name:</strong> {user.first_name} {user.last_name}</p>
            <p><strong>Is Admin:</strong> {user.is_admin}</p>
            <p><strong>Is Active:</strong> {user.is_active}</p>
            <p><strong>Password Hash:</strong> {user.password_hash[:50]}...</p>
        </div>
        """)
    return f"<h1>All Users ({len(users)})</h1>" + "".join(output)


@auth_bp.route('/create-admin')
def create_admin():
    """Manually create admin user"""
    try:
        # Check if admin already exists
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@nkuna.co.za')
        existing_admin = User.query.filter_by(email=admin_email).first()
        
        if existing_admin:
            return f"Admin already exists: {admin_email}"
        
        # Create admin
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
        
        admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
        admin.set_password(admin_password)
        
        db.session.add(admin)
        db.session.commit()
        
        return f"""
        <h1>✅ Admin Created Successfully!</h1>
        <p><strong>Email:</strong> {admin_email}</p>
        <p><strong>Password:</strong> {admin_password}</p>
        <p><strong>Is Admin:</strong> {admin.is_admin}</p>
        <p><strong>Is Active:</strong> {admin.is_active}</p>
        <br>
        <a href="{url_for('auth.login')}">Go to Login</a>
        """
        
    except Exception as e:
        db.session.rollback()
        return f"❌ Error creating admin: {str(e)}"


@auth_bp.route('/reset-admin-password')
def reset_admin_password():
    """Reset admin password"""
    try:
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@nkuna.co.za')
        admin = User.query.filter_by(email=admin_email).first()
        
        if not admin:
            return "Admin not found"
        
        admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
        admin.set_password(admin_password)
        
        db.session.commit()
        
        return f"""
        <h1>✅ Admin Password Reset!</h1>
        <p><strong>Email:</strong> {admin_email}</p>
        <p><strong>New Password:</strong> {admin_password}</p>
        <br>
        <a href="{url_for('auth.login')}">Go to Login</a>
        """
        
    except Exception as e:
        db.session.rollback()
        return f"❌ Error resetting password: {str(e)}"