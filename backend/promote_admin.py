import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'anime.db')

def promote_admin(email):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'admin' WHERE email = ?", (email,))
    conn.commit()
    print(f"User {email} promoted to admin.")
    conn.close()

if __name__ == '__main__':
    promote_admin('test@example.com')
