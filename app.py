from functools import wraps
from flask import Flask, request
from markupsafe import escape
from flask import render_template, redirect, url_for, session, flash, make_response
from flask_sqlalchemy import SQLAlchemy

import jwt
from datetime import datetime, timedelta

from pydantic import BaseModel, computed_field
from typing import Annotated, List

app = Flask(__name__)


# SQLite example (you can change to PostgreSQL/MySQL)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mydatabase.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = "azeem1233"

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(12))

    team_lead_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # points to Admin
    team_members = db.relationship('User', backref=db.backref('team_lead', remote_side=[id]), lazy=True)


    def __init__(self, username, password, role="Admin", team_lead_id=None):
        super().__init__()
        self.username = username
        self.password = password
        self.role = role
        self.team_lead_id = team_lead_id

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    content = db.Column(db.String(500), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    deadline = db.Column(db.DateTime, nullable=True)


    def __init__(self, created_by, content, points, deadline=lambda: datetime.utcnow() + timedelta(days=1)):
        self.created_by = created_by
        self.content = content
        self.points = points
        self.deadline = deadline
        
class Task_Assigned(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    admin = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    worker = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    task = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    status = db.Column(db.String(10))

    task_data = db.relationship("Task", backref="assignments")

    def __init__(self, admin, worker, task, status="Pending"):
        self.admin = admin
        self.worker = worker
        self.task = task
        self.status = status

class StudentStats:
    def __init__(self, task_assigned: Task_Assigned):
        self.task_assigned = task_assigned

    @property
    def id(self) -> int:
        return self.task_assigned.worker

    @property
    def name(self) -> str:
        user = User.query.filter_by(id=self.id).first()
        return user.username

    @property
    def completed_tasks(self) -> list:
        return Task_Assigned.query.filter_by(worker=self.id, status="Completed").all()

    @property
    def completed(self) -> int:
        return len(self.completed_tasks)

    @property
    def uncompleted(self) -> int:
        return Task_Assigned.query.filter_by(worker=self.id, status="Pending").count()

    @property
    def progress(self) -> float:
        total = self.completed + self.uncompleted
        return round((self.completed / total) * 100, 2) if total > 0 else 0

    @property
    def points(self) -> int:
        return sum(
            Task.query.get(task.task).points
            for task in self.completed_tasks
            if Task.query.get(task.task)
        )


def create_token(user_id):
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow()+timedelta(hours=1),
        "iat": datetime.utcnow(),
    }

    token = jwt.encode(payload, app.secret_key, algorithm="HS256")

    return token

def decode_token(token):
    try:
        decoded_token = jwt.decode(token, app.secret_key, algorithms=["HS256"])
        return decoded_token.get("user_id")
    except jwt.ExpiredSignatureError:
        print("Token expired!")
        return None
    except jwt.InvalidTokenError:
        print("Invalid token!")
        return None

def jwt_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        access_token = request.cookies.get("access_token", "")
        if access_token:
            user_id = decode_token(access_token)
            if user_id:
                request.user_id = user_id
                return func(*args, **kwargs)
            else:
                flash("Token Is Not Valid! Please Login Again", "error")
        else:
            flash("Token Not Found Please Login!", "info")
        return redirect(url_for("login", next=request.path))
    return wrapper

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = request.user_id
        user = User.query.filter_by(id=user_id, role="Admin").first()
        if user:
            return func(*args, **kwargs)
        else:
            flash("You are not and Admin!", "info")
            return redirect(url_for("index"))
    return wrapper

@app.route('/')
@jwt_required
def index():
    my_user = User.query.filter_by(id=request.user_id).first()
    if my_user:
        user = my_user.username
        user_id = my_user.id
        role = my_user.role
        total_points = 0
        if my_user.role is not "Admin":
            tasks_assigned = Task_Assigned.query.filter_by(worker=user_id, status="Completed").all()
            for task_ in tasks_assigned:
                total_points += task_.task_data.points
        return render_template('index.html', user_name=user, user_id=user_id, role=role, total_points=total_points)
    else:
        flash("You have to login to access this page!", "error")
        return(redirect(url_for("login")))
    
@app.route('/students', methods=['GET', 'POST'])
@jwt_required
@admin_required
def students():
    if request.method == "GET":
        admin = User.query.get(request.user_id)
        students = admin.team_members
        username = request.args.get("username", "").strip()
        found_student = None
        my_user = User.query.filter_by(id=request.user_id).first()
        if my_user:
            user = my_user.username
            user_id = my_user.id
            role = my_user.role
        if username:
            found_student = User.query.filter_by(username=username, team_lead_id=admin.id).first()
            if not found_student:
                flash("Student not found!", "info")
        return render_template("admin/students.html", students=students, found_student=found_student, user=user, user_id=user_id, role=role)
    elif request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        _method = request.form.get("_method", "")
        if not _method:
            if username and password:
                found_user = User.query.filter_by(username=username).first()
                if found_user:
                    flash("Username is already taken!", "info")
                else:
                    student = User(username=username, password=password, role="Student", team_lead_id=request.user_id)
                    db.session.add(student)
                    db.session.commit()
                    flash(f"Student {student.username} is Created.", "success")
            else:
                flash("Thses Fields Are Required. [Username, Password]", "info")
        elif _method=="PUT":
            user_id = request.form.get("user_id", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            found_student = User.query.filter_by(id=user_id).first()
            if found_student:
                found_student.username = username
                found_student.password = password
                db.session.commit()
                flash("Student Updated Successfully!", "success")
            else:
                flash("Student not found!", "error")
        elif _method=="DELETE":
            user_id = request.form.get("user_id", "").strip()
            found_student = User.query.filter_by(id=user_id).first()
            if found_student:
                db.session.delete(found_student)
                db.session.commit()
                flash("Student Deleted Successfully!", "success")
            else:
                flash("Student not found!", "error")
    return redirect(url_for("students"))

@app.route('/tasks', methods=['GET', 'POST'])
@jwt_required
@admin_required
def tasks():
    if request.method == "GET":
        tasks = Task.query.filter_by(created_by=request.user_id).all()
        task_id = request.args.get("task_id", "").strip()
        found_task = None
        if task_id:
            found_task = Task.query.filter_by(id=task_id, created_by=request.user_id).first()
            if not found_task:
                flash("Task not found!", "info")
        my_user = User.query.filter_by(id=request.user_id).first()
        if my_user:
            user = my_user.username
            user_id = my_user.id
            role = my_user.role
        print(found_task)
        return render_template("admin/tasks.html", tasks=tasks, found_task=found_task, user=user, user_id=user_id, role=role)

    elif request.method == "POST":
        content = request.form.get("content", "").strip()
        points = request.form.get("points", "").strip()
        deadline_str = request.form.get("deadline", "").strip()
        _method = request.form.get("_method", "")

        # Convert deadline
        deadline = None
        if deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                flash("Invalid deadline format.", "error")
                return redirect(url_for("tasks"))

        if not _method:
            # Create Task
            if content and points and deadline:
                task = Task(created_by=request.user_id, content=content, points=int(points), deadline=deadline)
                db.session.add(task)
                db.session.commit()
                flash("Task Created Successfully!", "success")
            else:
                flash("All fields are required to create a task.", "info")

        elif _method == "PUT":
            # Update Task
            task_id = request.form.get("task_id", "").strip()
            found_task = Task.query.filter_by(id=task_id, created_by=request.user_id).first()
            if found_task:
                found_task.content = content
                found_task.points = int(points)
                found_task.deadline = deadline
                db.session.commit()
                flash("Task Updated Successfully!", "success")
            else:
                flash("Task not found!", "error")

        elif _method == "DELETE":
            # Delete Task
            task_id = request.form.get("task_id", "").strip()
            found_task = Task.query.filter_by(id=task_id, created_by=request.user_id).first()
            if found_task:
                db.session.delete(found_task)
                db.session.commit()
                flash("Task Deleted Successfully!", "success")
            else:
                flash("Task not found!", "error")

    return redirect(url_for("tasks"))

@app.route("/stats", methods=['GET'])
@jwt_required
@admin_required
def stats():
    tasks_assigned: Task_Assigned = Task_Assigned.query.filter_by(admin=request.user_id).all()
    unique_ids = set()
    stats = []
    for t in tasks_assigned:
        if t.worker not in unique_ids:
            unique_ids.add(t.worker)
            stats.append(StudentStats(task_assigned=t))
    my_user = User.query.filter_by(id=request.user_id).first()
    if my_user:
        user = my_user.username
        user_id = my_user.id
        role = my_user.role
    return render_template("admin/task_stats.html", stats=stats, my_user=my_user, user_id=user_id, role=role)
 
@app.route('/assign_task', methods=['GET', 'POST'])
@jwt_required
@admin_required
def assign_task():
    if request.method=='GET':
        tasks = Task.query.filter_by(created_by=request.user_id).all()
        students = User.query.filter_by(team_lead_id=request.user_id).all()
        my_user = User.query.filter_by(id=request.user_id).first()
        if my_user:
            user = my_user.username
            user_id = my_user.id
            role = my_user.role
        return render_template("admin/assign_task.html", tasks=tasks, students=students, user=user, user_id=user_id, role=role)
    else:
        students = request.form.getlist("student_ids")
        task_id = request.form.get("task_id", "")
        if task_id and students:
            for student_id in students:
                assign_task_obj = Task_Assigned(admin=request.user_id, worker=student_id, task=task_id)
                db.session.add(assign_task_obj)
                db.session.commit()
            flash("Task Assigned Successfully!", "success")
        else:
            flash("Required Fields [Task, Students (At least 1)]", "error")
        return redirect(url_for('stats'))

@app.route('/student_tasks', methods=['GET', 'POST'])
@jwt_required
def student_tasks():
    tasks_assigned = Task_Assigned.query.filter_by(worker=request.user_id).all()
    my_user = User.query.filter_by(id=request.user_id).first()
    if my_user:
        user = my_user.username
        user_id = my_user.id
        role = my_user.role
    return render_template("student/tasks.html", tasks_assigned=tasks_assigned, user=user, user_id=user_id, role=role)

@app.route('/toggle_task_status/<int:assigned_id>', methods=['POST'])
@jwt_required
def toggle_task_status(assigned_id):
    task = Task_Assigned.query.filter_by(id=assigned_id, worker=request.user_id).first()
    if task:
        task.status = "Completed" if task.status != "Completed" else "Pending"
        db.session.commit()
        flash("Task status updated!", "success")
    else:
        flash("Task not found or unauthorized!", "error")
    return redirect(url_for("student_tasks"))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method=="GET":
       username = session.get("username", "")
       next = request.args.get("next", None)
       return render_template('login.html', username=username, next_page=next)
    elif request.method=="POST":
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember_me = request.form.get('remember', '')
        found_user = User.query.filter_by(username=username).first()
        if username and password:
            if found_user:
                if found_user.password == password:
                    if request.args.get("next", ""):
                        response = make_response(redirect(request.args.get("next")))
                        token = create_token(found_user.id)
                        response.set_cookie("access_token", token, httponly=False)
                        flash("Logged in Successfuly!", "success")
                        return response
                    response = make_response(redirect(url_for("index")))
                    token = create_token(found_user.id)
                    response.set_cookie("access_token", token, httponly=False)
                    flash("Logged in Successfuly!", "success")
                    return response
                else:
                    flash("Password is Incorrect!", "error")
                    session['username'] = username
                    return redirect(url_for("login"))
            else:
                flash("User Not Found!", "error")
                return (redirect(url_for("login")))
        else:
            flash("Required Fields: [Username, Password]")
            return redirect(url_for("Login"))
    else:
        return f"Method {request.method} is not available!"
    
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method=="GET":
       return render_template('signup.html')
    elif request.method=="POST":
        username = request.form.get('username', "")
        password = request.form.get('password', "")
        confirm_password = request.form.get("confirm_password", "")
        if not (not username and not password and not confirm_password):
            found_user = User.query.filter_by(username=username).first()
            if found_user:
                flash("Username Already Taken!", "error")
                return redirect(url_for("signup"))
            else:
                if password == confirm_password: # Success
                    new_user = User(username=username, password=password)
                    db.session.add(new_user)
                    db.session.commit()
                    flash("Your Account Created Successfully!", "success")
                    return redirect(url_for("login"))
                else:
                    flash("Password is not equal to Confirm Password!", "error")
                    return redirect(url_for("signup"))
        else:
            flash("Fields Required: [Username, Password, Confirm Password]", "error")
            return redirect(url_for("signup"))
    else:
        return f"Method {request.method} is not available!"
    
@app.route("/logout")
def logout():
    token = request.cookies.get("access_token")
    if token:
        response = make_response(redirect(url_for("login")))
        response.delete_cookie("access_token")
        flash("Logged Out Successfully!", "success")
        return response
    else:
        flash("You have to login for logout!", "info")
        return redirect(url_for("login"))



if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)