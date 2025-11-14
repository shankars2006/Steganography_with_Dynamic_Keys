import os
import sqlite3
import base64
import secrets
import string
from io import BytesIO
from flask import Flask, request, redirect, url_for, render_template, session, send_file, flash
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
from stegano import lsb

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET') or secrets.token_hex(16)
DB_PATH = 'stego_app.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            original_name TEXT,
            stego_name TEXT,
            png_blob BLOB,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

def xor_encrypt(data_bytes: bytes, key_str: str) -> bytes:
    key = key_str.encode('utf-8')
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data_bytes)])

def gen_key(length=8):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))

def to_png_bytes(file_stream):
    img = Image.open(file_stream).convert('RGB')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()

def hide_message(png_bytes, message):
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp.write(png_bytes)
        tmp.flush()
        path = tmp.name
    secret_img = lsb.hide(path, message)
    out = BytesIO()
    secret_img.save(out, format='PNG')
    out.seek(0)
    os.remove(path)
    return out.read()

def reveal_message(png_bytes):
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp.write(png_bytes)
        tmp.flush()
        path = tmp.name
    msg = lsb.reveal(path)
    os.remove(path)
    return msg

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    conn = get_db()
    u = conn.execute('SELECT id, username FROM users WHERE id=?', (uid,)).fetchone()
    conn.close()
    return u

@app.route('/')
def index():
    if current_user():
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        if not u or not p:
            flash('Fields required')
            return redirect(url_for('register'))
        conn = get_db()
        try:
            conn.execute('INSERT INTO users (username, password_hash) VALUES (?,?)',
                         (u, generate_password_hash(p)))
            conn.commit()
            flash('Registered successfully!')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already taken!')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT id, password_hash FROM users WHERE username=?', (u,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], p):
            session['user_id'] = user['id']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=user)

@app.route('/upload', methods=['POST'])
def upload():
    user = current_user()
    if not user:
        return redirect(url_for('login'))

    file = request.files['image']
    message = request.form['message']

    if not file or not message:
        flash("Please upload both image and message.")
        return redirect(url_for('dashboard'))

    png_bytes = to_png_bytes(file.stream)
    key = gen_key()
    enc = xor_encrypt(message.encode(), key)
    b64 = base64.b64encode(enc).decode()
    stego_png = hide_message(png_bytes, b64)

    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO images (user_id, original_name, stego_name, png_blob) VALUES (?, ?, ?, ?)',
                (user['id'], file.filename, file.filename + '_stego.png', stego_png))
    conn.commit()
    image_id = cur.lastrowid
    conn.close()

    # Show key and provide image download link
    return render_template('upload_success.html',
                           key=key,
                           image_id=image_id,
                           filename=file.filename + '_stego.png')

@app.route('/download_image/<int:image_id>')
def download_image(image_id):
    user = current_user()
    if not user:
        flash('Please log in first!')
        return redirect(url_for('login'))

    conn = get_db()
    row = conn.execute('SELECT stego_name, png_blob FROM images WHERE id=? AND user_id=?',
                       (image_id, user['id'])).fetchone()
    conn.close()

    if not row:
        flash('File not found!')
        return redirect(url_for('dashboard'))

    return send_file(BytesIO(row['png_blob']),
                     as_attachment=True,
                     download_name=row['stego_name'],
                     mimetype='image/png')

@app.route('/decrypt', methods=['POST'])
def decrypt():
    user = current_user()
    if not user:
        return redirect(url_for('login'))

    file = request.files['image']
    key = request.form['key']

    if not file or not key or len(key) != 8:
        flash('Image and 8-character key required')
        return redirect(url_for('dashboard'))

    png_bytes = to_png_bytes(file.stream)
    hidden = reveal_message(png_bytes)

    if not hidden:
        flash('No hidden message found')
        return redirect(url_for('dashboard'))

    dec = xor_encrypt(base64.b64decode(hidden), key)
    message = dec.decode()

    return render_template('reveal.html', message=message)

if __name__ == '__main__':
    app.run(debug=True)
