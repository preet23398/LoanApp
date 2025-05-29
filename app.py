from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysql_connector import MySQL

app = Flask(__name__)
app.secret_key = 'your-very-secret-key-here'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Cherry.2005'
app.config['MYSQL_DATABASE'] = 'loan_db'

mysql = MySQL(app)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/homepage')
def homepage():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()
    cur.execute("SELECT email, phone FROM users WHERE user_id = %s", (user_id,))
    user_data = cur.fetchone()
    cur.close()

    # Check if any details are missing
    show_popup = False
    if user_data:
        email, phone = user_data
        if not email or not phone:
            show_popup = True

    return render_template('homepage.html', show_popup=show_popup)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    email = request.form.get('email')
    phone = request.form.get('phone')

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE users SET email=%s, phone=%s, created_at=NOW() WHERE user_id=%s
    """, (email, phone, user_id))
    mysql.connection.commit()
    cur.close()

    return redirect(url_for('homepage'))



@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        company_name = request.form.get('company_name')
        email = request.form.get('email')
        phone = request.form.get('phone')

        if not all([username, password, company_name, email, phone]):
            error = "Please fill all the required fields."
            return render_template('signup.html', error=error)

        cur = mysql.connection.cursor()

        # Check if username already exists in signup_requests or users
        cur.execute("SELECT 1 FROM signup_requests WHERE username = %s", (username,))
        if cur.fetchone():
            error = "Signup request already submitted."
            cur.close()
            return render_template('signup.html', error=error)

        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            error = "Username already exists."
            cur.close()
            return render_template('signup.html', error=error)

        # Insert the signup request with email, phone; created_at defaults to NOW()
        cur.execute("""
            INSERT INTO signup_requests (username, password, company_name, email, phone)
            VALUES (%s, %s, %s, %s, %s)
        """, (username, password, company_name, email, phone))

        mysql.connection.commit()
        cur.close()

        return render_template('to_be_approved.html', username=username)

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            error = "Please enter both username and password."
            return render_template('login.html', error=error)

        cur = mysql.connection.cursor()
        cur.execute("SELECT user_id, password FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()

        if user:
            user_id_db, stored_password = user
            if stored_password == password:
                session['user_id'] = user_id_db
                session['username'] = username
                return redirect(url_for('homepage'))
            else:
                error = "Wrong password entered."
        else:
            error = "Username not found."

    return render_template('login.html', error=error)


@app.route('/workflows')
def get_workflows():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM workflows")
    workflows = cur.fetchall()
    cur.close()
    return jsonify(workflows)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            error = "Please enter both username and password."
            return render_template('admin_login.html', error=error)

        cur = mysql.connection.cursor()
        cur.execute("SELECT employee_id, password FROM admin WHERE username = %s", (username,))
        admin = cur.fetchone()
        cur.close()

        if admin:
            employee_id_db, stored_password = admin
            if stored_password == password:
                session['admin_id'] = employee_id_db
                session['admin_username'] = username
                return redirect(url_for('admin_dashboard'))  # Create this route later
            else:
                error = "Wrong password entered."
        else:
            error = "Username not found."

    return render_template('admin_login.html', error=error)


@app.route('/admin/signup', methods=['GET', 'POST'])
def admin_signup():
    error = None
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        username = request.form.get('username')
        password = request.form.get('password')

        if not employee_id or not username or not password:
            error = "Please fill all required fields."
            return render_template('admin_signup.html', error=error)

        cur = mysql.connection.cursor()
        # Check if employee_id exists in admin table
        cur.execute("SELECT employee_id, username FROM admin WHERE employee_id = %s", (employee_id,))
        record = cur.fetchone()

        if not record:
            error = "Not a valid employee ID."
            cur.close()
            return render_template('admin_signup.html', error=error)

        # Check if username already exists for some other employee
        cur.execute("SELECT 1 FROM admin WHERE username = %s AND employee_id != %s", (username, employee_id))
        if cur.fetchone():
            error = "Username already exists."
            cur.close()
            return render_template('admin_signup.html', error=error)

        # Update the admin record with username and password for the given employee_id
        cur.execute("""
            UPDATE admin SET username = %s, password = %s WHERE employee_id = %s
        """, (username, password, employee_id))

        mysql.connection.commit()
        cur.close()

        return redirect(url_for('admin_login'))

    return render_template('admin_signup.html', error=error)



@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    return "Welcome Admin! (Dashboard placeholder)"


if __name__ == '__main__':
    app.run(debug=True)
