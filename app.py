import os
import time
import io
import csv
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_mail import Mail, Message
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.utils import secure_filename
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

#Email config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

mail = Mail(app)

mongo_uri = os.environ.get('MONGO_URI', "mongodb+srv://local:local@local-cluster.crpsu8t.mongodb.net/")
client = MongoClient(mongo_uri)
db = client["inventory"]
users_collection = db["users"]
collection = db["items"]
tokens_collection = db["reset_tokens"]

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']

@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    return User(user) if user else None

UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def calculate_poshmark_fee(sp):
    return 2.95 if sp < 15 else sp * 0.20 if sp > 0 else 0.0

@app.route('/')
@login_required
def index():
    sort = request.args.get('sort', 'item_name')
    order = request.args.get('order', 'asc')
    direction = ASCENDING if order == 'asc' else DESCENDING

    allowed_sorts = {
        'item_name','purchase_date','store','quantity',
        'original_price','sold_price','profit','return_by'
    }
    if sort not in allowed_sorts:
        sort = 'item_name'

    items = list(collection.find({'user_id': current_user.id}).sort(sort, direction))
    next_order = 'desc' if order == 'asc' else 'asc'

    return render_template('index.html', items=items, sort=sort, order=order, next_order=next_order)

@app.route('/add_item', methods=['GET','POST'])
@login_required
def add_item():
    if request.method == 'POST':
        name = request.form['item_name'].strip()
        try:
            qty = int(request.form['quantity'])
        except ValueError:
            flash("Quantity must be an integer.", "danger")
            return redirect(url_for('add_item'))

        op = safe_float(request.form['original_price'])
        sp = safe_float(request.form.get('sold_price',''))
        fee = calculate_poshmark_fee(sp)
        prf = round(sp - fee - op, 2) if sp > 0 else 0.0

        try:
            purchase_date = datetime.datetime.strptime(request.form.get('purchase_date',''), '%Y-%m-%d')
        except ValueError:
            flash("Invalid purchase date.", "danger")
            return redirect(url_for('add_item'))

        store = request.form.get('store','').strip()
        if not store:
            flash("Store is required.", "danger")
            return redirect(url_for('add_item'))

        return_by = purchase_date + datetime.timedelta(days=30)

        img_url = None
        f = request.files.get('image')
        if f and allowed_file(f.filename):
            fn = secure_filename(f.filename)
            fn = f"{int(time.time())}_{fn}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], fn)
            f.save(path)
            img_url = f"uploads/{fn}"

        doc = {
            'item_name': name,
            'quantity': qty,
            'original_price': op,
            'sold_price': sp,
            'poshmark_fee': fee,
            'profit': prf,
            'purchase_date': purchase_date,
            'store': store,
            'return_by': return_by,
            'image_url': img_url,
            'user_id': current_user.id
        }
        collection.insert_one(doc)
        flash("Item added!", "success")
        return redirect(url_for('index'))

    return render_template('add_item.html')

@app.route('/update_item/<item_id>', methods=['GET','POST'])
@login_required
def update_item(item_id):
    item = collection.find_one({'_id': ObjectId(item_id), 'user_id': current_user.id})
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            qty = int(request.form['new_quantity'])
        except ValueError:
            flash("Quantity must be an integer.", "danger")
            return redirect(url_for('update_item', item_id=item_id))

        op = safe_float(request.form['new_original_price'])
        sp = safe_float(request.form.get('new_sold_price',''))
        fee = calculate_poshmark_fee(sp)
        prf = round(sp - fee - op, 2) if sp > 0 else 0.0

        try:
            purchase_date = datetime.datetime.strptime(request.form.get('new_purchase_date',''), '%Y-%m-%d')
        except ValueError:
            flash("Invalid purchase date.", "danger")
            return redirect(url_for('update_item', item_id=item_id))

        store = request.form.get('new_store','').strip()
        if not store:
            flash("Store is required.", "danger")
            return redirect(url_for('update_item', item_id=item_id))

        return_by = purchase_date + datetime.timedelta(days=30)

        img_url = item.get('image_url')
        f = request.files.get('image')
        if f and allowed_file(f.filename):
            fn = secure_filename(f.filename)
            fn = f"{int(time.time())}_{fn}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], fn)
            f.save(path)
            img_url = f"uploads/{fn}"

        collection.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': {
                'quantity': qty,
                'original_price': op,
                'sold_price': sp,
                'poshmark_fee': fee,
                'profit': prf,
                'purchase_date': purchase_date,
                'store': store,
                'return_by': return_by,
                'image_url': img_url
            }}
        )
        flash("Item updated!", "success")
        return redirect(url_for('index'))

    return render_template('update_item.html', item=item)

@app.route('/delete/<item_id>')
@login_required
def delete_item(item_id):
    collection.delete_one({'_id': ObjectId(item_id), 'user_id': current_user.id})
    return redirect(url_for('index'))

@app.route('/export_csv')
@login_required
def export_csv():
    items = list(collection.find({'user_id': current_user.id}))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Item Name','Quantity','Original Price','Sold Price','Poshmark Fee','Profit','Purchase Date','Store','Return By','Image URL'])
    for it in items:
        w.writerow([
            it['item_name'],
            it['quantity'],
            f"{it['original_price']:.2f}",
            f"{it['sold_price']:.2f}" if it['sold_price']>0 else '',
            f"{it['poshmark_fee']:.2f}" if it['poshmark_fee']>0 else '',
            f"{it['profit']:.2f}",
            it['purchase_date'].strftime('%Y-%m-%d'),
            it['store'],
            it['return_by'].strftime('%Y-%m-%d'),
            it.get('image_url','')
        ])
    buf.seek(0)
    return send_file(
        io.BytesIO(buf.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='inventory_export.csv'
    )

@app.route('/import_csv', methods=['GET','POST'])
@login_required
def import_csv():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash("Please select a CSV file.", "danger")
            return redirect(url_for('import_csv'))

        stream = io.StringIO(file.stream.read().decode(), newline=None)
        reader = csv.reader(stream)
        next(reader, None)
        count = 0

        for row in reader:
            try:
                doc = {
                    'item_name': row[0],
                    'quantity': int(row[1]),
                    'original_price': safe_float(row[2]),
                    'sold_price': safe_float(row[3]),
                    'poshmark_fee': safe_float(row[4]),
                    'profit': safe_float(row[5]),
                    'purchase_date': datetime.datetime.strptime(row[6], '%Y-%m-%d'),
                    'store': row[7],
                    'return_by': datetime.datetime.strptime(row[8], '%Y-%m-%d'),
                    'image_url': row[9] if len(row) > 9 else None,
                    'user_id': current_user.id
                }
                collection.insert_one(doc)
                count += 1
            except Exception:
                continue

        flash(f"Imported {count} rows.", "success")
        return redirect(url_for('index'))

    return render_template('import_csv.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        username = request.form['username'].strip()
        password = request.form['password']
        confirm = request.form['confirm']

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))
        
        if users_collection.find_one({'$or': [{'username': username}, {'email': email}]}):
            flash("Username or email already exists.", "danger")
            return redirect(url_for('register'))
        
        users_collection.insert_one({
            'email': email,
            'username': username,
            'password': generate_password_hash(password)
        })
        flash("Account created! Please log in.", "success")
        return redirect(url_for('login'))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = users_collection.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            login_user(User(user))
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'danger')  # ✅ More accurate
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        user = users_collection.find_one({'email': email})
        if user:
            token = secrets.token_urlsafe(24)
            tokens_collection.insert_one({
                'token': token,
                'user_id': str(user['_id']),
                'created_at': datetime.datetime.utcnow()
            })
            link = url_for('reset_password', token=token, _external=True)

            msg = Message("Password Reset Request",
                          sender = app.config['MAIL_USERNAME'],
                          recipients=[email])
            msg.body = f"Hi {user['username']}, click the link below to reset your password:\n{link}"
            mail.send(msg)
            flash("Password reset email sent! Check your inbox.", "success")
        else:
            flash("No account with that email.", "danger")
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_doc = tokens_collection.find_one({'token': token})
    if not token_doc:
        flash("Invalid or expired token.", "danger")
    if not token_doc:
        flash("Invalid or expired token.", "danger")
        return redirect(url_for('login'))
    
    user_id = token_doc['user_id']
    
    user_id = token_doc['user_id']
    
    if request.method == 'POST':
        password = request.form['password']
        confirm = request.form['confirm']
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(request.url)
        
        hashed_pw = generate_password_hash(password)
        users_collection.update_one({'_id': ObjectId(user_id)}, {'$set': {'password': hashed_pw}})
        tokens_collection.delete_one({'token': token})
        flash("Password updated successfully!", "success")
        return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
