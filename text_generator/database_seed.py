from database import create_connection


connection = create_connection()

try:
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS books")
        cursor.execute(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT,
                publication_year INTEGER,
                in_stock INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO books (title, author, publication_year, in_stock)
            VALUES (%s, %s, %s, %s)
            """,
            ("The Catcher in the Rye", "J.D. Salinger", 1951, True),
        )
        cursor.executemany(
            """
            INSERT INTO books (title, author, publication_year, in_stock)
            VALUES (%s, %s, %s, %s)
            """,
            [
                ("The Hobbit", "J.R.R. Tolkien", 1937, True),
                ("1984", "George Orwell", 1949, True),
                ("Dune", "Frank Herbert", 1965, False),
            ],
        )
    connection.commit()
    print("SQLite-seed voltooid.")
finally:
    connection.close()

