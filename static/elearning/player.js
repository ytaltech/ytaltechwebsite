/**
 * Ytal Tech Slide Player Controller
 * Enforces 1-minute dwell time, handles pause/resume, server sync,
 * practice MCQs with dual input (click or type response letter).
 */
document.addEventListener('DOMContentLoaded', function () {
    const nextBtn = document.getElementById('btnNextSlide');
    const timerDisplay = document.getElementById('slideTimerDisplay');
    const pauseBtn = document.getElementById('btnPauseResume');
    
    if (!nextBtn) return;
    
    const isCompletedPreviously = nextBtn.dataset.completed === 'true';
    const isRevision = nextBtn.dataset.revision === 'true' || window.IS_REVISION_MODE === true;
    const hasPractice = nextBtn.dataset.hasPractice === 'true';
    let practiceAnswered = nextBtn.dataset.practiceAnswered === 'true';
    // 3 seconds for lecture slides (for testing); 0 seconds (no timer) for MCQ slides or revision
    let requiredSeconds = (hasPractice || isCompletedPreviously || isRevision) ? 0 : parseInt(nextBtn.dataset.dwell || '3', 10);
    
    let secondsLeft = (isCompletedPreviously || isRevision || hasPractice) ? 0 : requiredSeconds;
    let isPaused = false;
    let timerInterval = null;
    
    function updateTimerUI() {
        if (!timerDisplay) return;
        if (isRevision) {
            timerDisplay.innerHTML = '📖 Revision Mode (Free Navigation)';
            timerDisplay.classList.add('completed');
            checkEnableNext();
            return;
        }
        if (hasPractice) {
            timerDisplay.innerHTML = practiceAnswered ? '✓ Answer Submitted' : '📝 Submit Response to Proceed';
            if (practiceAnswered) {
                timerDisplay.classList.add('completed');
            } else {
                timerDisplay.classList.remove('completed');
            }
            checkEnableNext();
            return;
        }
        if (secondsLeft <= 0) {
            timerDisplay.innerHTML = '✓ Slide Read & Completed';
            timerDisplay.classList.add('completed');
            checkEnableNext();
        } else {
            const mins = Math.floor(secondsLeft / 60);
            const secs = secondsLeft % 60;
            const timeStr = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
            timerDisplay.innerHTML = `⏱ Required Time: ${timeStr}`;
            timerDisplay.classList.remove('completed');
        }
    }
    
    function checkEnableNext() {
        if (isRevision || isCompletedPreviously) {
            // Free navigation without timer
            if (!hasPractice || practiceAnswered || isRevision) {
                nextBtn.removeAttribute('disabled');
                nextBtn.classList.remove('disabled');
                nextBtn.classList.add('btn-next-active');
                return;
            }
        }
        if (hasPractice) {
            // MCQ slides do NOT have any timer: enabled as soon as answer is submitted
            if (practiceAnswered) {
                nextBtn.removeAttribute('disabled');
                nextBtn.classList.remove('disabled');
                nextBtn.classList.add('btn-next-active');
            } else {
                nextBtn.setAttribute('disabled', 'disabled');
                nextBtn.classList.add('disabled');
                nextBtn.classList.remove('btn-next-active');
            }
            return;
        }

        // Regular lecture slides: enabled when dwell timer completes
        if (secondsLeft <= 0) {
            nextBtn.removeAttribute('disabled');
            nextBtn.classList.remove('disabled');
            nextBtn.classList.add('btn-next-active');
        } else {
            nextBtn.setAttribute('disabled', 'disabled');
            nextBtn.classList.add('disabled');
            nextBtn.classList.remove('btn-next-active');
        }
    }
    
    // Only run timer countdown on regular slides (NOT on MCQ slides)
    if (!hasPractice && secondsLeft > 0) {
        timerInterval = setInterval(function () {
            if (!isPaused && secondsLeft > 0) {
                secondsLeft--;
                updateTimerUI();
                if (secondsLeft <= 0) {
                    clearInterval(timerInterval);
                }
            }
        }, 1000);
    }
    
    updateTimerUI();
    checkEnableNext();
    
    // Pause / Resume capability
    if (pauseBtn) {
        pauseBtn.addEventListener('click', function () {
            isPaused = !isPaused;
            pauseBtn.textContent = isPaused ? 'Resume Timer ▶' : 'Pause Timer ⏸';
            pauseBtn.classList.toggle('btn-warning', isPaused);
        });
    }
    
    // Next Slide Click
    nextBtn.addEventListener('click', function () {
        if (nextBtn.hasAttribute('disabled')) return;
        
        const slug = nextBtn.dataset.slug;
        const slideNum = parseInt(nextBtn.dataset.slideNum, 10);
        const navText = nextBtn.querySelector('.nav-text');
        const origText = navText ? navText.innerHTML : 'Next<br>Page';
        
        nextBtn.setAttribute('disabled', 'disabled');
        nextBtn.classList.remove('btn-next-active');
        nextBtn.classList.add('disabled');
        if (navText) navText.innerHTML = 'Saving...';
        
        fetch('/elearning/api/slide/complete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ slug: slug, slide_number: slideNum })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.href = data.next_url;
            } else {
                alert(data.message || 'Error advancing to next slide.');
                nextBtn.removeAttribute('disabled');
                nextBtn.classList.add('btn-next-active');
                nextBtn.classList.remove('disabled');
                if (navText) navText.innerHTML = origText;
            }
        })
        .catch(err => {
            console.error('Slide completion error:', err);
            nextBtn.removeAttribute('disabled');
            nextBtn.classList.add('btn-next-active');
            nextBtn.classList.remove('disabled');
            if (navText) navText.innerHTML = origText;
        });
    });

    // Keyboard navigation: Left Arrow -> Previous, Right Arrow -> Next
    document.addEventListener('keydown', function (e) {
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
        if (e.key === 'ArrowLeft') {
            const prevBtn = document.getElementById('btnPrevSlide');
            if (prevBtn && !prevBtn.hasAttribute('disabled') && !prevBtn.classList.contains('disabled')) {
                prevBtn.click();
            }
        } else if (e.key === 'ArrowRight') {
            if (nextBtn && !nextBtn.hasAttribute('disabled')) {
                nextBtn.click();
            }
        }
    });
    
    // Practice MCQ: Bi-directional click & text input sync + Submission
    const practiceForms = document.querySelectorAll('.practice-mcq-form');
    practiceForms.forEach(form => {
        const textInput = form.querySelector('.practice-text-input');
        const radios = form.querySelectorAll('input[name="practice_option"]');
        const mcqId = form.dataset.mcqId;
        const prevResponse = (window.PREVIOUS_MCQ_RESPONSES && window.PREVIOUS_MCQ_RESPONSES[mcqId]) ? window.PREVIOUS_MCQ_RESPONSES[mcqId] : null;

        // If previously answered & vetted by system, restore full vetted state immediately
        if (prevResponse) {
            // Select user's previous option and disable inputs
            radios.forEach(r => {
                if (r.value === prevResponse.selected_option) {
                    r.checked = true;
                }
                r.disabled = true;
            });
            if (textInput) {
                textInput.value = prevResponse.selected_option || '';
                textInput.disabled = true;
            }

            // Disable all option clicks so no other option is clickable
            form.querySelectorAll('.option-item').forEach(item => {
                item.style.pointerEvents = 'none';
                item.style.cursor = 'default';
            });

            // Highlight options: green for correct, red for incorrect chosen
            form.querySelectorAll('.option-item').forEach(item => {
                const optInput = item.querySelector('input');
                if (optInput) {
                    const val = optInput.value;
                    if (val === prevResponse.correct_option) {
                        item.classList.add('correct');
                    } else if (val === prevResponse.selected_option && !prevResponse.is_correct) {
                        item.classList.add('incorrect');
                    }
                }
            });

            // Display vetted result and rationale box
            const resultContainer = form.querySelector('.practice-result');
            if (resultContainer) {
                resultContainer.style.display = 'block';
                const isCorrect = prevResponse.is_correct;
                resultContainer.innerHTML = `
                    <div class="explanation-box" style="border-left-color: ${isCorrect ? '#22c55e' : '#ef4444'}; background: ${isCorrect ? '#f0fdf4' : '#fef2f2'}; padding: 15px; border-radius: 6px;">
                        <div style="font-size: 1.1rem; font-weight: bold; color: ${isCorrect ? '#166534' : '#991b1b'};">
                            ${isCorrect ? '✓ Correct Answer!' : '✗ Incorrect Response.'}
                        </div>
                        <div style="margin-top: 6px; font-weight: 700; color: #1e293b;">
                            Correct Option: <strong>Option ${prevResponse.correct_option}</strong>
                        </div>
                        <div style="margin-top: 6px; font-size: 0.95rem; color: #334155; line-height: 1.5;">
                            <strong>Rationale:</strong> ${prevResponse.explanation || 'Answer previously recorded and vetted by system.'}
                        </div>
                    </div>
                `;
            }

            // Set submit button to disabled "Submitted & Vetted" state
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.setAttribute('disabled', 'disabled');
                submitBtn.textContent = 'Submitted & Vetted ✓';
                submitBtn.style.background = '#64748b';
            }

            practiceAnswered = true;
            if (timerDisplay && hasPractice) {
                timerDisplay.innerHTML = '✓ Vetted & Completed';
                timerDisplay.classList.add('completed');
            }
            checkEnableNext();
        }
        
        // When clicking a radio option, sync text input
        radios.forEach(r => {
            r.addEventListener('change', function () {
                if (textInput && r.checked) {
                    textInput.value = r.value;
                }
            });
        });
        
        // When typing in text input, select corresponding radio option
        if (textInput) {
            textInput.addEventListener('input', function () {
                const val = (textInput.value || '').trim().toUpperCase();
                textInput.value = val;
                if (['A', 'B', 'C', 'D'].includes(val)) {
                    radios.forEach(r => {
                        if (r.value === val) {
                            r.checked = true;
                        }
                    });
                }
            });
        }
        
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            const mcqId = form.dataset.mcqId;
            const selectedRadio = form.querySelector('input[name="practice_option"]:checked');
            if (!selectedRadio) {
                alert('Please select or type an option (A, B, C, or D) to submit your answer.');
                return;
            }
            
            const submitBtn = form.querySelector('button[type="submit"]');
            submitBtn.setAttribute('disabled', 'disabled');
            submitBtn.textContent = 'Verifying...';
            
            fetch('/elearning/api/practice/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mcq_id: parseInt(mcqId, 10),
                    selected_option: selectedRadio.value
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const resultContainer = form.querySelector('.practice-result');
                    resultContainer.style.display = 'block';
                    
                    const isCorrect = data.is_correct;
                    resultContainer.innerHTML = `
                        <div class="explanation-box" style="border-left-color: ${isCorrect ? '#22c55e' : '#ef4444'}; background: ${isCorrect ? '#f0fdf4' : '#fef2f2'}; padding: 15px; border-radius: 6px;">
                            <div style="font-size: 1.1rem; font-weight: bold; color: ${isCorrect ? '#166534' : '#991b1b'};">
                                ${isCorrect ? '✓ Correct Answer!' : '✗ Incorrect Response.'}
                            </div>
                            <div style="margin-top: 6px; font-weight: 700; color: #1e293b;">
                                Correct Option: <strong>Option ${data.correct_option}</strong>
                            </div>
                            <div style="margin-top: 6px; font-size: 0.95rem; color: #334155; line-height: 1.5;">
                                <strong>Rationale:</strong> ${data.explanation}
                            </div>
                        </div>
                    `;
                    
                    // Visual indicators on options & lock so no other option is clickable
                    form.querySelectorAll('.option-item').forEach(item => {
                        const val = item.querySelector('input').value;
                        if (val === data.correct_option) item.classList.add('correct');
                        else if (val === selectedRadio.value && !isCorrect) item.classList.add('incorrect');
                        item.style.pointerEvents = 'none';
                        item.style.cursor = 'default';
                    });
                    
                    // Disable inputs completely so response cannot be changed
                    radios.forEach(r => { r.disabled = true; });
                    if (textInput) textInput.disabled = true;

                    submitBtn.setAttribute('disabled', 'disabled');
                    submitBtn.textContent = 'Submitted & Vetted ✓';
                    submitBtn.style.background = '#64748b';
                    submitBtn.style.pointerEvents = 'none';
                    practiceAnswered = true;
                    if (timerDisplay && hasPractice) {
                        timerDisplay.innerHTML = '✓ Answer Submitted';
                        timerDisplay.classList.add('completed');
                    }
                    checkEnableNext();
                } else {
                    alert(data.message || 'Error submitting practice question.');
                    submitBtn.removeAttribute('disabled');
                    submitBtn.textContent = 'Submit Response ➔';
                }
            })
            .catch(err => {
                console.error(err);
                submitBtn.removeAttribute('disabled');
                submitBtn.textContent = 'Submit Response ➔';
            });
        });
    });
});
