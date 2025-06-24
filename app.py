import os
import time
import io
import csv
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.secret_key = os.environ['Aurora143:)']  # Replace with a strong secret

# static/uploads for images
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# MongoDB
client = MongoClient("mongodb+srv://local:local@local-cluster.crpsu8t.mongodb.net/")
db = client["inventory"]
collection = db["items"]

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

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
    items = list(collection.find())
    return render_template('index.html', items=items)

@app.route('/add_item', methods=['GET','POST'])
def add_item():
    if request.method=='POST':
        name = request.form['item_name'].strip()
        qty  = int(request.form['quantity'])
        op   = safe_float(request.form['original_price'])
        sp_in= request.form.get('sold_price','').strip()
        sp   = safe_float(sp_in)
        fee  = calculate_poshmark_fee(sp)
        prf  = round(sp - fee - op,2) if sp>0 else 0.0

        # image upload
        img_url = None
        f = request.files.get('image')
        if f and allowed_file(f.filename):
            fn = secure_filename(f.filename)
            fn = f"{int(time.time())}_{fn}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], fn)
            f.save(path)
            img_url = f"uploads/{fn}"

        item = {
            'item_name':       name,
            'quantity':        qty,
            'original_price':  op,
            'sold_price':      sp,
            'poshmark_fee':    fee,
            'profit':          prf,
            'image_url':       img_url
        }
        collection.insert_one(item)
        flash("Item added!", "success")
        return redirect(url_for('index'))
    return render_template('add_item.html')

@app.route('/update_item/<item_id>', methods=['GET','POST'])
def update_item(item_id):
    item = collection.find_one({'_id': ObjectId(item_id)})
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for('index'))

    if request.method=='POST':
        qty   = int(request.form['new_quantity'])
        op    = safe_float(request.form['new_original_price'])
        sp_in = request.form.get('new_sold_price','').strip()
        sp    = safe_float(sp_in)
        fee   = calculate_poshmark_fee(sp)
        prf   = round(sp - fee - op,2) if sp>0 else 0.0

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
                'quantity':       qty,
                'original_price': op,
                'sold_price':     sp,
                'poshmark_fee':   fee,
                'profit':         prf,
                'image_url':      img_url
            }}
        )
        flash("Item updated!", "success")
        return redirect(url_for('index'))

    return render_template('update_item.html', item=item)

@app.route('/delete_item/<item_id>')
def delete_item(item_id):
    collection.delete_one({'_id': ObjectId(item_id)})
    flash("Deleted.", "info")
    return redirect(url_for('index'))

@app.route('/export_csv')
def export_csv():
    items = list(collection.find())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Item Name','Quantity','Original Price','Sold Price','Poshmark Fee','Profit','Image URL'])
    for it in items:
        w.writerow([
            it['item_name'],
            it['quantity'],
            f"{it['original_price']:.2f}",
            f"{it['sold_price']:.2f}" if it['sold_price']>0 else '',
            f"{it['poshmark_fee']:.2f}" if it['poshmark_fee']>0 else '',
            f"{it['profit']:.2f}",
            it.get('image_url','')
        ])
    buf.seek(0)
    return send_file(io.BytesIO(buf.getvalue().encode()),
                     mimetype='text/csv',
                     as_attachment=True,
                     download_name='inventory_export.csv')

@app.route('/import_csv', methods=['GET','POST'])
def import_csv():
    if request.method=='POST':
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
                qty  = int(row[1])
                op   = safe_float(row[2])
                sp   = safe_float(row[3])
                fee  = safe_float(row[4])
                prf  = safe_float(row[5])
                img  = row[6] if len(row)>6 else None
                item = {
                    'item_name':name, 'quantity':qty, 'original_price':op,
                    'sold_price':sp, 'poshmark_fee':fee, 'profit':prf,
                    'image_url':img
                }
                collection.insert_one(item)
                count += 1
            except Exception:
                continue
        flash(f"Imported {count} rows.", "success")
        return redirect(url_for('index'))
    return render_template('import_csv.html')

if __name__=='__main__':
    app.run(debug=True)
