from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, TextAreaField, DecimalField, DateField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, NumberRange, Optional
from datetime import datetime, date
import re

class LoginForm(FlaskForm):
    """Login form"""
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')


class RegistrationForm(FlaskForm):
    """User registration form"""
    id_number = StringField('ID Number', validators=[
        DataRequired(),
        Length(min=13, max=13, message='ID number must be 13 digits')
    ])
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=50)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=50)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(max=20)])
    address = TextAreaField('Residential Address', validators=[DataRequired()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    agree_terms = BooleanField('I agree to the terms and conditions', validators=[DataRequired()])
    
    def validate_id_number(self, field):
        """Validate South African ID number"""
        id_num = field.data
        
        # Check if all characters are digits
        if not id_num.isdigit():
            raise ValidationError('ID number must contain only digits')
        
        # Check length (should be 13 for SA)
        if len(id_num) != 13:
            raise ValidationError('ID number must be 13 digits')


class DepositForm(FlaskForm):
    """Deposit form for virtual balance"""
    amount = DecimalField('Amount (R)', validators=[
        DataRequired(),
        NumberRange(min=10, max=50000, message='Amount must be between R10 and R50,000')
    ])
    reference = StringField('Payment Reference', validators=[Optional(), Length(max=100)])


class PolicyForm(FlaskForm):
    """Policy creation form"""
    policy_name = StringField('Policy Name', validators=[DataRequired(), Length(max=100)])
    coverage_amount = DecimalField('Coverage Amount (R)', validators=[
        DataRequired(),
        NumberRange(min=1000, max=1000000, message='Coverage must be between R1,000 and R1,000,000')
    ])
    start_date = DateField('Start Date', default=date.today, validators=[DataRequired()])


class MemberForm(FlaskForm):
    """Add member to policy form"""
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=50)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=50)])
    id_number = StringField('ID Number', validators=[
        DataRequired(),
        Length(min=13, max=13, message='ID number must be 13 digits')
    ])
    relationship = SelectField('Relationship', choices=[
        ('self', 'Self'),
        ('spouse', 'Spouse'),
        ('child', 'Child'),
        ('parent', 'Parent'),
        ('sibling', 'Sibling'),
        ('grandparent', 'Grandparent'),
        ('grandchild', 'Grandchild'),
        ('other', 'Other Relative')
    ], validators=[DataRequired()])
    date_of_birth = DateField('Date of Birth', validators=[DataRequired()])


class ClaimForm(FlaskForm):
    """Claim submission form"""
    deceased_name = StringField('Deceased Full Name', validators=[DataRequired(), Length(max=100)])
    date_of_death = DateField('Date of Death', validators=[DataRequired()])
    date_of_burial = DateField('Date of Burial', validators=[DataRequired()])
    cause_of_death = StringField('Cause of Death', validators=[Optional(), Length(max=200)])
    place_of_death = StringField('Place of Death', validators=[Optional(), Length(max=200)])
    
    # Document uploads
    death_certificate = FileField('Death Certificate', validators=[
        FileAllowed(['pdf', 'jpg', 'jpeg', 'png'], 'PDF and images only!')
    ])
    id_copy = FileField('ID Copy of Deceased', validators=[
        FileAllowed(['pdf', 'jpg', 'jpeg', 'png'], 'PDF and images only!')
    ])
    burial_order = FileField('Burial Order/Permit', validators=[
        FileAllowed(['pdf', 'jpg', 'jpeg', 'png'], 'PDF and images only!')
    ])
    
    # Bank details
    bank_name = StringField('Bank Name', validators=[DataRequired()])
    account_holder = StringField('Account Holder Name', validators=[DataRequired()])
    account_number = StringField('Account Number', validators=[DataRequired()])
    branch_code = StringField('Branch Code', validators=[DataRequired()])


class ProfileUpdateForm(FlaskForm):
    """Profile update form"""
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=50)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=50)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(max=20)])
    address = TextAreaField('Residential Address', validators=[DataRequired()])
    current_password = PasswordField('Current Password (leave blank to keep unchanged)', validators=[Optional()])
    new_password = PasswordField('New Password', validators=[Optional(), Length(min=8)])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('new_password', message='Passwords must match')])


class AdminFeeForm(FlaskForm):
    """Admin fee configuration form"""
    fee_type = StringField('Fee Type', validators=[DataRequired(), Length(max=50)])
    description = TextAreaField('Description', validators=[DataRequired()])
    percentage = DecimalField('Percentage (%)', validators=[Optional(), NumberRange(min=0, max=100)])
    fixed_amount = DecimalField('Fixed Amount (R)', validators=[Optional(), NumberRange(min=0)])
    minimum = DecimalField('Minimum Amount (R)', validators=[Optional(), NumberRange(min=0)])
    is_active = BooleanField('Active', default=True)


class ClaimReviewForm(FlaskForm):
    """Claim review form for admins"""
    status = SelectField('Status', choices=[
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('paid', 'Paid')
    ], validators=[DataRequired()])
    admin_notes = TextAreaField('Admin Notes', validators=[Optional()])


class PremiumPaymentForm(FlaskForm):
    """Premium payment form"""
    policy_id = SelectField('Select Policy', coerce=int, validators=[DataRequired()])
    amount = DecimalField('Amount (R)', validators=[DataRequired(), NumberRange(min=1)])