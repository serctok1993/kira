import sqlite3

def getLocationNumbers(db_path):
    """
    Retrieves all unique location numbers from the SQLite database.
    
    Args:
        db_path (str): The file path to the SQLite database.
    
    Returns:
        list: A list of unique location numbers as integers. If an error occurs, returns None.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Execute a query to fetch all unique location numbers
        cursor.execute("SELECT DISTINCT location_number FROM locations")
        rows = cursor.fetchall()
        # Extract the location numbers from the result set and return them as a list of integers
        location_numbers = [row[0] for row in rows]
        conn.close()
        return location_numbers
    except sqlite3.Error:
        # Handle any database-related errors by returning None
        return None