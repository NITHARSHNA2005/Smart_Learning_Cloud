from flask import Flask, render_template, request, redirect, url_for, jsonify, g, flash, send_from_directory, session
import sqlite3
import os
from datetime import datetime
import json
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# Simple NLP stuff
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import re
import random

import os

# Database configuration
APP_DB = os.environ.get('DATABASE_URL', 'smart_learning.db')
if APP_DB.startswith('postgres://'):
    APP_DB = APP_DB.replace('postgres://', 'postgresql://', 1)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['DEBUG'] = os.environ.get('FLASK_ENV') != 'production'

# Add custom filter for JSON parsing in templates
@app.template_filter('from_json')
def from_json_filter(value):
    return json.loads(value)

# Upload configuration
UPLOAD_FOLDER = 'uploads/videos'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -----------------------
# Database helpers
# -----------------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(APP_DB)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def init_db():
    db = sqlite3.connect(APP_DB)
    cur = db.cursor()
    
    # Check if users table exists, if not create all tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if cur.fetchone() is None:
        cur.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_type TEXT NOT NULL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            video_url TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER,
            title TEXT
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER,
            question TEXT,
            options TEXT, -- JSON list
            answer_index INTEGER,
            topic TEXT
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT,
            quiz_id INTEGER,
            score REAL,
            detail TEXT,
            taken_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            message TEXT,
            sent_at TEXT,
            is_read INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            badge_type TEXT,
            earned_at TEXT
        );
        CREATE TABLE IF NOT EXISTS study_streaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            current_streak INTEGER DEFAULT 0,
            last_activity TEXT,
            total_points INTEGER DEFAULT 0
        );
        """)
        
        # Create default users
        now = datetime.now().isoformat()
        # Default teacher
        cur.execute("INSERT INTO users (name, email, password_hash, user_type, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("Demo Teacher", "teacher@smartlearning.com", generate_password_hash("teacher123"), "teacher", now))
        # Default student
        cur.execute("INSERT INTO users (name, email, password_hash, user_type, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("Demo Student", "student@smartlearning.com", generate_password_hash("student123"), "student", now))
        
        # Check if sample lesson exists
        cur.execute("SELECT COUNT(*) FROM lessons")
        if cur.fetchone()[0] == 0:
            # sample lesson + quiz + questions
            now = datetime.now().isoformat()
            cur.execute("INSERT INTO lessons (title,description,video_url,created_at) VALUES (?,?,?,?)",
                        ("Mathematics: Fractions",
                         "Intro to fractions and basic operations",
                         "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # replace with a working video
                         now))
            lesson_id = cur.lastrowid
            cur.execute("INSERT INTO quizzes (lesson_id,title) VALUES (?,?)", (lesson_id, "Fractions Quiz"))
            quiz_id = cur.lastrowid
            qlist = [
                ("What is 1/2 + 1/3 ?", ["5/6","2/5","3/5","1/6"], 0, "fractions"),
                ("Which is equivalent to 2/4 ?", ["1/2","2/3","3/4","1/4"], 0, "fractions"),
                ("What is 3/5 - 1/5 ?", ["2/5","1/5","3/10","4/5"], 0, "fractions"),
                ("Convert 3/4 to decimal.", ["0.75","0.85","0.5","1.25"], 0, "decimal")
            ]
            for q in qlist:
                cur.execute("INSERT INTO questions (quiz_id,question,options,answer_index,topic) VALUES (?,?,?,?,?)",
                            (quiz_id, q[0], json.dumps(q[1]), q[2], q[3]))
    
    # Check if messages table exists, if not create it
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    if cur.fetchone() is None:
        cur.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                message TEXT,
                sent_at TEXT,
                is_read INTEGER DEFAULT 0
            )
        """)
    
    db.commit()
    db.close()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# -----------------------
# Simple chatbot (FAQ-based + TF-IDF similarity)
# -----------------------
FAQ_PAIRS = [
    # Platform Usage
    ("How do I join live class?", "Click on any lesson from the Student Portal, then watch the video lesson. Teachers upload video content for you to learn at your own pace."),
    ("How to attempt quiz?", "Go to Student Portal → Select a lesson → Click 'Start Learning' → After watching the video, click 'Take Quiz' to test your knowledge."),
    ("How are recommendations generated?", "Our AI analyzes your quiz performance by topic. If you score below 70% in any topic, we recommend focusing on those areas for improvement."),
    ("I forgot my password", "This platform doesn't require passwords! Just enter your name when taking quizzes to track your progress."),
    ("How do I track my progress?", "Visit the Results page to see all your quiz attempts, scores, and performance analytics. You can access it from the main navigation."),
    ("Can I retake a quiz?", "Yes! You can retake any quiz multiple times to improve your understanding and score."),
    
    # Mathematics - Fractions
    ("What is a fraction?", "A fraction represents a part of a whole. It has two parts: numerator (top number) and denominator (bottom number). For example, in 3/4, 3 is the numerator and 4 is the denominator."),
    ("How to add fractions?", "To add fractions: 1) Make denominators the same, 2) Add numerators, 3) Keep the denominator. Example: 1/4 + 1/4 = 2/4 = 1/2"),
    ("Convert 3/4 to decimal", "To convert 3/4 to decimal, divide 3 by 4: 3 ÷ 4 = 0.75"),
    ("What is equivalent fraction?", "Equivalent fractions represent the same value but look different. Example: 1/2 = 2/4 = 3/6. Multiply or divide both numerator and denominator by the same number."),
    ("How to subtract fractions?", "Similar to addition: 1) Make denominators the same, 2) Subtract numerators, 3) Keep the denominator. Example: 3/4 - 1/4 = 2/4 = 1/2"),
    
    # General Study Tips
    ("How to study effectively?", "1) Watch video lessons completely, 2) Take notes of key points, 3) Practice with quizzes, 4) Review topics you scored low on, 5) Ask me questions when confused!"),
    ("I'm struggling with math", "Don't worry! Math takes practice. Start with basics, watch videos multiple times, take quizzes to identify weak areas, and ask specific questions. I'm here to help!"),
    ("Tips for rural students", "1) Use this platform regularly, 2) Don't hesitate to ask questions, 3) Practice consistently, 4) Connect with urban teachers through video lessons, 5) Believe in yourself!"),
    ("How does AI tutoring work?", "I use artificial intelligence to understand your questions and provide helpful explanations. I can help with concepts, solve doubts, give study tips, and guide you through problems."),
    
    # Technical Support
    ("Video not loading", "Try refreshing the page or check your internet connection. If the problem persists, the teacher might be updating the video content."),
    ("Quiz not submitting", "Make sure you've answered all questions and entered your name. Check your internet connection and try again."),
    ("How to contact teacher?", "Currently, you can learn from teacher-created videos and use this AI tutor for doubts. More direct communication features are coming soon!"),
    
    # Motivational
    ("I feel discouraged", "Learning is a journey with ups and downs. Every expert was once a beginner. Keep practicing, use this platform regularly, and celebrate small victories. You've got this!"),
    ("Am I smart enough?", "Absolutely! Intelligence isn't fixed - it grows with effort and practice. This platform is designed to help you learn at your own pace. Keep going!"),
]

faq_questions = [q for q,a in FAQ_PAIRS]
vectorizer = TfidfVectorizer().fit(faq_questions)

def chatbot_answer(user_input):
    ui = user_input.lower().strip()
    
    # Handle empty input
    if not ui:
        return "I'm here to help! You can ask me about math concepts, how to use the platform, study tips, or anything else related to your learning journey. What's on your mind? 🤔"
    
    # Handle greetings with more variety
    greetings = ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening', 'howdy', 'sup']
    if any(greeting in ui for greeting in greetings):
        responses = [
            "Hello there! 👋 I'm your AI tutor, ready to help you learn and grow. What subject would you like to explore today?",
            "Hi! Great to see you here! 😊 I can help with math, study strategies, or any questions about the platform. What can I assist you with?",
            "Hey! Welcome to your learning session! 🎓 I'm here to make your studies easier and more effective. How can I help?"
        ]
        return random.choice(responses)
    
    # Handle thanks with warmth
    thanks = ['thank', 'thanks', 'thank you', 'thx', 'appreciate']
    if any(thank in ui for thank in thanks):
        responses = [
            "You're very welcome! 😊 I'm always happy to help you succeed. Keep up the great work!",
            "My pleasure! That's what I'm here for. Feel free to ask me anything else - I love helping students learn! 🌟",
            "Glad I could help! Remember, there's no such thing as a silly question. I'm here whenever you need me! 💪"
        ]
        return random.choice(responses)
    
    # Handle motivation and encouragement
    motivation_words = ['tired', 'difficult', 'hard', 'struggling', 'confused', 'frustrated', 'give up', 'quit']
    if any(word in ui for word in motivation_words):
        return "I understand learning can be challenging sometimes, but you're doing great by asking for help! 💪 Remember, every expert was once a beginner. Take a short break if needed, then let's tackle this together. What specific topic is giving you trouble?"
    
    # Handle compliments
    compliments = ['good', 'great', 'awesome', 'amazing', 'helpful', 'smart']
    if any(comp in ui for comp in compliments) and ('you' in ui or 'tutor' in ui):
        return "Thank you so much! 😊 Your kind words motivate me to help even more. I'm here to support your learning journey every step of the way. What else can we work on together?"
    
    # Enhanced keyword matching with context
    for q, a in FAQ_PAIRS:
        question_words = set(re.findall(r'\w+', q.lower()))
        input_words = set(re.findall(r'\w+', ui))
        
        # Check for significant word overlap or specific topic matches
        common_words = question_words.intersection(input_words)
        topic_matches = {
            'fraction': ['fraction', 'fractions', 'numerator', 'denominator'],
            'decimal': ['decimal', 'decimals', 'point'],
            'quiz': ['quiz', 'test', 'exam', 'question'],
            'video': ['video', 'lesson', 'watch'],
            'study': ['study', 'learn', 'practice']
        }
        
        # Check for topic-specific matches
        topic_found = False
        for topic, keywords in topic_matches.items():
            if any(keyword in ui for keyword in keywords) and topic in q.lower():
                topic_found = True
                break
        
        if len(common_words) >= 2 or topic_found:
            return f"{a}\n\n💡 **Need more help?** Feel free to ask follow-up questions or request examples!"
    
    # Use TF-IDF for semantic similarity
    try:
        user_vector = vectorizer.transform([ui])
        faq_vectors = vectorizer.transform(faq_questions)
        similarities = cosine_similarity(user_vector, faq_vectors)[0]
        best_match_idx = similarities.argmax()
        
        if similarities[best_match_idx] > 0.3:
            answer = FAQ_PAIRS[best_match_idx][1]
            return f"{answer}\n\n🤔 **Was this helpful?** If you need clarification or have a different question, just ask!"
    except:
        pass
    
    # Contextual responses for common topics
    if 'math' in ui or 'mathematics' in ui:
        return "I love helping with math! 📚 I can explain fractions, decimals, basic operations, and more. Try asking specific questions like:\n• 'What is a fraction?'\n• 'How to add fractions?'\n• 'Convert fractions to decimals'\n\nWhat math topic interests you most?"
    
    if 'help' in ui:
        return "I'm here to help! 🌟 You can ask me about:\n\n📚 **Math concepts** (fractions, decimals, operations)\n🎯 **Platform usage** (taking quizzes, watching videos)\n📝 **Study strategies** (effective learning tips)\n💡 **Motivation** (staying focused and confident)\n\nWhat specific topic would you like to explore?"
    
    # Fallback with helpful suggestions
    fallback_responses = [
        "I want to help, but I'm not sure I understand your question completely. Could you rephrase it or be more specific? 🤔\n\n**I'm great at helping with:**\n• Math concepts (fractions, decimals, etc.)\n• Platform navigation\n• Study tips and strategies\n• Quiz guidance",
        "Hmm, that's an interesting question! I might need a bit more context to give you the best answer. 💭\n\n**Try asking about:**\n• Specific math topics\n• How to use platform features\n• Study techniques\n• Quiz preparation tips",
        "I'd love to help you with that! Could you provide a bit more detail or ask in a different way? 😊\n\n**Popular topics I can help with:**\n• Mathematics explanations\n• Learning strategies\n• Platform tutorials\n• Academic support"
    ]
    
    return random.choice(fallback_responses)

# -----------------------
# Authentication helpers
# -----------------------
def login_required(role=None):
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if 'user_type' not in session:
                return redirect(url_for('login'))
            if role and session.get('user_type') != role:
                flash('Access denied!', 'error')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

# -----------------------
# Routes
# -----------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please enter both email and password!', 'error')
            return render_template('login.html')
        
        # Check user credentials
        user = query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_type'] = user['user_type']
            session['username'] = user['name']
            session['email'] = user['email']
            
            flash(f'Welcome back, {user["name"]}!', 'success')
            
            if user['user_type'] == 'teacher':
                return redirect(url_for('teacher'))
            else:
                return redirect(url_for('student'))
        else:
            flash('Invalid email or password!', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        user_type = request.form.get('user_type', '')
        
        # Validation
        if not all([name, email, password, confirm_password, user_type]):
            flash('Please fill in all fields!', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long!', 'error')
            return render_template('register.html')
        
        if user_type not in ['student', 'teacher']:
            flash('Please select a valid user type!', 'error')
            return render_template('register.html')
        
        # Check if email already exists
        existing_user = query_db("SELECT id FROM users WHERE email = ?", (email,), one=True)
        if existing_user:
            flash('Email already registered! Please use a different email or login.', 'error')
            return render_template('register.html')
        
        # Create new user
        try:
            db = get_db()
            password_hash = generate_password_hash(password)
            db.execute("INSERT INTO users (name, email, password_hash, user_type, created_at) VALUES (?, ?, ?, ?, ?)",
                      (name, email, password_hash, user_type, datetime.now().isoformat()))
            db.commit()
            
            flash('Registration successful! Please login with your credentials.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Registration failed. Please try again.', 'error')
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_type' not in session:
        return redirect(url_for('login'))
    
    if session['user_type'] == 'teacher':
        return redirect(url_for('teacher'))
    else:
        return redirect(url_for('student'))

@app.route('/teacher', methods=['GET','POST'])
@login_required('teacher')
def teacher():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        video_url = request.form.get('video_url', '')
        
        # Handle video file upload
        if 'video_file' in request.files:
            file = request.files['video_file']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to avoid conflicts
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                filename = timestamp + filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                video_url = url_for('uploaded_video', filename=filename)
                flash('Video uploaded successfully!', 'success')
        
        db = get_db()
        db.execute("INSERT INTO lessons (title,description,video_url,created_at) VALUES (?,?,?,?)",
                   (title, description, video_url, datetime.now().isoformat()))
        db.commit()
        flash('Lesson created successfully!', 'success')
        return redirect(url_for('teacher'))
    
    lessons = query_db("SELECT * FROM lessons")
    # Get quiz information for each lesson
    lessons_with_quizzes = {}
    for lesson in lessons:
        quiz = query_db("SELECT * FROM quizzes WHERE lesson_id=?", (lesson['id'],), one=True)
        if quiz:
            lessons_with_quizzes[lesson['id']] = quiz
    return render_template('teacher.html', lessons=lessons, lessons_with_quizzes=lessons_with_quizzes)

@app.route('/uploads/videos/<filename>')
def uploaded_video(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/student')
@login_required('student')
def student():
    lessons = query_db("SELECT * FROM lessons")
    return render_template('student.html', lessons=lessons)

@app.route('/lesson/<int:lid>')
def lesson_view(lid):
    lesson = query_db("SELECT * FROM lessons WHERE id=?", (lid,), one=True)
    quiz = query_db("SELECT * FROM quizzes WHERE lesson_id=?", (lid,), one=True)
    return render_template('lesson.html', lesson=lesson, quiz=quiz)

@app.route('/quiz/<int:quiz_id>')
@login_required('student')
def quiz(quiz_id):
    quiz = query_db("SELECT * FROM quizzes WHERE id=?", (quiz_id,), one=True)
    questions = query_db("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    qlist = []
    for q in questions:
        qlist.append({
            "id": q["id"],
            "question": q["question"],
            "options": json.loads(q["options"]),
            "topic": q["topic"]
        })
    return render_template('quiz.html', quiz=quiz, questions=qlist)

@app.route('/submit_quiz', methods=['POST'])
@login_required('student')
def submit_quiz():
    data = request.json
    student = session.get('username', 'Anonymous')
    answers = data.get('answers',{})  
    quiz_id = data.get('quiz_id')
    questions = query_db("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    total = len(questions)
    correct = 0
    topic_scores = {}
    for q in questions:
        qid = str(q['id'])
        correct_idx = q['answer_index']
        topic = q['topic'] or 'general'
        chosen = answers.get(qid, -1)
        topic_scores.setdefault(topic, {"right":0,"total":0})
        topic_scores[topic]["total"] += 1
        if int(chosen) == int(correct_idx):
            correct += 1
            topic_scores[topic]["right"] += 1
    score = round((correct/total)*100,2) if total>0 else 0.0
    detail = json.dumps(topic_scores)
    db = get_db()
    db.execute("INSERT INTO attempts (student_name,quiz_id,score,detail,taken_at) VALUES (?,?,?,?,?)",
               (student, quiz_id, score, detail, datetime.now().isoformat()))
    db.commit()
    recs = []
    for t,vals in topic_scores.items():
        pct = (vals['right']/vals['total'])*100 if vals['total']>0 else 0.0
        if pct < 70:
            recs.append({"topic": t, "score_pct": round(pct,2)})
    return jsonify({"score": score, "recommendations": recs})

@app.route('/attempts')
@login_required('teacher')
def attempts():
    rows = query_db("SELECT * FROM attempts ORDER BY taken_at DESC")
    
    # Calculate analytics
    analytics = {}
    if rows:
        scores = [r['score'] for r in rows]
        analytics['total_attempts'] = len(rows)
        analytics['average_score'] = sum(scores) / len(scores)
        analytics['highest_score'] = max(scores)
        analytics['lowest_score'] = min(scores)
        analytics['pass_rate'] = len([s for s in scores if s >= 70]) / len(scores) * 100
        
        # Top performers
        analytics['top_performers'] = sorted(rows, key=lambda x: x['score'], reverse=True)[:5]
        
        # Score distribution
        analytics['excellent'] = len([s for s in scores if s >= 90])
        analytics['good'] = len([s for s in scores if 70 <= s < 90])
        analytics['average'] = len([s for s in scores if 50 <= s < 70])
        analytics['poor'] = len([s for s in scores if s < 50])
    
    return render_template('results.html', attempts=rows, analytics=analytics)

@app.route('/chatbot', methods=['POST'])
def chatbot():
    data = request.json
    q = data.get('q', '')
    ans = chatbot_answer(q)
    return jsonify({"answer": ans})

@app.route('/lesson-page/<int:lesson_id>')
@login_required('student')
def lesson_page(lesson_id):
    lesson = query_db("SELECT * FROM lessons WHERE id=?", (lesson_id,), one=True)
    if not lesson:
        return redirect(url_for('index'))
    quiz = query_db("SELECT * FROM quizzes WHERE lesson_id=?", (lesson_id,), one=True)
    return render_template('lesson.html', lesson=lesson, quiz=quiz)

@app.route('/edit-lesson/<int:lesson_id>', methods=['GET', 'POST'])
@login_required('teacher')
def edit_lesson(lesson_id):
    lesson = query_db("SELECT * FROM lessons WHERE id=?", (lesson_id,), one=True)
    if not lesson:
        return redirect(url_for('teacher'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        video_url = request.form.get('video_url', lesson['video_url'])
        
        # Handle video file upload
        if 'video_file' in request.files:
            file = request.files['video_file']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                filename = timestamp + filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                video_url = url_for('uploaded_video', filename=filename)
                flash('Video updated successfully!', 'success')
        
        db = get_db()
        db.execute("UPDATE lessons SET title=?, description=?, video_url=? WHERE id=?",
                   (title, description, video_url, lesson_id))
        db.commit()
        flash('Lesson updated successfully!', 'success')
        return redirect(url_for('teacher'))
    
    return render_template('edit_lesson.html', lesson=lesson)

@app.route('/create-quiz/<int:lesson_id>', methods=['GET', 'POST'])
@login_required('teacher')
def create_quiz(lesson_id):
    lesson = query_db("SELECT * FROM lessons WHERE id=?", (lesson_id,), one=True)
    if not lesson:
        flash('Lesson not found!', 'error')
        return redirect(url_for('teacher'))
    
    if request.method == 'POST':
        quiz_title = request.form.get('quiz_title', f"{lesson['title']} Quiz")
        questions_data = request.form.getlist('questions')
        options_data = request.form.getlist('options')
        answers_data = request.form.getlist('correct_answers')
        topics_data = request.form.getlist('topics')
        
        if not questions_data or len([q for q in questions_data if q.strip()]) == 0:
            flash('Please add at least one question!', 'error')
            return render_template('create_quiz.html', lesson=lesson)
        
        try:
            db = get_db()
            # Create quiz
            cursor = db.execute("INSERT INTO quizzes (lesson_id, title) VALUES (?, ?)", 
                      (lesson_id, quiz_title))
            quiz_id = cursor.lastrowid
            
            # Add questions
            questions_added = 0
            for i, question in enumerate(questions_data):
                if question.strip():
                    options_text = options_data[i] if i < len(options_data) else ""
                    options_list = [opt.strip() for opt in options_text.replace('\n', ';').split(';') if opt.strip()]
                    
                    if len(options_list) >= 2:
                        correct_answer = int(answers_data[i]) if i < len(answers_data) and answers_data[i].isdigit() else 0
                        topic = topics_data[i] if i < len(topics_data) else 'general'
                        
                        db.execute(
                            "INSERT INTO questions (quiz_id, question, options, answer_index, topic) VALUES (?, ?, ?, ?, ?)",
                            (quiz_id, question, json.dumps(options_list), correct_answer, topic)
                        )
                        questions_added += 1
            
            if questions_added == 0:
                db.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
                flash('No valid questions were added. Please check your question format.', 'error')
                db.commit()
                return render_template('create_quiz.html', lesson=lesson)
            
            db.commit()
            flash(f'Quiz created successfully with {questions_added} questions!', 'success')
            return redirect(url_for('teacher'))
        except Exception as e:
            flash(f'Error creating quiz: {str(e)}', 'error')
            return render_template('create_quiz.html', lesson=lesson)
    
    return render_template('create_quiz.html', lesson=lesson)

@app.route('/edit-quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required('teacher')
def edit_quiz(quiz_id):
    quiz = query_db("SELECT * FROM quizzes WHERE id=?", (quiz_id,), one=True)
    if not quiz:
        return redirect(url_for('teacher'))
    
    lesson = query_db("SELECT * FROM lessons WHERE id=?", (quiz['lesson_id'],), one=True)
    questions = query_db("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    
    if request.method == 'POST':
        quiz_title = request.form.get('quiz_title', quiz['title'])
        questions_data = request.form.getlist('questions')
        options_data = request.form.getlist('options')
        answers_data = request.form.getlist('correct_answers')
        topics_data = request.form.getlist('topics')
        
        try:
            db = get_db()
            # Update quiz title
            db.execute("UPDATE quizzes SET title=? WHERE id=?", (quiz_title, quiz_id))
            
            # Delete existing questions
            db.execute("DELETE FROM questions WHERE quiz_id=?", (quiz_id,))
            
            # Add new questions
            for i, question in enumerate(questions_data):
                if question.strip():
                    options_text = options_data[i] if i < len(options_data) else ""
                    options_list = [opt.strip() for opt in options_text.replace('\n', ';').split(';') if opt.strip()]
                    
                    if len(options_list) >= 2:
                        correct_answer = int(answers_data[i]) if i < len(answers_data) and answers_data[i].isdigit() else 0
                        topic = topics_data[i] if i < len(topics_data) else 'general'
                        
                        db.execute(
                            "INSERT INTO questions (quiz_id, question, options, answer_index, topic) VALUES (?, ?, ?, ?, ?)",
                            (quiz_id, question, json.dumps(options_list), correct_answer, topic)
                        )
            
            db.commit()
            flash('Quiz updated successfully!', 'success')
            return redirect(url_for('teacher'))
        except Exception as e:
            flash(f'Error updating quiz: {str(e)}', 'error')
    
    return render_template('edit_quiz.html', quiz=quiz, lesson=lesson, questions=questions)

@app.route('/delete-lesson/<int:lesson_id>', methods=['POST'])
@login_required('teacher')
def delete_lesson(lesson_id):
    try:
        db = get_db()
        # Delete related questions first
        db.execute("DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE lesson_id=?)", (lesson_id,))
        # Delete related quizzes
        db.execute("DELETE FROM quizzes WHERE lesson_id=?", (lesson_id,))
        # Delete lesson
        db.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
        db.commit()
        flash('Lesson deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting lesson: {str(e)}', 'error')
    return redirect(url_for('teacher'))

@app.route('/messages')
@app.route('/messages/<int:chat_user_id>')
@login_required()
def messages(chat_user_id=None):
    # Ensure messages table exists
    db = get_db()
    try:
        db.execute("SELECT 1 FROM messages LIMIT 1")
    except:
        db.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                message TEXT,
                sent_at TEXT,
                is_read INTEGER DEFAULT 0
            )
        """)
        db.commit()
    
    user_id = session['user_id']
    user_type = session['user_type']
    
    # Get all contacts
    if user_type == 'teacher':
        contacts = query_db("""
            SELECT u.id, u.name, u.email, u.user_type,
                   (SELECT COUNT(*) FROM messages WHERE sender_id = u.id AND receiver_id = ? AND is_read = 0) as unread_count,
                   (SELECT message FROM messages WHERE (sender_id = u.id AND receiver_id = ?) OR (sender_id = ? AND receiver_id = u.id) ORDER BY sent_at DESC LIMIT 1) as last_message,
                   (SELECT sent_at FROM messages WHERE (sender_id = u.id AND receiver_id = ?) OR (sender_id = ? AND receiver_id = u.id) ORDER BY sent_at DESC LIMIT 1) as last_message_time
            FROM users u WHERE u.user_type = 'student'
            ORDER BY last_message_time DESC, u.name
        """, (user_id, user_id, user_id, user_id, user_id))
    else:
        contacts = query_db("""
            SELECT u.id, u.name, u.email, u.user_type,
                   (SELECT COUNT(*) FROM messages WHERE sender_id = u.id AND receiver_id = ? AND is_read = 0) as unread_count,
                   (SELECT message FROM messages WHERE (sender_id = u.id AND receiver_id = ?) OR (sender_id = ? AND receiver_id = u.id) ORDER BY sent_at DESC LIMIT 1) as last_message,
                   (SELECT sent_at FROM messages WHERE (sender_id = u.id AND receiver_id = ?) OR (sender_id = ? AND receiver_id = u.id) ORDER BY sent_at DESC LIMIT 1) as last_message_time
            FROM users u WHERE u.user_type = 'teacher'
            ORDER BY last_message_time DESC, u.name
        """, (user_id, user_id, user_id, user_id, user_id))
    
    # Get chat messages if a user is selected
    chat_messages = []
    selected_user = None
    if chat_user_id:
        selected_user = query_db("SELECT * FROM users WHERE id = ?", (chat_user_id,), one=True)
        if selected_user:
            chat_messages = query_db("""
                SELECT m.*, u.name as sender_name FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?)
                ORDER BY m.sent_at ASC
            """, (user_id, chat_user_id, chat_user_id, user_id))
            
            # Mark messages as read
            db.execute("UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?", (chat_user_id, user_id))
            db.commit()
    
    return render_template('whatsapp_chat.html', contacts=contacts, chat_messages=chat_messages, selected_user=selected_user)

@app.route('/chat/<int:other_user_id>')
@login_required()
def chat(other_user_id):
    user_id = session['user_id']
    other_user = query_db("SELECT * FROM users WHERE id = ?", (other_user_id,), one=True)
    
    if not other_user:
        flash('User not found!', 'error')
        return redirect(url_for('messages'))
    
    # Get chat messages
    messages = query_db("""
        SELECT m.*, u.name as sender_name FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY m.sent_at ASC
    """, (user_id, other_user_id, other_user_id, user_id))
    
    # Mark messages as read
    db = get_db()
    db.execute("UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ?", (other_user_id, user_id))
    db.commit()
    
    return render_template('chat.html', messages=messages, other_user=other_user)

@app.route('/send_message', methods=['POST'])
@login_required()
def send_message():
    data = request.json
    receiver_id = data.get('receiver_id')
    message = data.get('message', '').strip()
    
    if not message or not receiver_id:
        return jsonify({'success': False, 'error': 'Invalid message'})
    
    sender_id = session['user_id']
    
    db = get_db()
    db.execute("INSERT INTO messages (sender_id, receiver_id, message, sent_at) VALUES (?, ?, ?, ?)",
               (sender_id, receiver_id, message, datetime.now().isoformat()))
    db.commit()
    
    return jsonify({'success': True})

@app.route('/study-notes')
@login_required('student')
def study_notes():
    return render_template('study_notes.html')

@app.route('/leaderboard')
@login_required('student')
def leaderboard():
    # Ensure gamification tables exist
    db = get_db()
    try:
        db.execute("SELECT 1 FROM study_streaks LIMIT 1")
    except:
        db.execute("""
            CREATE TABLE study_streaks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                current_streak INTEGER DEFAULT 0,
                last_activity TEXT,
                total_points INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                badge_type TEXT,
                earned_at TEXT
            )
        """)
        db.commit()
    
    # Get top students by points
    top_students = query_db("""
        SELECT u.name, COALESCE(s.total_points, 0) as points, COALESCE(s.current_streak, 0) as streak
        FROM users u
        LEFT JOIN study_streaks s ON u.id = s.user_id
        WHERE u.user_type = 'student'
        ORDER BY points DESC, streak DESC
        LIMIT 10
    """)
    
    # Get current user's rank
    user_stats = query_db("""
        SELECT total_points, current_streak FROM study_streaks WHERE user_id = ?
    """, (session['user_id'],), one=True)
    
    return render_template('leaderboard.html', top_students=top_students, user_stats=user_stats)

@app.route('/math-games')
@login_required('student')
def math_games():
    return render_template('math_games.html')

@app.route('/check-answer', methods=['POST'])
@login_required('student')
def check_answer():
    data = request.json
    answer = data.get('answer')
    correct = data.get('correct')
    
    # Update points and streak
    user_id = session['user_id']
    db = get_db()
    
    # Get or create streak record
    streak_record = query_db("SELECT * FROM study_streaks WHERE user_id = ?", (user_id,), one=True)
    
    if not streak_record:
        db.execute("INSERT INTO study_streaks (user_id, current_streak, total_points, last_activity) VALUES (?, 0, 0, ?)",
                   (user_id, datetime.now().isoformat()))
        db.commit()
        streak_record = query_db("SELECT * FROM study_streaks WHERE user_id = ?", (user_id,), one=True)
    
    points_earned = 10 if str(answer) == str(correct) else 0
    new_streak = streak_record['current_streak'] + 1 if points_earned > 0 else 0
    new_points = streak_record['total_points'] + points_earned
    
    db.execute("UPDATE study_streaks SET current_streak = ?, total_points = ?, last_activity = ? WHERE user_id = ?",
               (new_streak, new_points, datetime.now().isoformat(), user_id))
    db.commit()
    
    return jsonify({
        'correct': str(answer) == str(correct),
        'points_earned': points_earned,
        'total_points': new_points,
        'streak': new_streak
    })

@app.route('/virtual-lab')
@login_required('student')
def virtual_lab():
    return render_template('virtual_lab.html')

def run_flask_app():
    """Function to run Flask app - can be called separately"""
    init_db()
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)

if __name__ == '__main__':
    run_flask_app()