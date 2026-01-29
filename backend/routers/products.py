"""Products router for product management (Stock Entry Operator & Admin)"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

import database
import models
from utils.security import get_current_active_user, require_inventory, require_admin, get_client_ip
from utils.audit import log_price_change, log_stock_change, log_action

router = APIRouter(prefix="/api/products", tags=["Products"])


class ProductCreate(BaseModel):
    product_name: str
    barcode: Optional[str] = None
    purchase_price: float = 0.0
    selling_price: float
    stock_quantity: int = 0
    category: Optional[str] = None
    unit: str = "pcs"


class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    barcode: Optional[str] = None
    purchase_price: Optional[float] = None
    selling_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    is_active: Optional[bool] = None


class StockAdjustment(BaseModel):
    quantity: int  # Positive to add, negative to subtract
    reason: str


class ProductResponse(BaseModel):
    id: int
    product_name: str
    barcode: Optional[str]
    purchase_price: float
    selling_price: float
    stock_quantity: int
    category: Optional[str]
    unit: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=List[ProductResponse])
async def list_products(
    search: Optional[str] = Query(None, description="Search by name or barcode"),
    category: Optional[str] = Query(None),
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """List all products with optional filters"""
    query = db.query(models.Product)
    
    if active_only:
        query = query.filter(models.Product.is_active == True)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Product.product_name.ilike(search_term),
                models.Product.barcode.ilike(search_term)
            )
        )
    
    if category:
        query = query.filter(models.Product.category == category)
    
    return query.offset(skip).limit(limit).all()


@router.get("/search")
async def search_products(
    q: str = Query(..., min_length=1, description="Search query"),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Quick search products by name or barcode (for billing screen)"""
    search_term = f"%{q}%"
    products = db.query(models.Product).filter(
        models.Product.is_active == True,
        or_(
            models.Product.product_name.ilike(search_term),
            models.Product.barcode.ilike(search_term)
        )
    ).limit(20).all()
    
    return [
        {
            "id": p.id,
            "product_name": p.product_name,
            "barcode": p.barcode,
            "selling_price": p.selling_price,
            "stock_quantity": p.stock_quantity,
            "unit": p.unit
        }
        for p in products
    ]


@router.get("/barcode/{barcode}")
async def get_product_by_barcode(
    barcode: str,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get product by barcode (for scanner input)"""
    product = db.query(models.Product).filter(
        models.Product.barcode == barcode,
        models.Product.is_active == True
    ).first()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return {
        "id": product.id,
        "product_name": product.product_name,
        "barcode": product.barcode,
        "selling_price": product.selling_price,
        "stock_quantity": product.stock_quantity,
        "unit": product.unit
    }


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get product by ID"""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/", response_model=ProductResponse)
async def create_product(
    product: ProductCreate,
    request: Request,
    current_user: models.User = Depends(require_inventory),
    db: Session = Depends(database.get_db)
):
    """Create new product (Stock Entry Operator or Admin only)"""
    # Check for duplicate barcode
    if product.barcode:
        existing = db.query(models.Product).filter(
            models.Product.barcode == product.barcode
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Barcode already exists")
    
    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    # Log creation
    log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        table_name="products",
        record_id=db_product.id,
        new_value=product.dict(),
        ip_address=get_client_ip(request),
        description=f"Created product: {product.product_name}"
    )
    
    return db_product


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    request: Request,
    current_user: models.User = Depends(require_inventory),
    db: Session = Depends(database.get_db)
):
    """Update product (Stock Entry Operator or Admin only)"""
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    client_ip = get_client_ip(request)
    update_data = product.dict(exclude_unset=True)
    
    # Track price changes
    if "selling_price" in update_data and update_data["selling_price"] != db_product.selling_price:
        log_price_change(
            db=db,
            user_id=current_user.id,
            product_id=product_id,
            old_price=db_product.selling_price,
            new_price=update_data["selling_price"],
            ip_address=client_ip
        )
    
    # Track stock changes
    if "stock_quantity" in update_data and update_data["stock_quantity"] != db_product.stock_quantity:
        log_stock_change(
            db=db,
            user_id=current_user.id,
            product_id=product_id,
            old_stock=db_product.stock_quantity,
            new_stock=update_data["stock_quantity"],
            reason="Manual update",
            ip_address=client_ip
        )
    
    # Update product
    for key, value in update_data.items():
        setattr(db_product, key, value)
    
    db_product.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_product)
    
    return db_product


@router.post("/{product_id}/adjust-stock")
async def adjust_stock(
    product_id: int,
    adjustment: StockAdjustment,
    request: Request,
    current_user: models.User = Depends(require_inventory),
    db: Session = Depends(database.get_db)
):
    """Adjust product stock (Stock Entry Operator or Admin only)"""
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    old_stock = db_product.stock_quantity
    new_stock = old_stock + adjustment.quantity
    
    if new_stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
    
    db_product.stock_quantity = new_stock
    db_product.updated_at = datetime.utcnow()
    
    log_stock_change(
        db=db,
        user_id=current_user.id,
        product_id=product_id,
        old_stock=old_stock,
        new_stock=new_stock,
        reason=adjustment.reason,
        ip_address=get_client_ip(request)
    )
    
    db.commit()
    
    return {
        "message": "Stock adjusted successfully",
        "old_stock": old_stock,
        "new_stock": new_stock,
        "adjustment": adjustment.quantity
    }


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db)
):
    """Soft delete product (Admin only)"""
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db_product.is_active = False
    db_product.updated_at = datetime.utcnow()
    
    log_action(
        db=db,
        user_id=current_user.id,
        action="delete",
        table_name="products",
        record_id=product_id,
        ip_address=get_client_ip(request),
        description=f"Deleted product: {db_product.product_name}"
    )
    
    db.commit()
    
    return {"message": "Product deleted successfully"}


@router.get("/categories/list")
async def list_categories(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get list of unique product categories"""
    categories = db.query(models.Product.category).filter(
        models.Product.category.isnot(None),
        models.Product.is_active == True
    ).distinct().all()
    
    return [c[0] for c in categories if c[0]]
