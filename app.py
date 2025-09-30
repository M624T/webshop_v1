from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from markupsafe import Markup            # ✅ Flask 2.3+ da Markup shu yerdan olinadi
from flask_cors import CORS              # ✅ Flutter web bilan ishlash uchun
import sqlite3
import ollama
import random
import requests
from datetime import datetime
import uuid
from werkzeug.utils import secure_filename
import os
import re

app = Flask(__name__)
CORS(app)  # ✅ CORS ni yoqib qo'yamiz (Flutter web so'rovlariga ruxsat)
app.secret_key = 'secretkey123'
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_all_products_from_db():
    conn = sqlite3.connect("database/shop.db")  # ← Fayl nomini to‘g‘ri yozganingga ishonch hosil qil
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products ORDER BY id DESC")
    products = cursor.fetchall()
    conn.close()
    return products

def get_db_connection():
    conn = sqlite3.connect('database/shop.db')
    conn.row_factory = sqlite3.Row
    return conn

def normalize_cart(cart):
    """Convert cart to dictionary format if it's a list"""
    if isinstance(cart, list):
        return {str(pid): 1 for pid in cart}
    return cart

def render_description(raw_text):
    """
    Bazadagi description matnida {fayl.jpg} ko‘rinishidagi joylarni
    avtomatik <img> tegi bilan almashtiradi va <br> qo‘shadi.
    """

    # {fayl.jpg} ni <img> bilan almashtirish
    def replace_image(match):
        filename = match.group(1).strip()
        img_url = url_for('static', filename=f'images/{filename}')
        return f'<img src="{img_url}" alt="Rasm" style="max-width:100%;height:auto;">'

    # 1) Avval rasmlar
    html = re.sub(r'\{([^}]+)\}', replace_image, raw_text)

    # 2) Qator bo‘linishlarini saqlash (ixtiyoriy)
    html = html.replace('\n', '<br>')

    return Markup(html)   # Markup HTML ni xavfsiz qabul qiladi

@app.route('/')
def index():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    recommended = random.sample(products, min(6, len(products)))
    return render_template('index.html', recommended=recommended)

@app.route('/product/<int:product_id>')
def product(product_id):
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    if product is None:
        return "Mahsulot topilmadi", 404
    return render_template('product.html', product=product)

@app.route('/cart')
def cart():
    cart = normalize_cart(session.get('cart', {}))
    conn = get_db_connection()
    products = []
    for pid, quantity in cart.items():
        product = conn.execute('SELECT * FROM products WHERE id = ?', (int(pid),)).fetchone()
        if product:
            product = dict(product)
            product['quantity'] = quantity
            product['total_price'] = product['price'] * quantity
            products.append(product)
    conn.close()
    return render_template('cart.html', products=products)

@app.route('/reverse', methods=['GET'])
def reverse():
    import requests

    lat = request.args.get('lat')
    lon = request.args.get('lon')

    if not lat or not lon:
        return jsonify({'error': 'Koordinata topilmadi'}), 400

    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
        headers = {"User-Agent": "webshop/1.0"}  # 🔑 Nominatim uchun kerak
        r = requests.get(url, headers=headers, timeout=10)

        if r.status_code != 200:
            return jsonify({'error': f"Nominatim xatosi: {r.status_code}"}), 500

        # Agar bo‘sh javob bo‘lsa JSONDecodeError bo‘lmasligi uchun
        if not r.text.strip():
            return jsonify({'error': 'Bo‘sh javob keldi'}), 500

        data = r.json()
        address = data.get("display_name", "Manzil topilmadi")
        return jsonify({'address': address})

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f"So‘rov xatosi: {e}"}), 500
    except ValueError as e:
        return jsonify({'error': f"JSON xatosi: {e}"}), 500


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = normalize_cart(session.get("cart", {}))
    conn = get_db_connection()
    products, total = [], 0

    # Savatni hisoblash
    for pid, quantity in cart.items():
        product = conn.execute("SELECT * FROM products WHERE id = ?", (int(pid),)).fetchone()
        if product:
            product = dict(product)
            product["quantity"] = quantity
            product["total_price"] = product["price"] * quantity
            total += product["total_price"]
            products.append(product)

    # Buyurtma yuborish
    if request.method == "POST":
        name     = request.form["name"]
        phone    = request.form["phone"]
        address  = request.form["address"]   # foydalanuvchi o‘zi kiritadi
        location = request.form.get("location", "")  # faqat yashirin input

        product_list = ", ".join(
            [f"(#{p['id']} {p['name']} x {p['quantity']})" for p in products]
        )

        c = conn.cursor()
        c.execute(
            """
            INSERT INTO orders (name, phone, address, location, products, total_price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, phone, address, location, product_list, total)
        )
        order_id = c.lastrowid
        conn.commit()
        conn.close()

        session["cart"] = {}   # savatni tozalash
        return redirect(url_for("success", order_id=order_id))

    conn.close()
    return render_template("checkout.html", cart_items=products, total=total)

@app.route('/add-to-cart/<int:product_id>', methods=['GET', 'POST'])  # Mahsulotni savatga qo'shish uchun POST so'rovini kutayotgan yo'lni belgilaydi.
def add_to_cart(product_id):  # Mahsulotni savatga qo'shish funksiyasini belgilaydi.
    try:  # Har qanday istisnolarni ushlash uchun try blokini boshlaydi.
        quantity = int(request.form.get('quantity', 1))  # Formadan miqdorni olish, agar berilmasa 1 ga o'rnatish.
        cart = normalize_cart(session.get('cart', {}))  # Sessiyadan joriy savatni olish va uni lug'at formatiga normallashtirish.
        
        product_id_str = str(product_id)  # Mahsulot ID sini savatdagi kalit sifatida ishlatish uchun satrga aylantirish.
        cart[product_id_str] = cart.get(product_id_str, 0) + quantity  # Berilgan mahsulot ID uchun yangi miqdorni yangilash.

        session['cart'] = cart  # Yangilangan savatni sessiyaga saqlash.
        return redirect(url_for('cart'))  # Mahsulot qo'shilgandan so'ng foydalanuvchini savat sahifasiga yo'naltirish.
    except Exception as e:  # Jarayon davomida yuzaga keladigan har qanday istisnolarni ushlash.
        print(f"Error in add_to_cart: {str(e)}")  # Xatolik xabarini konsolga chiqarish.
        return redirect(url_for('product', product_id=product_id))  # Xatolik yuzaga kelganda mahsulot sahifasiga qaytish.

@app.route('/remove-from-cart/<int:product_id>')
def remove_from_cart(product_id):
    try:
        cart = normalize_cart(session.get('cart', {}))
        product_id_str = str(product_id)
        if product_id_str in cart:
            del cart[product_id_str]
            session['cart'] = cart
        return redirect(url_for('cart'))
    except Exception as e:
        print(f"Error in remove_from_cart: {str(e)}")
        return redirect(url_for('cart'))

@app.route('/update-cart/<int:product_id>')
def update_cart(product_id):
    try:
        action = request.args.get('action', 'inc')
        cart = normalize_cart(session.get('cart', {}))
        product_id_str = str(product_id)
        
        if action == 'inc':
            cart[product_id_str] = cart.get(product_id_str, 0) + 1
        else:  # dec
            current_qty = cart.get(product_id_str, 1)
            cart[product_id_str] = max(1, current_qty - 1)
        
        session['cart'] = cart
        return redirect(url_for('cart'))
    except Exception as e:
        print(f"Error in update_cart: {str(e)}")
        return redirect(url_for('cart'))

@app.route('/success/<int:order_id>')
def success(order_id):
    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()

    products = []
    if order and order['products']:
        # Mahsulotlar odatda '), (' bilan ajratilgan
        raw_items = re.split(r'\),\s*\(', order['products'])
        # Har birini qavsdan tozalaymiz
        products = [item.strip("() ").strip() for item in raw_items]

    return render_template('success.html', order=order, products=products)


@app.template_filter('first_image')
def first_image_filter(image_string):
    if image_string:
        return image_string.split(',')[0].strip()
    return 'default-product.jpg'

@app.route('/admin/add', methods=['GET', 'POST'])
def admin_add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = int(request.form['price'])
        description = request.form['description'].replace('\r\n', '\n')
        stock = int(request.form['stock'])

        # Frontenddan keladigan tartiblar
        product_order = request.form.get('image_order', '')
        desc_order    = request.form.get('desc_image_order', '')
        ordered_product = product_order.split(',') if product_order else []
        ordered_desc    = desc_order.split(',') if desc_order else []

        original_to_unique = {}

        # ✅ Umumiy saqlash funksiyasi
        def save_files(file_list):
            for file in file_list:
                if file and allowed_file(file.filename):
                    ext = os.path.splitext(file.filename)[1]
                    unique_filename = (
                        datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' +
                        uuid.uuid4().hex[:6] + ext
                    )
                    secure_name = secure_filename(unique_filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                    file.save(filepath)
                    original_to_unique[file.filename] = secure_name

        # Mahsulot rasmlari
        save_files(request.files.getlist('images'))
        # Tavsif rasmlari
        save_files(request.files.getlist('desc_images'))

        # ✅ Tartib bo‘yicha birlashtirish
        ordered_images = []
        for orig in ordered_product:
            if orig in original_to_unique:
                ordered_images.append(original_to_unique[orig])
        for orig in ordered_desc:
            if orig in original_to_unique:
                ordered_images.append(original_to_unique[orig])

        # ✅ Tavsif ichidagi {rasm.jpg} larni yangi nomlarga almashtirish
        for orig, unique in original_to_unique.items():
            description = description.replace(f'{{{orig}}}', f'{{{unique}}}')

        images_str = ','.join(ordered_images)

        # ✅ DB ga yozish
        conn = get_db_connection()
        conn.execute(
            'INSERT INTO products (name, price, description, stock, image) VALUES (?, ?, ?, ?, ?)',
            (name, price, description, stock, images_str)
        )
        conn.commit()
        conn.close()

        return redirect(url_for('index'))

    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin_add_product.html', products=products)

@app.route("/admin/edit/<int:product_id>", methods=["GET", "POST"])
def admin_edit_product(product_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        name = request.form['name']
        price = request.form['price']
        description = request.form['description']
        stock = request.form['stock']
        image_order = request.form.get('image_order', '')   # mavjud rasm tartibi
        # Yangi rasmlarni ham saqlashni qo‘shing
        # ...
        cur.execute("""
            UPDATE products
            SET name=?, price=?, description=?, stock=?, image=?
            WHERE id=?""",
            (name, price, description, stock, image_order, product_id)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("admin_add_product", product_id=product_id))

    cur.execute("SELECT * FROM products WHERE id=?", (product_id,))
    product = cur.fetchone()
    conn.close()
    return render_template("admin_edit_product.html", product=product)

@app.route('/admin/delete/<int:product_id>', methods=['POST'])
def admin_delete_product(product_id):
    conn = get_db_connection()
    
    # Mahsulotni olish
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if product:
        # Rasm nomlarini olish va o'chirish
        image_names = product['image'].split(',') if product['image'] else []
        for img_name in image_names:
            img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
            if os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except Exception as e:
                    print(f"Rasmni o'chirishda xato: {e}")
        
        # Bazadan mahsulotni o'chirish
        conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('admin_add_product'))

# ---------- API ROUTES (Flutter uchun) ----------
# @app.route('/api/products', methods=['GET'])
# def api_products():
#     conn = get_db_connection()
#     products = conn.execute('SELECT * FROM products').fetchall()
#     conn.close()
#     return jsonify([dict(p) for p in products])

# --- CHAT QISMI ---
@app.route('/chat')
def chat_ui():
    return render_template('chat.html')

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")
    conn = get_db_connection()
    cursor = conn.cursor()
    context_text = ""

    if "buyurtma" in user_message.lower():
        cursor.execute("SELECT * FROM orders")
        rows = cursor.fetchall()
        for r in rows:
            context_text += str(dict(r)) + "\n"

    elif "mahsulot" in user_message.lower():
        cursor.execute("SELECT * FROM products")
        rows = cursor.fetchall()
        for r in rows:
            context_text += str(dict(r)) + "\n"

    conn.close()

    prompt = f"""
    Siz onlayn do'kon operatorisiz. Faqat do'kon va mahsulotlar haqida gapiring.
    Savol: {user_message}
    Ma'lumot: {context_text or "Hech qanday ma'lumot topilmadi."}
    """

    response = ollama.chat(model="mistral", messages=[{"role": "user", "content": prompt}])

    if "message" in response:
        reply_text = response["message"]["content"]
    elif "messages" in response and response["messages"]:
        reply_text = response["messages"][-1]["content"]
    else:
        reply_text = "Javob olinmadi."

    return jsonify({"reply": reply_text})

# ---------- API ENDPOINTS ----------
@app.route('/api/products')
def api_products():
    base_url = request.host_url.rstrip('/')  # masalan: https://few-bats-enter.loca.lt
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()

    product_list = []
    for p in products:
        p_dict = dict(p)
        # Rasm nomlarini vergul bilan bo‘lib listga aylantirish
        filenames = [x.strip() for x in p_dict['image'].split(',') if x.strip()]
        # To‘liq URL yaratish
        p_dict['images'] = [f"{base_url}/static/images/{name}" for name in filenames]
        # Eski 'image' maydoni keraksiz bo‘lsa o‘chirib tashlash mumkin
        del p_dict['image']
        product_list.append(p_dict)

    return jsonify(product_list)

@app.route('/api/add-to-cart/<int:product_id>', methods=['POST'])
def api_add_to_cart(product_id):
    cart = normalize_cart(session.get('cart', {}))
    quantity = int(request.json.get('quantity', 1))
    cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
    session['cart'] = cart
    return jsonify({'cart': cart})

@app.route('/api/cart')
def api_cart():
    cart = normalize_cart(session.get('cart', {}))
    conn = get_db_connection()
    products = []
    total = 0
    for pid, qty in cart.items():
        product = conn.execute("SELECT * FROM products WHERE id = ?", (int(pid),)).fetchone()
        if product:
            p = dict(product)
            p['quantity'] = qty
            p['total_price'] = p['price'] * qty
            total += p['total_price']
            products.append(p)
    conn.close()
    return jsonify({'products': products, 'total': total})

@app.route('/api/checkout', methods=['POST'])
def api_checkout():
    data = request.json
    cart = normalize_cart(session.get('cart', {}))
    conn = get_db_connection()
    products, total = [], 0
    for pid, qty in cart.items():
        product = conn.execute("SELECT * FROM products WHERE id = ?", (int(pid),)).fetchone()
        if product:
            p = dict(product)
            p['quantity'] = qty
            p['total_price'] = p['price'] * qty
            total += p['total_price']
            products.append(p)
    # Buyurtmani saqlash
    c = conn.cursor()
    product_list = ", ".join([f"(#{p['id']} {p['name']} x {p['quantity']})" for p in products])
    c.execute("INSERT INTO orders (name, phone, address, location, products, total_price) VALUES (?, ?, ?, ?, ?, ?)",
              (data['name'], data['phone'], data['address'], data.get('location', ''), product_list, total))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    session['cart'] = {}
    return jsonify({'success': True, 'order_id': order_id})

@app.route('/api/reverse', methods=['GET'])
def api_reverse():
    import requests
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if not lat or not lon:
        return jsonify({'error': 'Koordinata topilmadi'}), 400
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
        headers = {"User-Agent": "webshop/1.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        address = data.get("display_name", "Manzil topilmadi")
        return jsonify({'address': address})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Chat endpoint ---
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message', '')
    # Ollama chat yoki boshqa logic
    reply_text = f"Siz yubordingiz: {user_message}"  # minimal javob
    return jsonify({'reply': reply_text})
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')