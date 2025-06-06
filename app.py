from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysql_connector import MySQL
from flask import make_response

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

    show_popup = False
    if user_data:
        email, phone = user_data
        if not email or not phone:
            show_popup = True

    response = make_response(render_template('homepage.html', show_popup=show_popup))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response


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
                error= "Wrong Password."
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

@app.route('/loan-requests')
def loan_requests():
    user_id = session.get('user_id')
    filter_type = request.args.get('filter')
    workflow_id = request.args.get('workflow_id')
    product_id = request.args.get('product_id')
    status = request.args.get('status')

    cur = mysql.connection.cursor(dictionary=True)

    base_query = """
        SELECT la.*, w.name AS workflow_name, lp.name AS product_name
        FROM loan_applications la
        JOIN workflows w ON la.workflow_id = w.workflow_id
        JOIN loan_products lp ON la.workflow_id = lp.workflow_id
        WHERE la.user_id = %s
    """
    params = [user_id]

    if filter_type == 'workflow' and workflow_id:
        base_query += " AND la.workflow_id = %s"
        params.append(workflow_id)
    elif filter_type == 'loan_product' and product_id:
        base_query += " AND lp.product_id = %s"
        params.append(product_id)
    elif filter_type == 'status' and status:
        base_query += " AND la.status = %s"
        params.append(status)

    cur.execute(base_query, tuple(params))
    applications = cur.fetchall()
    cur.close()

    return render_template('loan-requests.html', applications=applications)


@app.route('/statistics')
def statistics():
    return render_template('statistics.html')

@app.route('/alerts')
def alerts():
    return render_template('alerts.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route("/application/<int:application_id>")
def application_detail(application_id):
    cursor = mysql.connection.cursor(dictionary=True)

    cursor.execute("SELECT * FROM loan_applications WHERE application_id = %s", (application_id,))
    application = cursor.fetchone()

    if not application:
        cursor.close()
        return "Application not found", 404

    workflow_id = application['workflow_id']
    current_stage_id = application['current_stage_id']
    current_status = application.get('status')

    cursor.execute("SELECT * FROM workflow_stages WHERE workflow_id = %s ORDER BY stage_order", (workflow_id,))
    stages = cursor.fetchall()

    cursor.close()

    current_stage = next((s for s in stages if s['stage_id'] == current_stage_id), None)
    current_stage_order = current_stage['stage_order'] if current_stage else 0

    statuses = ['pending', 'in progress', 'credit check', 'under review', 'approved', 'rejected']

    return render_template("application_detail.html", 
                           application=application, 
                           stages=stages, 
                           current_stage_id=current_stage_id,
                           current_stage_order=current_stage_order,
                           statuses=statuses,
                           current_status=current_status)

@app.route('/update_stage/<int:application_id>', methods=['POST'])
def update_stage(application_id):
    next_order = request.form.get('next_stage_order')
    remark = request.form.get('remark')

    cursor = mysql.connection.cursor(dictionary=True)

    cursor.execute("SELECT * FROM loan_applications WHERE application_id = %s", (application_id,))
    application = cursor.fetchone()
    if not application:
        cursor.close()
        return "Application not found", 404

    workflow_id = application['workflow_id']

    username = session.get('username')
    cursor.execute("SELECT company_name FROM users WHERE username = %s", (username,))
    result = cursor.fetchone()
    company_name = result['company_name'] if result else 'Unknown'

    try:
        next_order_int = int(next_order)
    except (TypeError, ValueError):
        next_order_int = None

    if next_order_int is not None:
        cursor.execute("SELECT * FROM workflow_stages WHERE workflow_id = %s ORDER BY stage_order", (workflow_id,))
        stages = cursor.fetchall()
        next_stage = next((s for s in stages if s['stage_order'] == next_order_int), None)

        if next_stage:
            new_stage_id = next_stage['stage_id']

            cursor.execute("""
                UPDATE loan_applications SET current_stage_id = %s, status = %s WHERE application_id = %s
                """, (new_stage_id, 'pending', application_id))


            cursor.execute("""
                INSERT INTO application_stage_history (application_id, stage_id, updated_by, updated_at, remarks)
                VALUES (%s, %s, %s, NOW(), %s)
            """, (application_id, new_stage_id, company_name, remark))

            mysql.connection.commit()
            cursor.close()
            return redirect(url_for('application_detail', application_id=application_id))

    cursor.close()
    flash('Invalid stage selected.', 'error')
    return redirect(url_for('application_detail', application_id=application_id))

@app.route('/update_status/<int:application_id>', methods=['POST'])
def update_status(application_id):
    new_status = request.form.get('new_status')
    allowed_statuses = ['pending', 'in progress', 'credit check', 'under review', 'approved', 'rejected']

    if new_status not in allowed_statuses:
        flash('Invalid status selected.', 'error')
        return redirect(url_for('application_detail', application_id=application_id))

    cursor = mysql.connection.cursor()

    cursor.execute("SELECT application_id FROM loan_applications WHERE application_id = %s", (application_id,))
    if not cursor.fetchone():
        cursor.close()
        flash('Application not found.', 'error')
        return redirect(url_for('application_detail', application_id=application_id))

    if new_status == 'rejected':
        cursor.execute("DELETE FROM loan_applications WHERE application_id = %s", (application_id,))
        mysql.connection.commit()
        cursor.close()
        flash('Application rejected and deleted successfully.', 'success')
        return redirect(url_for('loan_requests'))  

    cursor.execute(
        "UPDATE loan_applications SET status = %s WHERE application_id = %s",
        (new_status, application_id)
    )
    mysql.connection.commit()
    cursor.close()

    flash('Status updated successfully!', 'success')
    return redirect(url_for('application_detail', application_id=application_id))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    return render_template('forgot_password.html')


@app.route('/new_application', methods=['GET', 'POST'])
def new_application():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor(dictionary=True)

    if request.method == 'POST':
        print("POST received")
        client_id = request.form.get('client_id')
        workflow_id = request.form.get('workflow_id')
        product_id = request.form.get('product_id')
        current_stage_id = request.form.get('current_stage_id')
        status = request.form.get('status')
        print(f"Received: client_id={client_id}, workflow_id={workflow_id}, product_id={product_id}, current_stage_id={current_stage_id}, status={status}")

        if not all([client_id, workflow_id, product_id, current_stage_id, status]):
            cursor.execute("SELECT client_id FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error = "All fields are required."
            return render_template('new_application.html', clients=clients, error=error)

        try:
            client_id = int(client_id)
            workflow_id = int(workflow_id)
            product_id = int(product_id)
            current_stage_id = int(current_stage_id)
        except ValueError:
            cursor.execute("SELECT client_id FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error = "Invalid numeric values in form."
            return render_template('new_application.html', clients=clients, error=error)

        try:
            sql = """
                INSERT INTO loan_applications 
                (user_id, client_id, workflow_id, product_id, current_stage_id, status) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (user_id, client_id, workflow_id, product_id, current_stage_id, status))
            mysql.connection.commit()
            cursor.close()
            print("Insert successful, redirecting to loan_requests")
            return redirect(url_for('loan_requests'))
        except Exception as err:
            print(f"DB insert error: {err}")
            cursor.execute("SELECT client_id FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error = f"Database error: {err}"
            return render_template('new_application.html', clients=clients, error=error)

    cursor.execute("SELECT client_id FROM client")
    clients = cursor.fetchall()
    cursor.close()
    return render_template('new_application.html', clients=clients)

if __name__ == '__main__':
    app.run(debug=True)
