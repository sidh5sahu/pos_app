"""Returns and Refunds router with multi-step workflow"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

import database
import models
from utils.security import get_current_active_user, require_accounts, require_sales, require_inventory, get_client_ip
from utils.audit import log_refund, log_stock_change, log_action

router = APIRouter(prefix="/api/returns", tags=["Returns & Refunds"])


class ReturnCreate(BaseModel):
    order_id: int
    product_id: int
    quantity: int
    reason: str


class StockVerify(BaseModel):
    stock_notes: Optional[str] = None


class RefundProcess(BaseModel):
    status: str  # refund_approved, rejected
    refund_type: str = "cash"  # cash, voucher
    refund_amount: Optional[float] = None


class ReturnResponse(BaseModel):
    id: int
    order_id: int
    product_id: int
    quantity: int
    reason: Optional[str]
    refund_amount: float
    refund_type: str
    status: str
    created_by: Optional[int]
    stock_verified_by: Optional[int]
    processed_by: Optional[int]
    created_at: datetime
    stock_verified_at: Optional[datetime]
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ==================== STEP 1: Sales Person Creates Return Request ====================

@router.post("/", response_model=ReturnResponse)
async def create_return(
    return_item: ReturnCreate,
    request: Request,
    current_user: models.User = Depends(require_sales),  # Sales can create
    db: Session = Depends(database.get_db)
):
    """Create a return request (Sales Person)"""
    order = db.query(models.Order).filter(models.Order.id == return_item.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order_item = db.query(models.OrderItem).filter(
        models.OrderItem.order_id == return_item.order_id,
        models.OrderItem.product_id == return_item.product_id
    ).first()
    
    if not order_item:
        raise HTTPException(status_code=400, detail="Product was not in this order")
    
    # Check quantity
    existing_returns = db.query(models.Return).filter(
        models.Return.order_id == return_item.order_id,
        models.Return.product_id == return_item.product_id,
        models.Return.status.in_(["pending_verification", "verified", "approved"])
    ).all()
    
    returned_qty = sum(r.quantity for r in existing_returns)
    if returned_qty + return_item.quantity > order_item.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot return more than ordered. Original: {order_item.quantity}, Already in process: {returned_qty}"
        )
    
    refund_amount = order_item.unit_price * return_item.quantity
    
    new_return = models.Return(
        order_id=return_item.order_id,
        product_id=return_item.product_id,
        quantity=return_item.quantity,
        reason=return_item.reason,
        refund_amount=refund_amount,
        status="pending_verification",
        created_by=current_user.id
    )
    
    db.add(new_return)
    db.commit()
    db.refresh(new_return)
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        table_name="returns",
        record_id=new_return.id,
        new_value={"order_id": return_item.order_id, "quantity": return_item.quantity},
        ip_address=get_client_ip(request),
        description=f"Return request created for order {order.bill_number}"
    )
    
    return new_return


# ==================== STEP 2: Stock Entry Person Verifies Stock ====================

@router.post("/{return_id}/verify-stock")
async def verify_stock(
    return_id: int,
    verify_data: StockVerify,
    request: Request,
    current_user: models.User = Depends(require_inventory),  # Inventory verifies
    db: Session = Depends(database.get_db)
):
    """Verify returned stock received (Stock Entry Person)"""
    return_item = db.query(models.Return).filter(models.Return.id == return_id).first()
    if not return_item:
        raise HTTPException(status_code=404, detail="Return not found")
    
    if return_item.status != "pending_verification":
        raise HTTPException(status_code=400, detail=f"Cannot verify. Current status: {return_item.status}")
    
    # Restore stock
    product = db.query(models.Product).filter(models.Product.id == return_item.product_id).first()
    if product:
        old_stock = product.stock_quantity
        product.stock_quantity += return_item.quantity
        
        log_stock_change(
            db=db,
            user_id=current_user.id,
            product_id=product.id,
            old_stock=old_stock,
            new_stock=product.stock_quantity,
            reason=f"Return verified - Return #{return_id}",
            ip_address=get_client_ip(request)
        )
    
    return_item.status = "verified"
    return_item.verified_by = current_user.id
    return_item.verified_at = datetime.utcnow()
    return_item.verification_notes = verify_data.stock_notes
    
    db.commit()
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="update",
        table_name="returns",
        record_id=return_id,
        new_value={"status": "verified"},
        ip_address=get_client_ip(request),
        description=f"Stock verified for return #{return_id}"
    )
    
    return {"message": "Stock verified", "return_id": return_id, "status": "verified"}


# ==================== STEP 3: Accountant Approves/Rejects & Issues Voucher ====================

@router.post("/{return_id}/approve")
async def approve_return(
    return_id: int,
    request: Request,
    current_user: models.User = Depends(require_accounts),  # Accountant approves
    db: Session = Depends(database.get_db)
):
    """Approve return and issue credit voucher (Accountant)"""
    return_item = db.query(models.Return).filter(models.Return.id == return_id).first()
    if not return_item:
        raise HTTPException(status_code=404, detail="Return not found")
    
    if return_item.status != "verified":
        raise HTTPException(status_code=400, detail=f"Return not verified by stock. Current status: {return_item.status}")
    
    # Generate unique voucher code
    import string
    import random
    chars = string.ascii_uppercase + string.digits
    voucher_code = 'VOU-' + ''.join(random.choices(chars, k=8))
    
    # Ensure uniqueness
    while db.query(models.CreditVoucher).filter(models.CreditVoucher.voucher_code == voucher_code).first():
        voucher_code = 'VOU-' + ''.join(random.choices(chars, k=8))
    
    # Create credit voucher with 30 days validity
    from datetime import timedelta
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    # Get customer_id from order
    order = db.query(models.Order).filter(models.Order.id == return_item.order_id).first()
    customer_id = order.customer_id if order else None
    
    voucher = models.CreditVoucher(
        voucher_code=voucher_code,
        return_id=return_id,
        customer_id=customer_id,
        amount=return_item.refund_amount,
        issued_by=current_user.id,
        expires_at=expires_at
    )
    
    # Update return status
    return_item.status = "approved"
    return_item.approved_by = current_user.id
    return_item.approved_at = datetime.utcnow()
    
    db.add(voucher)
    db.commit()
    db.refresh(voucher)
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        table_name="credit_vouchers",
        record_id=voucher.id,
        new_value={"voucher_code": voucher_code, "amount": return_item.refund_amount},
        ip_address=get_client_ip(request),
        description=f"Credit voucher {voucher_code} issued for return #{return_id}"
    )
    
    return {
        "message": "Return approved and credit voucher issued",
        "return_id": return_id,
        "voucher": {
            "code": voucher.voucher_code,
            "amount": voucher.amount,
            "expires_at": voucher.expires_at.isoformat(),
            "days_valid": 30
        }
    }


@router.post("/{return_id}/reject")
async def reject_return(
    return_id: int,
    rejection_reason: str,
    request: Request,
    current_user: models.User = Depends(require_accounts),  # Accountant or Stock can reject
    db: Session = Depends(database.get_db)
):
    """Reject return request"""
    return_item = db.query(models.Return).filter(models.Return.id == return_id).first()
    if not return_item:
        raise HTTPException(status_code=404, detail="Return not found")
    
    if return_item.status not in ["pending_verification", "verified"]:
        raise HTTPException(status_code=400, detail=f"Cannot reject. Current status: {return_item.status}")
    
    # If stock was already verified, reverse it
    if return_item.status == "verified":
        product = db.query(models.Product).filter(models.Product.id == return_item.product_id).first()
        if product:
            old_stock = product.stock_quantity
            product.stock_quantity -= return_item.quantity
            
            log_stock_change(
                db=db,
                user_id=current_user.id,
                product_id=product.id,
                old_stock=old_stock,
                new_stock=product.stock_quantity,
                reason=f"Return rejected - stock reversed for Return #{return_id}",
                ip_address=get_client_ip(request)
            )
    
    return_item.status = "rejected"
    return_item.rejection_reason = rejection_reason
    return_item.approved_by = current_user.id
    return_item.approved_at = datetime.utcnow()
    
    db.commit()
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="update",
        table_name="returns",
        record_id=return_id,
        new_value={"status": "rejected"},
        ip_address=get_client_ip(request),
        description=f"Return #{return_id} rejected: {rejection_reason}"
    )
    
    return {"message": "Return rejected", "return_id": return_id}


# ==================== List and Get Returns ====================

@router.get("/", response_model=List[ReturnResponse])
async def list_returns(
    status: Optional[str] = None,
    order_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """List returns - filtered by role"""
    query = db.query(models.Return)
    
    # Sales sees their own returns
    if current_user.role == "sales":
        query = query.filter(models.Return.created_by == current_user.id)
    # Inventory sees pending returns needing stock verification
    elif current_user.role == "inventory":
        if not status:
            status = "pending_verification"
    # Accounts sees verified returns needing approval
    elif current_user.role == "accounts":
        if not status:
            status = "verified"
    
    if status:
        query = query.filter(models.Return.status == status)
    if order_id:
        query = query.filter(models.Return.order_id == order_id)
    
    return query.order_by(models.Return.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{return_id}")
async def get_return(
    return_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get return details"""
    return_item = db.query(models.Return).filter(models.Return.id == return_id).first()
    if not return_item:
        raise HTTPException(status_code=404, detail="Return not found")
    
    product = db.query(models.Product).filter(models.Product.id == return_item.product_id).first()
    order = db.query(models.Order).filter(models.Order.id == return_item.order_id).first()
    
    return {
        "id": return_item.id,
        "order_id": return_item.order_id,
        "bill_number": order.bill_number if order else None,
        "product_id": return_item.product_id,
        "product_name": product.product_name if product else "Unknown",
        "quantity": return_item.quantity,
        "reason": return_item.reason,
        "refund_amount": return_item.refund_amount,
        "refund_type": return_item.refund_type,
        "status": return_item.status,
        "created_by": return_item.created_by,
        "stock_verified_by": return_item.stock_verified_by,
        "stock_verified_at": return_item.stock_verified_at,
        "stock_notes": return_item.stock_notes,
        "processed_by": return_item.processed_by,
        "created_at": return_item.created_at,
        "processed_at": return_item.processed_at
    }


# ==================== Order Verification (Accountant) ====================

@router.post("/orders/{order_id}/verify")
async def verify_order(
    order_id: int,
    request: Request,
    current_user: models.User = Depends(require_accounts),
    db: Session = Depends(database.get_db)
):
    """Verify/approve an order (Accountant only)"""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status == "verified":
        raise HTTPException(status_code=400, detail="Order already verified")
    
    order.status = "verified"
    order.verified_at = datetime.utcnow()
    order.verified_by = current_user.id
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="update",
        table_name="orders",
        record_id=order_id,
        new_value={"status": "verified"},
        ip_address=get_client_ip(request),
        description=f"Order {order.bill_number} verified"
    )
    
    db.commit()
    
    return {"message": "Order verified", "bill_number": order.bill_number}
