# -------------------------
# Flask va extensions
# -------------------------
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, send_file, abort
)
from flask_cors import CORS
from markupsafe import Markup
from werkzeug.utils import secure_filename

# -------------------------
# Standart kutubxonalar
# -------------------------
import os
import re
import uuid
import random
import sqlite3
import requests
from io import BytesIO
from datetime import datetime

# -------------------------
# 3rd-party kutubxonalar
# -------------------------
import ollama
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
# -------------------------

app = Flask(__name__)
CORS(app)  # ✅ CORS ni yoqib qo'yamiz (Flutter web so'rovlariga ruxsat)
app.secret_key = 'secretkey123'
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm', 'mkv'}

# Font papkasi va fayllar (static ichida)
FONT_DIR = os.path.join(app.root_path, 'static', 'fonts')
FONT_FILES = {
    'DejaVuSans': os.path.join(FONT_DIR, 'DejaVuSans.ttf'),
    'NotoSans': os.path.join(FONT_DIR, 'NotoSans-Regular.ttf')
}
# Ro'yxatga olish
REGISTERED_FONTS = {}
for short, path in FONT_FILES.items():
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont(short, path))
            REGISTERED_FONTS[short] = path
        except Exception as e:
            print("Font register error:", short, e)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_video(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS

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

def ensure_products_videos_column():
    """Agar 'products' jadvalida 'videos' ustuni bo'lmasa, qo'shib qo'yadi."""
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

@app.route('/products')
def products_list():
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
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    if product is None:
        return "Mahsulot topilmadi", 404
    rendered_description = render_description(product['description']) if product and product['description'] else Markup("")
    return render_template('product.html', product=product, rendered_description=rendered_description)

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

@app.route('/download_receipt/<int:order_id>')
def download_receipt(order_id):
    # tanlangan shrift (query param orqali o'zgartirish mumkin)
    requested_font = request.args.get('font', 'DejaVuSans')
    font_name = requested_font if requested_font in REGISTERED_FONTS else 'DejaVuSans'
    font_size = 10  # o'zgartiring, 9-11 oralig'i chek uchun yaxshi

    conn = get_db_connection()
    order = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        conn.close()
        return abort(404, "Order not found")

    raw_products = order['products'] or ''
    # (1) pars qiling: (#{id} name x qty)
    parsed = re.findall(r'\(#(\d+)\s+(.*?)\s+x\s+(\d+)\)', raw_products)
    items = []
    if parsed:
        for pid, name, qty in parsed:
            # har bir mahsulot uchun DB dan narx olishga urinib ko'ramiz
            prow = conn.execute('SELECT price FROM products WHERE id = ?', (int(pid),)).fetchone()
            price = int(prow['price']) if prow and prow['price'] else None
            items.append({'id': pid, 'name': name.strip(), 'qty': int(qty), 'price': price})
    else:
        # fallback — oddiy bo'linish
        parts = [p.strip() for p in re.split(r',\s*|\n', raw_products) if p.strip()]
        for p in parts:
            items.append({'id': '', 'name': p, 'qty': '', 'price': None})

    conn.close()

    # PDF o'lchamlari — kenglik 80 mm (termal chek), balandlikni hisoblab qo'yamiz
    page_width = 80 * mm
    left_margin = 6 * mm
    right_margin = 6 * mm
    content_width = page_width - left_margin - right_margin

    # Helper: matnni qatorlarga bo'lish (fontga mos)
    def wrap_text(text, font, size, max_width):
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
        if not lines:
            return [""]
        return lines

    # yuqoridagi tekshiruvlar bo'yicha qancha qatordan iborat ekanligini hisoblaymiz
    line_height = font_size * 1.3
    lines_count = 0

    # header lines
    header_lines = [
        "ONLINE DO'KON / ОNLINE МАГАЗИН",
        f"Check / Чек: {order['id']}",
        f"Sana / Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    ]
    lines_count += sum(len(wrap_text(l, font_name, font_size + 1, content_width)) for l in header_lines)

    # mijoz ma'lumotlari
    customer_lines = [
        f"Ism / Имя: {order['name']}",
        f"Tel / Тел: {order['phone']}",
        f"Manzil / Адрес: {order['address'] or ''}"
    ]
    lines_count += sum(len(wrap_text(l, font_name, font_size, content_width)) for l in customer_lines)

    # products lines
    for it in items:
        # satrda: "Nomi (id) xqty — narx — jami"
        # lekin narx bo'lmasa, faqat nom va qty
        title = it['name']
        lines = wrap_text(title, font_name, font_size, content_width - (20 * mm))  # ozgina joy vaqtinchalik raqam uchun
        lines_count += len(lines)
        # bitta qo'shimcha satr - qty+price ko'rsatish (agar kerak)
        lines_count += 1

    # total, qr va footer
    footer_lines = ["", f"JAMI / ИТОГО: {int(order['total_price']):,} so'm", "", "Rahmat! Спасибо за покупку!"]
    lines_count += sum(len(wrap_text(l, font_name, font_size, content_width)) for l in footer_lines)

    # QR joylashuvi uchun balandlikni hisoblaymiz (qr_size mm)
    qr_size = 40 * mm
    # umumiy balandlik
    top_margin = 6 * mm
    bottom_margin = 8 * mm
    content_height = lines_count * line_height
    height_pts = top_margin + content_height + qr_size + bottom_margin + 20  # kichik kesh

    # minimal balandlikni belgilaymiz
    min_h = 120 * mm
    if height_pts < min_h:
        height_pts = min_h

    # PDF yaratayapmiz
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, height_pts))

    # Fon va font
    c.setFont(font_name, font_size + 2)
    y = height_pts - top_margin

    # header
    for hl in header_lines:
        # markazlashtirilgan
        c.setFont(font_name, font_size + 1)
        c.drawCentredString(page_width / 2, y, hl)
        y -= line_height

    y -= 3  # kichik bo'shliq
    # mijoz ma'lumotlari
    c.setFont(font_name, font_size)
    for cl in customer_lines:
        wrapped = wrap_text(cl, font_name, font_size, content_width)
        for w in wrapped:
            c.drawString(left_margin, y, w)
            y -= line_height

    y -= 3
    # Chiziq
    c.line(left_margin, y, page_width - right_margin, y)
    y -= line_height

    # Mahsulotlar sarlavhasi
    c.setFont(font_name, font_size)
    c.drawString(left_margin, y, "Nomi / Товар")
    # quantity va narx uchun sarlavha o'ng tomonda
    c.drawRightString(page_width - right_margin, y, "Soni  Narx  Jami")
    y -= line_height

    # Tovarlar
    # qayta ochish uchun DB olish (agar kerak bo'lsa)
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
        y -= 2  # kichik oraliq

    y -= line_height/2
    # chiziq
    c.line(left_margin, y, page_width - right_margin, y)
    y -= line_height

    # TOTAL
    c.setFont(font_name, font_size + 1)
    total_str = f"JAMI / ИТОГО: {int(order['total_price']):,} so'm"
    c.drawString(left_margin, y, total_str)
    y -= line_height * 1.5

    # QR ma'lumotini tayyorlash
    # QR da qisqacha ma'lumot: order id, name, phone, va qisqacha mahsulotlar
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

    # QR ni pastga o'ngga chizish (y joyi taxminan)
    qr_x = page_width - right_margin - qr_size
    qr_y = bottom_margin + 4 * mm
    c.drawImage(qr_reader, qr_x, qr_y, width=qr_size, height=qr_size)

    # Footer text (QR yoniga yoki pastga)
    c.setFont(font_name, font_size - 1)
    c.drawString(left_margin, bottom_margin + 2 * mm, "Rahmat! Спасибо за покупку!")

    c.showPage()
    c.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"chek_{order_id}.pdf",
                     mimetype='application/pdf')

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
    ensure_products_videos_column()
    if request.method == 'POST':
        name = request.form['name']
        price = int(request.form['price'])
        description = request.form['description'].replace('\r\n', '\n')
        stock = int(request.form['stock'])

        # Frontenddan keladigan tartiblar
        product_order = request.form.get('image_order', '')
        desc_order    = request.form.get('desc_image_order', '')
        video_order   = request.form.get('video_order', '')
        ordered_product = product_order.split(',') if product_order else []
        ordered_desc    = desc_order.split(',') if desc_order else []
        ordered_videos  = video_order.split(',') if video_order else []

        original_to_unique = {}
        original_video_to_unique = {}

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

        # Videolarni saqlash
        for vfile in request.files.getlist('videos'):
            if vfile and allowed_video(vfile.filename):
                ext = os.path.splitext(vfile.filename)[1]
                unique_filename = (
                    datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' +
                    uuid.uuid4().hex[:6] + ext
                )
                secure_name = secure_filename(unique_filename)
                vpath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                vfile.save(vpath)
                original_video_to_unique[vfile.filename] = secure_name

        # ✅ Tartib bo‘yicha birlashtirish
        ordered_images = []
        for orig in ordered_product:
            if orig in original_to_unique:
                ordered_images.append(original_to_unique[orig])
        for orig in ordered_desc:
            if orig in original_to_unique:
                ordered_images.append(original_to_unique[orig])

        # Videolar tartibi
        ordered_video_files = []
        for orig in ordered_videos:
            if orig in original_video_to_unique:
                ordered_video_files.append(original_video_to_unique[orig])

        # ✅ Tavsif ichidagi {rasm.jpg} larni yangi nomlarga almashtirish
        for orig, unique in original_to_unique.items():
            description = description.replace(f'{{{orig}}}', f'{{{unique}}}')

        images_str = ','.join(ordered_images)
        videos_str = ','.join(ordered_video_files)

        # ✅ DB ga yozish
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO products (name, price, description, stock, image, videos) VALUES (?, ?, ?, ?, ?, ?)',
                (name, price, description, stock, images_str, videos_str)
            )
        except Exception:
            # Agar eski schema bo'lsa (videos yo'q) - fallback
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
        ensure_products_videos_column()
        name = request.form['name']
        price = int(request.form['price']) if request.form.get('price') else 0
        description = request.form['description']
        stock = int(request.form['stock']) if request.form.get('stock') else 0

        # Mavjud media tartiblari
        image_order = request.form.get('image_order', '')
        ordered_images = [x.strip() for x in image_order.split(',') if x.strip()]
        video_order = request.form.get('video_order', '')
        ordered_videos = [x.strip() for x in video_order.split(',') if x.strip()]

        # Yangi rasmlar
        for file in request.files.getlist('new_images'):
            if file and allowed_file(file.filename):
                ext = os.path.splitext(file.filename)[1]
                unique_filename = (
                    datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' + uuid.uuid4().hex[:6] + ext
                )
                secure_name = secure_filename(unique_filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                file.save(filepath)
                ordered_images.append(secure_name)

        # Yangi videolar
        for vfile in request.files.getlist('new_videos'):
            if vfile and allowed_video(vfile.filename):
                ext = os.path.splitext(vfile.filename)[1]
                unique_filename = (
                    datetime.now().strftime('%Y%m%d%H%M%S%f') + '_' + uuid.uuid4().hex[:6] + ext
                )
                secure_name = secure_filename(unique_filename)
                vpath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)
                vfile.save(vpath)
                ordered_videos.append(secure_name)

        # Diskdan o'chiriladigan fayllar
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
            """
            UPDATE products
            SET name=?, price=?, description=?, stock=?, image=?, videos=?
            WHERE id=?
            """,
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
    # Next page bor-yo'qligini bilish uchun umumiy sonni ham qaytaramiz
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
    app.run(debug=True, host='0.0.0.0', port=5000)