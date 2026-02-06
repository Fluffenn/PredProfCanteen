import sqlite3
import os
import re
from datetime import date, timedelta, datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, Response
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import csv
from io import StringIO
from urllib.parse import quote


SECRET_KEY_FILE = 'secret.key'
if not os.path.exists(SECRET_KEY_FILE):
    key = Fernet.generate_key()
    with open(SECRET_KEY_FILE, 'wb') as f:
        f.write(key)
else:
    with open(SECRET_KEY_FILE, 'rb') as f:
        key = f.read()

fernet = Fernet(key)

app = Flask(__name__)
app.secret_key = 'school_canteen_secret_key_2026'
DATABASE = 'database.db'


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('student', 'cook', 'admin')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS student_profiles (
                user_id INTEGER PRIMARY KEY,
                allergies TEXT,
                preferences TEXT,
                balance REAL DEFAULT 0.0,
                encrypted_card_number TEXT,
                card_expiry TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dishes (
                name TEXT PRIMARY KEY,
                price REAL NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS menu_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_date DATE NOT NULL UNIQUE,
                breakfast_main TEXT NOT NULL,
                breakfast_drink TEXT NOT NULL,
                lunch_first TEXT NOT NULL,
                lunch_second TEXT NOT NULL,
                lunch_drink TEXT NOT NULL,
                FOREIGN KEY(breakfast_main) REFERENCES dishes(name),
                FOREIGN KEY(breakfast_drink) REFERENCES dishes(name),
                FOREIGN KEY(lunch_first) REFERENCES dishes(name),
                FOREIGN KEY(lunch_second) REFERENCES dishes(name),
                FOREIGN KEY(lunch_drink) REFERENCES dishes(name)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dish_recipes (
                dish_name TEXT NOT NULL,
                ingredient TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                FOREIGN KEY(dish_name) REFERENCES dishes(name),
                FOREIGN KEY(ingredient) REFERENCES inventory(product_name)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_type TEXT CHECK(payment_type IN ('one-time', 'subscription')),
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(student_id) REFERENCES users(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS meal_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                menu_id INTEGER NOT NULL,
                meal_type TEXT NOT NULL CHECK(meal_type IN ('breakfast', 'lunch')),
                taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed BOOLEAN DEFAULT 0,
                FOREIGN KEY(student_id) REFERENCES users(id),
                FOREIGN KEY(menu_id) REFERENCES menu_sets(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                product_name TEXT PRIMARY KEY,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cook_id INTEGER NOT NULL,
                items TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by INTEGER,
                FOREIGN KEY(cook_id) REFERENCES users(id),
                FOREIGN KEY(approved_by) REFERENCES users(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                dish_name TEXT NOT NULL,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(student_id) REFERENCES users(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                duration TEXT NOT NULL CHECK(duration IN ('week', 'month', 'year')),
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(student_id) REFERENCES users(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prepared_dishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                prepared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(dish_name) REFERENCES dishes(name)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        test_users = [
            ('Петров Иван Сергеевич', 'admin', 'admin'),
            ('Сидоров Сидор Сидорович', 'cook', 'cook'),
            ('Шнец Владимир Владимирович', 'student', 'student')
        ]
        for full_name, pwd, role in test_users:
            cursor.execute("SELECT 1 FROM users WHERE full_name = ?", (full_name,))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO users (full_name, password_hash, role)
                    VALUES (?, ?, ?)
                ''', (full_name, generate_password_hash(pwd), role))
                if role == 'student':
                    user_id = cursor.lastrowid
                    cursor.execute('INSERT INTO student_profiles (user_id, balance) VALUES (?, 0.0)', (user_id,))
        dishes = [
            ("Овсяная каша", 40),
            ("Какао", 20),
            ("Борщ", 60),
            ("Котлета с картошкой", 70),
            ("Компот", 15)
        ]
        for name, price in dishes:
            cursor.execute("INSERT OR IGNORE INTO dishes (name, price) VALUES (?, ?)", (name, price))

        recipes = [
            ("Овсяная каша", "Овсянка", 0.1, "кг"),
            ("Овсяная каша", "Молоко", 0.2, "литров"),
            ("Какао", "Какао-порошок", 0.01, "кг"),
            ("Какао", "Молоко", 0.2, "литров"),
            ("Борщ", "Свекла", 0.3, "кг"),
            ("Борщ", "Капуста", 0.2, "кг"),
            ("Борщ", "Картофель", 0.2, "кг"),
            ("Котлета с картошкой", "Фарш", 0.15, "кг"),
            ("Котлета с картошкой", "Картофель", 0.2, "кг"),
            ("Компот", "Сухофрукты", 0.05, "кг"),
            ("Компот", "Сахар", 0.02, "кг")
        ]
        for dish, ing, qty, unit in recipes:
            cursor.execute('''
                INSERT OR IGNORE INTO dish_recipes (dish_name, ingredient, quantity, unit)
                VALUES (?, ?, ?, ?)
            ''', (dish, ing, qty, unit))

        inventory = [
            ("Овсянка", 10, "кг"),
            ("Молоко", 50, "литров"),
            ("Какао-порошок", 2, "кг"),
            ("Свекла", 15, "кг"),
            ("Капуста", 12, "кг"),
            ("Картофель", 30, "кг"),
            ("Фарш", 8, "кг"),
            ("Сухофрукты", 5, "кг"),
            ("Сахар", 10, "кг")
        ]
        for name, qty, unit in inventory:
            cursor.execute("INSERT OR REPLACE INTO inventory (product_name, quantity, unit) VALUES (?, ?, ?)",
                           (name, qty, unit))

        for i in range(2):
            day = date.today() + timedelta(days=i)
            cursor.execute('''
                INSERT OR IGNORE INTO menu_sets (
                    meal_date, breakfast_main, breakfast_drink,
                    lunch_first, lunch_second, lunch_drink
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (day, "Овсяная каша", "Какао", "Борщ", "Котлета с картошкой", "Компот"))

        db.commit()


def has_active_subscription(student_id, db):
    today = date.today()
    sub = db.execute('''
        SELECT 1 FROM subscriptions 
        WHERE student_id = ? AND status = 'active' AND ? BETWEEN start_date AND end_date
    ''', (student_id, today)).fetchone()
    return sub is not None


def get_unread_notifications_count(user_id, db):
    count = db.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', (user_id,)).fetchone()
    return count[0] if count else 0


def send_notification(user_id, message):
    db = get_db()
    db.execute('INSERT INTO notifications (user_id, message) VALUES (?, ?)', (user_id, message))
    db.commit()


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for(f"{session['role']}_dashboard"))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        full_name = request.form['full_name']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE full_name = ?', (full_name,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            return redirect(url_for(f"{user['role']}_dashboard"))
        flash('Неверное ФИО или пароль')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        password = request.form['password']
        role = 'student'
        if not full_name or not password:
            flash('ФИО и пароль обязательны')
            return render_template('register.html')
        db = get_db()
        try:
            db.execute('INSERT INTO users (full_name, password_hash, role) VALUES (?, ?, ?)',
                       (full_name, generate_password_hash(password), role))
            user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute('INSERT INTO student_profiles (user_id, balance) VALUES (?, 0.0)', (user_id,))
            db.commit()
            flash('Регистрация успешна! Войдите.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Пользователь с таким ФИО уже существует')
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('register'))
@app.route('/student/dashboard')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    return render_template('student/dashboard.html', unread_count=unread_count)


@app.route('/student/menu')
def student_menu():
    if session.get('role') != 'student':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    today = date.today()
    menu_set = db.execute('SELECT * FROM menu_sets WHERE meal_date = ?', (today,)).fetchone()
    taken_meals = db.execute('''
        SELECT meal_type FROM meal_records 
        WHERE student_id = ? AND date(taken_at) = ?
    ''', (session['user_id'], today)).fetchall()
    taken_types = {row['meal_type'] for row in taken_meals}


    breakfast_price = 0.0
    lunch_price = 0.0
    if menu_set:

        breakfast_items = [menu_set['breakfast_main'], menu_set['breakfast_drink']]
        prices = db.execute('''
            SELECT price FROM dishes WHERE name IN (?, ?)
        ''', (menu_set['breakfast_main'], menu_set['breakfast_drink'])).fetchall()
        breakfast_price = sum(p['price'] for p in prices)

        lunch_items = [menu_set['lunch_first'], menu_set['lunch_second'], menu_set['lunch_drink']]
        prices = db.execute('''
            SELECT price FROM dishes WHERE name IN (?, ?, ?)
        ''', (menu_set['lunch_first'], menu_set['lunch_second'], menu_set['lunch_drink'])).fetchall()
        lunch_price = sum(p['price'] for p in prices)

    profile = db.execute('SELECT allergies, preferences FROM student_profiles WHERE user_id = ?',
                         (session['user_id'],)).fetchone()

    allergies = set()
    if profile and profile['allergies']:
        allergies = {a.strip().lower() for a in profile['allergies'].split(',') if a.strip()}

    preferences = set()
    if profile and profile['preferences']:
        preferences = {p.strip().lower() for p in profile['preferences'].split(',') if p.strip()}

    allergen_warnings = {}
    preference_matches = {}

    if menu_set:
        all_dishes = [
            menu_set['breakfast_main'],
            menu_set['breakfast_drink'],
            menu_set['lunch_first'],
            menu_set['lunch_second'],
            menu_set['lunch_drink']
        ]
        for dish_name in all_dishes:
            if not dish_name:
                continue
            ingredients = db.execute('''
                SELECT ingredient FROM dish_recipes WHERE dish_name = ?
            ''', (dish_name,)).fetchall()
            dish_ingredients = {ing['ingredient'].lower() for ing in ingredients}

            if allergies & dish_ingredients:
                allergen_warnings[dish_name] = True

            if preferences & dish_ingredients:
                preference_matches[dish_name] = True

    return render_template(
        'student/menu.html',
        menu_set=menu_set,
        today=today,
        taken_types=taken_types,
        allergen_warnings=allergen_warnings,
        preference_matches=preference_matches,
        allergies_list=', '.join(allergies) if allergies else None,
        preferences_list=', '.join(preferences) if preferences else None,
        breakfast_price=breakfast_price,
        lunch_price=lunch_price,
        unread_count=unread_count
    )


@app.route('/student/get_meal/<meal_type>')
def student_get_meal(meal_type):
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    if meal_type not in ('breakfast', 'lunch'):
        flash('Неверный тип питания')
        return redirect(url_for('student_menu'))

    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    today = date.today()

    existing = db.execute('''
        SELECT 1 FROM meal_records 
        WHERE student_id = ? AND meal_type = ? AND date(taken_at) = ?
    ''', (session['user_id'], meal_type, today)).fetchone()

    if existing:
        flash(f'Вы уже получили {meal_type} сегодня!')
        return redirect(url_for('student_menu'))

    menu_set = db.execute('SELECT * FROM menu_sets WHERE meal_date = ?', (today,)).fetchone()
    if not menu_set:
        flash('Меню на сегодня не составлено')
        return redirect(url_for('student_menu'))

    if meal_type == 'breakfast':
        dishes = [menu_set['breakfast_main'], menu_set['breakfast_drink']]
    else:
        dishes = [menu_set['lunch_first'], menu_set['lunch_second'], menu_set['lunch_drink']]

    for dish in dishes:
        ingredients = db.execute('''
            SELECT dr.ingredient, dr.quantity, i.quantity as stock
            FROM dish_recipes dr
            JOIN inventory i ON dr.ingredient = i.product_name
            WHERE dr.dish_name = ?
        ''', (dish,)).fetchall()
        for ing in ingredients:
            if ing['stock'] < ing['quantity']:
                flash(f'Не хватает "{ing["ingredient"]}" для "{dish}"')
                return redirect(url_for('student_menu'))

    has_sub = db.execute('''
        SELECT 1 FROM subscriptions 
        WHERE student_id = ? AND status = 'active' AND ? BETWEEN start_date AND end_date
    ''', (session['user_id'], today)).fetchone()

    total_price = 0
    if not has_sub:
        for dish in dishes:
            price_row = db.execute('SELECT price FROM dishes WHERE name = ?', (dish,)).fetchone()
            if not price_row:
                flash(f'Блюдо "{dish}" не найдено')
                return redirect(url_for('student_menu'))
            total_price += price_row['price']

        profile = db.execute('SELECT balance FROM student_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
        if not profile or profile['balance'] < total_price:
            current = profile['balance'] if profile else 0
            flash(f'Недостаточно средств. Нужно: {total_price} ₽, у вас: {current} ₽')
            return redirect(url_for('student_menu'))

    for dish in dishes:
        ingredients = db.execute('SELECT ingredient, quantity FROM dish_recipes WHERE dish_name = ?',
                                 (dish,)).fetchall()
        for ing in ingredients:
            db.execute('UPDATE inventory SET quantity = quantity - ? WHERE product_name = ?',
                       (ing['quantity'], ing['ingredient']))

    if not has_sub:
        db.execute('UPDATE student_profiles SET balance = balance - ? WHERE user_id = ?',
                   (total_price, session['user_id']))
        db.execute('INSERT INTO payments (student_id, amount, payment_type, description) VALUES (?, ?, "one-time", ?)',
                   (session['user_id'], total_price, f'Оплата за {meal_type}'))

    db.execute('INSERT INTO meal_records (student_id, menu_id, meal_type) VALUES (?, ?, ?)',
               (session['user_id'], menu_set['id'], meal_type))
    db.commit()


    send_notification(session['user_id'], f'Вы получили {meal_type}!')

    cook_id = db.execute("SELECT id FROM users WHERE role = 'cook' LIMIT 1").fetchone()
    if cook_id:
        if has_sub:
            send_notification(cook_id['id'], f'Ученик {session["full_name"]} получил {meal_type} по абонементу.')
        else:
            send_notification(cook_id['id'],
                              f'Ученик {session["full_name"]} получил {meal_type}. Списано: {total_price} ₽.')

    flash(f'Вы получили {meal_type}!')
    return redirect(url_for('student_menu'))


@app.route('/student/payment', methods=['GET', 'POST'])
def student_payment():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    PRICES = {
        'week': 300,
        'month': 1000,
        'year': 10000
    }

    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    today = date.today()

    if request.method == 'POST':
        duration = request.form['duration']
        if duration not in PRICES:
            flash('Недопустимый срок абонемента')
            return redirect(url_for('student_payment'))

        amount = PRICES[duration]


        if duration == 'week':
            days_to_add = 7
        elif duration == 'month':
            days_to_add = 30
        else:
            days_to_add = 365


        profile = db.execute('SELECT balance FROM student_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
        if not profile or profile['balance'] < amount:
            flash(f'Недостаточно средств для покупки абонемента. Нужно: {amount} ₽')
            return redirect(url_for('student_payment'))


        current_end_row = db.execute('''
            SELECT end_date FROM subscriptions 
            WHERE student_id = ? AND status = 'active' AND end_date >= ?
            ORDER BY end_date DESC LIMIT 1
        ''', (session['user_id'], today)).fetchone()


        start_from = today
        if current_end_row:
            start_from = date.fromisoformat(current_end_row['end_date'])

        new_end_date = start_from + timedelta(days=days_to_add)


        db.execute('UPDATE student_profiles SET balance = balance - ? WHERE user_id = ?', (amount, session['user_id']))

        db.execute('''
            INSERT INTO payments (student_id, amount, payment_type, description)
            VALUES (?, ?, 'subscription', ?)
        ''', (session['user_id'], amount, f'Абонемент на {duration}'))


        db.execute('''
            INSERT INTO subscriptions (student_id, duration, start_date, end_date)
            VALUES (?, ?, ?, ?)
        ''', (session['user_id'], duration, start_from, new_end_date))


        send_notification(session['user_id'], f'Абонемент активирован до {new_end_date}!')

        db.commit()
        flash(f'Абонемент продлён до {new_end_date}!')
        return redirect(url_for('student_payment'))


    profile = db.execute('SELECT balance FROM student_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
    balance = profile['balance'] if profile else 0


    active_sub = db.execute('''
        SELECT duration, end_date
        FROM subscriptions 
        WHERE student_id = ? AND status = 'active' AND end_date >= ?
        ORDER BY end_date DESC
        LIMIT 1
    ''', (session['user_id'], today)).fetchone()

    return render_template(
        'student/payment.html',
        balance=balance,
        active_sub=active_sub,
        prices=PRICES,
        unread_count=unread_count
    )



@app.route('/student/card_topup', methods=['GET', 'POST'])
def student_card_topup():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount_str = request.form.get('amount', '').strip()
        try:
            amount = float(amount_str)
            if amount <= 0:
                amount = 100.0
        except (ValueError, TypeError):
            amount = 100.0

        card_number = request.form.get('card_number', '')
        expiry = request.form.get('expiry', '')
        cvv = request.form.get('cvv', '')

        card_digits = re.sub(r'\D', '', card_number)
        if not card_digits:
            card_digits = '0000000000000000'
        encrypted_card = fernet.encrypt(card_digits.encode()).decode()

        db = get_db()
        unread_count = get_unread_notifications_count(session['user_id'], db)
        db.execute('''
            UPDATE student_profiles 
            SET encrypted_card_number = ?, card_expiry = ?
            WHERE user_id = ?
        ''', (encrypted_card, expiry, session['user_id']))

        db.execute('UPDATE student_profiles SET balance = balance + ? WHERE user_id = ?', (amount, session['user_id']))
        db.execute('''
            INSERT INTO payments (student_id, amount, payment_type, description)
            VALUES (?, ?, 'one-time', 'Пополнение с карты')
        ''', (session['user_id'], amount))
        db.commit()

        flash(f'Баланс пополнен на {amount:.2f} ₽!')
        return redirect(url_for('student_payment'))

    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    return render_template('student/card_topup.html', unread_count=unread_count)


@app.route('/student/profile', methods=['GET', 'POST'])
def student_profile():
    if session.get('role') != 'student':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    if request.method == 'POST':
        allergies = request.form.get('allergies', '')
        prefs = request.form.get('preferences', '')
        db.execute('UPDATE student_profiles SET allergies = ?, preferences = ? WHERE user_id = ?',
                   (allergies, prefs, session['user_id']))
        db.commit()
        flash('Данные сохранены')
    profile = db.execute('SELECT * FROM student_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
    return render_template('student/profile.html', profile=profile, unread_count=unread_count)


@app.route('/student/reviews', methods=['GET', 'POST'])
def student_reviews():
    if session.get('role') != 'student':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    if request.method == 'POST':
        dish = request.form['dish']
        rating = int(request.form['rating'])
        comment = request.form.get('comment', '')
        db.execute('INSERT INTO reviews (student_id, dish_name, rating, comment) VALUES (?, ?, ?, ?)',
                   (session['user_id'], dish, rating, comment))
        db.commit()

        admin_id = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        cook_id = db.execute("SELECT id FROM users WHERE role = 'cook' LIMIT 1").fetchone()

        if admin_id:
            send_notification(admin_id['id'], f'Новый отзыв от {session["full_name"]} о блюде "{dish}"')
        if cook_id:
            send_notification(cook_id['id'], f'Новый отзыв от {session["full_name"]} о блюде "{dish}": {rating} ⭐')

        flash('Отзыв отправлен')
    reviews = db.execute('SELECT * FROM reviews WHERE student_id = ?', (session['user_id'],)).fetchall()
    return render_template('student/reviews.html', reviews=reviews, unread_count=unread_count)


@app.route('/cook/dashboard')
def cook_dashboard():
    if session.get('role') != 'cook':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    records = db.execute('''
        SELECT mr.id, u.full_name, ms.meal_date, mr.meal_type, mr.taken_at, mr.confirmed
        FROM meal_records mr
        JOIN users u ON mr.student_id = u.id
        JOIN menu_sets ms ON mr.menu_id = ms.id
        WHERE date(mr.taken_at) = date('now')
        ORDER BY mr.taken_at DESC
    ''').fetchall()
    return render_template('cook/dashboard.html', records=records, unread_count=unread_count)


@app.route('/cook/confirm_meal/<int:record_id>')
def cook_confirm_meal(record_id):
    if session.get('role') != 'cook':
        return redirect(url_for('login'))
    db = get_db()
    db.execute('UPDATE meal_records SET confirmed = 1 WHERE id = ?', (record_id,))
    db.commit()
    flash('Выдача подтверждена!')
    return redirect(url_for('cook_dashboard'))


@app.route('/cook/inventory', methods=['GET', 'POST'])
def cook_inventory():
    if session.get('role') != 'cook':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    if request.method == 'POST':
        items = request.form['items']
        db.execute('INSERT INTO purchase_requests (cook_id, items) VALUES (?, ?)',
                   (session['user_id'], items))
        db.commit()


        admin_id = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        if admin_id:
            send_notification(admin_id['id'], f'Новая заявка от повара {session["full_name"]}')

        flash('Заявка отправлена администратору')
    inventory = db.execute('SELECT * FROM inventory ORDER BY product_name').fetchall()
    requests = db.execute('SELECT * FROM purchase_requests WHERE cook_id = ?', (session['user_id'],)).fetchall()
    return render_template('cook/inventory.html', inventory=inventory, requests=requests, unread_count=unread_count)


@app.route('/cook/prepare', methods=['GET'])
def cook_prepare():
    if session.get('role') != 'cook':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    search = request.args.get('search', '').strip()

    if search:
        dishes = db.execute('''
            SELECT name, price FROM dishes 
            WHERE name LIKE ?
            ORDER BY name
        ''', (f'%{search}%',)).fetchall()
    else:
        dishes = db.execute('SELECT name, price FROM dishes ORDER BY name').fetchall()

    recipes = {}
    available = {}

    for dish in dishes:
        rows = db.execute('''
            SELECT ingredient, quantity, unit 
            FROM dish_recipes 
            WHERE dish_name = ?
        ''', (dish['name'],)).fetchall()

        unique_ings = {}
        for row in rows:
            ing = row['ingredient']
            if ing not in unique_ings:
                unique_ings[ing] = {
                    'ingredient': ing,
                    'quantity': row['quantity'],
                    'unit': row['unit']
                }
        recipes[dish['name']] = list(unique_ings.values())

        can_cook = True
        for ing in unique_ings.values():
            stock_row = db.execute('SELECT quantity FROM inventory WHERE product_name = ?',
                                   (ing['ingredient'],)).fetchone()
            if not stock_row or stock_row['quantity'] < ing['quantity']:
                can_cook = False
                break
        available[dish['name']] = can_cook

    return render_template('cook/prepare.html', dishes=dishes, recipes=recipes, available=available, search=search,
                           unread_count=unread_count)


@app.route('/cook/prepare_dish/<dish_name>', methods=['POST'])
def cook_prepare_dish(dish_name):
    if session.get('role') != 'cook':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)

    try:
        quantity = int(request.form.get('quantity', 1))
        if quantity < 1:
            quantity = 1
        if quantity > 100:
            flash('Максимум 100 порций за раз')
            return redirect(url_for('cook_prepare'))
    except (ValueError, TypeError):
        quantity = 1

    dish = db.execute('SELECT 1 FROM dishes WHERE name = ?', (dish_name,)).fetchone()
    if not dish:
        flash('Блюдо не найдено')
        return redirect(url_for('cook_prepare'))

    ingredients = db.execute('''
        SELECT dr.ingredient, dr.quantity, i.quantity as stock
        FROM dish_recipes dr
        LEFT JOIN inventory i ON dr.ingredient = i.product_name
        WHERE dr.dish_name = ?
    ''', (dish_name,)).fetchall()

    for ing in ingredients:
        if not ing['stock'] or ing['stock'] is None:
            flash(f'Ингредиент "{ing["ingredient"]}" отсутствует на складе')
            return redirect(url_for('cook_prepare'))
        needed = round(ing['quantity'] * quantity, 2)
        if ing['stock'] < needed:
            flash(f'Не хватает "{ing["ingredient"]}" для {quantity} порций "{dish_name}"')
            return redirect(url_for('cook_prepare'))

    for ing in ingredients:
        needed = round(ing['quantity'] * quantity, 2)
        current = db.execute('SELECT quantity FROM inventory WHERE product_name = ?', (ing['ingredient'],)).fetchone()
        if not current or current['quantity'] < needed:
            flash('Ошибка: недостаточно ингредиентов (состояние склада изменилось)')
            return redirect(url_for('cook_prepare'))

        db.execute('''
            UPDATE inventory 
            SET quantity = ROUND(quantity - ?, 2)
            WHERE product_name = ?
        ''', (needed, ing['ingredient']))

    db.execute('INSERT INTO prepared_dishes (dish_name, quantity) VALUES (?, ?)', (dish_name, quantity))
    db.commit()
    flash(f'Приготовлено {quantity} порций "{dish_name}"!')
    return redirect(url_for('cook_prepared'))


@app.route('/cook/prepared')
def cook_prepared():
    if session.get('role') != 'cook':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    prepared = db.execute('''
        SELECT dish_name, SUM(quantity) as total
        FROM prepared_dishes
        GROUP BY dish_name
        ORDER BY dish_name
    ''').fetchall()
    return render_template('cook/prepared.html', prepared=prepared, unread_count=unread_count)


@app.route('/cook/add_dish', methods=['GET', 'POST'])
def cook_add_dish():
    if session.get('role') != 'cook':
        return redirect(url_for('login'))

    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)

    if request.method == 'POST':
        dish_name = request.form['dish_name'].strip()
        try:
            price = float(request.form['price'])
        except (ValueError, TypeError):
            flash('Цена должна быть числом')
            return redirect(url_for('cook_add_dish'))

        if not dish_name or price <= 0:
            flash('Название и цена обязательны')
            return redirect(url_for('cook_add_dish'))

        ingredients = request.form.getlist('ingredient[]')
        quantities = request.form.getlist('quantity[]')
        units = request.form.getlist('unit[]')

        if not any(ing.strip() for ing in ingredients):
            flash('Добавьте хотя бы один ингредиент')
            return redirect(url_for('cook_add_dish'))

        try:
            db.execute('INSERT INTO dishes (name, price) VALUES (?, ?)', (dish_name, price))
            for i in range(len(ingredients)):
                ing = ingredients[i].strip()
                qty_str = quantities[i].strip()
                unit = units[i].strip()
                if not ing or not qty_str or not unit:
                    continue
                try:
                    qty = float(qty_str)
                    if qty <= 0:
                        continue
                except ValueError:
                    continue
                db.execute('''
                    INSERT INTO dish_recipes (dish_name, ingredient, quantity, unit)
                    VALUES (?, ?, ?, ?)
                ''', (dish_name, ing, qty, unit))
            db.commit()
            flash(f'Блюдо "{dish_name}" добавлено!')
            return redirect(url_for('cook_prepare'))
        except sqlite3.IntegrityError:
            flash('Блюдо с таким названием уже существует')
            return redirect(url_for('cook_add_dish'))

    inventory = db.execute('SELECT product_name FROM inventory ORDER BY product_name').fetchall()
    return render_template('cook/add_dish.html', inventory=inventory, unread_count=unread_count)


@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    total_payments = db.execute('SELECT SUM(amount) FROM payments').fetchone()[0] or 0
    today_attendance = db.execute('''
        SELECT COUNT(DISTINCT student_id) 
        FROM meal_records 
        WHERE date(taken_at) = date('now')
    ''').fetchone()[0]
    total_students = db.execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0]

    stats = {
        'total_payments': total_payments,
        'today_attendance': today_attendance,
        'total_students': total_students
    }

    requests = db.execute('''
        SELECT pr.id, pr.items, pr.status, u.full_name, pr.cook_id
        FROM purchase_requests pr
        JOIN users u ON pr.cook_id = u.id
        WHERE pr.status = 'pending'
    ''').fetchall()

    return render_template('admin/dashboard.html', stats=stats, requests=requests, unread_count=unread_count)


@app.route('/admin/approve_request/<int:req_id>')
def admin_approve_request(req_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    db = get_db()
    request_row = db.execute('SELECT items, cook_id FROM purchase_requests WHERE id = ?', (req_id,)).fetchone()
    if not request_row:
        flash('Заявка не найдена')
        return redirect(url_for('admin_dashboard'))


    send_notification(request_row['cook_id'], f'Ваша заявка №{req_id} одобрена! Продукты добавлены на склад.')

    items_text = request_row['items']
    lines = items_text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line or ' ' not in line:
            continue

        parts = line.split()
        try:
            quantity = float(parts[-1].replace(',', '.'))
            product_name = ' '.join(parts[:-1]).strip()
            if not product_name:
                continue
            db.execute('''
                INSERT INTO inventory (product_name, quantity, unit)
                VALUES (?, ?, 'шт')
                ON CONFLICT(product_name) 
                DO UPDATE SET quantity = quantity + excluded.quantity
            ''', (product_name, quantity))
        except (ValueError, IndexError):
            continue

    db.execute('UPDATE purchase_requests SET status = "approved", approved_by = ? WHERE id = ?',
               (session['user_id'], req_id))
    db.commit()
    flash('Заявка одобрена! Продукты добавлены на склад.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/operations')
def admin_operations():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    operations = []

    payments = db.execute('''
        SELECT 'Платёж' as type, p.amount, p.payment_type, u.full_name, p.created_at
        FROM payments p
        JOIN users u ON p.student_id = u.id
        ORDER BY p.created_at DESC
        LIMIT 50
    ''').fetchall()

    meals = db.execute('''
        SELECT 'Питание' as type, mr.meal_type, '' as payment_type, u.full_name, mr.taken_at
        FROM meal_records mr
        JOIN users u ON mr.student_id = u.id
        ORDER BY mr.taken_at DESC
        LIMIT 50
    ''').fetchall()

    all_ops = []
    for p in payments:
        category = "Абонемент" if p['payment_type'] == 'subscription' else "Разовое пополнение"
        all_ops.append({
            'type': 'Платёж',
            'detail': f"{p['amount']:.2f} ₽ ({category})",
            'user': p['full_name'],
            'date': p['created_at']
        })
    for m in meals:
        all_ops.append({
            'type': 'Питание',
            'detail': m['meal_type'],
            'user': m['full_name'],
            'date': m['taken_at']
        })

    all_ops.sort(key=lambda x: x['date'], reverse=True)
    operations = all_ops[:100]

    return render_template('admin/operations.html', operations=operations, unread_count=unread_count)


@app.route('/admin/report/<period>')
def admin_report_csv(period):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    db = get_db()
    output = StringIO()

    headers = ["Тип записи", "Период", "Дата формирования", "ID ученика", "ФИО ученика", "Сумма / Тип питания",
               "Категория", "Дата операции"]
    output.write(";".join(headers) + "\n")

    today = date.today()
    if period == 'week':
        start_date = today - timedelta(days=7)
        period_label = "Последняя неделя"
        filename = "Otchet_za_nedelyu.csv"
        filename_ru = f"Отчёт_за_неделю_{today}.csv"
    elif period == 'month':
        start_date = today - timedelta(days=30)
        period_label = "Последний месяц"
        filename = "Otchet_za_mesyac.csv"
        filename_ru = f"Отчёт_за_месяц_{today}.csv"
    else:
        start_date = None
        period_label = "Всё время"
        filename = "Polnyj_otchet.csv"
        filename_ru = f"Полный_отчёт_{today}.csv"

    report_date = datetime.now().strftime('%Y-%m-%d %H:%M')

    def safe_str(s):
        if s is None:
            return ""
        s = str(s).replace('"', '""')
        if ',' in s or ';' in s or '\n' in s or '"' in s:
            return f'"{s}"'
        return s

    if start_date:
        payments = db.execute('''
            SELECT p.student_id, u.full_name, p.amount, p.payment_type, p.created_at
            FROM payments p
            JOIN users u ON p.student_id = u.id
            WHERE p.created_at >= ?
            ORDER BY p.created_at
        ''', (start_date.isoformat(),)).fetchall()
    else:
        payments = db.execute('''
            SELECT p.student_id, u.full_name, p.amount, p.payment_type, p.created_at
            FROM payments p
            JOIN users u ON p.student_id = u.id
            ORDER BY p.created_at
        ''').fetchall()

    for p in payments:
        category = "Абонемент" if p['payment_type'] == 'subscription' else "Разовое пополнение"
        row = [
            "Платёж",
            period_label,
            report_date,
            str(p['student_id']),
            safe_str(p['full_name']),
            f"{p['amount']:.2f}",
            category,
            p['created_at'][:10]
        ]
        output.write(";".join(row) + "\n")

    if start_date:
        meals = db.execute('''
            SELECT mr.student_id, u.full_name, ms.meal_date, mr.meal_type
            FROM meal_records mr
            JOIN users u ON mr.student_id = u.id
            JOIN menu_sets ms ON mr.menu_id = ms.id
            WHERE mr.taken_at >= ?
            ORDER BY mr.taken_at
        ''', (start_date.isoformat(),)).fetchall()
    else:
        meals = db.execute('''
            SELECT mr.student_id, u.full_name, ms.meal_date, mr.meal_type
            FROM meal_records mr
            JOIN users u ON mr.student_id = u.id
            JOIN menu_sets ms ON mr.menu_id = ms.id
            ORDER BY mr.taken_at
        ''').fetchall()

    for m in meals:
        row = [
            "Питание",
            period_label,
            report_date,
            str(m['student_id']),
            safe_str(m['full_name']),
            safe_str(m['meal_type']),
            "",
            m['meal_date']
        ]
        output.write(";".join(row) + "\n")

    csv_data = output.getvalue().encode('utf-8-sig')
    quoted_filename = quote(filename_ru, encoding='utf-8')

    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{quoted_filename}"
        }
    )


@app.route('/admin/reports')
def admin_reports():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    return render_template('admin/reports.html', unread_count=unread_count)


@app.route('/admin/users')
def admin_users():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    db = get_db()
    unread_count = get_unread_notifications_count(session['user_id'], db)
    users = db.execute('''
        SELECT id, full_name, role 
        FROM users 
        WHERE role IN ('student', 'cook')
        ORDER BY role, full_name
    ''').fetchall()
    return render_template('admin/users.html', users=users, unread_count=unread_count)



@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    notifs = db.execute('''
        SELECT id, message, is_read, created_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()

    db.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (session['user_id'],))
    db.commit()

    unread_count = 0
    return render_template('notifications.html', notifications=notifs, unread_count=unread_count)


@app.route('/notification/<int:notification_id>/delete')
def delete_notification(notification_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    db.execute('DELETE FROM notifications WHERE id = ? AND user_id = ?', (notification_id, session['user_id']))
    db.commit()
    return redirect(url_for('notifications'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)