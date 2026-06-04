"""Billing router for sales operations"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

import database
import models
from utils.security import get_current_active_user, require_sales, get_client_ip
from utils.billing import generate_bill_number, generate_bill_pdf, generate_thermal_receipt
from utils.audit import log_action

router = APIRouter(prefix="/api/billing", tags=["Billing"])


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    discount: float = 0.0


class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    customer_id: Optional[int] = None
    discount_percent: float = 0.0
    discount_amount: float = 0.0
    payment_mode: str = "cash"  # cash, upi, card
    notes: Optional[str] = None


class OrderResponse(BaseModel):
    id: int
    bill_number: str
    salesperson_id: int
    customer_id: Optional[int]
    subtotal: float
    discount_percent: float
    discount_amount: float
    total_amount: float
    payment_mode: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/orders", response_model=OrderResponse)
async def create_order(
    order: OrderCreate,
    request: Request,
    current_user: models.User = Depends(require_sales),
    db: Session = Depends(database.get_db)
):
    """Create a new sales order/bill (Sales Person or Admin only)"""
    if not order.items:
        raise HTTPException(status_code=400, detail="Order must have at least one item")
    
    # Validate payment mode
    if order.payment_mode not in ["cash", "upi", "card"]:
        raise HTTPException(status_code=400, detail="Invalid payment mode")
    
    # Create order
    bill_number = generate_bill_number()
    new_order = models.Order(
        bill_number=bill_number,
        salesperson_id=current_user.id,
        customer_id=order.customer_id,
        discount_percent=order.discount_percent,
        payment_mode=order.payment_mode,
        notes=order.notes,
        status="completed"
    )
    
    subtotal = 0.0
    order_items = []
    
    for item in order.items:
        # Get product
        product = db.query(models.Product).filter(
            models.Product.id == item.product_id,
            models.Product.is_active == True
        ).first()
        
        if not product:
            raise HTTPException(status_code=404, detail=f"Product ID {item.product_id} not found")
        
        if product.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {product.product_name}. Available: {product.stock_quantity}"
            )
        
        # Calculate item total
        item_total = product.selling_price * item.quantity
        if item.discount > 0:
            item_total -= item.discount
        
        # Create order item
        order_item = models.OrderItem(
            product_id=product.id,
            quantity=item.quantity,
            unit_price=product.selling_price,
            discount=item.discount,
            total=item_total
        )
        order_items.append(order_item)
        subtotal += item_total
        
        # Reduce stock
        product.stock_quantity -= item.quantity
    
    # Calculate totals
    new_order.subtotal = subtotal
    
    # Apply order-level discount
    order_discount = order.discount_amount
    if order.discount_percent > 0:
        order_discount += (subtotal * order.discount_percent / 100)
    
    new_order.discount_amount = order_discount
    new_order.total_amount = subtotal - order_discount
    
    # Add order and items
    new_order.items = order_items
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    
    # Log the sale
    log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        table_name="orders",
        record_id=new_order.id,
        new_value={"bill_number": bill_number, "total": new_order.total_amount},
        ip_address=get_client_ip(request),
        description=f"Created bill {bill_number} for ₹{new_order.total_amount:.2f}"
    )
    
    return new_order


@router.get("/orders", response_model=List[OrderResponse])
async def list_orders(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    status: Optional[str] = None,
    payment_mode: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """List orders with filters"""
    query = db.query(models.Order)
    
    # Sales users can only see their own orders
    if current_user.role == "sales":
        query = query.filter(models.Order.salesperson_id == current_user.id)
    
    if date_from:
        query = query.filter(models.Order.created_at >= date_from)
    if date_to:
        query = query.filter(models.Order.created_at <= date_to)
    if status:
        query = query.filter(models.Order.status == status)
    if payment_mode:
        query = query.filter(models.Order.payment_mode == payment_mode)
    
    return query.order_by(models.Order.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/orders/{order_id}")
async def get_order(
    order_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get order details with items"""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Sales users can only see their own orders
    if current_user.role == "sales" and order.salesperson_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get salesperson info
    salesperson = db.query(models.User).filter(models.User.id == order.salesperson_id).first()
    
    # Get customer info
    customer = None
    if order.customer_id:
        customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
    
    # Build items list with product details
    items = []
    for item in order.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        items.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": product.product_name if product else "Unknown",
            "barcode": product.barcode if product else None,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "discount": item.discount,
            "total": item.total
        })
    
    return {
        "id": order.id,
        "bill_number": order.bill_number,
        "salesperson": {
            "id": salesperson.id,
            "name": salesperson.name or salesperson.username
        } if salesperson else None,
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "mobile": customer.mobile
        } if customer else None,
        "items": items,
        "subtotal": order.subtotal,
        "discount_percent": order.discount_percent,
        "discount_amount": order.discount_amount,
        "total_amount": order.total_amount,
        "payment_mode": order.payment_mode,
        "payment_status": order.payment_status,
        "status": order.status,
        "notes": order.notes,
        "created_at": order.created_at,
        "verified_at": order.verified_at
    }


@router.get("/orders/{order_id}/print-pdf")
async def print_order_pdf(
    order_id: int,
    token: Optional[str] = None,  # Allow token via query param for new tab
    db: Session = Depends(database.get_db)
):
    """Generate PDF bill for printing. Accepts token as query parameter for new tab printing."""
    # Validate token (from query param)
    if not token:
        raise HTTPException(status_code=401, detail="Token required. Add ?token=YOUR_TOKEN to URL")
    
    from jose import JWTError, jwt
    from utils.security import SECRET_KEY, ALGORITHM
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Get salesperson
    salesperson = db.query(models.User).filter(models.User.id == order.salesperson_id).first()
    
    # Get customer
    customer = None
    if order.customer_id:
        customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
    
    # Build items
    items = []
    for item in order.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        items.append({
            "product_name": product.product_name if product else "Unknown",
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total": item.total
        })
    
    order_data = {
        "bill_number": order.bill_number,
        "date": order.created_at.strftime("%d-%m-%Y %H:%M"),
        "customer_name": customer.name if customer else "Walk-in Customer",
        "items": items,
        "subtotal": order.subtotal,
        "discount": order.discount_amount,
        "total": order.total_amount,
        "payment_mode": order.payment_mode,
        "salesperson": salesperson.name or salesperson.username if salesperson else ""
    }
    
    pdf_buffer = generate_bill_pdf(order_data)
    
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=bill_{order.bill_number}.pdf"}
    )


@router.get("/orders/{order_id}/thermal-receipt")
async def get_thermal_receipt(
    order_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get thermal printer formatted receipt"""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Get salesperson
    salesperson = db.query(models.User).filter(models.User.id == order.salesperson_id).first()
    
    # Get customer
    customer = None
    if order.customer_id:
        customer = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
    
    # Build items
    items = []
    for item in order.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        items.append({
            "product_name": product.product_name if product else "Unknown",
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total": item.total
        })
    
    order_data = {
        "bill_number": order.bill_number,
        "date": order.created_at.strftime("%d-%m-%Y %H:%M"),
        "customer_name": customer.name if customer else "Walk-in",
        "items": items,
        "subtotal": order.subtotal,
        "discount": order.discount_amount,
        "total": order.total_amount,
        "payment_mode": order.payment_mode,
        "salesperson": salesperson.name or salesperson.username if salesperson else ""
    }
    
    receipt_text = generate_thermal_receipt(order_data)
    
    return Response(content=receipt_text, media_type="text/plain")


@router.get("/orders/by-bill/{bill_number}")
async def get_order_by_bill_number(
    bill_number: str,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Find order by bill number"""
    order = db.query(models.Order).filter(models.Order.bill_number == bill_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return await get_order(order.id, current_user, db)
