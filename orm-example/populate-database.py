from engine import ENGINE
from models import Base, Child, Parent
from sqlalchemy.orm import Session


def main():
    Base.metadata.drop_all(ENGINE)
    Base.metadata.create_all(ENGINE)
    insert()


def insert():
    with Session(ENGINE) as session:
        p1 = Parent(
            name="Parent 1",
            child=Child(name="Child 1"),
        )
        p2 = Parent(
            name="Parent 2",
            child=Child(name="Child 2"),
        )
        p3 = Parent(name="Parent 3")

        session.add_all([p1, p2, p3])
        session.commit()


if __name__ == "__main__":
    main()
