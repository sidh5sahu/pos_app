let products = [];
let today = new Date().toISOString().split('T')[0];
document.getElementById('inv-date').value = today;

function generateInvoiceNumber() {
    const prefix = 'INV-';
    const randomNum = Math.floor(1000 + Math.random() * 9000);
    document.getElementById('inv-no').value = prefix + randomNum;
    updateInvoice();
}

function addProduct() {
    products.push({
        id: Date.now(),
        name: '',
        qty: 1,
        price: 0
    });
    renderProductList();
    updateInvoice();
}

function removeProduct(id) {
    products = products.filter(p => p.id !== id);
    renderProductList();
    updateInvoice();
}

function updateProduct(id, field, value) {
    const product = products.find(p => p.id === id);
    if (product) {
        if (field === 'qty' || field === 'price') {
            product[field] = parseFloat(value) || 0;
        } else {
            product[field] = value;
        }
    }
    updateInvoice();
}

function renderProductList() {
    const container = document.getElementById('product-list');
    container.innerHTML = '';
    
    products.forEach((p, index) => {
        const div = document.createElement('div');
        div.className = 'product-card';
        div.innerHTML = `
            <button class="remove-btn" onclick="removeProduct(${p.id})" title="Remove Item"><i class="ph ph-trash"></i></button>
            <div class="input-group" style="margin-bottom: 8px;">
                <label>Item Description <span style="color:var(--danger)">*</span></label>
                <input type="text" value="${p.name}" oninput="updateProduct(${p.id}, 'name', this.value)" placeholder="Product Name">
            </div>
            <div class="grid-2">
                <div class="input-group">
                    <label>Qty</label>
                    <input type="number" min="1" value="${p.qty}" oninput="updateProduct(${p.id}, 'qty', this.value)">
                </div>
                <div class="input-group">
                    <label>Rate (₹)</label>
                    <input type="number" min="0" value="${p.price}" oninput="updateProduct(${p.id}, 'price', this.value)">
                </div>
            </div>
        `;
        container.appendChild(div);
    });
}

// Convert Number to Indian Rupees Words
function numberToWords(num) {
    if (num === 0) return 'Zero Rupees Only';
    const a = ['', 'One ', 'Two ', 'Three ', 'Four ', 'Five ', 'Six ', 'Seven ', 'Eight ', 'Nine ', 'Ten ', 'Eleven ', 'Twelve ', 'Thirteen ', 'Fourteen ', 'Fifteen ', 'Sixteen ', 'Seventeen ', 'Eighteen ', 'Nineteen '];
    const b = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];
    
    function inWords(n) {
        if ((n = n.toString()).length > 9) return 'overflow';
        let nArray = ('000000000' + n).substr(-9).match(/^(\d{2})(\d{2})(\d{2})(\d{1})(\d{2})$/);
        if (!nArray) return;
        let str = '';
        str += (nArray[1] != 0) ? (a[Number(nArray[1])] || b[nArray[1][0]] + ' ' + (nArray[1][1] != 0 ? a[nArray[1][1]] : '')) + 'Crore ' : '';
        str += (nArray[2] != 0) ? (a[Number(nArray[2])] || b[nArray[2][0]] + ' ' + (nArray[2][1] != 0 ? a[nArray[2][1]] : '')) + 'Lakh ' : '';
        str += (nArray[3] != 0) ? (a[Number(nArray[3])] || b[nArray[3][0]] + ' ' + (nArray[3][1] != 0 ? a[nArray[3][1]] : '')) + 'Thousand ' : '';
        str += (nArray[4] != 0) ? (a[Number(nArray[4])] || b[nArray[4][0]] + ' ' + (nArray[4][1] != 0 ? a[nArray[4][1]] : '')) + 'Hundred ' : '';
        str += (nArray[5] != 0) ? ((str != '') ? 'and ' : '') + (a[Number(nArray[5])] || b[nArray[5][0]] + ' ' + (nArray[5][1] != 0 ? a[nArray[5][1]] : '')) : '';
        return str.trim();
    }
    return inWords(Math.round(num)) + ' Rupees Only';
}

function formatCurrency(val) {
    return '₹' + val.toFixed(2);
}

function updateInvoice() {
    // Top Info
    const bName = document.getElementById('b-name').value || 'YOUR COMPANY NAME';
    document.getElementById('out-b-name').innerText = bName;
    document.getElementById('out-sign-name').innerText = bName;
    
    document.getElementById('out-b-address').innerText = document.getElementById('b-address').value || 'Company Address Area, City, State - Pincode';
    document.getElementById('out-b-contact').innerText = document.getElementById('b-contact').value || 'N/A';

    document.getElementById('out-c-name').innerText = document.getElementById('c-name').value || 'Customer Name';
    document.getElementById('out-c-address').innerText = document.getElementById('c-address').value || 'Customer Address Area, City';

    document.getElementById('out-inv-no').innerText = document.getElementById('inv-no').value || 'N/A';
    
    const dateVal = document.getElementById('inv-date').value;
    if(dateVal) {
        const parts = dateVal.split('-');
        document.getElementById('out-inv-date').innerText = `${parts[2]}/${parts[1]}/${parts[0]}`;
    } else {
        document.getElementById('out-inv-date').innerText = 'N/A';
    }

    document.getElementById('out-inv-payment').innerText = document.getElementById('inv-payment').value || 'Cash';

    // Calculate Items
    const tbody = document.getElementById('out-items-body');
    tbody.innerHTML = '';
    
    let subtotal = 0;

    if (products.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 20px;">No items added.</td></tr>';
    } else {
        products.forEach((p, index) => {
            const lineTotal = p.qty * p.price;
            subtotal += lineTotal;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${index + 1}</td>
                <td>${p.name || '-'}</td>
                <td>${p.qty}</td>
                <td>${p.price.toFixed(2)}</td>
                <td>${lineTotal.toFixed(2)}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    const calculatedGrandTotal = subtotal;
    const roundOffGrandTotal = Math.round(calculatedGrandTotal);
    const roundOffAmount = roundOffGrandTotal - calculatedGrandTotal;

    document.getElementById('out-subtotal').innerText = formatCurrency(subtotal);
    document.getElementById('out-roundoff').innerText = formatCurrency(roundOffAmount);
    document.getElementById('out-grandtotal').innerText = formatCurrency(roundOffGrandTotal);

    document.getElementById('out-words').innerText = numberToWords(roundOffGrandTotal);
}

function downloadPDF() {
    const invoiceElement = document.getElementById('invoice-preview');
    const invNo = document.getElementById('inv-no').value || '001';
    
    const opt = {
        margin:       0,
        filename:     `Invoice_${invNo}.pdf`,
        image:        { type: 'jpeg', quality: 0.98 },
        html2canvas:  { scale: 2, useCORS: true },
        jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };
    
    html2pdf().set(opt).from(invoiceElement).save();
}

// Init
generateInvoiceNumber();
addProduct(); // Add one default product row
