// Chat functionality is now handled in individual page scripts

// Enhanced Quiz Functionality with better UX
async function submitQuiz(quiz_id) {
  // Validation - check if all questions are answered
  
  const totalQuestions = document.querySelectorAll('.question').length;
  const answeredQuestions = document.querySelectorAll('form#quiz-form input[type=radio]:checked').length;
  
  if (answeredQuestions < totalQuestions) {
    if (!confirm(`You have answered ${answeredQuestions} out of ${totalQuestions} questions. Submit anyway?`)) {
      return;
    }
  }
  
  // Disable submit button to prevent double submission
  const submitBtn = event.target;
  const originalText = submitBtn.innerHTML;
  submitBtn.disabled = true;
  submitBtn.innerHTML = '⏳ Submitting...';
  
  try {
    const inputs = document.querySelectorAll('form#quiz-form input[type=radio]:checked');
    let answers = {};
    inputs.forEach(input => {
      const questionName = input.name; // q<id>
      const questionId = questionName.replace('q', '');
      answers[questionId] = parseInt(input.value);
    });
    
    const res = await fetch('/submit_quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        quiz_id: quiz_id,
        answers: answers
      })
    });
    
    const data = await res.json();
    showQuizResults(data);
    
  } catch (error) {
    alert('Error submitting quiz. Please try again.');
    console.error('Quiz submission error:', error);
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = originalText;
  }
}

function showQuizResults(data) {
  const resultDiv = document.getElementById('result');
  resultDiv.style.display = 'block';
  
  let scoreClass = 'success';
  let scoreEmoji = '🎉';
  let scoreMessage = 'Excellent work!';
  
  if (data.score < 50) {
    scoreClass = 'danger';
    scoreEmoji = '📚';
    scoreMessage = 'Keep studying!';
  } else if (data.score < 70) {
    scoreClass = 'warning';
    scoreEmoji = '👍';
    scoreMessage = 'Good effort!';
  }
  
  let html = `
    <div style="text-align: center; margin-bottom: 2rem;">
      <div style="font-size: 4rem; margin-bottom: 1rem;">${scoreEmoji}</div>
      <h2 style="margin: 0; color: var(--${scoreClass === 'success' ? 'success' : scoreClass === 'warning' ? 'warning' : 'danger'});">Your Score: ${data.score}%</h2>
      <p style="font-size: 1.2rem; margin: 0.5rem 0;">${scoreMessage}</p>
    </div>
  `;
  
  if (data.recommendations && data.recommendations.length > 0) {
    html += `
      <div style="background: var(--bg); padding: 1.5rem; border-radius: 0.5rem; margin-top: 1rem;">
        <h3 style="margin-top: 0; color: var(--primary);">📈 Recommendations for Improvement</h3>
        <ul style="margin: 0; padding-left: 1.5rem;">
    `;
    data.recommendations.forEach(rec => {
      html += `<li style="margin-bottom: 0.5rem;">Focus on <strong>${rec.topic}</strong> (scored ${rec.score_pct}%)</li>`;
    });
    html += `
        </ul>
        <p style="margin-top: 1rem; color: var(--text-light);">💡 Tip: Use the AI tutor to get help with these topics!</p>
      </div>
    `;
  } else {
    html += `
      <div class="alert alert-success">
        <strong>🌟 Perfect!</strong> You've mastered all the concepts. Keep up the great work!
      </div>
    `;
  }
  
  html += `
    <div style="text-align: center; margin-top: 2rem;">
      <a href="javascript:history.back()" class="btn btn-secondary">← Back to Lesson</a>
      <a href="/student" class="btn" style="margin-left: 1rem;">🏠 Student Home</a>
    </div>
  `;
  
  resultDiv.innerHTML = html;
  
  // Scroll to results
  resultDiv.scrollIntoView({ behavior: 'smooth' });
}

// Utility Functions
function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString() + ' at ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Initialize page functionality
document.addEventListener('DOMContentLoaded', function() {
  // Auto-focus on name input in quiz page
  const nameInput = document.getElementById('student-name');
  if (nameInput && !nameInput.value) {
    nameInput.focus();
  }
  
  // Add keyboard shortcuts
  document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + Enter to submit quiz
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      const submitBtn = document.querySelector('button[onclick*="submitQuiz"]');
      if (submitBtn) {
        submitBtn.click();
      }
    }
  });
});

// Add smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    e.preventDefault();
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      target.scrollIntoView({ behavior: 'smooth' });
    }
  });
});

// Add loading states for buttons
function addLoadingState(button, originalText) {
  button.disabled = true;
  button.innerHTML = '⏳ Loading...';
  
  return function removeLoadingState() {
    button.disabled = false;
    button.innerHTML = originalText;
  };
}
