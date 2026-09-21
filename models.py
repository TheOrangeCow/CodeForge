from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

REQUIRED_APPROVALS = (2)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    is_admin = db.Column(db.Boolean, default=False)
    is_reviewer = db.Column(
        db.Boolean, default=False
    )

    submissions = db.relationship("Submission", backref="user", lazy="dynamic")
    ratings = db.relationship("Rating", backref="user", lazy="dynamic")
    authored = db.relationship(
        "Problem", backref="author", lazy="dynamic", foreign_keys="Problem.author_id"
    )
    reviews = db.relationship("Review", backref="reviewer", lazy="dynamic")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def score(self):
        return (
            db.session.query(db.func.coalesce(db.func.sum(Problem.points), 0))
            .join(Submission, Submission.problem_id == Problem.id)
            .filter(Submission.user_id == self.id, Submission.is_correct.is_(True))
            .scalar()
        )

    @property
    def solved_count(self):
        return self.submissions.filter_by(is_correct=True).count()


class Book(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    icon = db.Column(db.String(8), default="∑")
    sort_order = db.Column(db.Integer, default=0)

    problems = db.relationship("Problem", backref="book", lazy="dynamic")

    @property
    def approved_problems(self):
        return self.problems.filter_by(status="approved").order_by(Problem.number.asc())


class Problem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("book.id"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(140), nullable=False)
    slug = db.Column(db.String(160), nullable=False, unique=True)
    statement = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.Integer, default=1)
    points = db.Column(db.Integer, default=10)
    answer_hash = db.Column(db.String(255), nullable=False)
    answer_text = db.Column(db.String(255), nullable=True)

    status = db.Column(db.String(16), default="pending")
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    last_edited_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    last_edited_at = db.Column(db.DateTime, nullable=True)
    last_editor = db.relationship("User", foreign_keys=[last_edited_by_id])

    reviews_rel = db.relationship(
        "Review", backref="problem", lazy="dynamic", cascade="all, delete-orphan"
    )
    submissions = db.relationship(
        "Submission", backref="problem", lazy="dynamic", cascade="all, delete-orphan"
    )
    ratings = db.relationship(
        "Rating", backref="problem", lazy="dynamic", cascade="all, delete-orphan"
    )

    def set_answer(self, plain_answer):
        self.answer_text = plain_answer.strip()
        norm = self.answer_text.lower()
        self.answer_hash = generate_password_hash(norm)

    def check_answer(self, guess):
        norm = (guess or "").strip().lower()
        return check_password_hash(self.answer_hash, norm)

    @property
    def approvals(self):
        return self.reviews_rel.filter_by(decision="approve").count()

    @property
    def rejections(self):
        return self.reviews_rel.filter_by(decision="reject").count()

    @property
    def solver_count(self):
        return self.submissions.filter_by(is_correct=True).count()

    @property
    def avg_rating(self):
        val = (
            db.session.query(db.func.avg(Rating.stars))
            .filter(Rating.problem_id == self.id)
            .scalar()
        )
        return round(val, 1) if val else None

    @property
    def rating_count(self):
        return self.ratings.count()

    def solved_by(self, user):
        if not user or not user.is_authenticated:
            return False
        return (
            self.submissions.filter_by(user_id=user.id, is_correct=True).first()
            is not None
        )


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    decision = db.Column(db.String(8), nullable=False)  # approve | reject
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "problem_id", "reviewer_id", name="one_review_per_reviewer"
        ),
    )


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem.id"), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)


class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem.id"), nullable=False)
    stars = db.Column(db.Integer, nullable=False)  # 1..5
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "problem_id", name="one_rating_per_user_per_problem"
        ),
    )


class BookRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, default="")
    reason = db.Column(db.Text, default="")
    status = db.Column(
        db.String(16), default="pending"
    )  # pending | approved | declined
    admin_note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("book_requests", lazy="dynamic"))
