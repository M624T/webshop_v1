# ==============================================================================
# ONLINE DO'KON - E-COMMERCE WEB APPLICATION
# ==============================================================================

# ------------------------------------------------------------------------------
# IMPORT QISMI - Kerakli kutubxonalar
# ------------------------------------------------------------------------------

# Flask va asosiy extensionlar
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, send_file, abort
)
from flask_cors import CORS
from markupsafe import Markup
from werkzeug.utils import secure_filename

# Standart Python kutubxonalari
import os
import re
import uuid
import random
import sqlite3
import requests
from io import BytesIO
from datetime import datetime

# PDF va QR kod uchun kutubxonalar
import ollama
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth


# ==============================================================================
# ILOVANI SOZLASH - Configuration
# ==============================================================================

app = Flask(__name__)
CORS(app)  # CORS - boshqa domenlardan so'rovlarga ruxsat
app.secret_key = 'secretkey123'

# Fayl yuklash sozlamalari
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm', 'mkv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# PDF uchun fontlarni ro'yxatdan o'tkazish
FONT_DIR = os.path.join(app.root_path, 'static', 'fonts')
FONT_FILES = {
    'DejaVuSans': os.path.join(FONT_DIR, 'DejaVuSans.ttf'),
    'NotoSans': os.path.join(FONT_DIR, 'NotoSans-Regular.ttf')
}

REGISTERED_FONTS = {}
for short, path in FONT_FILES.items():
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont(short, path))
            REGISTERED_FONTS[short] = path
        except Exception as e:
            print(f"Font register error: {short}, {e}")


# ==============================================================================
# DATABASE FUNKSIYALARI
# ==============================================================================

def get_db_connection():
    """Ma'lumotlar bazasiga ulanish"""
    conn = sqlite3.connect('database/shop.db')
    conn.row_factory = sqlite3.Row
    return conn


def get_all_products_from_db():
    """Barcha mahsulotlarni olish"""
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
    conn.close()
    return products


def ensure_products_videos_column():
    """'products' jadvaliga 'videos' ustuni qo'shish (agar yo'q bo'lsa)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(products)")
        cols = [r[1] for r in cur.fetchall()]
        if 'videos' not in cols:
            cur.execute("ALTER TABLE products ADD COLUMN videos TEXT DEFAULT ''")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Schema migration (videos) failed: {e}")


# ==============================================================================
# YORDAMCHI FUNKSIYALAR - Utility Functions
# ==============================================================================

def allowed_file(filename):
    """Rasm fayli to'g'ri formatda ekanligini tekshirish"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_video(filename):
    """Video fayli to'g'ri formatda ekanligini tekshirish"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


def normalize_cart(cart):
    """Savatni dictionary formatiga o'zgartirish"""
    if isinstance(cart, list):
        return {str(pid): 1 for pid in cart}
    return cart


def render_description(raw_text):
    """
    Tavsif matnidagi {fayl.jpg} larni <img> tegiga aylantirish
    va qator bo'linishlarini <br> bilan almashtirish
    """
    def replace_image(match):
        filename = match.group(1).strip()
        img_url = url_for('static', filename=f'images/{filename}')
        return f'<img src="{img_url}" alt="Rasm" style="max-width:100%;height:auto;">'
    
    html = re.sub(r'\{([^}]+)\}', replace_image, raw_text)
    html = html.replace('\n', '<br>')
    return Markup(html)


# ==============================================================================
# ASOSIY SAHIFALAR - Customer Pages
# ==============================================================================

@app.route('/')
def index():
    """Bosh sahifa - tavsiya etilgan mahsulotlar bilan"""
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    recommended = random.sample(products, min(6, len(products)))
    return render_template('index.html', recommended=recommended)


@app.route('/products')
def products_list():
    """Mahsulotlar ro'yxati - sahifalash bilan"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 24))
        page = max(1, page)
        per_page = max(1, min(per_page, 60))
    except ValueError:
        page, per_page = 1, 24

    offset = (page - 1) * per_page
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM products')
    total_products = cur.fetchone()[0]
    cur.execute('SELECT * FROM products ORDER BY id DESC LIMIT ? OFFSET ?', (per_page, offset))
    rows = cur.fetchall()
    conn.close()

    total_pages = (total_products + per_page - 1) // per_page if per_page else 1
    return render_template(
        'products.html',
        products=rows,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_products=total_products
    )


@app.route('/product/<int:product_id>')
def product(product_id):
    """Mahsulot tafsilotlari sahifasi"""
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    
    if product is None:
        return "Mahsulot topilmadi", 404
    
    rendered_description = render_description(product['description']) if product and product['description'] else Markup("")
    return render_template('product.html', product=product, rendered_description=rendered_description)


# ==============================================================================
# SAVAT BOSHQARUVI - Cart Management
# ==============================================================================

@app.route('/cart')
def cart():
    """Savat sahifasi"""
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


@app.route('/add-to-cart/<int:product_id>', methods=['GET', 'POST'])
def add_to_cart(product_id):
    """Mahsulotni savatga qo'shish"""
    try:
        quantity = int(request.form.get('quantity', 1))
        cart = normalize_cart(session.get('cart', {}))
        
        product_id_str = str(product_id)
        cart[product_id_str] = cart.get(product_id_str, 0) + quantity
        
        session['cart'] = cart
        return redirect(url_for('cart'))
    except Exception as e:
        print(f"Error in add_to_cart: {str(e)}")
        return redirect(url_for('product', product_id=product_id))


@app.route('/remove-from-cart/<int:product_id>')
def remove_from_cart(product_id):
    """Mahsulotni savatdan o'chirish"""
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
    """Savat miqdorini yangilash (oshirish/kamaytirish)"""
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


# ==============================================================================
# BUYURTMA VA TO'LOV - Checkout & Orders
# ==============================================================================

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """Buyurtmani rasmiylashtirish sahifasi"""
    cart = normalize_cart(session.get('cart', {}))
    conn = get_db_connection()
    products, total = [], 0
    
    # Savatdagi mahsulotlarni hisoblash
    for pid, quantity in cart.items():
        product = conn.execute('SELECT * FROM products WHERE id = ?', (int(pid),)).fetchone()
        if product:
            product = dict(product)
            product['quantity'] = quantity
            product['total_price'] = product['price'] * quantity
            total += product['total_price']
            products.append(product)
    
    # POST so'rov - buyurtmani saqlash
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        address = request.form['address']
        location = request.form.get('location', '')
        
        product_list = ', '.join(
            [f"(#{p['id']} {p['name']} x {p['quantity']})" for p in products]
        )
        
        c = conn.cursor()
        c.execute(
            '''INSERT INTO orders (name, phone, address, location, products, total_price)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (name, phone, address, location, product_list, total)
        )
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        
        session['cart'] = {}
        return redirect(url_for('success', order_id=order_id))
    
    conn.close()
    return render_template('checkout.html', cart_items=products, total=total)


@app.route('/reverse', methods=['GET'])
def reverse():
    """Koordinatalarni manzilga aylantirish (reverse geocoding)"""
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    
    if not lat or not lon:
        return jsonify({'error': 'Koordinata topilmadi'}), 400
    
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
        headers = {"User-Agent": "webshop/1.0"}
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code != 200:
            return jsonify({'error': f"Nominatim xatosi: {r.status_code}"}), 500
        
        if not r.text.strip():
            return jsonify({'error': 'Bo\'sh javob keldi'}), 500
        
        data = r.json()
        address = data.get("display_name", "Manzil topilmadi")
        return jsonify({'address': address})
    
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f"So'rov xatosi: {e}"}), 500
    except ValueError as e:
        return jsonify({'error': f"JSON xatosi: {e}"}), 500


@app.route('/success/<int:order_id>')
def success(order_id):
    """Buyurtma muvaffaqiyatli sahifasi"""
    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()
    
    products = []
    if order and order['products']:
        raw_items = re.split(r'\),\s*\(', order['products'])
        products = [item.strip("() ").strip() for item in raw_items]
    
    return render_template('success.html', order=order, products=products)


@app.route('/download_receipt/<int:order_id>')
def download_receipt(order_id):
    """PDF chek yuklab olish"""
    requested_font = request.args.get('font', 'DejaVuSans')
    font_name = requested_font if requested_font in REGISTERED_FONTS else 'DejaVuSans'
    font_size = 10
    
    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return abort(404, "Order not found")
    
    # Mahsulotlarni parsing qilish
    raw_products = order['products'] or ''
    parsed = re.findall(r'\(#(\d+)\s+(.*?)\s+x\s+(\d+)\)', raw_products)
    items = []
    
    if parsed:
        for pid, name, qty in parsed:
            prow = conn.execute('SELECT price FROM products WHERE id = ?', (int(pid),)).fetchone()
            price = int(prow['price']) if prow and prow['price'] else None
            items.append({'id': pid, 'name': name.strip(), 'qty': int(qty), 'price': price})
    else:
        parts = [p.strip() for p in re.split(r',\s*|\n', raw_products) if p.strip()]
        for p in parts:
            items.append({'id': '', 'name': p, 'qty': '', 'price': None})
    
    conn.close()
    
    # PDF parametrlari
    page_width = 80 * mm
    left_margin = 6 * mm
    right_margin = 6 * mm
    content_width = page_width - left_margin - right_margin
    
    def wrap_text(text, font, size, max_width):
        """Matnni kenglikka mos qatorlarga bo'lish"""
        words = text.split()
        lines = []
        cur = ""
        for w in words:
            test = cur + (" " if cur else "") + w
            if stringWidth(test, font, size) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines if lines else [""]
    
    # Chek balandligini hisoblash
    line_height = font_size * 1.3
    lines_count = 0
    
    header_lines = [
        "ONLINE DO'KON / ОNLINE МАГАЗИН",
        f"Check / Чек: {order['id']}",
        f"Sana / Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    ]
    lines_count += sum(len(wrap_text(l, font_name, font_size + 1, content_width)) for l in header_lines)
    
    customer_lines = [
        f"Ism / Имя: {order['name']}",
        f"Tel / Тел: {order['phone']}",
        f"Manzil / Адрес: {order['address'] or ''}"
    ]
    lines_count += sum(len(wrap_text(l, font_name, font_size, content_width)) for l in customer_lines)
    
    for it in items:
        lines = wrap_text(it['name'], font_name, font_size, content_width - (20 * mm))
        lines_count += len(lines) + 1
    
    footer_lines = ["", f"JAMI / ИТОГО: {int(order['total_price']):,} so'm", "", "Rahmat! Спасибо за покупку!"]
    lines_count += sum(len(wrap_text(l, font_name, font_size, content_width)) for l in footer_lines)
    
    qr_size = 40 * mm
    top_margin = 6 * mm
    bottom_margin = 8 * mm
    content_height = lines_count * line_height
    height_pts = max(top_margin + content_height + qr_size + bottom_margin + 20, 120 * mm)
    
    # PDF yaratish
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, height_pts))
    y = height_pts - top_margin
    
    # Header
    for hl in header_lines:
        c.setFont(font_name, font_size + 1)
        c.drawCentredString(page_width / 2, y, hl)
        y -= line_height
    
    y -= 3
    
    # Mijoz ma'lumotlari
    c.setFont(font_name, font_size)
    for cl in customer_lines:
        for w in wrap_text(cl, font_name, font_size, content_width):
            c.drawString(left_margin, y, w)
            y -= line_height
    
    y -= 3
    c.line(left_margin, y, page_width - right_margin, y)
    y -= line_height
    
    # Mahsulotlar sarlavhasi
    c.drawString(left_margin, y, "Nomi / Товар")
    c.drawRightString(page_width - right_margin, y, "Soni  Narx  Jami")
    y -= line_height
    
    # Mahsulotlar
    for it in items:
        name_lines = wrap_text(it['name'], font_name, font_size, content_width - (30 * mm))
        for i, nl in enumerate(name_lines):
            c.drawString(left_margin, y, nl)
            if i == 0:
                qty = str(it['qty']) if it.get('qty') != '' else ''
                price = f"{int(it['price']):,}" if it.get('price') else ''
                total_line = f"{qty}  {price}" if price else qty
                c.drawRightString(page_width - right_margin, y, total_line)
            y -= line_height
        y -= 2
    
    y -= line_height/2
    c.line(left_margin, y, page_width - right_margin, y)
    y -= line_height
    
    # Jami summa
    c.setFont(font_name, font_size + 1)
    c.drawString(left_margin, y, f"JAMI / ИТОГО: {int(order['total_price']):,} so'm")
    y -= line_height * 1.5
    
    # QR kod yaratish
    qr_text_items = []
    for it in items:
        if it.get('id'):
            qr_text_items.append(f"#{it['id']}:{it['qty']}")
        else:
            qr_text_items.append(f"{it['name']} x{it['qty']}")
    qr_data = f"Order:{order['id']};Name:{order['name']};Phone:{order['phone']};Items:{'|'.join(qr_text_items)}"
    
    qr_img = qrcode.make(qr_data)
    qr_buf = BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    qr_reader = ImageReader(qr_buf)
    
    qr_x = page_width - right_margin - qr_size
    qr_y = bottom_margin + 4 * mm
    c.drawImage(qr_reader, qr_x, qr_y, width=qr_size, height=qr_size)
    
    # Footer
    c.setFont(font_name, font_size - 1)
    c.drawString(left_margin, bottom_margin + 2 * mm, "Rahmat! Спасибо за покупку!")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True,
                     download_name=f"chek_{order_id}.pdf",
                     mimetype='application/pdf')


# ==============================================================================
# ADMIN PANEL - Administrator Routes
# ==============================================================================

@app.route('/admin/add', methods=['GET', 'POST'])
def admin_add_product():
    """Admin: Yangi mahsulot qo'shish"""
    ensure_products_videos_column()
    
    if request.method == 'POST':
        name = request.form['name']
        price = int(request.form['price'])
        description = request.form['description'].replace('\r\n', '\n')
        stock = int(request.form['stock'])
        
        product_order = request.form.get('image_order', '')
        desc_order = request.form.get('desc_image_order', '')
        video_order = request.form.get('video_order', '')
        ordered_product = product_order.split(',') if product_order else []
        ordered_desc = desc_order.split(',') if desc_order else []
        ordered_videos = video_order.split(',') if video_order else []
        
        original_to_unique = {}
        original_video_to_unique = {}
        
        # Rasmlarni saqlash
        def save_files(file_list):
            for file in file_list:
                if file and allowed_file(file.filename):
                    ext = os.path.splitext(file.filename)[1]
                    unique_filename = datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' + uuid.uuid4().hex[:6] + ext
                    secure_name = secure_filename(unique_filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                    file.save(filepath)
                    original_to_unique[file.filename] = secure_name
        
        save_files(request.files.getlist('images'))
        save_files(request.files.getlist('desc_images'))
        
        # Videolarni saqlash
        for vfile in request.files.getlist('videos'):
            if vfile and allowed_video(vfile.filename):
                ext = os.path.splitext(vfile.filename)[1]
                unique_filename = datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' + uuid.uuid4().hex[:6] + ext
                secure_name = secure_filename(unique_filename)
                vpath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                vfile.save(vpath)
                original_video_to_unique[vfile.filename] = secure_name
        
        # Tartib bo'yicha birlashtirish
        ordered_images = []
        for orig in ordered_product:
            if orig in original_to_unique:
                ordered_images.append(original_to_unique[orig])
        for orig in ordered_desc:
            if orig in original_to_unique:
                ordered_images.append(original_to_unique[orig])
        
        ordered_video_files = []
        for orig in ordered_videos:
            if orig in original_video_to_unique:
                ordered_video_files.append(original_video_to_unique[orig])
        
        # Tavsif ichidagi {rasm.jpg} larni yangilash
        for orig, unique in original_to_unique.items():
            description = description.replace(f'{{{orig}}}', f'{{{unique}}}')
        
        images_str = ','.join(ordered_images)
        videos_str = ','.join(ordered_video_files)
        
        # Ma'lumotlar bazasiga saqlash
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO products (name, price, description, stock, image, videos) VALUES (?, ?, ?, ?, ?, ?)',
                (name, price, description, stock, images_str, videos_str)
            )
        except Exception:
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


@app.route('/admin/edit/<int:product_id>', methods=['GET', 'POST'])
def admin_edit_product(product_id):
    """Admin: Mahsulotni tahrirlash"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        ensure_products_videos_column()
        name = request.form['name']
        price = int(request.form['price']) if request.form.get('price') else 0
        description = request.form['description']
        stock = int(request.form['stock']) if request.form.get('stock') else 0
        
        image_order = request.form.get('image_order', '')
        ordered_images = [x.strip() for x in image_order.split(',') if x.strip()]
        video_order = request.form.get('video_order', '')
        ordered_videos = [x.strip() for x in video_order.split(',') if x.strip()]
        
        # Yangi rasmlar
        for file in request.files.getlist('new_images'):
            if file and allowed_file(file.filename):
                ext = os.path.splitext(file.filename)[1]
                unique_filename = datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' + uuid.uuid4().hex[:6] + ext
                secure_name = secure_filename(unique_filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                file.save(filepath)
                ordered_images.append(secure_name)
        
        # Yangi videolar
        for vfile in request.files.getlist('new_videos'):
            if vfile and allowed_video(vfile.filename):
                ext = os.path.splitext(vfile.filename)[1]
                unique_filename = datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' + uuid.uuid4().hex[:6] + ext
                secure_name = secure_filename(unique_filename)
                vpath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                vfile.save(vpath)
                ordered_videos.append(secure_name)
        
        # O'chirilgan fayllarni diskdan o'chirish
        cur.execute("SELECT image, videos FROM products WHERE id=?", (product_id,))
        row = cur.fetchone()
        existing_images = [x.strip() for x in (row['image'] or '').split(',') if x.strip()]
        existing_videos = [x.strip() for x in (row['videos'] or '').split(',') if x.strip()]
        removed_images = set(existing_images) - set(ordered_images)
        removed_videos = set(existing_videos) - set(ordered_videos)
        
        for fname in list(removed_images) + list(removed_videos):
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    print(f"File delete error: {e}")
        
        cur.execute(
            '''UPDATE products
               SET name=?, price=?, description=?, stock=?, image=?, videos=?
               WHERE id=?''',
            (name, price, description, stock, ','.join(ordered_images), ','.join(ordered_videos), product_id)
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
    """Admin: Mahsulotni o'chirish"""
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    
    if product:
        # Rasmlarni diskdan o'chirish
        image_names = product['image'].split(',') if product['image'] else []
        for img_name in image_names:
            img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
            if os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except Exception as e:
                    print(f"Rasmni o'chirishda xato: {e}")
        
        # Ma'lumotlar bazasidan o'chirish
        conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('admin_add_product'))


# ==============================================================================
# CHAT - AI Support
# ==============================================================================

@app.route('/chat')
def chat_ui():
    """Chat sahifasi"""
    return render_template('chat.html')


@app.route('/chat', methods=['POST'])
def chat():
    """Chat bot - AI javob berish"""
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


# ==============================================================================
# API ENDPOINTS - Mobile/Web API
# ==============================================================================

@app.route('/api/products')
def api_products():
    """API: Mahsulotlar ro'yxati"""
    base_url = request.host_url.rstrip('/')
    
    try:
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 24))
        offset = max(0, offset)
        limit = max(1, min(limit, 60))
    except ValueError:
        offset, limit = 0, 24
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
    products = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM products")
    total_count = cur.fetchone()[0]
    conn.close()
    
    product_list = []
    for p in products:
        p_dict = dict(p)
        filenames = [x.strip() for x in p_dict['image'].split(',') if x.strip()]
        p_dict['images'] = [f"{base_url}/static/images/{name}" for name in filenames]
        del p_dict['image']
        product_list.append(p_dict)
    
    return jsonify({
        'items': product_list,
        'offset': offset,
        'limit': limit,
        'total': total_count,
        'has_more': offset + limit < total_count
    })


@app.route('/api/add-to-cart/<int:product_id>', methods=['POST'])
def api_add_to_cart(product_id):
    """API: Savatga qo'shish"""
    cart = normalize_cart(session.get('cart', {}))
    quantity = int(request.json.get('quantity', 1))
    cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
    session['cart'] = cart
    return jsonify({'cart': cart})


@app.route('/api/cart')
def api_cart():
    """API: Savat ma'lumotlari"""
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
    """API: Buyurtmani rasmiylashtirish"""
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
    
    c = conn.cursor()
    product_list = ", ".join([f"(#{p['id']} {p['name']} x {p['quantity']})" for p in products])
    c.execute(
        "INSERT INTO orders (name, phone, address, location, products, total_price) VALUES (?, ?, ?, ?, ?, ?)",
        (data['name'], data['phone'], data['address'], data.get('location', ''), product_list, total)
    )
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    
    session['cart'] = {}
    return jsonify({'success': True, 'order_id': order_id})


@app.route('/api/reverse', methods=['GET'])
def api_reverse():
    """API: Reverse geocoding"""
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


@app.route('/api/chat', methods=['POST'])
def api_chat():
    """API: Chat"""
    data = request.json
    user_message = data.get('message', '')
    reply_text = f"Siz yubordingiz: {user_message}"
    return jsonify({'reply': reply_text})


# ==============================================================================
# TEMPLATE FILTERS
# ==============================================================================

@app.template_filter('first_image')
def first_image_filter(image_string):
    """Template filter: Birinchi rasmni olish"""
    if image_string:
        return image_string.split(',')[0].strip()
    return 'default-product.jpg'


# ==============================================================================
# ILOVANI ISHGA TUSHIRISH
# ==============================================================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
