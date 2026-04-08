"""Seed permissions script."""
from sqlalchemy.orm import Session
from db.session import SessionLocal, engine
from db.models import User, Crew, UserPermission, Space
from uuid import uuid4


def seed_permissions():
    """Create test permissions."""
    db = SessionLocal()
    try:
        # Create a test user
        test_user = User(
            id=str(uuid4()),
            email="test@example.com",
            name="Test User",
            is_active=True
        )
        db.add(test_user)
        
        # Create a test space
        test_space = Space(
            id=str(uuid4()),
            name="Test Space"
        )
        db.add(test_space)
        db.flush()
        
        # Create a test crew
        test_crew = Crew(
            id=str(uuid4()),
            space_id=test_space.id,
            name="Test Crew"
        )
        db.add(test_crew)
        db.flush()
        
        # Create permission
        permission = UserPermission(
            id=str(uuid4()),
            user_id=test_user.id,
            crew_id=test_crew.id,
            permission="admin"
        )
        db.add(permission)
        
        db.commit()
        print("Permissions seeded successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding permissions: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_permissions()

