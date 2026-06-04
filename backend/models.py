from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class User(Base):
    """User model with roles: admin, sales, inventory, accounts"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(200))
    role = Column(String(50), nullable=False)  # admin, sales, inventory, accounts
    ip_address = Column(String(50), nullable=True)  # Allowed IP for this user
    login_status = Column(Boolean, default=False)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    orders = relationship("Order", back_populates="salesperson")
    audit_logs = relationship("AuditLog", back_populates="user")


class Customer(Base):
    """Customer model for optional customer tracking"""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    mobile = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    orders = relationship("Order", back_populates="customer")


class Product(Base):
    """Product model with barcode support"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String(200), index=True, nullable=False)
    barcode = Column(String(100), unique=True, index=True, nullable=True)
    purchase_price = Column(Float, default=0.0)  # Cost price
    selling_price = Column(Float, nullable=False)  # Selling price
    stock_quantity = Column(Integer, default=0)
    category = Column(String(100), nullable=True)
    unit = Column(String(50), default="pcs")  # pcs, kg, ltr, etc.
    gst_rate = Column(Float, default=18.0)  # GST percentage (0, 5, 12, 18, 28)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    order_items = relationship("OrderItem", back_populates="product")
    return_items = relationship("Return", back_populates="product")


class Order(Base):
    """Sales/Bill model"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    bill_number = Column(String(50), unique=True, index=True, nullable=False)
    salesperson_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    
    subtotal = Column(Float, default=0.0)
    discount_percent = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    
    payment_mode = Column(String(20), default="cash")  # cash, upi, card
    payment_status = Column(String(20), default="paid")  # paid, pending, refunded
    status = Column(String(20), default="completed")  # pending, completed, verified, refunded
    
    is_gst = Column(Boolean, default=False)
    cgst = Column(Float, default=0.0)
    sgst = Column(Float, default=0.0)
    
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    verified_by = Column(Integer, nullable=True)

    # Relationships
    salesperson = relationship("User", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    returns = relationship("Return", back_populates="order")


class OrderItem(Base):
    """Order line items"""
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)  # Price at time of sale
    discount = Column(Float, default=0.0)
    total = Column(Float, nullable=False)

    # Relationships
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class Return(Base):
    """Return/Refund model with multi-step workflow"""
    __tablename__ = "returns"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    refund_amount = Column(Float, default=0.0)
    
    # Multi-step workflow status: pending_verification → verified → approved/rejected
    status = Column(String(30), default="pending_verification")
    
    # Step 1: Created by Sales Person
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Step 2: Stock verified by Inventory Person
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verification_notes = Column(Text, nullable=True)
    
    # Step 3: Approved/rejected by Accountant
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Relationships
    order = relationship("Order", back_populates="returns")
    product = relationship("Product", back_populates="return_items")


class CreditVoucher(Base):
    """Credit voucher model with 30-day validity"""
    __tablename__ = "credit_vouchers"

    id = Column(Integer, primary_key=True, index=True)
    voucher_code = Column(String(20), unique=True, nullable=False, index=True)
    return_id = Column(Integer, ForeignKey("returns.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    amount = Column(Float, nullable=False)
    
    # Issued by accountant
    issued_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # 30 days from issue
    
    # Redemption tracking
    is_redeemed = Column(Boolean, default=False)
    redeemed_at = Column(DateTime, nullable=True)
    redeemed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    redeemed_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """Audit logging for tracking changes"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(50), nullable=False)  # create, update, delete, login, logout
    table_name = Column(String(50), nullable=True)
    record_id = Column(Integer, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="audit_logs")


class Settings(Base):
    """System settings"""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
