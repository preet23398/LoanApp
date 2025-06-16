from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysql_connector import MySQL
from flask import make_response
from datetime import datetime
from flask import jsonify


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
    user_idd = session.get('user_id')
    cursor = mysql.connection.cursor(dictionary=True)

    # Total applications
    cursor.execute("SELECT COUNT(*) AS count FROM loan_applications WHERE user_id = %s", (user_idd,))
    total_applications = cursor.fetchone()['count']

    # Workflow counts
    cursor.execute("""
        SELECT w.workflow_id, w.name AS workflow_name, COUNT(la.application_id) AS count
        FROM workflows w
        LEFT JOIN loan_applications la 
            ON la.workflow_id = w.workflow_id AND la.user_id = %s
        GROUP BY w.workflow_id, w.name
    """, (user_idd,))
    workflow_counts = cursor.fetchall()

    # Status counts (excluding rejected)
    all_statuses = ['pending', 'in progress', 'credit check', 'under review', 'approved']
    placeholders = ','.join(['%s'] * len(all_statuses))
    query = f"""
        SELECT status, COUNT(*) AS count
        FROM loan_applications
        WHERE user_id = %s AND status IN ({placeholders})
        GROUP BY status
    """
    cursor.execute(query, (user_idd, *all_statuses))
    raw_status_counts = cursor.fetchall()
    status_dict = {row['status']: row['count'] for row in raw_status_counts}
    status_counts = [{'status': s, 'count': status_dict.get(s, 0)} for s in all_statuses]

    # Rejected count directly from rejected_applications table
    cursor.execute("""
        SELECT COUNT(*) AS count 
        FROM rejected_applications
        WHERE user_id = %s
    """, (user_idd,))
    rejected_count = cursor.fetchone()['count'] or 0

    # Stuck stage (longest time spent)
    cursor.execute("""
        SELECT 
            ws.stage_name,
            ROUND(AVG(TIMESTAMPDIFF(MINUTE, ash.updated_at, next_stage.next_updated_at) / 60), 2) AS avg_duration_hours
        FROM 
            application_stage_history ash
        JOIN 
            workflow_stages ws ON ash.stage_id = ws.stage_id
        JOIN 
            loan_applications la ON ash.application_id = la.application_id
        JOIN (
            SELECT 
                history_id,
                application_id,
                updated_at,
                LEAD(updated_at) OVER (PARTITION BY application_id ORDER BY updated_at) AS next_updated_at
            FROM application_stage_history
        ) next_stage ON ash.history_id = next_stage.history_id
        WHERE 
            next_stage.next_updated_at IS NOT NULL
            AND la.user_id = %s
        GROUP BY ash.stage_id
        ORDER BY avg_duration_hours DESC
        LIMIT 1
    """, (user_idd,))

    stuck_stage = cursor.fetchone()

    # Count of completed applications
    cursor.execute("""
        SELECT COUNT(DISTINCT ash.application_id) AS completed_applications
        FROM application_stage_history ash
        JOIN loan_applications la ON ash.application_id = la.application_id
        JOIN (
            SELECT workflow_id, MAX(stage_order) AS last_mandatory_order
            FROM workflow_stages
            WHERE is_mandatory = 1
            GROUP BY workflow_id
        ) ws_last ON la.workflow_id = ws_last.workflow_id
        JOIN (
            SELECT application_id, MAX(ws.stage_order) AS max_stage_order
            FROM application_stage_history ash2
            JOIN workflow_stages ws ON ash2.stage_id = ws.stage_id
            GROUP BY application_id
        ) app_stage ON ash.application_id = app_stage.application_id
        WHERE ash.application_id = app_stage.application_id
          AND app_stage.max_stage_order >= ws_last.last_mandatory_order
          AND la.user_id = %s;
    """, (user_idd,))
    completed_count = cursor.fetchone()['completed_applications']

    cursor.close()

    return render_template(
        'statistics.html',
        total_applications=total_applications,
        workflow_counts=workflow_counts,
        status_counts=status_counts,   # no rejected here
        rejected_count=rejected_count, # separate rejected count
        stuck_stage=stuck_stage,
        completed_count=completed_count
    )

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
    # Get user_id of the application
        cursor.execute("SELECT user_id FROM loan_applications WHERE application_id = %s", (application_id,))
        user_row = cursor.fetchone()
        if user_row:
            user_id = user_row[0]

        # Insert into rejected_applications
            cursor.execute(
            "INSERT INTO rejected_applications (user_id, application_id) VALUES (%s, %s)",
            (user_id, application_id)
            )

    # Now delete the application
    cursor.execute("DELETE FROM loan_applications WHERE application_id = %s", (application_id,))
    mysql.connection.commit()
    cursor.close()
    flash('Application rejected and deleted successfully.', 'success')
    return redirect(url_for('loan_requests'))


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
            cursor.execute("SELECT * FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error = "All fields are required."
            return render_template('new_application.html', clients=clients, error=error,
                                   client_data={}, doc_type='', file_path='', application_id=None)

        try:
            client_id = int(client_id)
            workflow_id = int(workflow_id)
            product_id = int(product_id)
            current_stage_id = int(current_stage_id)
        except ValueError:
            cursor.execute("SELECT * FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error = "Invalid numeric values in form."
            return render_template('new_application.html', clients=clients, error=error,
                                   client_data={}, doc_type='', file_path='', application_id=None)

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
            cursor.execute("SELECT * FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error = f"Database error: {err}"
            return render_template('new_application.html', clients=clients, error=error,
                                   client_data={}, doc_type='', file_path='', application_id=None)

    # GET request: fetch all client details
    cursor.execute("SELECT * FROM client")
    clients = cursor.fetchall()
    cursor.close()
    return render_template('new_application.html', clients=clients,
                           client_data={}, doc_type='', file_path='', application_id=None)



@app.route('/save_client_info', methods=['POST'])
def save_client_info():

    # Get basic client info
    first_name = request.form.get('first_name')
    middle_name = request.form.get('middle_name')
    last_name = request.form.get('last_name')
    gender = request.form.get('gender')
    dob = request.form.get('dob')
    age = request.form.get('age')
    marital_status = request.form.get('marital_status')
    father_name = request.form.get('father_name')
    mother_name = request.form.get('mother_name')
    spouse_name = request.form.get('spouse_name')
    education = request.form.get('education')
    phone = request.form.get('phone')
    email = request.form.get('email')

    # Get documents
    doc_types = request.form.getlist('doc_type[]')
    file_paths = request.form.getlist('file_path[]')

    cursor = mysql.connection.cursor()

     # Check for existing client by doc_type and file_path
    for doc_type, file_path in zip(doc_types, file_paths):
        query = """
            SELECT client_id FROM application_documents 
            WHERE doc_type = %s AND file_path = %s
        """
        cursor.execute(query, (doc_type, file_path))
        result = cursor.fetchone()

        if result:
            existing_client_id = result[0]
            cursor.execute("SELECT client_id FROM client")
            clients = cursor.fetchall()
            cursor.close()
            error_message = f"Client with the same documents exists. Select (Client ID: {existing_client_id}) in the existing clients dropdown"
            return render_template(
                'new_application.html',
                clients=clients,
                client_data={
                    'first_name': first_name,
                    'middle_name': middle_name,
                    'last_name': last_name,
                    'gender': gender,
                    'dob': dob,
                    'age': age,
                    'marital_status': marital_status,
                    'father_name': father_name,
                    'mother_name': mother_name,
                    'spouse_name': spouse_name,
                    'education': education,
                    'phone': phone,
                    'email': email
                },
                document_data=list(zip(doc_types, file_paths)),
                error=error_message
            )

    # No duplicates found: insert new client
    client_insert_query = """
        INSERT INTO client (
            first_name, middle_name, last_name, gender, dob, age, 
            marital_status, father_name, mother_name, spouse_name, 
            education, phone, email
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    client_data = (
        first_name, middle_name, last_name, gender, dob, age,
        marital_status, father_name, mother_name, spouse_name,
        education, phone, email
    )
    cursor.execute(client_insert_query, client_data)
    mysql.connection.commit()

    client_id = cursor.lastrowid

    # Insert application documents
    for doc_type, file_path in zip(doc_types, file_paths):
        doc_insert_query = """
            INSERT INTO application_documents (client_id, doc_type, file_path)
            VALUES (%s, %s, %s)
        """
        cursor.execute(doc_insert_query, (client_id, doc_type, file_path))

    mysql.connection.commit()
    cursor.close()

    # OPTIONAL: flash a success message (remove if you want no message at all)
    # flash("Client and documents saved successfully.", "success")
    return redirect(url_for('homepage'))



@app.route('/get_client_data/<int:client_id>')
def get_client_data(client_id):
    cursor = mysql.connection.cursor(dictionary=True)

    # Get client info
    cursor.execute("SELECT * FROM client WHERE client_id = %s", (client_id,))
    client = cursor.fetchone()

    # Get top 3 documents for client
    cursor.execute("""
        SELECT doc_type, file_path
        FROM application_documents
        WHERE client_id = %s
        ORDER BY uploaded_at DESC
        LIMIT 3
    """, (client_id,))
    documents = cursor.fetchall()

    cursor.close()

    if client:
        return jsonify({
            **client,
            "documents": documents
        })
    else:
        return jsonify({"error": "Client not found"}), 404

@app.route('/new_loan_application', methods=['GET', 'POST'])
def new_loan_application():
    cursor = mysql.connection.cursor(dictionary=True)

    if request.method == 'POST':
        client_id = request.form.get('client_id')
        workflow_id = request.form.get('workflow_id')
        product_id = request.form.get('product_id')
        loan_amount = request.form.get('loan_amount')

        # Get the first stage ID for the workflow
        cursor.execute("SELECT stage_id FROM workflow_stages WHERE workflow_id = %s ORDER BY stage_order ASC LIMIT 1", (workflow_id,))
        stage = cursor.fetchone()
        current_stage_id = stage['stage_id'] if stage else None

        # Insert new loan application
        cursor.execute("""
            INSERT INTO loan_applications (user_id, client_id, workflow_id, product_id, current_stage_id, status, loan_amount)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s)
        """, (session['user_id'], client_id, workflow_id, product_id, current_stage_id, loan_amount))
        mysql.connection.commit()

        cursor.close()

        return redirect(url_for('new_loan_application', success=1))

    # GET method
    cursor.execute("SELECT client_id, first_name, last_name FROM client")
    clients = cursor.fetchall()

    cursor.execute("""
        SELECT w.workflow_id, w.name, p.product_id, p.max_amount
        FROM workflows w
        JOIN loan_products p ON w.workflow_id = p.workflow_id
    """)
    workflows = cursor.fetchall()

    cursor.execute("SELECT product_id, name, workflow_id FROM loan_products")
    products = cursor.fetchall()

    cursor.close()

    return render_template(
        'new_loan_application.html',
        clients=clients,
        workflows=workflows,
        products=products,
        success=request.args.get('success')
    )



if __name__ == '__main__':
    app.run(debug=True)
