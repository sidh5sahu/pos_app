"""Bill number generation and printing utilities"""
import os
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from dotenv import load_dotenv

load_dotenv()


def generate_bill_number() -> str:
    """Generate a unique bill number in format: BILL-YYYYMMDD-XXXXXX"""
    date_str = datetime.now().strftime("%Y%m%d")
    timestamp = datetime.now().strftime("%H%M%S")
    return f"BILL-{date_str}-{timestamp}"


def generate_bill_pdf(order_data: dict) -> BytesIO:
    """
    Generate a PDF bill for an order.
    
    Args:
        order_data: Dictionary containing:
            - bill_number: str
            - date: str
            - customer_name: str (optional)
            - items: list of {product_name, quantity, unit_price, total}
            - subtotal: float
            - discount: float
            - total: float
            - payment_mode: str
            - salesperson: str
    
    Returns:
        BytesIO buffer containing PDF
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    
    # Company info from environment
    company_name = os.getenv("COMPANY_NAME", "Sales Billing System")
    company_address = os.getenv("COMPANY_ADDRESS", "")
    company_phone = os.getenv("COMPANY_PHONE", "")
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        alignment=1,
        spaceAfter=6
    )
    elements.append(Paragraph(company_name, title_style))
    
    if company_address:
        elements.append(Paragraph(company_address, ParagraphStyle('Address', alignment=1, fontSize=10)))
    if company_phone:
        elements.append(Paragraph(f"Phone: {company_phone}", ParagraphStyle('Phone', alignment=1, fontSize=10)))
    
    elements.append(Spacer(1, 20))
    
    # Bill Info
    bill_info = [
        ["Bill No:", order_data.get("bill_number", "")],
        ["Date:", order_data.get("date", datetime.now().strftime("%d-%m-%Y %H:%M"))],
        ["Customer:", order_data.get("customer_name", "Walk-in Customer")],
        ["Payment:", order_data.get("payment_mode", "Cash").upper()],
    ]
    
    bill_table = Table(bill_info, colWidths=[80, 200])
    bill_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(bill_table)
    elements.append(Spacer(1, 20))
    
    # Items Table
    items_data = [["#", "Product", "Qty", "Price", "Total"]]
    for i, item in enumerate(order_data.get("items", []), 1):
        items_data.append([
            str(i),
            item.get("product_name", ""),
            str(item.get("quantity", 0)),
            f"Rs.{item.get('unit_price', 0):.2f}",
            f"Rs.{item.get('total', 0):.2f}"
        ])
    
    items_table = Table(items_data, colWidths=[30, 250, 50, 80, 80])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 20))
    
    # Totals
    totals_data = [
        ["Subtotal:", f"Rs.{order_data.get('subtotal', 0):.2f}"],
        ["Discount:", f"Rs.{order_data.get('discount', 0):.2f}"],
        ["Grand Total:", f"Rs.{order_data.get('total', 0):.2f}"],
    ]
    
    totals_table = Table(totals_data, colWidths=[400, 90])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 30))
    
    # Footer
    footer_style = ParagraphStyle('Footer', alignment=1, fontSize=10)
    elements.append(Paragraph("Thank you for your purchase!", footer_style))
    elements.append(Paragraph(f"Served by: {order_data.get('salesperson', '')}", footer_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_thermal_receipt(order_data: dict) -> str:
    """
    Generate thermal receipt text format (58mm or 80mm).
    
    Returns formatted text string for thermal printer.
    """
    company_name = os.getenv("COMPANY_NAME", "Sales Billing System")
    company_phone = os.getenv("COMPANY_PHONE", "")
    
    lines = []
    width = 32  # Characters for 58mm thermal
    
    # Header
    lines.append("=" * width)
    lines.append(company_name.center(width))
    if company_phone:
        lines.append(f"Ph: {company_phone}".center(width))
    lines.append("=" * width)
    
    # Bill Info
    lines.append(f"Bill: {order_data.get('bill_number', '')}")
    lines.append(f"Date: {order_data.get('date', datetime.now().strftime('%d-%m-%Y %H:%M'))}")
    lines.append(f"Customer: {order_data.get('customer_name', 'Walk-in')[:20]}")
    lines.append("-" * width)
    
    # Items
    lines.append("Item           Qty   Price  Total")
    lines.append("-" * width)
    
    for item in order_data.get("items", []):
        name = item.get("product_name", "")[:14]
        qty = str(item.get("quantity", 0))
        price = f"{item.get('unit_price', 0):.0f}"
        total = f"{item.get('total', 0):.0f}"
        lines.append(f"{name:<14} {qty:>3} {price:>6} {total:>6}")
    
    lines.append("-" * width)
    
    # Totals
    lines.append(f"{'Subtotal:':>22} {order_data.get('subtotal', 0):>8.2f}")
    if order_data.get('discount', 0) > 0:
        lines.append(f"{'Discount:':>22} {order_data.get('discount', 0):>8.2f}")
    lines.append(f"{'TOTAL:':>22} {order_data.get('total', 0):>8.2f}")
    lines.append(f"{'Payment:':>22} {order_data.get('payment_mode', 'Cash').upper():>8}")
    
    lines.append("=" * width)
    lines.append("Thank you!".center(width))
    lines.append(f"Served by: {order_data.get('salesperson', '')}".center(width))
    lines.append("\n\n\n")  # Feed lines for cutting
    
    return "\n".join(lines)
