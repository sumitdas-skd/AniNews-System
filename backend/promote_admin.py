from database import get_db_connection

def promote_admin(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = 'admin' WHERE email = ?", (email,))
    conn.commit()
    print(f"User {email} promoted to admin.")
    conn.close()

if __name__ == '__main__':
    promote_admin('test@example.com')
