"""
Sales Billing Application - Main FastAPI Application
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

import database
import models
from utils.security import get_password_hash

# Load environment variables
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # Startup
    models.Base.metadata.create_all(bind=database.engine)
    
    db = database.SessionLocal()
    try:
        # Create default admin if not exists
        admin = db.query(models.User).filter(models.User.username == "admin").first()
        if not admin:
            admin = models.User(
                username="admin",
                hashed_password=get_password_hash("admin123"),
                name="Administrator",
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.commit()
        
        # Create demo users
        demo_users = [
            ("sales1", "sales123", "Sales User", "sales"),
            ("accountant", "acc123", "Accountant", "accounts"),
            ("stock", "stock123", "Stock Operator", "inventory"),
        ]
        for username, password, name, role in demo_users:
            if not db.query(models.User).filter(models.User.username == username).first():
                db.add(models.User(
                    username=username,
                    hashed_password=get_password_hash(password),
                    name=name,
                    role=role,
                    is_active=True
                ))
        db.commit()
    finally:
        db.close()
    
    yield  # Application running
    # Shutdown (nothing needed here)


# Create FastAPI app
app = FastAPI(
    title=os.getenv("APP_NAME", "Sales Billing System"),
    description="Desktop-based Sales Billing Application",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Mount static files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Include routers
from routers import auth, products, billing, returns, reports, admin, customers, vouchers

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(billing.router)
app.include_router(returns.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(customers.router)
app.include_router(vouchers.router)


# Template routes
@app.get("/")
async def root():
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard")
async def dashboard_redirect(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/sales")
async def sales_dashboard(request: Request):
    return templates.TemplateResponse("dashboard_sales.html", {"request": request})


@app.get("/accountant")
async def accountant_dashboard(request: Request):
    return templates.TemplateResponse("dashboard_accountant.html", {"request": request})


@app.get("/stock")
async def stock_dashboard(request: Request):
    return templates.TemplateResponse("dashboard_stock.html", {"request": request})


@app.get("/admin")
async def admin_dashboard(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/reports")
async def reports_page(request: Request):
    return templates.TemplateResponse("reports.html", {"request": request})


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
