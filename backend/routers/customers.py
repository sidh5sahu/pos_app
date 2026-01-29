"""Customer management router"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

import database
import models
from utils.security import get_current_active_user

router = APIRouter(prefix="/api/customers", tags=["Customers"])


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


@router.get("/", response_model=List[CustomerResponse])
async def list_customers(
    search: Optional[str] = Query(None, description="Search by name or mobile"),
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """List customers with optional search"""
    query = db.query(models.Customer)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Customer.name.ilike(search_term),
                models.Customer.mobile.ilike(search_term)
            )
        )
    
    return query.order_by(models.Customer.name).offset(skip).limit(limit).all()


@router.get("/search")
async def search_customers(
    q: str = Query(..., min_length=1, description="Search query"),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Quick search customers (for billing autocomplete)"""
    search_term = f"%{q}%"
    customers = db.query(models.Customer).filter(
        or_(
            models.Customer.name.ilike(search_term),
            models.Customer.mobile.ilike(search_term)
        )
    ).limit(10).all()
    
    return [
        {
            "id": c.id,
            "name": c.name,
            "mobile": c.mobile,
            "display": f"{c.name}" + (f" ({c.mobile})" if c.mobile else "")
        }
        for c in customers
    ]


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get customer by ID"""
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("/", response_model=CustomerResponse)
async def create_customer(
    customer: CustomerCreate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Create new customer (any authenticated user can add)"""
    new_customer = models.Customer(**customer.dict())
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    customer: CustomerCreate,
    current_user: models.User = Depends(get_current_active_user),
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


@router.get("/{customer_id}/details")
async def get_customer_details(
    customer_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get customer details with purchase history"""
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Get all orders for this customer
    orders = db.query(models.Order).filter(
        models.Order.customer_id == customer_id
    ).order_by(models.Order.created_at.desc()).all()
    
    # Calculate statistics
    total_orders = len([o for o in orders if o.status != "refunded"])
    total_spent = sum(o.total_amount for o in orders if o.status != "refunded")
    
    # Recent orders
    recent_orders = []
    for order in orders[:10]:  # Last 10 orders
        recent_orders.append({
            "id": order.id,
            "bill_number": order.bill_number,
            "total_amount": order.total_amount,
            "payment_mode": order.payment_mode,
            "status": order.status,
            "created_at": order.created_at.isoformat()
        })
    
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "mobile": customer.mobile,
            "email": customer.email,
            "address": customer.address,
            "created_at": customer.created_at.isoformat()
        },
        "statistics": {
            "total_orders": total_orders,
            "total_spent": round(total_spent, 2)
        },
        "recent_orders": recent_orders
    }

