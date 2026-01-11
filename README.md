# Smart Learning Cloud 

AI-Powered Smart Learning Platform for Bridging Urban-Rural Educational Gaps

## Overview

Smart Learning Cloud is a comprehensive educational platform designed to connect urban teachers with rural students through cloud-based technology. The platform leverages artificial intelligence to provide personalized learning experiences, instant doubt clearing, and performance analytics.

## Features

### Core Features
- **Live Video Lessons**: Teachers can upload and share video content
- **Interactive Quizzes**: Automated quiz creation and assessment
- **AI Tutor Chatbot**: 24/7 instant doubt clearing and study assistance
- **Performance Analytics**: Detailed progress tracking and recommendations
- **Responsive Design**: Works on all devices - desktop, tablet, mobile

###  For Teachers
- Create and manage video lessons
- Design custom quizzes with multiple choice questions
- Track student performance and analytics
- Professional dashboard with insights

###  For Students
- Access video lessons anytime, anywhere
- Take interactive quizzes to test understanding
- Get personalized learning recommendations
- Chat with AI tutor for instant help
- Track learning progress over time

###  AI Features
- Intelligent chatbot for doubt clearing
- Performance-based learning recommendations
- Topic-wise score analysis
- Motivational support and study tips

## Technology Stack

- **Backend**: Python Flask
- **Frontend**: HTML5, CSS3, JavaScript
- **Database**: SQLite (development) / PostgreSQL (production)
- **AI/ML**: scikit-learn, TF-IDF vectorization
- **Deployment**: Heroku, AWS-ready
- **Styling**: Modern CSS with CSS Grid and Flexbox

## Quick Start

### Local Development

1. **Clone the repository**
   
   git clone <repository-url>
   cd smart-learning-full
  

2. **Install dependencies**
   
   pip install -r requirements.txt
  

3. **Run the application**
  
   python app.py
  


#### AWS Deployment
1. Use AWS Elastic Beanstalk for easy deployment
2. Configure environment variables
3. Set up RDS for production database
4. Use CloudFront for CDN (optional)

## Usage Guide

### For Teachers
1. Go to **Teacher Dashboard**
2. Create new lessons with title, description, and video URL
3. Add quizzes using the **Add Quiz** button
4. Monitor student progress in **Results** section

### For Students
1. Visit **Student Portal**
2. Browse available courses
3. Click **Start Learning** to watch video lessons
4. Take quizzes to test your knowledge
5. Use the **AI Tutor** chatbot for help
6. Check your progress in **Results**

### AI Tutor Usage
The AI tutor can help with:
- Math concepts (fractions, decimals, basic operations)
- Platform navigation and usage
- Study tips and motivation
- Quiz guidance and explanations

Example questions:
- "What is a fraction?"
- "How do I take a quiz?"
- "I'm struggling with math"
- "How to study effectively?"

## Configuration

### Environment Variables

FLASK_ENV=production
SECRET_KEY=your-secret-key-here
DATABASE_URL=your-database-url (for production)


### Database Schema
The application uses the following tables:
- `lessons`: Store video lessons and content
- `quizzes`: Quiz metadata linked to lessons
- `questions`: Individual quiz questions with options
- `attempts`: Student quiz attempts and scores
