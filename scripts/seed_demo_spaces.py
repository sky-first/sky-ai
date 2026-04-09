"""Seed demo spaces script."""
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db.models import Space, Crew, DataConnection
from uuid import uuid4


def seed_demo_spaces():
    """Create demo spaces, crews, and connections."""
    db = SessionLocal()
    try:
        # Create demo space
        demo_space = Space(
            id=uuid4(),
            name="Demo Space",
            description="Demo space with sample data",
            is_active=True
        )
        db.add(demo_space)
        db.flush()
        
        # Create demo crew
        demo_crew = Crew(
            id=uuid4(),
            space_id=demo_space.id,
            name="Demo Crew",
            description="Demo crew for testing",
            is_active=True
        )
        db.add(demo_crew)
        db.flush()
        
        # Create demo connection (placeholder)
        demo_connection = DataConnection(
            id=uuid4(),
            space_id=demo_space.id,
            name="Demo Connection",
            connection_type="postgres",
            config={"connection_string": "postgresql://user:pass@localhost/demo"},
            is_active=True
        )
        db.add(demo_connection)
        
        db.commit()
        print("Demo spaces seeded successfully!")
        print(f"Space ID: {demo_space.id}")
        print(f"Crew ID: {demo_crew.id}")
    except Exception as e:
        db.rollback()
        print(f"Error seeding demo spaces: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_spaces()

