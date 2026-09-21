import os
import random
import re
from datetime import datetime

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
    abort,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
    UserMixin,
)
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

from models import (
    db,
    User,
    Book,
    Problem,
    Review,
    Submission,
    Rating,
    BookRequest,
    REQUIRED_APPROVALS,
)
from gate import new_gate_puzzle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    BASE_DIR, "codeforge.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Sign in to keep going."
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


# utilities


def reviewer_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user.is_authenticated or not (
            current_user.is_reviewer or current_user.is_admin
        ):
            abort(403)
        return fn(*a, **kw)

    return wrapper


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return fn(*a, **kw)

    return wrapper


@app.context_processor
def inject_globals():
    pending_requests = 0
    if current_user.is_authenticated and current_user.is_admin:
        pending_requests = BookRequest.query.filter_by(status="pending").count()
    return {
        "REQUIRED_APPROVALS": REQUIRED_APPROVALS,
        "now": datetime.utcnow(),
        "pending_book_requests": pending_requests,
    }

def first_problems():
    firsts = []
    for book in Book.query.order_by(Book.sort_order.asc()).all():
        p = book.approved_problems.first()
        if p:
            firsts.append(p)
    return firsts


def set_gate():
    firsts = first_problems()
    if firsts:
        current = session.get("gate_problem_id")
        pool = [p for p in firsts if p.id != current] or firsts
        session["gate_problem_id"] = random.choice(pool).id
        session.pop("gate_prompt", None)
        session.pop("gate_hash", None)
    else:
        prompt, answer = new_gate_puzzle()
        session.pop("gate_problem_id", None)
        session["gate_prompt"] = prompt
        session["gate_hash"] = generate_password_hash(answer.strip().lower())


def current_gate():
    pid = session.get("gate_problem_id")
    if pid:
        p = Problem.query.get(pid)
        if p and p.status == "approved":
            return {
                "title": p.title,
                "label": f"{p.book.name} · Problem {p.number:02d}",
                "prompt": p.statement,
            }
        return None
    if session.get("gate_prompt") and session.get("gate_hash"):
        return {"title": None, "label": "Generated puzzle", "prompt": session["gate_prompt"]}
    return None


def gate_is_correct(answer):
    answer = (answer or "").strip()
    pid = session.get("gate_problem_id")
    if pid:
        p = Problem.query.get(pid)
        return bool(p and p.status == "approved" and p.check_answer(answer))
    return check_password_hash(session.get("gate_hash", ""), answer.lower())


def clear_gate():
    for k in ("gate_problem_id", "gate_prompt", "gate_hash"):
        session.pop(k, None)


# home


@app.route("/")
def index():
    books = Book.query.order_by(Book.sort_order.asc()).all()
    stats = {
        "problems": Problem.query.filter_by(status="approved").count(),
        "members": User.query.count(),
        "solves": Submission.query.filter_by(is_correct=True).count(),
    }
    recent = (
        Problem.query.filter_by(status="approved")
        .order_by(Problem.decided_at.desc())
        .limit(5)
        .all()
    )
    return render_template("index.html", books=books, stats=stats, recent=recent)


@app.route("/leaderboard")
def leaderboard():
    users = sorted(
        User.query.all(), key=lambda u: (-u.score, -u.solved_count, u.username.lower())
    )
    return render_template("leaderboard.html", users=users[:100])


# books/list


@app.route("/book/<slug>")
@login_required
def book_view(slug):
    book = Book.query.filter_by(slug=slug).first_or_404()
    problems = book.approved_problems.all()
    return render_template("book.html", book=book, problems=problems)


# problem


@app.route("/problem/<slug>", methods=["GET", "POST"])
@login_required
def problem_view(slug):
    problem = Problem.query.filter_by(slug=slug).first_or_404()
    if problem.status != "approved" and not (
        current_user.is_authenticated
        and (
            current_user.is_admin
            or current_user.id == problem.author_id
            or current_user.is_reviewer
        )
    ):
        abort(404)

    result = None
    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Sign in to submit an answer.", "info")
            return redirect(url_for("login"))
        guess = request.form.get("answer", "")
        correct = problem.check_answer(guess)
        sub = Submission(
            user_id=current_user.id, problem_id=problem.id, is_correct=correct
        )
        db.session.add(sub)
        db.session.commit()
        result = "correct" if correct else "incorrect"
        if correct:
            flash(f"Correct! +{problem.points} points.", "success")
        else:
            flash("Not quite. Give it another shot.", "error")

    my_rating = None
    if current_user.is_authenticated:
        r = Rating.query.filter_by(
            user_id=current_user.id, problem_id=problem.id
        ).first()
        my_rating = r.stars if r else None

    solved = problem.solved_by(current_user)
    attempts = 0
    if current_user.is_authenticated:
        attempts = problem.submissions.filter_by(user_id=current_user.id).count()

    feedback = []
    if (
        problem.status != "approved"
        and current_user.is_authenticated
        and (
            current_user.id == problem.author_id
            or current_user.is_reviewer
            or current_user.is_admin
        )
    ):
        feedback = problem.reviews_rel.order_by(Review.created_at.asc()).all()

    return render_template(
        "problem.html",
        problem=problem,
        result=result,
        my_rating=my_rating,
        solved=solved,
        attempts=attempts,
        feedback=feedback,
    )


@app.route("/problem/<slug>/rate", methods=["POST"])
@login_required
def rate_problem(slug):
    problem = Problem.query.filter_by(slug=slug).first_or_404()
    if not problem.solved_by(current_user):
        flash("Solve a problem before rating it.", "error")
        return redirect(url_for("problem_view", slug=slug))
    stars = max(1, min(5, int(request.form.get("stars", 0) or 0)))
    r = Rating.query.filter_by(user_id=current_user.id, problem_id=problem.id).first()
    if r:
        r.stars = stars
    else:
        r = Rating(user_id=current_user.id, problem_id=problem.id, stars=stars)
        db.session.add(r)
    db.session.commit()
    flash("Thanks for rating this problem!", "success")
    return redirect(url_for("problem_view", slug=slug))


# signin


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if current_gate() is None:
        set_gate()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        gate_answer = request.form.get("gate_answer", "")

        errors = []
        gate_ok = gate_is_correct(gate_answer)

        if not request.form.get('agree_terms'):
            errors.append("You must agree to the Terms and Conditions and the Privacy Policy to register.")
            

        
        if not gate_ok:
            errors.append(
                "That's not the right answer to the entry problem - give it another go."
            )
        if len(username) < 3:
            errors.append("Username needs to be at least 3 characters.")
        if len(password) < 6:
            errors.append("Password needs to be at least 6 characters.")
        if User.query.filter_by(username=username).first():
            errors.append("That username is already taken.")
        if User.query.filter_by(email=email).first():
            errors.append("That email is already registered.")

        if errors:
            for e in errors:
                flash(e, "error")
            if not gate_ok:
                set_gate()
            return render_template(
                "register.html",
                gate=current_gate(),
                username=username,
                email=email,
            )

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        clear_gate()
        login_user(user)
        flash(f"Welcome, {username} - you solved your way in.", "success")
        return redirect(url_for("index"))

    return render_template("register.html", gate=current_gate())


@app.route("/register/new-puzzle")
def register_new_puzzle():
    set_gate()
    return redirect(url_for("register"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        ident = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            (User.username == ident) | (User.email == ident.lower())
        ).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.username}.", "success")
            nxt = request.args.get("next")
            return redirect(nxt or url_for("index"))
        flash("Those credentials don't match.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("index"))


# dashboard


@app.route("/dashboard")
@login_required
def dashboard():
    solved_ids = [
        s.problem_id for s in current_user.submissions.filter_by(is_correct=True)
    ]
    solved_problems = (
        Problem.query.filter(Problem.id.in_(solved_ids)).all() if solved_ids else []
    )
    authored = current_user.authored.order_by(Problem.created_at.desc()).all()
    return render_template(
        "dashboard.html", solved_problems=solved_problems, authored=authored
    )


@app.route("/user/<username>")
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    solved_ids = [s.problem_id for s in user.submissions.filter_by(is_correct=True)]
    solved_problems = (
        Problem.query.filter(Problem.id.in_(solved_ids)).all() if solved_ids else []
    )
    return render_template(
        "profile.html", profile_user=user, solved_problems=solved_problems
    )


# writing new


@app.route("/write", methods=["GET", "POST"])
@login_required
def write_problem():
    books = Book.query.order_by(Book.name.asc()).all()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        book_id = request.form.get("book_id", type=int)
        statement = request.form.get("statement", "").strip()
        answer = request.form.get("answer", "").strip()
        difficulty = request.form.get("difficulty", type=int) or 1
        points = request.form.get("points", type=int) or 10

        errors = []
        if len(title) < 4:
            errors.append("Give the problem a real title.")
        if len(statement) < 20:
            errors.append("Write out the full problem statement.")
        if not answer:
            errors.append("An answer is required so submissions can be checked.")
        book = Book.query.get(book_id) if book_id else None
        if not book:
            errors.append("Choose which book this problem belongs to.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("write_problem.html", books=books, form=request.form)

        next_number = (
            db.session.query(db.func.coalesce(db.func.max(Problem.number), 0))
            .filter(Problem.book_id == book.id)
            .scalar()
        ) + 1
        base_slug = slugify(f"{book.slug}-{title}")
        slug = base_slug
        n = 2
        while Problem.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{n}"
            n += 1

        problem = Problem(
            book_id=book.id,
            number=next_number,
            title=title,
            slug=slug,
            statement=statement,
            difficulty=max(1, min(5, difficulty)),
            points=max(1, points),
            author_id=current_user.id,
            status="pending",
        )
        problem.set_answer(answer)
        db.session.add(problem)
        db.session.commit()
        flash(
            "Problem submitted for review. It needs two reviewer approvals to go live.",
            "success",
        )
        return redirect(url_for("dashboard"))

    return render_template("write_problem.html", books=books, form={})


# review board


@app.route("/review")
@reviewer_required
def review_queue():
    pending = (
        Problem.query.filter_by(status="pending")
        .order_by(Problem.created_at.asc())
        .all()
    )
    return render_template("review_queue.html", pending=pending)


@app.route("/review/<slug>", methods=["GET", "POST"])
@reviewer_required
def review_problem(slug):
    problem = Problem.query.filter_by(slug=slug).first_or_404()
    if problem.author_id == current_user.id and not current_user.is_admin:
        flash("You can't review your own problem.", "error")
        return redirect(url_for("review_queue"))

    my_review = Review.query.filter_by(
        problem_id=problem.id, reviewer_id=current_user.id
    ).first()

    if request.method == "POST" and problem.status == "pending":
        decision = request.form.get("decision")
        comment = request.form.get("comment", "").strip()
        if decision not in ("approve", "reject"):
            abort(400)
        if my_review:
            my_review.decision = decision
            my_review.comment = comment
            my_review.created_at = datetime.utcnow()
        else:
            my_review = Review(
                problem_id=problem.id,
                reviewer_id=current_user.id,
                decision=decision,
                comment=comment,
            )
            db.session.add(my_review)
        db.session.commit()

        if problem.approvals >= REQUIRED_APPROVALS:
            problem.status = "approved"
            problem.decided_at = datetime.utcnow()
            db.session.commit()
            flash(
                f'"{problem.title}" has {REQUIRED_APPROVALS} approvals and is now live!',
                "success",
            )
        elif problem.rejections >= REQUIRED_APPROVALS:
            problem.status = "rejected"
            problem.decided_at = datetime.utcnow()
            db.session.commit()
            flash(f'"{problem.title}" was rejected by the review board.', "info")
        else:
            flash("Review recorded.", "success")
        return redirect(url_for("review_queue"))

    all_reviews = problem.reviews_rel.all()
    return render_template(
        "review_problem.html",
        problem=problem,
        my_review=my_review,
        all_reviews=all_reviews,
    )


@app.route("/review/<slug>/edit", methods=["GET", "POST"])
@reviewer_required
def review_edit(slug):
    """Reviewers can tidy up a pending problem: statement, answer, metadata."""
    problem = Problem.query.filter_by(slug=slug).first_or_404()
    if problem.author_id == current_user.id and not current_user.is_admin:
        flash("You can't edit your own problem in review.", "error")
        return redirect(url_for("review_queue"))
    if problem.status != "pending":
        flash("Only problems that are still pending can be edited.", "error")
        return redirect(url_for("review_problem", slug=slug))

    books = Book.query.order_by(Book.name.asc()).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        book_id = request.form.get("book_id", type=int)
        statement = request.form.get("statement", "").strip()
        answer = request.form.get("answer", "").strip()
        difficulty = request.form.get("difficulty", type=int) or 1
        points = request.form.get("points", type=int) or 10

        errors = []
        if len(title) < 4:
            errors.append("Give the problem a real title.")
        if len(statement) < 20:
            errors.append("The problem statement needs to be written out in full.")
        if not answer and not problem.answer_text:
            errors.append("This problem has no stored answer yet - enter one.")
        book = Book.query.get(book_id) if book_id else None
        if not book:
            errors.append("Choose which book this problem belongs to.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "review_edit.html", problem=problem, books=books, form=request.form
            )

        difficulty = max(1, min(5, difficulty))
        points = max(1, points)

        changed = (
            title != problem.title
            or statement != problem.statement
            or difficulty != problem.difficulty
            or points != problem.points
            or book.id != problem.book_id
            or (answer and answer != (problem.answer_text or ""))
        )

        if changed:
            if book.id != problem.book_id:
                problem.book_id = book.id
                problem.number = (
                    db.session.query(db.func.coalesce(db.func.max(Problem.number), 0))
                    .filter(Problem.book_id == book.id)
                    .scalar()
                ) + 1
            problem.title = title
            problem.statement = statement
            problem.difficulty = difficulty
            problem.points = points
            if answer:
                problem.set_answer(answer)
            problem.last_edited_by_id = current_user.id
            problem.last_edited_at = datetime.utcnow()
            db.session.commit()
            flash("Problem updated.", "success")
        else:
            flash("No changes to save.", "info")
        return redirect(url_for("review_problem", slug=slug))

    form = {
        "title": problem.title,
        "book_id": problem.book_id,
        "statement": problem.statement,
        "difficulty": problem.difficulty,
        "points": problem.points,
        "answer": problem.answer_text or "",
    }
    return render_template(
        "review_edit.html", problem=problem, books=books, form=form
    )


# book requests


@app.route("/request-book", methods=["GET", "POST"])
@login_required
def request_book():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        reason = request.form.get("reason", "").strip()

        errors = []
        if len(name) < 2:
            errors.append("Give the book a name.")
        elif len(name) > 80:
            errors.append("Book names are limited to 80 characters.")
        if Book.query.filter(db.func.lower(Book.name) == name.lower()).first():
            errors.append("We already have a book with that name.")
        if (
            BookRequest.query.filter(db.func.lower(BookRequest.name) == name.lower())
            .filter_by(user_id=current_user.id, status="pending")
            .first()
        ):
            errors.append("You've already requested that book - it's waiting on an admin.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "request_book.html",
                form=request.form,
                my_requests=current_user.book_requests.order_by(
                    BookRequest.created_at.desc()
                ).all(),
            )

        db.session.add(
            BookRequest(
                user_id=current_user.id,
                name=name,
                description=description,
                reason=reason,
            )
        )
        db.session.commit()
        flash("Thanks! Your book request has been sent to the admins.", "success")
        return redirect(url_for("request_book"))

    return render_template(
        "request_book.html",
        form={},
        my_requests=current_user.book_requests.order_by(
            BookRequest.created_at.desc()
        ).all(),
    )


# admin


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    if request.method == "POST":
        user_id = request.form.get("user_id", type=int)
        action = request.form.get("action")
        user = User.query.get_or_404(user_id)
        if user.id == current_user.id and action in ("revoke_admin",):
            flash("You can't remove your own admin rights.", "error")
        elif action == "make_reviewer":
            user.is_reviewer = True
        elif action == "revoke_reviewer":
            user.is_reviewer = False
        elif action == "make_admin":
            user.is_admin = True
        elif action == "revoke_admin":
            user.is_admin = False
        db.session.commit()
        flash(f"Updated {user.username}.", "success")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.username.asc()).all()
    return render_template("admin_users.html", users=users)


@app.route("/admin/books", methods=["GET", "POST"])
@admin_required
def admin_books():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        icon = request.form.get("icon", "").strip() or "∑"
        if len(name) < 2:
            flash("Book needs a name.", "error")
        elif Book.query.filter_by(name=name).first():
            flash("A book with that name already exists.", "error")
        else:
            book = Book(
                name=name,
                slug=slugify(name),
                description=description,
                icon=icon,
                sort_order=Book.query.count(),
            )
            db.session.add(book)
            db.session.commit()
            flash(f'Book "{name}" created.', "success")
        return redirect(url_for("admin_books"))
    books = Book.query.order_by(Book.sort_order.asc()).all()
    return render_template("admin_books.html", books=books)

@app.route("/admin/requests", methods=["GET", "POST"])
@admin_required
def admin_requests():
    if request.method == "POST":
        req = BookRequest.query.get_or_404(request.form.get("request_id", type=int))
        action = request.form.get("action")
        note = request.form.get("admin_note", "").strip()

        if req.status != "pending":
            flash("That request has already been handled.", "info")
        elif action == "approve":
            name = request.form.get("name", "").strip() or req.name
            icon = request.form.get("icon", "").strip() or "∑"
            if Book.query.filter(db.func.lower(Book.name) == name.lower()).first():
                flash("A book with that name already exists - edit the name first.", "error")
                return redirect(url_for("admin_requests"))
            base_slug = slugify(name) or "book"
            slug, n = base_slug, 2
            while Book.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{n}"
                n += 1
            db.session.add(
                Book(
                    name=name,
                    slug=slug,
                    description=req.description,
                    icon=icon,
                    sort_order=Book.query.count(),
                )
            )
            req.status = "approved"
            req.admin_note = note
            req.decided_at = datetime.utcnow()
            db.session.commit()
            flash(f'Book "{name}" created from the request.', "success")
        elif action == "decline":
            req.status = "declined"
            req.admin_note = note
            req.decided_at = datetime.utcnow()
            db.session.commit()
            flash(f'Declined the request for "{req.name}".', "info")
        return redirect(url_for("admin_requests"))

    pending = (
        BookRequest.query.filter_by(status="pending")
        .order_by(BookRequest.created_at.asc())
        .all()
    )
    handled = (
        BookRequest.query.filter(BookRequest.status != "pending")
        .order_by(BookRequest.decided_at.desc())
        .limit(30)
        .all()
    )
    return render_template("admin_requests.html", pending=pending, handled=handled)


@app.route("/tandc")
def tandc():
    return render_template("tandc.html")

@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Database initialised.")


def migrate_db():
    """Add columns introduced after a database was first created (SQLite)."""
    wanted = {
        "problem": [
            ("answer_text", "VARCHAR(255)"),
            ("last_edited_by_id", "INTEGER"),
            ("last_edited_at", "DATETIME"),
        ],
    }
    for table, columns in wanted.items():
        existing = {
            row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))
        }
        for name, ddl in columns:
            if name not in existing:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    db.session.commit()


def ensure_db():
    with app.app_context():
        db.create_all()
        migrate_db()


ensure_db()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)