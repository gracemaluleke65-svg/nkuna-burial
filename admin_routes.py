from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
import json
from functools import wraps  # ADD THIS LINE

from models import db, User, Policy, CoveredMember, Claim, Transaction, AdminFee, SystemLog
from forms import AdminFeeForm, ClaimReviewForm
from utils import generate_transaction_id, log_activity

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


# Template helper functions
def init_admin_templates():
    """Initialize admin template helpers"""
    # Add max/min functions to Jinja
    current_app.jinja_env.globals.update(max=max)
    current_app.jinja_env.globals.update(min=min)
    
    # Fix date comparison helper
    def is_today(created_date):
        """Safe date comparison for templates"""
        if isinstance(created_date, datetime):
            return created_date.date() == date.today()
        elif isinstance(created_date, date):
            return created_date == date.today()
        return False
    
    current_app.jinja_env.globals.update(is_today=is_today)
    
    # Date formatting helper
    def format_date(dt):
        """Format date consistently"""
        if isinstance(dt, datetime):
            return dt.date()
        return dt
    
    current_app.jinja_env.globals.update(format_date=format_date)


@admin_bp.before_request
def before_admin_request():
    """Run before each admin request"""
    init_admin_templates()


@admin_bp.route('/')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    # Statistics
    total_users = User.query.filter_by(is_admin=False).count()
    total_policies = Policy.query.count()
    total_claims = Claim.query.count()
    pending_claims = Claim.query.filter_by(status='pending').count()
    
    # Financial statistics
    total_deposits_result = db.session.query(db.func.sum(Transaction.amount))\
        .filter(Transaction.transaction_type == 'deposit')\
        .first()
    total_deposits = total_deposits_result[0] or 0.0
    
    total_fees_result = db.session.query(db.func.sum(Transaction.service_fee))\
        .filter(Transaction.transaction_type.in_(['deposit', 'premium_payment']))\
        .first()
    total_fees = total_fees_result[0] or 0.0
    
    # Recent activities
    recent_activities = SystemLog.query\
        .order_by(SystemLog.created_at.desc())\
        .limit(10)\
        .all()
    
    # Claims needing attention
    urgent_claims = Claim.query.filter(Claim.status.in_(['pending', 'under_review']))\
        .order_by(Claim.created_at.desc())\
        .limit(5)\
        .all()
    
    # Add missing variables for template
    total_users_today = User.query.filter(
        db.func.date(User.created_at) == datetime.utcnow().date()
    ).count()
    
    total_deposits_today = db.session.query(
        db.func.sum(Transaction.amount)
    ).filter(
        db.func.date(Transaction.created_at) == datetime.utcnow().date(),
        Transaction.transaction_type == 'deposit'
    ).scalar() or 0
    
    # ACTIVE MEMBERS FIX: only members with no paid claim and are active
    active_members = CoveredMember.query.filter_by(is_active=True, has_claim=False).count()
    
    return render_template('admin/dashboard.html',
                         total_users=total_users,
                         total_policies=total_policies,
                         total_claims=total_claims,
                         pending_claims=pending_claims,
                         total_deposits=total_deposits,
                         total_fees=total_fees,
                         recent_activities=recent_activities,
                         urgent_claims=urgent_claims,
                         total_users_today=total_users_today,
                         total_deposits_today=total_deposits_today,
                         active_members=active_members)   # <-- NEW


@admin_bp.route('/users')
@admin_required
def manage_users():
    """Manage users"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    users = User.query.filter_by(is_admin=False)\
        .order_by(User.created_at.desc())\
        .paginate(page=page, per_page=per_page)
    
    today = date.today()
    
    return render_template('admin/users.html', users=users, today=today)


@admin_bp.route('/user/<int:user_id>/toggle-active')
@admin_required
def toggle_user_active(user_id):
    """Toggle user active status"""
    user = User.query.get_or_404(user_id)
    
    if user.is_admin:
        flash('Cannot deactivate admin users', 'danger')
        return redirect(url_for('admin.manage_users'))
    
    user.is_active = not user.is_active
    status = 'activated' if user.is_active else 'deactivated'
    
    try:
        db.session.commit()
        log_activity(current_user.id, 'user_toggle', f'{status} user {user.email}')
        flash(f'User {status} successfully', 'success')
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'User toggle error: {str(e)}')
        flash('Failed to update user status', 'danger')
    
    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/user/<int:user_id>/details')
@admin_required
def user_details(user_id):
    """View user details"""
    user = User.query.get_or_404(user_id)
    
    if user.is_admin:
        abort(403)
    
    # Get user policies
    policies = Policy.query.filter_by(user_id=user_id).all()
    
    # Get user transactions
    transactions = Transaction.query.filter_by(user_id=user_id)\
        .order_by(Transaction.created_at.desc())\
        .limit(10)\
        .all()
    
    # Get user claims
    claims = Claim.query.filter_by(user_id=user_id)\
        .order_by(Claim.created_at.desc())\
        .all()
    
    return render_template('admin/user_details.html',
                         user=user,
                         policies=policies,
                         transactions=transactions,
                         claims=claims)


@admin_bp.route('/claims')
@admin_required
def manage_claims():
    """Manage claims"""
    status = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = Claim.query
    
    if status != 'all':
        query = query.filter_by(status=status)
    
    claims = query.order_by(Claim.created_at.desc())\
        .paginate(page=page, per_page=per_page)
    
    return render_template('admin/claims.html', claims=claims, status=status)


@admin_bp.route('/claim/<int:claim_id>', methods=['GET', 'POST'])
@admin_required
def review_claim(claim_id):
    """Review claim - AUTOMATED VERSION (view only for admin)"""
    claim = Claim.query.get_or_404(claim_id)
    
    # Get related data
    policy = Policy.query.get(claim.policy_id)
    user = User.query.get(claim.user_id)
    
    # For automated system, admin can only view details and add notes
    form = ClaimReviewForm(obj=claim)
    
    if form.validate_on_submit():
        # Only allow updating admin notes, not status (since it's automated)
        claim.admin_notes = form.admin_notes.data
        
        try:
            db.session.commit()
            flash(f'Notes updated for claim {claim.claim_number}', 'success')
            return redirect(url_for('admin.manage_claims'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Claim notes update error: {str(e)}')
            flash('Failed to update notes. Please try again.', 'danger')
    
    # Parse bank details
    bank_details = {}
    if claim.bank_details:
        try:
            bank_details = json.loads(claim.bank_details)
        except:
            bank_details = {}
    
    return render_template('admin/claim_review.html',
                         claim=claim,
                         form=form,
                         policy=policy,
                         user=user,
                         bank_details=bank_details,
                         is_automated=True)  # Flag for template


@admin_bp.route('/fees', methods=['GET', 'POST'])
@admin_required
def manage_fees():
    """Manage fee structure"""
    form = AdminFeeForm()
    
    if form.validate_on_submit():
        # Check if fee type exists
        existing_fee = AdminFee.query.filter_by(fee_type=form.fee_type.data).first()
        
        if existing_fee:
            flash('Fee type already exists', 'danger')
            return redirect(url_for('admin.manage_fees'))
        
        # Create new fee
        fee = AdminFee(
            fee_type=form.fee_type.data,
            description=form.description.data,
            percentage=float(form.percentage.data) if form.percentage.data else 0.0,
            fixed_amount=float(form.fixed_amount.data) if form.fixed_amount.data else 0.0,
            minimum=float(form.minimum.data) if form.minimum.data else 0.0,
            is_active=form.is_active.data
        )
        
        try:
            db.session.add(fee)
            db.session.commit()
            
            log_activity(current_user.id, 'fee_created', f'Created fee type: {form.fee_type.data}')
            flash('Fee configuration added successfully', 'success')
            return redirect(url_for('admin.manage_fees'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Fee creation error: {str(e)}')
            flash('Failed to add fee configuration', 'danger')
    
    # Get all fees
    fees = AdminFee.query.order_by(AdminFee.fee_type).all()
    
    return render_template('admin/fees.html', form=form, fees=fees)


@admin_bp.route('/fee/<int:fee_id>/toggle')
@admin_required
def toggle_fee(fee_id):
    """Toggle fee active status"""
    fee = AdminFee.query.get_or_404(fee_id)
    fee.is_active = not fee.is_active
    
    try:
        db.session.commit()
        status = 'activated' if fee.is_active else 'deactivated'
        log_activity(current_user.id, 'fee_toggle', f'{status} fee: {fee.fee_type}')
        flash(f'Fee {status} successfully', 'success')
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Fee toggle error: {str(e)}')
        flash('Failed to update fee status', 'danger')
    
    return redirect(url_for('admin.manage_fees'))


@admin_bp.route('/reports')
@admin_required
def reports():
    """Generate reports"""
    # Get date range
    days = int(request.args.get('days', 30))
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Financial report
    transactions = Transaction.query\
        .filter(Transaction.created_at.between(start_date, end_date))\
        .order_by(Transaction.created_at.desc())\
        .all()
    
    # Calculate totals by type
    totals = {}
    for trans in transactions:
        if trans.transaction_type not in totals:
            totals[trans.transaction_type] = {
                'count': 0,
                'amount': 0.0,
                'fees': 0.0
            }
        totals[trans.transaction_type]['count'] += 1
        totals[trans.transaction_type]['amount'] += trans.amount
        totals[trans.transaction_type]['fees'] += trans.service_fee
    
    # User registration report
    new_users = User.query\
        .filter(User.created_at.between(start_date, end_date))\
        .filter_by(is_admin=False)\
        .count()
    
    # Claims report
    claims = Claim.query\
        .filter(Claim.created_at.between(start_date, end_date))\
        .all()
    
    claims_by_status = {}
    for claim in claims:
        if claim.status not in claims_by_status:
            claims_by_status[claim.status] = {
                'count': 0,
                'amount': 0.0
            }
        claims_by_status[claim.status]['count'] += 1
        claims_by_status[claim.status]['amount'] += claim.claim_amount
    
    return render_template('admin/reports.html',
                         days=days,
                         start_date=start_date,
                         end_date=end_date,
                         transactions=transactions,
                         totals=totals,
                         new_users=new_users,
                         claims_by_status=claims_by_status)


@admin_bp.route('/api/dashboard-stats')
@admin_required
def dashboard_stats_api():
    """API endpoint for dashboard statistics"""
    # Quick stats for dashboard widgets
    stats = {
        'total_users': User.query.filter_by(is_admin=False).count(),
        'active_policies': Policy.query.filter_by(status='active').count(),
        'pending_claims': Claim.query.filter_by(status='pending').count(),
        'total_deposits_today': db.session.query(db.func.sum(Transaction.amount))
            .filter(Transaction.transaction_type == 'deposit')
            .filter(db.func.date(Transaction.created_at) == datetime.utcnow().date())
            .scalar() or 0,
        'active_members': CoveredMember.query.filter_by(is_active=True, has_claim=False).count()  # <-- NEW
    }
    
    return jsonify(stats)


@admin_bp.route('/activity-log')
@admin_required
def activity_log():
    """View system activity log"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    logs = SystemLog.query\
        .order_by(SystemLog.created_at.desc())\
        .paginate(page=page, per_page=per_page)
    
    return render_template('admin/activity_log.html', logs=logs)