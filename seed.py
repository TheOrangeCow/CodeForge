from datetime import datetime
from app import app, slugify
from models import db, User, Book, Problem, Review


BOOKS = [
    (
        "Beginner Problems",
        "❖",
        "Start your coding journey with bite-sized problems covering logic, maths, algorithms, and problem solving."
    ),
]


SAMPLE_PROBLEMS = [
    (
        "Beginner Problems",
        "Multiples of 5",
        "Starting from 0, consider all the numbers up to and including 56,397,746 "
        "that are multiples of 5.\n\n"
        "Find the sum of all of these multiples.",
        "318070592307375",
        1,
        10
    ),
]


def run():
    with app.app_context():
        db.create_all()

        # Admin
        admin = User.query.filter_by(username="admin").first()

        if not admin:
            admin = User(
                username="admin",
                email="admin@theorangecow.org",
                is_admin=True,
                is_reviewer=True
            )
            admin.set_password("pitb4c&sO")
            db.session.add(admin)

        # Reviewer 2
        rev2 = User.query.filter_by(username="theorangecow").first()

        if not rev2:
            rev2 = User(
                username="theorangecow",
                email="theorangecow@theorangecow.org",
                is_reviewer=True
            )
            rev2.set_password("pitb4c&sO")
            db.session.add(rev2)

        # Daniel
        rev3 = User.query.filter_by(username="daniel").first()

        if not rev3:
            rev3 = User(
                username="daniel",
                email="daniel@theorangecow.org",
                is_reviewer=False
            )
            rev3.set_password("pitb4c&sO")
            db.session.add(rev3)

        db.session.commit()

        # Get users again after commit
        admin = User.query.filter_by(username="admin").first()
        rev2 = User.query.filter_by(username="theorangecow").first()
        rev3 = User.query.filter_by(username="daniel").first()

        # Books
        for index, (name, icon, desc) in enumerate(BOOKS):
            book = Book.query.filter_by(name=name).first()

            if not book:
                book = Book(
                    name=name,
                    slug=slugify(name),
                    icon=icon,
                    description=desc,
                    sort_order=index
                )
                db.session.add(book)

        db.session.commit()

        # Problems
        for book_name, title, statement, answer, difficulty, points in SAMPLE_PROBLEMS:

            if Problem.query.filter_by(title=title).first():
                continue

            book = Book.query.filter_by(name=book_name).first()

            if not book:
                continue

            next_number = (
                db.session.query(
                    db.func.coalesce(
                        db.func.max(Problem.number),
                        0
                    )
                )
                .filter(Problem.book_id == book.id)
                .scalar()
            ) + 1

            problem = Problem(
                book_id=book.id,
                number=next_number,
                title=title,
                slug=slugify(f"{book.slug}-{title}"),
                statement=statement,
                difficulty=difficulty,
                points=points,
                author_id=admin.id,
                status="approved",
                decided_at=datetime.utcnow()
            )

            problem.set_answer(answer)

            db.session.add(problem)
            db.session.commit()

            # Admin review
            db.session.add(
                Review(
                    problem_id=problem.id,
                    reviewer_id=admin.id,
                    decision="approve",
                    comment="Seed data."
                )
            )

            # Reviewer 2 review
            db.session.add(
                Review(
                    problem_id=problem.id,
                    reviewer_id=rev2.id,
                    decision="approve",
                    comment="Seed data."
                )
            )

            db.session.commit()

        print("Seed complete.")


if __name__ == "__main__":
    run()