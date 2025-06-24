import os
import time
import io
import csv
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

# MongoDB connection
mongo_uri = os.environ.get(
    'MONGO_URI',
    "mongodb+srv://local:local@local-cluster.crpsu8t.mongodb.net/"
)
client = MongoClient(mongo_uri)
db = client["inventory"]
collection = db["items"]

# File uploads
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
    if sp <= 0:
        return 0.0
    return 2.95 if sp < 15 else sp * 0.20

@app.route('/')
def index():
    # Sorting parameters
    sort = request.args.get('sort', 'item_name')
    order = request.args.get('order', 'asc')
    direction = ASCENDING if order == 'asc' else DESCENDING

    # Whitelist sortable fields
    allowed_sorts = {
        'item_name','purchase_date','store','quantity',
        'original_price','sold_price','profit','return_by'
    }
    if sort not in allowed_sorts:
        sort = 'item_name'

    items = list(collection.find().sort(sort, direction))
    next_order = 'desc' if order == 'asc' else 'asc'

    return render_template(
        'index.html',
        items=items,
        sort=sort,
        order=order,
        next_order=next_order
    )

@app.route('/add_item', methods=['GET','POST'])
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

        # New fields
        pd_str = request.form.get('purchase_date','')
        try:
            purchase_date = datetime.datetime.strptime(pd_str, '%Y-%m-%d')
        except ValueError:
            flash("Invalid purchase date.", "danger")
            return redirect(url_for('add_item'))

        store = request.form.get('store','').strip()
        if not store:
            flash("Store is required.", "danger")
            return redirect(url_for('add_item'))

        return_by = purchase_date + datetime.timedelta(days=30)

        # Image upload
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
            'image_url': img_url
        }
        collection.insert_one(doc)
        flash("Item added!", "success")
        return redirect(url_for('index'))

    return render_template('add_item.html')

@app.route('/update_item/<item_id>', methods=['GET','POST'])
def update_item(item_id):
    item = collection.find_one({'_id': ObjectId(item_id)})
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

        # Update purchase date & store
        pd_str = request.form.get('new_purchase_date','')
        try:
            purchase_date = datetime.datetime.strptime(pd_str, '%Y-%m-%d')
        except ValueError:
            flash("Invalid purchase date.", "danger")
            return redirect(url_for('update_item', item_id=item_id))

        store = request.form.get('new_store','').strip()
        if not store:
            flash("Store is required.", "danger")
            return redirect(url_for('update_item', item_id=item_id))

        return_by = purchase_date + datetime.timedelta(days=30)

        # Image upload (optional replace)
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

@app.route('/delete_item/<item_id>')
def delete_item(item_id):
    collection.delete_one({'_id': ObjectId(item_id)})
    flash("Item deleted.", "info")
    return redirect(url_for('index'))

@app.route('/export_csv')
def export_csv():
    items = list(collection.find())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        'Item Name','Quantity','Original Price','Sold Price','Poshmark Fee',
        'Profit','Purchase Date','Store','Return By','Image URL'
    ])
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
def import_csv():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash("Please select a CSV file.", "danger")
            return redirect(url_for('import_csv'))

        stream = io.StringIO(file.stream.read().decode(), newline=None)
        reader = csv.reader(stream)
        next(reader, None)  # skip header
        count = 0

        for row in reader:
            try:
                name = row[0]
                qty = int(row[1])
                op = safe_float(row[2])
                sp = safe_float(row[3])
                fee = safe_float(row[4])
                prf = safe_float(row[5])
                pd = datetime.datetime.strptime(row[6], '%Y-%m-%d')
                store = row[7]
                rb = datetime.datetime.strptime(row[8], '%Y-%m-%d')
                img = row[9] if len(row) > 9 else None

                doc = {
                    'item_name': name,
                    'quantity': qty,
                    'original_price': op,
                    'sold_price': sp,
                    'poshmark_fee': fee,
                    'profit': prf,
                    'purchase_date': pd,
                    'store': store,
                    'return_by': rb,
                    'image_url': img
                }
                collection.insert_one(doc)
                count += 1
            except Exception:
                continue

        flash(f"Imported {count} rows.", "success")
        return redirect(url_for('index'))

    return render_template('import_csv.html')

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=True
    )
