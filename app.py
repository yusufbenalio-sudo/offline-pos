\"""
Offline POS (Point of Sale) System
Supports offline transactions with sync when online
"""

from flask import Flask, request, jsonify, render_template
import sqlite3
import json
import os
from datetime import datetime

app = Flask(__name__)
DB_PATH = "pos.db"

def init_db():
    """Initialize database with tables"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Products table
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        barcode TEXT UNIQUE,
        price REAL NOT NULL,
        cost REAL DEFAULT 0,
        stock INTEGER DEFAULT 0,
        category TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT UNIQUE,
        total_amount REAL NOT NULL,
        payment_method TEXT NOT NULL,
        amount_paid REAL NOT NULL,
        change_given REAL DEFAULT 0,
        status TEXT DEFAULT 'completed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Transaction items
    c.execute('''CREATE TABLE IF NOT EXISTS transaction_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    )''')
    
    # Daily sales summary
    c.execute('''CREATE TABLE IF NOT EXISTS daily_sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE,
        total_sales REAL DEFAULT 0,
        transaction_count INTEGER DEFAULT 0,
        cash_total REAL DEFAULT 0,
        card_total REAL DEFAULT 0,
        mobile_money_total REAL DEFAULT 0
    )''')
    
    conn.commit()
    conn.close()

def generate_transaction_id():
    """Generate unique transaction ID"""
    import random
    return f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}"

# Initialize database
init_db()

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Serve the POS interface"""
    return render_template('index.html')

# ==================== PRODUCTS ====================

@app.route('/api/products', methods=['GET', 'POST'])
def manage_products():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute("SELECT * FROM products ORDER BY name")
        products = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(products)
    
    if request.method == 'POST':
        data = request.json
        c.execute('''INSERT INTO products (name, barcode, price, cost, stock, category)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (data['name'], data.get('barcode'), data['price'], 
                   data.get('cost', 0), data.get('stock', 0), data.get('category')))
        conn.commit()
        product_id = c.lastrowrowid
        conn.close()
        return jsonify({"id": product_id, "message": "Product added"})

@app.route('/api/products/<int:product_id>', methods=['PUT', 'DELETE'])
def product_detail(product_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if request.method == 'PUT':
        data = request.json
        c.execute('''UPDATE products SET name=?, barcode=?, price=?, cost=?, stock=?, category=?
                     WHERE id=?''',
                  (data['name'], data.get('barcode'), data['price'],
                   data.get('cost', 0), data.get('stock', 0), data.get('category'), product_id))
        conn.commit()
        conn.close()
        return jsonify({"message": "Product updated"})
    
    if request.method == 'DELETE':
        c.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Product deleted"})

# ==================== SALES / CHECKOUT ====================

@app.route('/api/checkout', methods=['POST'])
def checkout():
    """Process a sale transaction"""
    data = request.json
    cart = data.get('cart', [])
    payment_method = data.get('payment_method', 'cash')
    amount_paid = data.get('amount_paid', 0)
    
    if not cart:
        return jsonify({"error": "Cart is empty"}), 400
    
    # Calculate total
    total = sum(item['quantity'] * item['price'] for item in cart)
    
    # Calculate change
    change = amount_paid - total if amount_paid >= total else 0
    
    if amount_paid < total:
        return jsonify({"error": "Insufficient payment"}), 400
    
    transaction_id = generate_transaction_id()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create transaction
    c.execute('''INSERT INTO transactions (transaction_id, total_amount, payment_method, amount_paid, change_given)
                 VALUES (?, ?, ?, ?, ?)''',
              (transaction_id, total, payment_method, amount_paid, change))
    
    # Add transaction items & update stock
    for item in cart:
        c.execute('''INSERT INTO transaction_items (transaction_id, product_id, product_name, quantity, unit_price, subtotal)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (transaction_id, item['id'], item['name'], item['quantity'], item['price'], 
                   item['quantity'] * item['price']))
        
        # Update stock
        c.execute("UPDATE products SET stock = stock - ? WHERE id = ?", 
                  (item['quantity'], item['id']))
    
    # Update daily sales
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute('''INSERT INTO daily_sales (date, total_sales, transaction_count, cash_total, card_total, mobile_money_total)
                 VALUES (?, ?, 1, ?, ?, ?)
                 ON CONFLICT(date) DO UPDATE SET
                 total_sales = total_sales + excluded.total_sales,
                 transaction_count = transaction_count + 1,
                 cash_total = cash_total + excluded.cash_total,
                 card_total = card_total + excluded.card_total,
                 mobile_money_total = mobile_money_total + excluded.mobile_money_total''',
              (today, total, 
               total if payment_method == 'cash' else 0,
               total if payment_method == 'card' else 0,
               total if payment_method == 'mobile_money' else 0))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "transaction_id": transaction_id,
        "total": total,
        "amount_paid": amount_paid,
        "change": change,
        "payment_method": payment_method
    })

# ==================== TRANSACTIONS ====================

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM transactions ORDER BY created_at DESC LIMIT 100")
    transactions = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(transactions)

@app.route('/api/transactions/<transaction_id>', methods=['GET'])
def get_transaction_detail(transaction_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
    transaction = c.fetchone()
    
    if not transaction:
        conn.close()
        return jsonify({"error": "Transaction not found"}), 404
    
    c.execute("SELECT * FROM transaction_items WHERE transaction_id = ?", (transaction_id,))
    items = [dict(row) for row in c.fetchall()]
    
    conn.close()
    return jsonify({
        "transaction": dict(transaction),
        "items": items
    })

# ==================== REPORTS ====================

@app.route('/api/reports/daily', methods=['GET'])
def daily_report():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM daily_sales WHERE date = ?", (date,))
    report = c.fetchone()
    
    if not report:
        conn.close()
        return jsonify({"date": date, "total_sales": 0, "transaction_count": 0})
    
    conn.close()
    return jsonify(dict(report))

@app.route('/api/reports/sales', methods=['GET'])
def sales_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if start_date and end_date:
        c.execute("SELECT * FROM daily_sales WHERE date BETWEEN ? AND ? ORDER BY date DESC", 
                  (start_date, end_date))
    else:
        c.execute("SELECT * FROM daily_sales ORDER BY date DESC LIMIT 30")
    
    reports = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(reports)

# ==================== DASHBOARD ====================

@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Today's sales
    c.execute("SELECT total_sales, transaction_count FROM daily_sales WHERE date = ?", (today,))
    today_data = c.fetchone()
    today_sales = today_data[0] if today_data else 0
    today_transactions = today_data[1] if today_data else 0
    
    # Total products
    c.execute("SELECT COUNT(*), SUM(stock) FROM products")
    products_data = c.fetchone()
    total_products = products_data[0]
    total_stock = products_data[1] or 0
    
    # Low stock alerts
    c.execute("SELECT * FROM products WHERE stock < 10 ORDER BY stock LIMIT 5")
    low_stock = [dict(zip([col[0] for col in c.description], row)) for row in c.fetchall()]
    
    conn.close()
    
    return jsonify({
        "today_sales": today_sales,
        "today_transactions": today_transactions,
        "total_products": total_products,
        "total_stock": total_stock,
        "low_stock": low_stock
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)