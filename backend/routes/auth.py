from fastapi import APIRouter, Depends, HTTPException, Header
from sqlmodel import Session, select
from models.postgres_models import Employee, Session as DBSession, Admin
from models.models import SignupData, SigninData, ForgotPasswordRequest, VerifyOTPRequest, ResetPasswordRequest
from database.db import get_session
from datetime import datetime, timedelta
import secrets
import bcrypt
import random
import string
from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

auth_router = APIRouter()

# In-memory OTP storage (you can replace this with Redis or database storage)

@auth_router.post("/signup", tags=["Authentication"])
def signup(data: SignupData, session: Session = Depends(get_session)):
    existing_user = session.exec(select(Employee).where(Employee.email == data.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed_password = bcrypt.hashpw(data.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Updated to include role from SignupData
    user = Employee(
        name=data.name,
        email=data.email,
        password_hash=hashed_password,
        role=data.role,
        joining_date=data.joining_date or datetime.utcnow().date()
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    return {
        "message": "Employee created successfully",
        "user_id": str(user.id),
        "role": user.role.value  # Include role in response
    }

@auth_router.post("/signin", tags=["Authentication"])
def signin(data: SigninData, session: Session = Depends(get_session)):
    # Check in Employee table
    user = session.exec(select(Employee).where(Employee.email == data.email)).first()
    if user and bcrypt.checkpw(data.password.encode('utf-8'), user.password_hash.encode('utf-8')):

        token = secrets.token_hex(32)
        expires_at = datetime.utcnow() + timedelta(days=1)

        db_session = DBSession(
            employee_id=user.id,
            token=token,
            expires_at=expires_at
        )
        session.add(db_session)
        session.commit()

        return {
            "token": token,
            "user": {
                "id": str(user.id),
                "name": user.name,
                "role": user.role.value,  # Include role in signin response
                "type": "employee"
            }
        }

    # Check in Admin table (unchanged)
    admin = session.exec(select(Admin).where(Admin.email == data.email)).first()
    if admin and bcrypt.checkpw(data.password.encode('utf-8'), admin.password_hash.encode('utf-8')):

        token = secrets.token_hex(32)
        expires_at = datetime.utcnow() + timedelta(days=1)

        db_session = DBSession(
            admin_id=admin.id,
            token=token,
            expires_at=expires_at
        )
        session.add(db_session)
        session.commit()

        return {
            "token": token,
            "user": {
                "id": str(admin.id),
                "email": admin.email,
                "type": "admin"
            }
        }

    raise HTTPException(status_code=401, detail="Invalid email or password")

@auth_router.post("/logout", tags=["Authentication"])
def logout(authorization: str = Header(None), session: Session = Depends(get_session)):
    # Log the full Authorization header for debugging
    print(f"Authorization Header: {authorization}")  # Debugging: log the Authorization header

    if not authorization or not authorization.startswith("Bearer"):
        raise HTTPException(status_code=400, detail="Authorization token missing or invalid")

    # Extract the token (after "Bearer ")
    token = authorization[7:].strip()  # Strip any leading/trailing spaces
    print(f"Extracted token: {token}")  # Debugging: print the extracted token

    # Find session associated with the token
    db_session = session.exec(select(DBSession).where(DBSession.token == token)).first()

    if not db_session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Delete the session to effectively log out
    session.delete(db_session)
    session.commit()

    return {"message": "Successfully logged out"}

# NEW FORGOT PASSWORD ENDPOINTS

@auth_router.post("/forgot-password", tags=["Reset Password"])
def forgot_password(data: ForgotPasswordRequest, session: Session = Depends(get_session)):
    """Initiate forgot password process by sending OTP to email"""
    
    # Check if user exists in Employee table
    user = session.exec(select(Employee).where(Employee.email == data.email)).first()
    if not user:
        # Check in Admin table
        admin = session.exec(select(Admin).where(Admin.email == data.email)).first()
        if not admin:
            # Don't reveal if email exists or not for security
            return {"message": "If the email exists, an OTP has been sent to it"}
    
    # Generate OTP
    otp = generate_otp()
    
    # Store OTP with expiration (10 minutes)
    otp_data = {
        "otp": otp,
        "email": data.email,
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
        "attempts": 0,
        "max_attempts": 3
    }
    
    # Use email as key for OTP storage
    otp_storage[data.email] = otp_data
    
    # Get user name for email
    user_name = user.name if user else (admin.email if admin else "User")
    
    # Send OTP via email
    email_sent = send_otp_email(data.email, otp, user_name)
    
    if not email_sent:
        raise HTTPException(status_code=500, detail="Failed to send OTP email")
    
    return {
        "message": "OTP has been sent to your email address",
        "expires_in_minutes": 10
    }


@auth_router.post("/reset-password", tags=["Reset Password"])
def reset_password(data: ResetPasswordRequest, session: Session = Depends(get_session)):
    """Reset password using verified OTP token"""
    
    # Find the OTP data with matching reset token
    otp_data = None
    email = None
    
    for stored_email, stored_data in otp_storage.items():
        if (stored_data.get("reset_token") == data.reset_token and 
            stored_data.get("verified") == True):
            otp_data = stored_data
            email = stored_email
            break
    
    if not otp_data:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Check if reset token has expired
    if datetime.utcnow() > otp_data["expires_at"]:
        # Clean up expired token
        if email in otp_storage:
            del otp_storage[email]
        raise HTTPException(status_code=400, detail="Reset token has expired")
    
    # Validate password confirmation
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Validate password strength (optional)
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long")
    
    # Hash the new password
    hashed_password = bcrypt.hashpw(data.new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Update password in database
    # Check Employee table first
    user = session.exec(select(Employee).where(Employee.email == email)).first()
    if user:
        user.password_hash = hashed_password
        session.add(user)
        session.commit()
        
        # Invalidate all existing sessions for this user
        existing_sessions = session.exec(select(DBSession).where(DBSession.employee_id == user.id)).all()
        for existing_session in existing_sessions:
            session.delete(existing_session)
        session.commit()
        
    else:
        # Check Admin table
        admin = session.exec(select(Admin).where(Admin.email == email)).first()
        if admin:
            admin.password_hash = hashed_password
            session.add(admin)
            session.commit()
            
            # Invalidate all existing sessions for this admin
            existing_sessions = session.exec(select(DBSession).where(DBSession.admin_id == admin.id)).all()
            for existing_session in existing_sessions:
                session.delete(existing_session)
            session.commit()
        else:
            raise HTTPException(status_code=404, detail="User not found")
    
    # Clean up OTP data
    if email in otp_storage:
        del otp_storage[email]
    
    return {
        "message": "Password reset successfully",
        "note": "Please sign in with your new password"
    }