"""Admin router for user management and system administration"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
import shutil

import database
import models
from utils.security import get_password_hash, require_admin, get_client_ip
from utils.audit import log_action

router = APIRouter(prefix="/api/admin", tags=["Admin"])


class UserCreate(BaseModel):
    username: str
    password: str
    name: Optional[str] = None
    role: str
    ip_address: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    ip_address: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    name: Optional[str]
    role: str
    ip_address: Optional[str]
    is_active: bool
    login_status: bool
    last_login: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerCreate(BaseModel):
    name: str
    mobile: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class CustomerResponse(BaseModel):
    id: int
    name: str
    mobile: Optional[str]
    email: Optional[str]
    address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# User Management
@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """List all users (Admin only)"""
    return db.query(models.User).all()


@router.post("/users", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Create new user (Admin only)"""
    # Check if username exists
    existing = db.query(models.User).filter(models.User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Validate role
    valid_roles = ["admin", "sales", "inventory", "accounts"]
    if user.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}")
    
    new_user = models.User(
        username=user.username,
        hashed_password=get_password_hash(user.password),
        name=user.name,
        role=user.role,
        ip_address=user.ip_address
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        table_name="users",
        record_id=new_user.id,
        new_value={"username": user.username, "role": user.role},
        ip_address=get_client_ip(request),
        description=f"Created user: {user.username} ({user.role})"
    )
    
    return new_user


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Get user by ID (Admin only)"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Update user (Admin only)"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_update.dict(exclude_unset=True)
    
    if "role" in update_data:
        valid_roles = ["admin", "sales", "inventory", "accounts"]
        if update_data["role"] not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role")
    
    for key, value in update_data.items():
        setattr(user, key, value)
    
    db.commit()
    db.refresh(user)
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="update",
        table_name="users",
        record_id=user_id,
        new_value=update_data,
        ip_address=get_client_ip(request),
        description=f"Updated user: {user.username}"
    )
    
    return user


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    new_password: str,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Reset user password (Admin only)"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.hashed_password = get_password_hash(new_password)
    db.commit()
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="update",
        table_name="users",
        record_id=user_id,
        ip_address=get_client_ip(request),
        description=f"Password reset for user: {user.username}"
    )
    
    return {"message": "Password reset successfully"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Delete user (Admin only) - Actually deactivates"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin user")
    
    user.is_active = False
    db.commit()
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="delete",
        table_name="users",
        record_id=user_id,
        ip_address=get_client_ip(request),
        description=f"Deactivated user: {user.username}"
    )
    
    return {"message": "User deactivated"}


# Customer Management
@router.get("/customers", response_model=List[CustomerResponse])
async def list_customers(
    search: Optional[str] = None,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """List customers"""
    query = db.query(models.Customer)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            models.Customer.name.ilike(search_term) |
            models.Customer.mobile.ilike(search_term)
        )
    return query.all()


@router.post("/customers", response_model=CustomerResponse)
async def create_customer(
    customer: CustomerCreate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Create customer"""
    new_customer = models.Customer(**customer.dict())
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer


@router.put("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    customer: CustomerCreate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Update customer"""
    db_customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    for key, value in customer.dict().items():
        setattr(db_customer, key, value)
    
    db.commit()
    db.refresh(db_customer)
    return db_customer


# Audit Logs
@router.get("/audit-logs")
async def get_audit_logs(
    action: Optional[str] = None,
    table_name: Optional[str] = None,
    user_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Get audit logs (Admin only)"""
    query = db.query(models.AuditLog)
    
    if action:
        query = query.filter(models.AuditLog.action == action)
    if table_name:
        query = query.filter(models.AuditLog.table_name == table_name)
    if user_id:
        query = query.filter(models.AuditLog.user_id == user_id)
    if date_from:
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(models.AuditLog.created_at >= start)
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.strptime(date_to, "%Y-%m-%d")
            end = datetime.combine(end.date(), datetime.max.time())
            query = query.filter(models.AuditLog.created_at <= end)
        except ValueError:
            pass
    
    logs = query.order_by(models.AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for log in logs:
        user = db.query(models.User).filter(models.User.id == log.user_id).first()
        result.append({
            "id": log.id,
            "user": user.username if user else "Unknown",
            "action": log.action,
            "table_name": log.table_name,
            "record_id": log.record_id,
            "description": log.description,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat()
        })
    
    return result


# Database Backup
@router.get("/backup")
async def backup_database(
    current_user: models.User = Depends(require_admin)
):
    """Create database backup (Admin only) - For SQLite"""
    db_path = "./pos.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")
    
    backup_dir = "./backups"
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{backup_dir}/pos_backup_{timestamp}.db"
    
    shutil.copy2(db_path, backup_path)
    
    return FileResponse(
        backup_path,
        media_type="application/octet-stream",
        filename=f"pos_backup_{timestamp}.db"
    )


# System Settings
@router.get("/settings")
async def get_settings(
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Get system settings"""
    settings = db.query(models.Settings).all()
    return {s.key: s.value for s in settings}


@router.post("/settings")
async def update_settings(
    settings: dict,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Update system settings"""
    for key, value in settings.items():
        setting = db.query(models.Settings).filter(models.Settings.key == key).first()
        if setting:
            setting.value = str(value)
        else:
            new_setting = models.Settings(key=key, value=str(value))
            db.add(new_setting)
    
    db.commit()
    return {"message": "Settings updated"}
