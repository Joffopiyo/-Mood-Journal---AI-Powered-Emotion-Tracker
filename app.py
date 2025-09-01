import os
import requests
import json
import mysql.connector
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS # Needed for cross-origin requests from the HTML file

# --- Configuration ---
# You need to set these environment variables before running the app
# Use a placeholder for a public API endpoint or your own API key
HF_API_URL = "https://api-inference.huggingface.co/models/j-hartmann/emotion-english-distilroberta-base"
# NOTE: For some free models, you may need an API key. 
#       Get one from huggingface.co and uncomment the line below.
# HF_API_KEY = os.getenv("HUGGING_FACE_API_KEY") 

DB_CONFIG = {
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'host': os.getenv('MYSQL_HOST', 'localhost')
}

DB_NAME = 'mood_journal_db'

# --- Database Connection ---
def get_db_connection(database=None):
    """Establishes a connection to the MySQL database."""
    config = DB_CONFIG.copy()
    if database:
        config['database'] = database
    try:
        conn = mysql.connector.connect(**config)
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to MySQL: {err}")
        return None

# --- Database Setup (new functionality) ---
def setup_database():
    """Creates the database and table if they don't exist."""
    conn = get_db_connection()
    if conn is None:
        return False
    
    try:
        cursor = conn.cursor()
        
        # Create database if it doesn't exist
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        cursor.close()
        conn.close()

        # Connect to the newly created/existing database
        conn = get_db_connection(database=DB_NAME)
        if conn is None:
            return False

        cursor = conn.cursor()
        
        # Create the table if it doesn't exist
        table_creation_query = """
        CREATE TABLE IF NOT EXISTS journal_entries (
            id INT AUTO_INCREMENT PRIMARY KEY,
            entry_text TEXT NOT NULL,
            primary_emotion VARCHAR(50) NOT NULL,
            primary_score DECIMAL(5, 2) NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        cursor.execute(table_creation_query)
        conn.commit()
        cursor.close()
        return True

    except mysql.connector.Error as err:
        print(f"Database setup failed: {err}")
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# --- Hugging Face API Integration ---
def analyze_emotion(text):
    """
    Sends text to the Hugging Face sentiment analysis API.
    Returns a dictionary of emotion scores or None on failure.
    """
    headers = {}
    # if HF_API_KEY:
    #     headers["Authorization"] = f"Bearer {HF_API_KEY}"
    
    payload = {"inputs": text}
    
    try:
        response = requests.post(HF_API_URL, headers=headers, json=payload)
        response.raise_for_status() # Raise an exception for bad status codes
        
        result = response.json()
        
        # The API returns a list of lists, we want the first item
        if result and isinstance(result, list) and isinstance(result[0], list):
            emotion_scores = {item['label']: item['score'] for item in result[0]}
            return emotion_scores
        else:
            print("Unexpected API response format.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON from API response: {e}")
        return None

# --- Flask Routes ---
@app.route('/add_entry', methods=['POST'])
def add_entry():
    """
    Analyzes a journal entry and saves it to the database.
    """
    data = request.json
    entry_text = data.get('text')

    if not entry_text:
        return jsonify({"error": "No text provided"}), 400

    # 1. Analyze emotion using Hugging Face API
    emotion_data = analyze_emotion(entry_text)
    if not emotion_data:
        return jsonify({"error": "Failed to analyze emotion"}), 500
    
    # Find the primary emotion and score
    primary_emotion = max(emotion_data, key=emotion_data.get)
    primary_score = emotion_data[primary_emotion] * 100 # Convert to percentage

    # 2. Save entry to MySQL
    conn = get_db_connection(database=DB_NAME)
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = conn.cursor()
        query = """
        INSERT INTO journal_entries (entry_text, primary_emotion, primary_score)
        VALUES (%s, %s, %s)
        """
        cursor.execute(query, (entry_text, primary_emotion, primary_score))
        conn.commit()
        cursor.close()
    except mysql.connector.Error as err:
        print(f"Database insertion failed: {err}")
        return jsonify({"error": "Failed to save entry to database"}), 500
    finally:
        if conn and conn.is_connected():
            conn.close()

    return jsonify({"message": "Entry saved successfully", "emotion": primary_emotion, "score": primary_score})

@app.route('/moods', methods=['GET'])
def get_moods():
    """
    Fetches the last 30 journal entries from the database.
    """
    conn = get_db_connection(database=DB_NAME)
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cursor = conn.cursor(dictionary=True) # Returns results as a dictionary
        query = """
        SELECT id, entry_text, primary_emotion, primary_score, timestamp
        FROM journal_entries
        ORDER BY timestamp DESC
        LIMIT 30
        """
        cursor.execute(query)
        entries = cursor.fetchall()
        cursor.close()
        
        # Format the timestamp for the frontend
        for entry in entries:
            if 'timestamp' in entry:
                # Convert the datetime object to an ISO 8601 string
                entry['timestamp'] = entry['timestamp'].isoformat()
    except mysql.connector.Error as err:
        print(f"Database query failed: {err}")
        return jsonify({"error": "Failed to retrieve moods"}), 500
    finally:
        if conn and conn.is_connected():
            conn.close()

    return jsonify(entries)

# --- Main entry point for the Flask app ---
if __name__ == '__main__':
    if not setup_database():
        print("Exiting due to database setup failure.")
    else:
        # You can specify host='0.0.0.0' for external access if needed for deployment
        app.run(debug=True, host='0.0.0.0')
