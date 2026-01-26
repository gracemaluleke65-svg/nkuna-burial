import os
from app import app, init_database

# Initialize database on startup
with app.app_context():
    init_database()

if __name__ == "__main__":
    app.run()