let cart = [];
let products = [];

async function loadProducts() {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = '/login';
        return;
    }

    try {
        const response = await fetch('/api/products', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.status === 401) {
            window.location.href = '/login';
            return;
        }
        products = await response.json();
        renderProducts();
    } catch (error) {
        console.error('Error loading products:', error);
    }
}

function renderProducts() {
    const grid = document.getElementById('products-grid');
    if (!grid) return;

    grid.innerHTML = products.map(product => `
        <div class="product-card" onclick="addToCart(${product.id})">
            <div class="product-name">${product.name}</div>
            <div class="product-sku">SKU: ${product.sku}</div>
            <div class="product-price">$${product.price.toFixed(2)}</div>
            <div class="product-stock">Stock: ${product.stock}</div>
        </div>
    `).join('');
}

function addToCart(productId) {
    const product = products.find(p => p.id === productId);
    if (!product || product.stock <= 0) {
        alert('Product out of stock!');
        return;
    }

    const existingItem = cart.find(item => item.product_id === productId);
    if (existingItem) {
        if (existingItem.quantity < product.stock) {
            existingItem.quantity++;
        } else {
            alert('Not enough stock!');
        }
    } else {
        cart.push({
            product_id: productId,
            name: product.name,
            price: product.price,
            quantity: 1
        });
    }
    renderCart();
}

function removeFromCart(productId) {
    cart = cart.filter(item => item.product_id !== productId);
    renderCart();
}

function renderCart() {
    const cartContainer = document.getElementById('cart-items');
    const totalEl = document.getElementById('total-amount');

    if (!cartContainer) return;

    let total = 0;
    cartContainer.innerHTML = cart.map(item => {
        total += item.price * item.quantity;
        return `
            <div class="cart-item">
                <div>
                    <div>${item.name}</div>
                    <small>$${item.price} x ${item.quantity}</small>
                </div>
                <button onclick="removeFromCart(${item.product_id})" style="color: red; border: none; background: none; cursor: pointer;">&times;</button>
            </div>
        `;
    }).join('');

    totalEl.textContent = total.toFixed(2);
}

async function checkout() {
    if (cart.length === 0) return;
    const token = localStorage.getItem('token');

    try {
        const response = await fetch('/api/orders', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                items: cart.map(item => ({
                    product_id: item.product_id,
                    quantity: item.quantity
                }))
            })
        });

        if (response.ok) {
            alert('Order placed successfully!');
            cart = [];
            renderCart();
            loadProducts(); // Refresh stock
        } else {
            const error = await response.json();
            alert('Error: ' + error.detail);
        }
    } catch (error) {
        console.error('Checkout error:', error);
        alert('Checkout failed');
    }
}

async function addProduct(event) {
    event.preventDefault();
    const token = localStorage.getItem('token');
    const form = event.target;
    const data = {
        name: form.name.value,
        sku: form.sku.value,
        price: parseFloat(form.price.value),
        cost_price: parseFloat(form.cost_price.value),
        stock: parseInt(form.stock.value)
    };

    try {
        const response = await fetch('/api/products', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            alert('Product added!');
            form.reset();
        } else {
            const err = await response.json();
            alert('Failed to add product: ' + (err.detail || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error:', error);
    }
}
