"""Reports router for generating sales reports"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, timedelta

import database
import models
from utils.security import get_current_active_user, require_accounts, require_admin_or_accounts

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/daily")
async def daily_sales_report(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(database.get_db)
):
    """Get daily sales report"""
    if date:
        try:
            report_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        report_date = datetime.utcnow().date()
    
    start_of_day = datetime.combine(report_date, datetime.min.time())
    end_of_day = datetime.combine(report_date, datetime.max.time())
    
    # Get orders for the day
    orders = db.query(models.Order).filter(
        models.Order.created_at >= start_of_day,
        models.Order.created_at <= end_of_day
    ).all()
    
    # Calculate summary
    total_orders = len(orders)
    total_sales = sum(o.total_amount for o in orders if o.status != "refunded")
    total_refunds = sum(o.total_amount for o in orders if o.status == "refunded")
    
    # Payment mode breakdown
    cash_sales = sum(o.total_amount for o in orders if o.payment_mode == "cash" and o.status != "refunded")
    upi_sales = sum(o.total_amount for o in orders if o.payment_mode == "upi" and o.status != "refunded")
    card_sales = sum(o.total_amount for o in orders if o.payment_mode == "card" and o.status != "refunded")
    
    # Top products
    product_sales = {}
    for order in orders:
        if order.status != "refunded":
            for item in order.items:
                if item.product_id not in product_sales:
                    product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
                    product_sales[item.product_id] = {
                        "product_name": product.product_name if product else "Unknown",
                        "quantity": 0,
                        "total": 0
                    }
                product_sales[item.product_id]["quantity"] += item.quantity
                product_sales[item.product_id]["total"] += item.total
    
    top_products = sorted(product_sales.values(), key=lambda x: x["total"], reverse=True)[:10]
    
    return {
        "date": report_date.isoformat(),
        "summary": {
            "total_orders": total_orders,
            "total_sales": round(total_sales, 2),
            "total_refunds": round(total_refunds, 2),
            "net_sales": round(total_sales - total_refunds, 2)
        },
        "payment_breakdown": {
            "cash": round(cash_sales, 2),
            "upi": round(upi_sales, 2),
            "card": round(card_sales, 2)
        },
        "top_products": top_products
    }


@router.get("/monthly")
async def monthly_sales_report(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_user: models.User = Depends(require_admin_or_accounts),
    db: Session = Depends(database.get_db)
):
    """Get monthly sales report"""
    from calendar import monthrange
    
    start_date = datetime(year, month, 1)
    _, last_day = monthrange(year, month)
    end_date = datetime(year, month, last_day, 23, 59, 59)
    
    # Get all orders for the month
    orders = db.query(models.Order).filter(
        models.Order.created_at >= start_date,
        models.Order.created_at <= end_date
    ).all()
    
    # Daily breakdown
    daily_sales = {}
    for order in orders:
        if order.status != "refunded":
            day = order.created_at.date().isoformat()
            if day not in daily_sales:
                daily_sales[day] = {"orders": 0, "total": 0}
            daily_sales[day]["orders"] += 1
            daily_sales[day]["total"] += order.total_amount
    
    # Summary
    total_orders = len([o for o in orders if o.status != "refunded"])
    total_sales = sum(o.total_amount for o in orders if o.status != "refunded")
    total_refunds = sum(o.total_amount for o in orders if o.status == "refunded")
    
    # Get returns for the month
    returns = db.query(models.Return).filter(
        models.Return.created_at >= start_date,
        models.Return.created_at <= end_date,
        models.Return.status == "approved"
    ).all()
    total_return_amount = sum(r.refund_amount for r in returns)
    
    return {
        "year": year,
        "month": month,
        "summary": {
            "total_orders": total_orders,
            "total_sales": round(total_sales, 2),
            "total_refunds": round(total_refunds, 2),
            "return_amount": round(total_return_amount, 2),
            "net_sales": round(total_sales - total_return_amount, 2),
            "average_order_value": round(total_sales / total_orders, 2) if total_orders > 0 else 0
        },
        "daily_breakdown": [
            {"date": k, **v} for k, v in sorted(daily_sales.items())
        ]
    }


@router.get("/returns")
async def returns_report(
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    current_user: models.User = Depends(require_accounts),
    db: Session = Depends(database.get_db)
):
    """Get returns report"""
    query = db.query(models.Return)
    
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(models.Return.created_at >= start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")
    
    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d")
            end_date = datetime.combine(end_date.date(), datetime.max.time())
            query = query.filter(models.Return.created_at <= end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")
    
    returns = query.all()
    
    # Aggregate by status
    pending = [r for r in returns if r.status == "pending"]
    approved = [r for r in returns if r.status == "approved"]
    rejected = [r for r in returns if r.status == "rejected"]
    
    # Build details list
    details = []
    for r in returns:
        product = db.query(models.Product).filter(models.Product.id == r.product_id).first()
        order = db.query(models.Order).filter(models.Order.id == r.order_id).first()
        details.append({
            "id": r.id,
            "bill_number": order.bill_number if order else None,
            "product_name": product.product_name if product else "Unknown",
            "quantity": r.quantity,
            "refund_amount": r.refund_amount,
            "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at.isoformat()
        })
    
    return {
        "summary": {
            "total_returns": len(returns),
            "pending": len(pending),
            "approved": len(approved),
            "rejected": len(rejected),
            "total_refund_amount": round(sum(r.refund_amount for r in approved), 2)
        },
        "returns": details
    }


@router.get("/profit-loss")
async def profit_loss_report(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: models.User = Depends(require_admin_or_accounts),
    db: Session = Depends(database.get_db)
):
    """Get profit/loss report"""
    query = db.query(models.Order).filter(models.Order.status != "refunded")
    
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(models.Order.created_at >= start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")
    
    if date_to:
        try:
            end_date = datetime.strptime(date_to, "%Y-%m-%d")
            end_date = datetime.combine(end_date.date(), datetime.max.time())
            query = query.filter(models.Order.created_at <= end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")
    
    orders = query.all()
    
    total_revenue = 0
    total_cost = 0
    
    for order in orders:
        total_revenue += order.total_amount
        for item in order.items:
            product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
            if product:
                total_cost += product.purchase_price * item.quantity
    
    gross_profit = total_revenue - total_cost
    profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    return {
        "period": {
            "from": date_from,
            "to": date_to
        },
        "summary": {
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "gross_profit": round(gross_profit, 2),
            "profit_margin_percent": round(profit_margin, 2)
        }
    }
