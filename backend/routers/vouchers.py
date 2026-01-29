"""Vouchers router for credit voucher management"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import string
import random

import database
import models
from utils.security import get_current_active_user, require_accounts, require_sales

router = APIRouter(prefix="/api/vouchers", tags=["Vouchers"])


def generate_voucher_code():
    """Generate unique voucher code: VOU-XXXXXXXX"""
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=8))
    return f"VOU-{code}"


@router.get("/")
async def list_vouchers(
    status: str = None,  # all, active, redeemed, expired
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """List all vouchers with optional filters"""
    query = db.query(models.CreditVoucher)
    
    now = datetime.utcnow()
    
    if status == "active":
        query = query.filter(
            models.CreditVoucher.is_redeemed == False,
            models.CreditVoucher.expires_at > now
        )
    elif status == "redeemed":
        query = query.filter(models.CreditVoucher.is_redeemed == True)
    elif status == "expired":
        query = query.filter(
            models.CreditVoucher.is_redeemed == False,
            models.CreditVoucher.expires_at <= now
        )
    
    vouchers = query.order_by(models.CreditVoucher.created_at.desc()).all()
    
    result = []
    for v in vouchers:
        customer = None
        if v.customer_id:
            customer = db.query(models.Customer).filter(models.Customer.id == v.customer_id).first()
        
        is_expired = v.expires_at < now and not v.is_redeemed
        
        result.append({
            "id": v.id,
            "voucher_code": v.voucher_code,
            "amount": v.amount,
            "customer_name": customer.name if customer else "Walk-in",
            "issued_at": v.issued_at.isoformat(),
            "expires_at": v.expires_at.isoformat(),
            "is_redeemed": v.is_redeemed,
            "is_expired": is_expired,
            "redeemed_at": v.redeemed_at.isoformat() if v.redeemed_at else None,
            "status": "redeemed" if v.is_redeemed else ("expired" if is_expired else "active")
        })
    
    return result


@router.get("/validate/{code}")
async def validate_voucher(
    code: str,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Validate if a voucher code is valid and can be used"""
    voucher = db.query(models.CreditVoucher).filter(
        models.CreditVoucher.voucher_code == code.upper()
    ).first()
    
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    
    # Check if already redeemed
    if voucher.is_redeemed:
        raise HTTPException(status_code=400, detail="Voucher has already been redeemed")
    
    # Check if expired
    if voucher.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Voucher has expired")
    
    # Get customer details if available
    customer = None
    if voucher.customer_id:
        customer = db.query(models.Customer).filter(models.Customer.id == voucher.customer_id).first()
    
    return {
        "valid": True,
        "voucher_code": voucher.voucher_code,
        "amount": voucher.amount,
        "customer_name": customer.name if customer else None,
        "expires_at": voucher.expires_at.isoformat(),
        "days_remaining": (voucher.expires_at - datetime.utcnow()).days
    }


@router.post("/{code}/redeem")
async def redeem_voucher(
    code: str,
    order_id: int,
    current_user: models.User = Depends(require_sales),
    db: Session = Depends(database.get_db)
):
    """Redeem a voucher against an order (Sales only)"""
    voucher = db.query(models.CreditVoucher).filter(
        models.CreditVoucher.voucher_code == code.upper()
    ).first()
    
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    
    if voucher.is_redeemed:
        raise HTTPException(status_code=400, detail="Voucher already redeemed")
    
    if voucher.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Voucher has expired")
    
    # Mark voucher as redeemed
    voucher.is_redeemed = True
    voucher.redeemed_at = datetime.utcnow()
    voucher.redeemed_by = current_user.id
    voucher.redeemed_order_id = order_id
    
    db.commit()
    
    return {
        "message": "Voucher redeemed successfully",
        "voucher_code": voucher.voucher_code,
        "amount": voucher.amount
    }


# Admin endpoint to manually create vouchers
from pydantic import BaseModel

class VoucherCreate(BaseModel):
    amount: float
    customer_id: int = None
    validity_days: int = 30
    reason: str = None


@router.post("/admin/create")
async def create_voucher_manual(
    voucher_data: VoucherCreate,
    current_user: models.User = Depends(require_accounts),  # Admin or Accountant
    db: Session = Depends(database.get_db)
):
    """Manually create a voucher (Admin/Accountant only)"""
    # Generate unique voucher code
    voucher_code = generate_voucher_code()
    
    # Ensure uniqueness
    while db.query(models.CreditVoucher).filter(models.CreditVoucher.voucher_code == voucher_code).first():
        voucher_code = generate_voucher_code()
    
    # Calculate expiry
    expires_at = datetime.utcnow() + timedelta(days=voucher_data.validity_days)
    
    # Create voucher
    voucher = models.CreditVoucher(
        voucher_code=voucher_code,
        return_id=None,  # Manually created, not from return
        customer_id=voucher_data.customer_id,
        amount=voucher_data.amount,
        issued_by=current_user.id,
        expires_at=expires_at
    )
    
    db.add(voucher)
    db.commit()
    db.refresh(voucher)
    
    return {
        "message": "Voucher created successfully",
        "voucher_code": voucher.voucher_code,
        "amount": voucher.amount,
        "expires_at": voucher.expires_at.isoformat(),
        "validity_days": voucher_data.validity_days
    }
