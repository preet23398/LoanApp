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

    show_popup = False
    if user_data:
        email, phone = user_data
        if not email or not phone:
            show_popup = True

    return render_template('homepage.html', show_popup=show_popup)


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

    # Get application details
    cursor.execute("SELECT * FROM loan_applications WHERE application_id = %s", (application_id,))
    application = cursor.fetchone()

    if not application:
        cursor.close()
        return "Application not found", 404

    workflow_id = application['workflow_id']
    current_stage_id = application['current_stage_id']

    # Get all stages for this workflow
    cursor.execute("SELECT * FROM workflow_stages WHERE workflow_id = %s ORDER BY stage_order", (workflow_id,))
    stages = cursor.fetchall()

    cursor.close()

    return render_template("application_detail.html", application=application, stages=stages, current_stage_id=current_stage_id)


@app.route('/update_stage/<int:application_id>', methods=['POST'])
def update_stage(application_id):
    new_stage_id = request.form.get('new_stage_id')
    
    if not new_stage_id:
        flash('No stage selected.', 'error')
        return redirect(url_for('application_detail', application_id=application_id))
    
    try:
        new_stage_id_int = int(new_stage_id)
    except ValueError:
        flash('Invalid stage selected.', 'error')
        return redirect(url_for('application_detail', application_id=application_id))

    cursor = mysql.connection.cursor()
    
    # Optional: Verify the stage belongs to the workflow of this application
    cursor.execute("SELECT workflow_id FROM loan_applications WHERE application_id = %s", (application_id,))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        flash('Application not found.', 'error')
        return redirect(url_for('application_detail', application_id=application_id))

    workflow_id = result[0]

    cursor.execute(
        "SELECT COUNT(*) FROM workflow_stages WHERE stage_id = %s AND workflow_id = %s",
        (new_stage_id_int, workflow_id)
    )
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.close()
        flash('Selected stage is not valid for this workflow.', 'error')
        return redirect(url_for('application_detail', application_id=application_id))
    
    # Update the application current_stage_id
    cursor.execute(
        "UPDATE loan_applications SET current_stage_id = %s WHERE application_id = %s",
        (new_stage_id_int, application_id)
    )
    mysql.connection.commit()
    cursor.close()

    flash('Stage updated successfully!', 'success')
    return redirect(url_for('application_detail', application_id=application_id))


if __name__ == '__main__':
    app.run(debug=True)
