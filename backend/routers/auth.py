"""Authentication router with IP-based login validation"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

import database
import models
from utils.security import (
    verify_password, get_password_hash, create_access_token,
    get_current_active_user, get_client_ip, validate_ip_access,
    ACCESS_TOKEN_EXPIRE_MINUTES, Token
)
from utils.audit import log_login, log_logout

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    name: Optional[str]
    role: str
    ip_address: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db)
):
    """Authenticate user and return JWT token"""
    client_ip = get_client_ip(request)
    
    # Find user
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(form_data.password, user.hashed_password):
        log_login(db, user.id, client_ip, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    # Validate IP access
    if not validate_ip_access(user, client_ip):
        log_login(db, user.id, client_ip, success=False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied from this IP address ({client_ip}). Contact admin."
        )
    
    # Update login status
    user.login_status = True
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Log successful login
    log_login(db, user.id, client_ip, success=True)
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "user_id": user.id},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "role": user.role
        }
    }


@router.post("/logout")
async def logout(
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Logout current user"""
    client_ip = get_client_ip(request)
    
    current_user.login_status = False
    db.commit()
    
    log_logout(db, current_user.id, client_ip)
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: models.User = Depends(get_current_active_user)
):
    """Get current logged in user info"""
    return current_user


@router.post("/change-password")
async def change_password(
    old_password: str,
    new_password: str,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Change current user's password"""
    if not verify_password(old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}
