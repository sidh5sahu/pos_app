"""Audit logging utility for tracking changes"""
import json
from datetime import datetime
from sqlalchemy.orm import Session
from models import AuditLog


def log_action(
    db: Session,
    user_id: int,
    action: str,
    table_name: str = None,
    record_id: int = None,
    old_value: dict = None,
    new_value: dict = None,
    ip_address: str = None,
    description: str = None
):
    """
    Log an action to the audit trail.
    
    Args:
        db: Database session
        user_id: ID of user performing action
        action: Type of action (create, update, delete, login, logout, price_change, stock_change, refund)
        table_name: Name of affected table
        record_id: ID of affected record
        old_value: Previous values (for updates)
        new_value: New values (for updates/creates)
        ip_address: IP address of user
        description: Human readable description
    """
    audit_entry = AuditLog(
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_value=json.dumps(old_value) if old_value else None,
        new_value=json.dumps(new_value) if new_value else None,
        ip_address=ip_address,
        description=description,
        created_at=datetime.utcnow()
    )
    db.add(audit_entry)
    db.commit()
    return audit_entry


def log_price_change(db: Session, user_id: int, product_id: int, old_price: float, new_price: float, ip_address: str = None):
    """Log a price change"""
    return log_action(
        db=db,
        user_id=user_id,
        action="price_change",
        table_name="products",
        record_id=product_id,
        old_value={"selling_price": old_price},
        new_value={"selling_price": new_price},
        ip_address=ip_address,
        description=f"Price changed from {old_price} to {new_price}"
    )


def log_stock_change(db: Session, user_id: int, product_id: int, old_stock: int, new_stock: int, reason: str = None, ip_address: str = None):
    """Log a stock change"""
    return log_action(
        db=db,
        user_id=user_id,
        action="stock_change",
        table_name="products",
        record_id=product_id,
        old_value={"stock_quantity": old_stock},
        new_value={"stock_quantity": new_stock},
        ip_address=ip_address,
        description=f"Stock changed from {old_stock} to {new_stock}. Reason: {reason or 'Not specified'}"
    )


def log_refund(db: Session, user_id: int, order_id: int, refund_amount: float, ip_address: str = None):
    """Log a refund action"""
    return log_action(
        db=db,
        user_id=user_id,
        action="refund",
        table_name="orders",
        record_id=order_id,
        new_value={"refund_amount": refund_amount},
        ip_address=ip_address,
        description=f"Refund processed: {refund_amount}"
    )


def log_login(db: Session, user_id: int, ip_address: str = None, success: bool = True):
    """Log a login attempt"""
    return log_action(
        db=db,
        user_id=user_id,
        action="login" if success else "login_failed",
        ip_address=ip_address,
        description=f"User {'logged in successfully' if success else 'failed to login'}"
    )


def log_logout(db: Session, user_id: int, ip_address: str = None):
    """Log a logout"""
    return log_action(
        db=db,
        user_id=user_id,
        action="logout",
        ip_address=ip_address,
        description="User logged out"
    )
