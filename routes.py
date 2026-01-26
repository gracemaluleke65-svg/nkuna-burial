from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os
import json

from models import db, User, Policy, CoveredMember, Claim, Transaction, AdminFee
from forms import DepositForm, PolicyForm, MemberForm, ClaimForm, PremiumPaymentForm
from utils import generate_transaction_id, generate_policy_number, generate_claim_number, calculate_age_premium, log_activity, save_uploaded_file
from config import Config

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Home page"""
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.admin_dashboard'))
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """User dashboard"""
    if current_user.is_admin:
        return redirect(url_for('admin.admin_dashboard'))
    
    # Check if registration fee needs to be paid
    if not current_user.registration_fee_paid:
        flash('Please pay the registration fee to access all features', 'warning')
        return redirect(url_for('auth.pay_registration_fee'))
    
    # Get user statistics
    policies = Policy.query.filter_by(user_id=current_user.id).all()
    total_policies = len(policies)
    
    total_premium = 0
    overdue_count = 0
    for policy in policies:
        total_premium += policy.calculate_total_premium()
        if policy.is_overdue():
            overdue_count += 1
    
    # Calculate upcoming payments (due in next 7 days or overdue)
    today = date.today()
    upcoming_payments = []
    for policy in policies:
        days_until = (policy.next_payment_date - today).days
        if days_until <= 7 or policy.is_overdue():
            upcoming_payments.append((policy, days_until))
    
    # Recent transactions
    recent_transactions = Transaction.query.filter_by(user_id=current_user.id)\
        .order_by(Transaction.created_at.desc())\
        .limit(5)\
        .all()
    
    # Recent claims
    recent_claims = Claim.query.filter_by(user_id=current_user.id)\
        .order_by(Claim.created_at.desc())\
        .limit(5)\
        .all()
    
    return render_template('user/dashboard.html',
                         user=current_user,
                         policies=policies,
                         total_policies=total_policies,
                         total_premium=total_premium,
                         overdue_count=overdue_count,
                         recent_transactions=recent_transactions,
                         recent_claims=recent_claims,
                         upcoming_payments=upcoming_payments,
                         today=today)
        

@main_bp.route('/deposit', methods=['GET', 'POST'])
@login_required
def deposit():
    """Deposit to virtual balance"""
    form = DepositForm()
    
    if form.validate_on_submit():
        amount = float(form.amount.data)
        
        # Check deposit limits
        if not current_user.can_deposit(amount):
            flash(f'Deposit limit exceeded. Max per transaction: R{Config.MAX_DEPOSIT_PER_TRANSACTION:.2f}, Max balance: R{Config.MAX_BALANCE:.2f}', 'danger')
            return redirect(url_for('main.deposit'))
        
        # Calculate service fee
        service_fee = (amount * Config.SERVICE_FEE_PERCENT / 100)
        if service_fee < Config.SERVICE_FEE_MIN:
            service_fee = Config.SERVICE_FEE_MIN
        
        net_amount = amount - service_fee
        
        # Update user balance
        current_user.virtual_balance += net_amount
        
        # Create transaction record
        transaction = Transaction(
            transaction_id=generate_transaction_id('DEP'),
            user_id=current_user.id,
            transaction_type='deposit',
            amount=amount,
            service_fee=service_fee,
            net_amount=net_amount,
            reference=form.reference.data or 'Deposit',
            status='completed'
        )
        
        try:
            db.session.add(transaction)
            db.session.commit()
            
            log_activity(current_user.id, 'deposit', f'Deposited R{amount:.2f} with fee R{service_fee:.2f}')
            flash(f'Successfully deposited R{amount:.2f}. Service fee: R{service_fee:.2f}. Net: R{net_amount:.2f}', 'success')
            return redirect(url_for('main.dashboard'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Deposit error: {str(e)}')
            flash('Deposit failed. Please try again.', 'danger')
    
    return render_template('user/deposit.html', form=form)


@main_bp.route('/policy/create', methods=['GET', 'POST'])
@login_required
def create_policy():
    """Create new policy"""
    if not current_user.registration_fee_paid:
        flash('Please pay the registration fee first', 'warning')
        return redirect(url_for('auth.pay_registration_fee'))
    
    form = PolicyForm()
    
    if form.validate_on_submit():
        # Generate policy number
        policy_number = generate_policy_number()
        
        # Calculate monthly premium (simplified calculation - 0.1% of coverage)
        base_premium = float(form.coverage_amount.data) * 0.001
        
        # Create policy
        policy = Policy(
            policy_number=policy_number,
            user_id=current_user.id,
            policy_name=form.policy_name.data,
            coverage_amount=float(form.coverage_amount.data),
            monthly_premium=base_premium,
            start_date=form.start_date.data,
            next_payment_date=form.start_date.data + timedelta(days=30),
            status='active'
        )
        
        try:
            db.session.add(policy)
            db.session.commit()
            
            log_activity(current_user.id, 'policy_created', f'Created policy {policy_number}')
            flash(f'Policy {policy_number} created successfully!', 'success')
            return redirect(url_for('main.view_policy', policy_id=policy.id))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Policy creation error: {str(e)}')
            flash('Failed to create policy. Please try again.', 'danger')
    
    return render_template('user/policy_create.html', form=form)


@main_bp.route('/policy/<int:policy_id>')
@login_required
def view_policy(policy_id):
    """View policy details"""
    policy = Policy.query.get_or_404(policy_id)
    
    # Check ownership
    if policy.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    # Calculate total premium
    total_premium = policy.calculate_total_premium()
    
    # Calculate days remaining
    today = date.today()
    days_remaining = (policy.next_payment_date - today).days
    is_overdue = policy.is_overdue()
    
    # Calculate review date (1 year from start)
    review_date = policy.start_date.replace(year=policy.start_date.year + 1)
    
    # Filter active and inactive members
    active_members = [member for member in policy.covered_members if member.is_active and not member.has_claim]
    inactive_members = [member for member in policy.covered_members if not member.is_active or member.has_claim]
    
    # Get recent claims for this policy
    recent_claims = Claim.query.filter_by(policy_id=policy_id)\
        .order_by(Claim.created_at.desc())\
        .limit(5)\
        .all()
    
    # Calculate member statistics
    total_members_count = len(active_members) + 1  # +1 for policy owner
    max_members = 15
    member_utilization = (total_members_count / max_members) * 100
    
    # Check if policy owner has any claims
    owner_has_claim = any(claim.covered_member_id is None and claim.policy_id == policy_id 
                         for claim in recent_claims if claim.status in ['approved', 'paid'])
    
    return render_template('user/policy_view.html', 
                         policy=policy,
                         total_premium=total_premium,
                         today=today,
                         days_remaining=days_remaining,
                         is_overdue=is_overdue,
                         review_date=review_date,
                         active_members=active_members,
                         inactive_members=inactive_members,
                         recent_claims=recent_claims,
                         total_members_count=total_members_count,
                         member_utilization=member_utilization,
                         owner_has_claim=owner_has_claim)   
   
    
@main_bp.route('/policy/<int:policy_id>/add-member', methods=['GET', 'POST'])
@login_required
def add_member(policy_id):
    """Add member to policy"""
    policy = Policy.query.get_or_404(policy_id)
    
    # Check ownership
    if policy.user_id != current_user.id:
        abort(403)
    
    # Check member limit (max 15 including policy owner)
    if len(policy.covered_members) >= 14:
        flash('Maximum members (15) reached for this policy', 'danger')
        return redirect(url_for('main.view_policy', policy_id=policy_id))
    
    form = MemberForm()
    
    if form.validate_on_submit():
        # Calculate age
        today = date.today()
        age = today.year - form.date_of_birth.data.year - (
            (today.month, today.day) < (form.date_of_birth.data.month, form.date_of_birth.data.day))
        
        # Calculate premium based on age
        monthly_premium = calculate_age_premium(age)
        
        # Create covered member
        member = CoveredMember(
            policy_id=policy_id,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            id_number=form.id_number.data,
            relationship=form.relationship.data,
            date_of_birth=form.date_of_birth.data,
            monthly_premium=monthly_premium
        )
        
        try:
            db.session.add(member)
            db.session.commit()
            
            log_activity(current_user.id, 'member_added', f'Added {member.first_name} {member.last_name} to policy {policy.policy_number}')
            flash(f'Member added successfully. Monthly premium: R{monthly_premium:.2f}', 'success')
            return redirect(url_for('main.view_policy', policy_id=policy_id))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Add member error: {str(e)}')
            flash('Failed to add member. Please try again.', 'danger')
    
    return render_template('user/member_add.html', form=form, policy=policy)


@main_bp.route('/policy/<int:policy_id>/pay-premium', methods=['GET', 'POST'])
@login_required
def pay_premium(policy_id):
    """Pay policy premium"""
    policy = Policy.query.get_or_404(policy_id)
    
    # Check ownership
    if policy.user_id != current_user.id:
        abort(403)
    
    form = PremiumPaymentForm()
    form.policy_id.choices = [(policy.id, f"{policy.policy_name} - R{policy.calculate_total_premium():.2f}")]
    
    # Calculate next payment date after this payment (for display in GET request)
    next_payment_after = policy.next_payment_date + timedelta(days=30)
    
    if form.validate_on_submit():
        amount = float(form.amount.data)
        total_premium = policy.calculate_total_premium()
        
        if amount < total_premium:
            flash(f'Minimum payment required: R{total_premium:.2f}', 'warning')
            return redirect(url_for('main.pay_premium', policy_id=policy_id))
        
        # Check balance
        if current_user.virtual_balance < amount:
            flash('Insufficient balance. Please deposit funds.', 'danger')
            return redirect(url_for('main.deposit'))
        
        # Calculate service fee
        service_fee = (amount * Config.SERVICE_FEE_PERCENT / 100)
        if service_fee < Config.SERVICE_FEE_MIN:
            service_fee = Config.SERVICE_FEE_MIN
        
        # Update user balance
        current_user.virtual_balance -= amount
        
        # Update policy next payment date
        policy.next_payment_date = policy.next_payment_date + timedelta(days=30)
        
        # Create transaction record
        transaction = Transaction(
            transaction_id=generate_transaction_id('PREM'),
            user_id=current_user.id,
            transaction_type='premium_payment',
            amount=amount,
            service_fee=service_fee,
            net_amount=-amount,
            reference=f'Premium payment for {policy.policy_number}',
            policy_id=policy.id,
            status='completed'
        )
        
        try:
            db.session.add(transaction)
            db.session.commit()
            
            log_activity(current_user.id, 'premium_paid', f'Paid premium R{amount:.2f} for policy {policy.policy_number}')
            flash(f'Premium payment successful! Next payment due: {policy.next_payment_date.strftime("%Y-%m-%d")}', 'success')
            return redirect(url_for('main.dashboard'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Premium payment error: {str(e)}')
            flash('Payment failed. Please try again.', 'danger')
    
    # Calculate total premium for display
    total_premium = policy.calculate_total_premium()
    
    return render_template('user/premium_payment.html', 
                           form=form, 
                           policy=policy, 
                           total_premium=total_premium,
                           next_payment_after=next_payment_after)


@main_bp.route('/claims')
@login_required
def claims():
    """View claims"""
    user_claims = Claim.query.filter_by(user_id=current_user.id)\
        .order_by(Claim.created_at.desc())\
        .all()
    
    return render_template('user/claims.html', claims=user_claims)




@main_bp.route('/claims/submit', methods=['GET', 'POST'])
@login_required
def submit_claim():
    """Submit a claim - AUTOMATED PAYMENT VERSION"""
    if not current_user.registration_fee_paid:
        flash('Please pay the registration fee first', 'warning')
        return redirect(url_for('auth.pay_registration_fee'))
    
    # Get user's active policies with members
    policies = Policy.query.filter_by(user_id=current_user.id, status='active').all()
    
    # Prepare choices for policy and member selection
    policy_choices = []
    for policy in policies:
        # Add policy owner as a member
        policy_choices.append({
            'policy_id': policy.id,
            'policy_name': policy.policy_name,
            'policy_number': policy.policy_number,
            'member_id': 0,
            'member_name': f"{current_user.first_name} {current_user.last_name}",
            'member_age': calculate_age(current_user.created_at.date()) if hasattr(current_user, 'created_at') else 0,
            'relationship': 'Policy Holder (Self)',
            'member_status': 'active',
            'has_claim': False
        })
        
        # Add covered members
        for member in policy.covered_members:
            if not member.has_claim:
                policy_choices.append({
                    'policy_id': policy.id,
                    'policy_name': policy.policy_name,
                    'policy_number': policy.policy_number,
                    'member_id': member.id,
                    'member_name': f"{member.first_name} {member.last_name}",
                    'member_age': member.calculate_age(),
                    'relationship': member.relationship.title(),
                    'member_status': 'active' if member.is_active else 'inactive',
                    'has_claim': False
                })
    
    form = ClaimForm()
    
    if form.validate_on_submit():
        # Get selected policy and member from hidden fields
        policy_id = request.form.get('policy_id')
        member_id = request.form.get('member_id')
        relationship = request.form.get('relationship')
        
        if not policy_id or not member_id:
            flash('Please select a policy and member', 'danger')
            return redirect(url_for('main.submit_claim'))
        
        try:
            policy_id = int(policy_id)
            member_id = int(member_id)
        except ValueError:
            flash('Invalid policy/member selection', 'danger')
            return redirect(url_for('main.submit_claim'))
        
        policy = Policy.query.get(policy_id)
        if not policy or policy.user_id != current_user.id:
            flash('Invalid policy selected', 'danger')
            return redirect(url_for('main.submit_claim'))
        
        # Generate claim number
        claim_number = generate_claim_number()
        
        # Calculate claim amount
        claim_amount = policy.coverage_amount
        
        # Calculate processing fee
        processing_fee = claim_amount * Config.CLAIM_FEE_PERCENT / 100
        if processing_fee < Config.CLAIM_FEE_MIN:
            processing_fee = Config.CLAIM_FEE_MIN
        
        net_amount = claim_amount - processing_fee
        
        # Save uploaded files
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        
        death_cert = save_uploaded_file(form.death_certificate.data, upload_folder)
        id_copy = save_uploaded_file(form.id_copy.data, upload_folder)
        burial_order = save_uploaded_file(form.burial_order.data, upload_folder)
        
        # Bank details JSON
        bank_details = {
            'bank_name': form.bank_name.data,
            'account_holder': form.account_holder.data,
            'account_number': form.account_number.data,
            'branch_code': form.branch_code.data
        }
        
        # Determine deceased name and relationship
        if member_id == 0:
            # Policy owner
            deceased_name = f"{current_user.first_name} {current_user.last_name}"
            covered_member_id = None
        else:
            # Covered member
            member = CoveredMember.query.get(member_id)
            if not member or member.policy_id != policy_id:
                flash('Invalid member selected', 'danger')
                return redirect(url_for('main.submit_claim'))
            
            deceased_name = f"{member.first_name} {member.last_name}"
            covered_member_id = member.id
            member.has_claim = True
        
        # Create claim with AUTOMATED PAID STATUS
        claim = Claim(
            claim_number=claim_number,
            policy_id=policy.id,
            covered_member_id=covered_member_id,
            user_id=current_user.id,
            deceased_name=deceased_name,
            date_of_death=form.date_of_death.data,
            date_of_burial=form.date_of_burial.data,
            cause_of_death=form.cause_of_death.data,
            place_of_death=form.place_of_death.data,
            death_certificate=death_cert,
            id_copy=id_copy,
            burial_order=burial_order,
            bank_details=json.dumps(bank_details),
            claim_amount=claim_amount,
            processing_fee=processing_fee,
            net_amount=net_amount,
            status='paid',  # AUTOMATED: Set to paid immediately
            processed_by=1,  # System/admin ID for automated processing
            processed_at=datetime.utcnow()  # Set processing time immediately
        )
        
        try:
            db.session.add(claim)
            
            # AUTOMATED PAYOUT: Add money to user's virtual balance immediately
            current_user.virtual_balance += net_amount
            
            # Create payout transaction record
            transaction = Transaction(
                transaction_id=generate_transaction_id('PAY'),
                user_id=current_user.id,
                transaction_type='claim_payout',
                amount=claim_amount,
                service_fee=processing_fee,
                net_amount=net_amount,
                reference=f'Automated claim payout {claim_number}',
                claim_id=claim.id,
                status='completed'
            )
            db.session.add(transaction)
            
            # Deactivate the member who claimed
            if covered_member_id:
                member = CoveredMember.query.get(covered_member_id)
                if member:
                    member.is_active = False
                    log_activity(current_user.id, 'member_deactivated', 
                               f'Automated deactivation of {member.first_name} {member.last_name} due to claim payout')
            
            db.session.commit()
            
            # Log the automated activity
            log_activity(current_user.id, 'claim_submitted_and_paid', 
                       f'Claim {claim_number} submitted and automatically paid out: R{net_amount:.2f} added to balance')
            
            # SUCCESS MESSAGE: Notify user that money has been added to their account
            flash(f'✅ Claim submitted successfully! Claim number: {claim_number}', 'success')
            flash(f'💰 R{net_amount:.2f} has been automatically added to your virtual balance!', 'success')
            flash(f'Your new balance is: R{current_user.virtual_balance:.2f}', 'info')
            
            return redirect(url_for('main.claims'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Automated claim processing error: {str(e)}')
            flash('Failed to process claim. Please try again.', 'danger')
    
    return render_template('user/claim_submit.html', 
                         form=form, 
                         policy_choices=policy_choices,
                         today=date.today().isoformat(),
                         timedelta=timedelta)



@main_bp.route('/transactions')
@login_required
def transactions():
    """View transaction history"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    transactions_query = Transaction.query.filter_by(user_id=current_user.id)\
        .order_by(Transaction.created_at.desc())\
        .paginate(page=page, per_page=per_page)
    
    return render_template('user/transactions.html', transactions=transactions_query)


@main_bp.route('/api/calculate-premium/<int:age>')
@login_required
def calculate_premium_api(age):
    """API endpoint to calculate premium for a given age"""
    premium = calculate_age_premium(age)
    return jsonify({'age': age, 'premium': premium})


def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))