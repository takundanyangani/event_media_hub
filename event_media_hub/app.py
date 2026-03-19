# import necessary libraries
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, session
import os
import sqlite3
import random
import string
import zipfile
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash


# function to get a database connection
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_code(length=6):
    # generate a random code consisting of uppercase letters and digits
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

# create a Flask application
app = Flask(__name__)

# set a secret key for the application to use sessions
app.secret_key = "your_secret_key"

# set the permanent session lifetime to 7 days
app.permanent_session_lifetime = timedelta(days=7)

# set the upload folder for the application
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# create the upload folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if not os.path.exists('static'):
    os.makedirs('static')

# define the route for the home page
@app.route('/')
def index():
    if "user_id" not in session:
        return redirect('/dashboard')
    return redirect('/login')

# define the route to create a new event
@app.route("/create_event", methods=["GET","POST"])
def create_event():

    if "user_id" not in session:
        return redirect('/login')

    if request.method == "POST":
        # get the event name from the form and generate a unique code for the event
        event_name = request.form["event_name"]
        event_code = generate_code()
        creator_id = session.get("user_id")

       # add the event to the events dictionary
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO events (name,code,creator_id) VALUES (?, ?, ?)",
            (event_name,event_code,creator_id)
        )
        conn.commit()
        conn.close()

        # initialize the event's list of files in the events dictionary
        return redirect("/dashboard")

    # render the create event page
    return render_template("create_event.html")

# define the route to display the event page and handle file uploads
@app.route("/event/<int:event_id>", methods=["GET","POST"])
def event_page(event_id):

    # check if the user is logged in, if not redirect to the login page
    if "user_id" not in session:
        return redirect('/login')
    
    # get the user ID from the session
    user_id = session["user_id"]
    # get the event from the database
    conn = get_db_connection()

    # check if the event exists and if the user is the creator or a member of the event
    event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not event:
        conn.close()
        return "Event not found", 404
 
    is_creator = event['creator_id'] == user_id
    is_member = conn.execute(
        "SELECT * FROM event_members WHERE event_id = ? AND user_id = ?",
        (event_id, user_id)
    ).fetchone()
 
    if not is_creator and not is_member:
        conn.close()
        return "Access denied. Please join the event first."

    # handle file upload if the request method is POST
    if request.method == "POST":
        file = request.files["media"]

        # save the uploaded file to the upload folder and store the file path in the database
        if file and file.filename:
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)
            conn.execute(
                "INSERT INTO media (event_id, filename) VALUES (?, ?)",
                (event_id, file.filename)
            )
            conn.commit()
   
    # get the media files associated with the event from the database
    media = conn.execute(
        "SELECT * FROM media WHERE event_id = ?",
        (event_id,)
    ).fetchall()

# get the comments associated with the media files from the database
    comments = conn.execute(
        "SELECT * FROM comments"
    ).fetchall()

    conn.close()

    # render the event page with the media files
    return render_template(
        "event.html",
        media=media,
        event_id=event_id,
        comments=comments,
        event = event,
        is_creator=is_creator
    )

# define a route to serve uploaded files
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# function to initialize the database and create the necessary tables
def innit_db():
    conn = get_db_connection()
    conn.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT UNIQUE,
        creator_id INTEGER
    )
    ''')

    # create the media table to store the file paths of the uploaded media
    conn.execute('''
    CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        filename TEXT,
        likes INTEGER DEFAULT 0,
        FOREIGN KEY (event_id) REFERENCES events (id)
    )
    ''')
    # create the comments table to store comments associated with media files
    conn.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_id INTEGER,
        username TEXT,
        text TEXT,
        FOREIGN KEY (media_id) REFERENCES media (id)
    )
    ''')

    # create the likes table to store which users have liked which media files
    conn.execute('''
    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_id INTEGER,
        username TEXT,
        UNIQUE(media_id, username)
    )
    ''')

    # create the users table to store user information for authentication
    conn.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    ''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS event_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        user_id INTEGER,
        UNIQUE(event_id, user_id)
    )
    ''')
    
    #commit the changes and close the database connection
    conn.commit()
    conn.close()

# define the route to join an event using the event code
@app.route('/join_event', methods=['GET', 'POST'])
def join_event():
    if 'user_id' not in session:
        return redirect('/login')
    
    if request.method == 'POST':
        code = request.form['code']
        user_id = session['user_id']
        
        conn = get_db_connection()
        event = conn.execute(
            "SELECT * FROM events WHERE code = ?",
            (code,)
        ).fetchone()

        if not event:
            conn.close()
            return render_template('join_event.html', error="Invalid event code. Please try again.")
        
        existing = conn.execute(
            "SELECT * FROM event_members WHERE event_id = ? AND user_id = ?",
            (event['id'], user_id)
        ).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO event_members (user_id, event_id) VALUES (?, ?)",
                (user_id, event['id'])
            )
            conn.commit()
        conn.close()
        return redirect(f"/event/{event['id']}")
    
    return render_template('join_event.html')
   

# define the route to delete a media file from an event
@app.route("/delete_media/<int:media_id>/<int:event_id>")
def delete_media(media_id, event_id):

    if "user_id" not in session:
        return redirect('/login')


    conn = get_db_connection()
    media = conn.execute(
        "SELECT filename FROM media WHERE id = ?",
        (media_id,)
    ).fetchone()

    if media:
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], media["filename"])

        if os.path.exists(filepath):
            os.remove(filepath)

        conn.execute(
            "DELETE FROM media WHERE id = ?",
            (media_id,)
        )
        conn.execute(
            "DELETE FROM comments WHERE media_id = ?",
            (media_id,)
        )
        conn.execute(
            "DELETE FROM likes WHERE media_id = ?",
            (media_id,)
        )

        conn.commit()
    conn.close()

    # redirect the user back to the event page after deleting the media file
    return redirect(f"/event/{event_id}")

# define the route to delete an event and all associated media files
@app.route("/delete_event/<int:event_id>")
def delete_event(event_id):

    if "user_id" not in session:
        return redirect('/login')

    conn = get_db_connection()
    media = conn.execute(
        "SELECT filename FROM media WHERE event_id = ?",
        (event_id,)
    ).fetchall()

    for file in media:
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], file["filename"])

        if os.path.exists(filepath):
            os.remove(filepath)

    conn.execute(
        "DELETE FROM media WHERE event_id = ?",
        (event_id,)
    )
    conn.execute(
        "DELETE FROM event_members WHERE event_id = ?",
        (event_id,)
    )
    conn.execute(
        "DELETE FROM events WHERE id = ?",
        (event_id,)
    )

    conn.commit()
    conn.close()

    # redirect the user back to the home page after deleting the event and associated media files
    return redirect("/dashboard")

# define the route to download all media files associated with an event as a zip file
@app.route("/download_event/<int:event_id>")
def download_event(event_id):

    conn = get_db_connection()
    media = conn.execute(
        "SELECT filename FROM media WHERE event_id = ?",
        (event_id,)
    ).fetchall()
    conn.close()

    zip_filename = f"event_{event_id}.zip"
    zip_path = os.path.join("static", zip_filename)
    # create a zip file and add all media files associated with the event to the zip file
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for file in media:
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file["filename"])

            if os.path.exists(filepath):
                zipf.write(filepath, file["filename"])

    return send_file(zip_path, as_attachment=True)

# define the route to like a media file associated with an event
@app.route("/like/<int:media_id>/<int:event_id>")
def like_media(media_id, event_id):

    if "user_id" not in session:
        return redirect('/login')

    username = session.get("username", "Anonymous")
    conn = get_db_connection()

    try:
        conn.execute(
            "INSERT INTO likes (media_id, username) VALUES (?, ?)",
            (media_id, username)
        )
        conn.execute(
            "UPDATE media SET likes = likes + 1 WHERE id = ?",
            (media_id,)
        )
        conn.commit()
    except:
        pass  # already liked

    conn.close()
    return redirect(f"/event/{event_id}")

# define the route to add a comment to a media file associated with an event
@app.route("/add_comment/<int:media_id>/<int:event_id>", methods=["POST"])
def add_comment(media_id, event_id):

    if "user_id" not in session:
        return redirect('/login')

    comment_text = request.form["comment"]
    username = session.get("username", "Anonymous")

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO comments (media_id, username, text) VALUES (?, ?, ?)",
        (media_id, username, comment_text)
    )

    conn.commit()
    conn.close()
    return redirect(f"/event/{event_id}")


# define the route to display the login page and handle user authentication
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect('/dashboard')

    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", 
            (username,)
        ).fetchone()
        conn.close()

        # Check password
        if user and check_password_hash(user['password'], password):

            session.permanent = True  # Make the session permanent so it lasts for the defined lifetime
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect('/dashboard')

        error = "Invalid username or password. Please try again."

    return render_template('login.html', error=error)

# define the route to display the signup page and handle user registration
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    error = None


    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        hashed = generate_password_hash(password)

        try:
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hashed)
            )
            conn.commit()
            conn.close()
            return redirect('/login')
        except:
            error = "Username already exists. Please choose a different username."

    return render_template('signup.html', error=error)

# define the route to log out the user and clear the session
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# define the route to display the user dashboard with created and joined events
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Events created by user
    created_events = conn.execute(
        "SELECT * FROM events WHERE creator_id = ?",
        (user_id,)
    ).fetchall()

    # Events joined by user
    joined_events = conn.execute("""
        SELECT events.* FROM events
        JOIN event_members ON events.id = event_members.event_id
        WHERE event_members.user_id = ?
    """, (user_id,)).fetchall()

    return render_template(
        'dashboard.html',
        created_events=created_events,
        joined_events=joined_events
    )


# run the application
if __name__ == "__main__":
    innit_db()
    app.run(debug=True)