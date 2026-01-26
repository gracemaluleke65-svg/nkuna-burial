from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for both members and admins"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    id_number = db.Column(db.String(13), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=False)
    
    # Authentication
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Virtual banking
    virtual_balance = db.Column(db.Float, default=0.0)
    registration_fee_paid = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    policies = db.relationship('Policy', backref='owner', lazy=True, cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', backref='user', lazy=True, cascade='all, delete-orphan')
    claims = db.relationship('Claim', 
                            backref='claimant', 
                            lazy=True, 
                            cascade='all, delete-orphan',
                            foreign_keys='Claim.user_id')  # FIXED: Specify foreign key
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def can_deposit(self, amount):
        from config import Config
        return (amount <= Config.MAX_DEPOSIT_PER_TRANSACTION and 
                self.virtual_balance + amount <= Config.MAX_BALANCE)
    
    def __repr__(self):
        return f'<User {self.email}>'


class Policy(db.Model):
    """Burial policy model"""
    __tablename__ = 'policies'
    
    id = db.Column(db.Integer, primary_key=True)
    policy_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Policy details
    policy_name = db.Column(db.String(100), nullable=False)
    coverage_amount = db.Column(db.Float, nullable=False)
    monthly_premium = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='active')  # active, suspended, cancelled
    start_date = db.Column(db.Date, nullable=False)
    next_payment_date = db.Column(db.Date, nullable=False)
    
    # Members covered by this policy (max 15)
    covered_members = db.relationship('CoveredMember', backref='policy', lazy=True, cascade='all, delete-orphan')
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def is_overdue(self):
        return datetime.utcnow().date() > self.next_payment_date
    
    def calculate_total_premium(self):
        total = self.monthly_premium
        for member in self.covered_members:
            total += member.monthly_premium
        return total
    
    def get_total_members(self):
        return 1 + len(self.covered_members)  # 1 for owner + covered members
    
    def __repr__(self):
        return f'<Policy {self.policy_number}>'


class CoveredMember(db.Model):
    """Members covered under a policy"""
    __tablename__ = 'covered_members'
    
    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey('policies.id'), nullable=False)
    
    # Personal details
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    id_number = db.Column(db.String(13), nullable=False)
    relationship = db.Column(db.String(50), nullable=False)  # spouse, child, parent, etc.
    date_of_birth = db.Column(db.Date, nullable=False)
    
    # Premium
    monthly_premium = db.Column(db.Float, nullable=False)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    has_claim = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def calculate_age(self):
        today = datetime.utcnow().date()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
    
    def __repr__(self):
        return f'<CoveredMember {self.first_name} {self.last_name}>'


class Claim(db.Model):
    """Funeral claim model"""
    __tablename__ = 'claims'
    
    id = db.Column(db.Integer, primary_key=True)
    claim_number = db.Column(db.String(20), unique=True, nullable=False)
    policy_id = db.Column(db.Integer, db.ForeignKey('policies.id'), nullable=False)
    covered_member_id = db.Column(db.Integer, db.ForeignKey('covered_members.id'), nullable=True)  # FIXED: Made nullable
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # FIXED: Added missing relationships
    policy = db.relationship('Policy', backref='claims', lazy=True)
    covered_member = db.relationship('CoveredMember', backref='claims', lazy=True)
    
    # Claim details
    deceased_name = db.Column(db.String(100), nullable=False)
    date_of_death = db.Column(db.Date, nullable=False)
    date_of_burial = db.Column(db.Date, nullable=False)
    cause_of_death = db.Column(db.String(200))
    place_of_death = db.Column(db.String(200))
    
    # Documents
    death_certificate = db.Column(db.String(255))
    id_copy = db.Column(db.String(255))
    burial_order = db.Column(db.String(255))
    bank_details = db.Column(db.Text)  # JSON string for bank details
    
    # Claim processing
    claim_amount = db.Column(db.Float, nullable=False)
    processing_fee = db.Column(db.Float, default=0.0)
    net_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='paid')  # pending, under_review, approved, rejected, paid
    admin_notes = db.Column(db.Text)
    
    # Admin processing
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    processed_at = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def get_processed_by_user(self):
        from models import User
        return User.query.get(self.processed_by) if self.processed_by else None
    
    def __repr__(self):
        return f'<Claim {self.claim_number}>'


class Transaction(db.Model):
    """Financial transaction model"""
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(30), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Transaction details
    transaction_type = db.Column(db.String(20), nullable=False)  # deposit, withdrawal, premium_payment, claim_payout, fee
    amount = db.Column(db.Float, nullable=False)
    service_fee = db.Column(db.Float, default=0.0)
    net_amount = db.Column(db.Float, nullable=False)
    
    # Reference
    reference = db.Column(db.String(100))
    policy_id = db.Column(db.Integer, db.ForeignKey('policies.id'))
    claim_id = db.Column(db.Integer, db.ForeignKey('claims.id'))
    
    # Status
    status = db.Column(db.String(20), default='completed')  # pending, completed, failed
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Transaction {self.transaction_id}>'


class AdminFee(db.Model):
    """Admin fee configuration"""
    __tablename__ = 'admin_fees'
    
    id = db.Column(db.Integer, primary_key=True)
    fee_type = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    percentage = db.Column(db.Float, default=0.0)
    fixed_amount = db.Column(db.Float, default=0.0)
    minimum = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def calculate_fee(self, amount):
        fee = 0.0
        if self.percentage > 0:
            fee = amount * self.percentage / 100
        fee += self.fixed_amount
        
        if self.minimum > 0 and fee < self.minimum:
            fee = self.minimum
        
        return fee
    
    def __repr__(self):
        return f'<AdminFee {self.fee_type}>'


class SystemLog(db.Model):
    """System activity log"""
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<SystemLog {self.action}>'