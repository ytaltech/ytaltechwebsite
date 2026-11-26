import os
import re
from datetime import datetime, timezone
from pptx import Presentation
from elearning.models import db, User, Course, Slide, MCQ, Enrolment, SystemSetting

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

COURSES_CONFIG = [
    {
        'slug': 'good-documentation-practices',
        'title': 'Good Documentation Practices (GDP)',
        'filename': 'Good Documentation Practice Training - Ytal Tech Edition.pptx',
        'mcq_filename': 'Good Documentation Practice Training - MCQs.pptx',
        'short_description': 'Master essential documentation standards, ALCOA+ principles, data integrity, and regulatory audit compliance across the record life cycle (GxP aligned).',
        'overview': 'This course provides comprehensive training on Good Documentation Practices (GDP) applicable across clinical trials, healthcare data management, and GxP regulated industries. Learners will understand ALCOA+ guidelines, contemporary signature rules, error rectification protocols, and electronic record compliance under 21 CFR Part 11.',
        'estimated_duration': '2 Hours',
        'language': 'English',
        'price_inr': 499.00,
        'gst_rate': 0.18,
        'price_usd': 9.49,
        'version': '1.0'
    },
    {
        'slug': 'ich-gcp',
        'title': 'Good Clinical Practices (ICH-GCP)',
        'filename': 'ICH GCP Training - Ytal Tech Edition.pptx',
        'mcq_filename': 'ICH GCP Training - MCQs.pptx',
        'short_description': 'Comprehensive training on ICH E6(R3) guidelines, investigator obligations, Ethics Committees, subject consent, trial monitoring, and quality management.',
        'overview': 'The Good Clinical Practice (GCP) module covers the international ethical, scientific, and quality standards for designing, conducting, recording, and reporting trials involving human subjects. Aligned with the latest International Council for Harmonisation (ICH E6(R2)/(R3)) standards.',
        'estimated_duration': '2.5 Hours',
        'language': 'English',
        'price_inr': 499.00,
        'gst_rate': 0.18,
        'price_usd': 9.49,
        'version': '1.0'
    },
    {
        'slug': 'new-drugs-clinical-trials-rules-2019',
        'title': 'New Drugs and Clinical Trial Rules, 2019',
        'filename': 'NDCT Rules 2019 Training Presentation - Ytal Tech Edition.pptx',
        'mcq_filename': 'NDCT Rules 2019 Training Presentation - MCQs.pptx',
        'short_description': 'Master the Indian regulatory landscape under CDSCO, Form CT approvals, Ethics Committee registration, compensation guidelines, and statutory formulas.',
        'overview': 'The New Drugs and Clinical Trial (NDCT) Rules, 2019 comprehensively govern clinical research in India. This module details CDSCO approval pathways (Form CT-04, CT-06), Ethics Committee governance, Academic Clinical Trial exemptions, and statutory compensation for trial-related injuries.',
        'estimated_duration': '2 Hours',
        'language': 'English',
        'price_inr': 499.00,
        'gst_rate': 0.18,
        'price_usd': 9.49,
        'version': '1.0'
    }
]


def clean_slide_text(text):
    """
    Cleans raw slide text, converts Private Use Area / Wingdings arrow characters
    (e.g., \uf0e0, \uf0e8, , ) and text arrows (-->) into standard arrows (➔),
    and removes extraneous bullet formatting.
    """
    if not text:
        return ""
    text = text.replace('\uf0e0', ' ➔ ')
    text = text.replace('\uf0e8', ' ➔ ')
    text = text.replace('', ' ➔ ')
    text = text.replace('', ' ➔ ')
    text = text.replace('-->', ' ➔ ')
    text = text.replace('->', ' ➔ ')
    text = re.sub(r'^[▸•\-\*✓\s]+', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def extract_mcq_data_from_slide(shapes, joined_text):
    """
    Extracts MCQ question prompt, options A, B, C, D, correct option, and explanation
    from slide shapes. Ensures correct answers and explanations are extracted
    for database storage and strictly hidden from slide display.
    """
    options = {'A': '', 'B': '', 'C': '', 'D': ''}
    
    # 1. Correct Option
    match = re.search(r'CORRECT ANSWER:\s*OPTION\s*([A-D])', joined_text, re.IGNORECASE)
    corr_opt = match.group(1).upper() if match else 'A'
    
    # 2. Explanation / Learning Key
    exp_match = re.search(r'Learning Key / Explanation:\s*(.+)', joined_text, re.IGNORECASE | re.DOTALL)
    explanation = exp_match.group(1).strip() if exp_match else 'Reinforces Good Clinical and Documentation Practice.'
    explanation = re.split(r'YTAL TECH E-LEARNING|Ytal Tech E-Learning', explanation)[0].strip()
    
    # 3. Extract Options based on PPTX 2x2 shape layout coordinates
    for shp in shapes:
        t = shp.text_frame.text.strip()
        if t in ['A', 'B', 'C', 'D'] and shp.width < 1000000 and shp.height < 1000000:
            continue
        if shp.top > 2000000 and shp.top < 4800000:
            if 'CORRECT ANSWER' not in t and 'QUESTION' not in t and 'CHECK' not in t and 'ASSESSMENT' not in t and 'YTAL' not in t:
                if shp.left < 5000000:
                    if shp.top < 3600000:
                        options['A'] = t
                    else:
                        options['C'] = t
                else:
                    if shp.top < 3600000:
                        options['B'] = t
                    else:
                        options['D'] = t

    # Fallback option extraction if coordinate extraction missed any
    if not (options['A'] and options['B'] and options['C'] and options['D']):
        plain_texts = [shp.text_frame.text.strip() for shp in shapes]
        for i, t in enumerate(plain_texts):
            if t in ['A', 'B', 'C', 'D'] and i + 1 < len(plain_texts):
                options[t] = plain_texts[i + 1]
            elif re.match(r'^[A-D][\.\:\)]\s*(.+)', t):
                m = re.match(r'^([A-D])[\.\:\)]\s*(.+)', t)
                options[m.group(1)] = m.group(2)
                
    # 4. Extract Question Prompt
    question = ''
    for shp in shapes:
        t = shp.text_frame.text.strip()
        if shp.top > 1000000 and shp.top < 2600000:
            if 'CHECK' not in t and 'ASSESSMENT' not in t and 'QUESTION' not in t and 'YTAL' not in t and len(t) > 10:
                question = t
                break
                
    if not question:
        for shp in shapes:
            t = shp.text_frame.text.strip()
            if len(t) > 15 and 'CORRECT ANSWER' not in t and 'YTAL TECH' not in t and t not in options.values():
                question = t
                break

    clean_options = {k: clean_slide_text(v) for k, v in options.items()}
    clean_question = clean_slide_text(question)
    clean_explanation = clean_slide_text(explanation)
    return clean_question or "Assessment Question", clean_options, corr_opt, clean_explanation


def build_slide_html(slide_type, breadcrumb, title, shapes, idx, total_slides, course_slug, q_data=None):
    """
    Constructs high-fidelity presentation HTML for the slide matching
    the exact visual layout, card structure, and colors from PowerPoint.
    """
    breadcrumb_clean = breadcrumb or f"YTAL TECH E-LEARNING • SLIDE {idx:02d}"
    title_clean = title or f"Slide {idx}"

    # Header and accent bar template (against white card background)
    header_html = f'''
    <div class="slide-presentation-header">
        <div class="slide-accent-bar"></div>
        <div class="slide-breadcrumb">{breadcrumb_clean}</div>
        <h2 class="slide-title-text">{title_clean}</h2>
        <div class="slide-title-underline"></div>
    </div>
    '''

    footer_html = f'''
    <div class="slide-presentation-footer">
        <div class="footer-left">Ytal Tech E-Learning Platform • <a href="https://www.ytaltech.com" target="_blank">www.ytaltech.com</a></div>
        <div class="footer-right">Page {idx}</div>
    </div>
    '''

    body_inner = ""

    # 1. COURSE COVER SLIDE (Slide 1)
    if slide_type == 'COVER':
        header_html = ""  # Cover has custom full-bleed hero layout
        subtitle = ""
        target_audience = "GMP, GCP, GLP, Pharmacovigilance, Quality, Regulatory, Laboratory & Clinical Data Professionals"
        for shp in shapes:
            t = shp.text_frame.text.strip()
            if 'TARGET AUDIENCE' in t.upper():
                target_audience = t.replace('TARGET AUDIENCE & APPLICABILITY:', '').strip()
            elif len(t) > 20 and 'Ytal Tech' not in t and 'CERTIFIED' not in t and 'Published' not in t:
                subtitle = t

        body_inner = f'''
        <div class="presentation-cover-slide">
            <div class="cover-top-eyebrow">Ytal Tech &nbsp;|&nbsp; PROFESSIONAL E-LEARNING</div>
            <div class="cover-badge">CERTIFIED E-LEARNING PROGRAM</div>
            <h1 class="cover-main-title">{title_clean}</h1>
            <div class="cover-subtitle">{subtitle}</div>
            <div class="cover-target-box">
                <div class="target-label">🎯 TARGET AUDIENCE & APPLICABILITY:</div>
                <div class="target-desc">{target_audience}</div>
            </div>
            <div class="cover-publisher-footer">
                Published by Ytal Tech Solutions & Services LLP • <a href="https://www.ytaltech.com" target="_blank" style="color: #38bdf8;">www.ytaltech.com</a>
            </div>
        </div>
        '''

    # 2. CURRICULUM DIRECTORY SLIDE (Slide 2)
    elif slide_type == 'CURRICULUM':
        modules = []
        for shp in shapes:
            t = shp.text_frame.text.strip()
            if re.match(r'^Module\s+\d+', t, re.IGNORECASE):
                # find matching text shape close to this badge vertically
                desc_text = ""
                for s2 in shapes:
                    if s2 != shp and s2.top > 1200000 and s2.top < 6200000:
                        if abs(s2.top - shp.top) < 250000:
                            if (shp.left < 5000000 and s2.left < 5000000 and s2.left > shp.left) or \
                               (shp.left >= 5000000 and s2.left >= 5000000 and s2.left > shp.left):
                                desc_text = s2.text_frame.text.strip()
                                break
                modules.append({'badge': t, 'desc': desc_text})

        # Deduplicate and sort modules
        unique_modules = []
        seen_badges = set()
        for m in modules:
            if m['badge'] not in seen_badges:
                seen_badges.add(m['badge'])
                unique_modules.append(m)

        cards_html = ""
        for m in unique_modules:
            title_part = ""
            desc_part = ""
            parts = m['desc'].split('\n')
            if parts:
                title_part = parts[0].strip()
                desc_part = " ".join(p.strip() for p in parts[1:]) if len(parts) > 1 else ""
            cards_html += f'''
            <div class="directory-module-card">
                <div class="module-badge-pill">{m['badge']}</div>
                <div class="module-info">
                    <div class="module-card-title">{title_part}</div>
                    <div class="module-card-desc">{desc_part}</div>
                </div>
            </div>
            '''

        body_inner = f'''
        <div class="presentation-directory-slide">
            <div class="directory-cards-grid">
                {cards_html}
            </div>
        </div>
        '''

    # 3. MODULE COVER SLIDE (e.g. Slide 3)
    elif slide_type == 'MODULE_COVER':
        module_badge = "MODULE"
        module_desc = ""
        structure_text = "Learning Objectives • Core Regulatory Lessons • Real-World Case Studies • Knowledge Check"
        for shp in shapes:
            t = shp.text_frame.text.strip()
            if re.match(r'^MODULE\s+\d+', t, re.IGNORECASE):
                module_badge = t
            elif 'MODULE STRUCTURE:' in t.upper():
                structure_text = t.replace('MODULE STRUCTURE:', '').strip()
            elif shp.top > 2000000 and shp.top < 4500000 and len(t) > 15 and 'YTAL' not in t:
                module_desc = t

        body_inner = f'''
        <div class="presentation-module-cover">
            <div class="module-separator-tag" style="color: #FFF200 !important; font-weight: 800; font-size: 0.95rem; letter-spacing: 1.2px; text-transform: uppercase; margin-bottom: 12px; text-shadow: 0 1px 3px rgba(0,0,0,0.5);">{breadcrumb_clean}</div>
            <div class="module-cover-pill" style="background: #FFF200 !important; color: #0A192F !important; font-weight: 900;">{module_badge}</div>
            <h2 class="module-cover-title" style="color: #FFF200 !important; font-size: 1.5rem; font-weight: 800; line-height: 1.3; margin: 8px 0 10px;">{title_clean}</h2>
            <div class="module-cover-desc">{module_desc}</div>
            <div class="module-structure-card">
                <span class="structure-label">MODULE STRUCTURE:</span>
                <span class="structure-items">{structure_text}</span>
            </div>
        </div>
        '''

    # 4. CASE STUDY SLIDE (Real-world scenarios with 2 columns & takeaway)
    elif slide_type == 'CASE_STUDY':
        scenario_title = "Case Scenario"
        scenario_text = ""
        discussion_points = []
        takeaway_text = ""

        for shp in shapes:
            t = shp.text_frame.text.strip()
            if 'CASE STUDY' in t.upper() and shp.top < 2200000 and shp.left < 5000000:
                scenario_title = clean_slide_text(t)
            elif 'KEY REGULATORY TAKEAWAY:' in t.upper():
                raw_takeaway = t.replace('KEY REGULATORY TAKEAWAY:', '').strip()
                raw_takeaway = re.split(r'Final Comprehensive Assessment|FINAL ASSESSMENT', raw_takeaway, flags=re.IGNORECASE)[0].strip()
                takeaway_text = clean_slide_text(raw_takeaway)
            elif shp.top > 1400000 and shp.top < 5000000:
                if 'REGULATORY ASSESSMENT' in t.upper() or 'CASE STUDY' in t.upper() or 'YTAL' in t.upper():
                    continue
                if shp.left < 5000000:
                    scenario_text += " " + clean_slide_text(t)
                else:
                    for line in t.split('\n'):
                        line_clean = clean_slide_text(line)
                        if line_clean:
                            discussion_points.append(line_clean)

        disc_html = "".join(f'<li class="discussion-item"><span class="disc-marker">▸</span><span>{p}</span></li>' for p in discussion_points)

        body_inner = f'''
        <div class="presentation-case-study">
            <div class="case-study-top-grid">
                <div class="case-study-scenario-card">
                    <div class="scenario-badge">{scenario_title}</div>
                    <div class="scenario-body-text">{scenario_text.strip()}</div>
                </div>
                <div class="case-study-discussion-card">
                    <div class="discussion-heading">REGULATORY ASSESSMENT & DISCUSSION</div>
                    <ul class="discussion-list">
                        {disc_html}
                    </ul>
                </div>
            </div>
            {f'<div class="case-study-takeaway-card"><strong>KEY REGULATORY TAKEAWAY:</strong> {takeaway_text}</div>' if takeaway_text else ''}
        </div>
        '''

    # 5. DUAL COMPARISON SLIDE (e.g. Documents vs Records)
    elif slide_type == 'COMPARISON':
        left_header = "CONTROLLED DOCUMENTS (INSTRUCTIONS)"
        right_header = "COMPLETED RECORDS (EVIDENCE)"
        left_points = []
        right_points = []

        for shp in shapes:
            t = shp.text_frame.text.strip()
            # Skip title, breadcrumb, footers, slide numbers
            if not t or 'YTAL' in t or 'Platform' in t or t == title_clean or (t.isdigit() and len(t) < 4):
                continue
            if shp.top > 1200000 and shp.top < 6200000:
                paras = [clean_slide_text(p.text.strip()) for p in shp.text_frame.paragraphs if p.text.strip()]
                if not paras:
                    continue
                if shp.left < 5500000:
                    left_header = paras[0]
                    left_points.extend(paras[1:])
                else:
                    right_header = paras[0]
                    right_points.extend(paras[1:])

        left_html = "".join(f'<li><span class="chk-icon">✓</span><span>{p}</span></li>' for p in left_points if p)
        right_html = "".join(f'<li><span class="chk-icon">✓</span><span>{p}</span></li>' for p in right_points if p)

        body_inner = f'''
        <div class="presentation-comparison-grid">
            <div class="comparison-column col-cyan">
                <div class="comparison-header-banner cyan-banner">{left_header}</div>
                <div class="comparison-card-body">
                    <ul>{left_html}</ul>
                </div>
            </div>
            <div class="comparison-column col-magenta">
                <div class="comparison-header-banner magenta-banner">{right_header}</div>
                <div class="comparison-card-body">
                    <ul>{right_html}</ul>
                </div>
            </div>
        </div>
        '''

    # 6. MCQ SLIDES (Both Sample MCQs in modules & Test MCQs towards end)
    elif slide_type in ['KNOWLEDGE_CHECK', 'FINAL_ASSESSMENT']:
        is_practice = (slide_type == 'KNOWLEDGE_CHECK')
        badge_label = "💡 KNOWLEDGE CHECK ASSESSMENT" if is_practice else "📝 FINAL ASSESSMENT QUESTION"
        q_prompt = q_data['question'] if q_data else "Assessment Question"
        opts = q_data['options'] if q_data else {'A': '', 'B': '', 'C': '', 'D': ''}

        body_inner = f'''
        <div class="presentation-mcq-container">
            <div class="mcq-prompt-card">
                <div class="mcq-badge-pill {'badge-practice' if is_practice else 'badge-final'}">{badge_label}</div>
                <div class="mcq-question-prompt">{q_prompt}</div>
            </div>

            <form class="practice-mcq-form" data-mcq-id="__MCQ_ID_PLACEHOLDER__">
                <div class="mcq-options-grid">
                    <label class="option-item mcq-option-card" data-opt="A">
                        <input type="radio" name="practice_option" value="A" required>
                        <span class="opt-badge">A</span>
                        <span class="opt-text">{opts['A']}</span>
                    </label>
                    <label class="option-item mcq-option-card" data-opt="B">
                        <input type="radio" name="practice_option" value="B" required>
                        <span class="opt-badge">B</span>
                        <span class="opt-text">{opts['B']}</span>
                    </label>
                    <label class="option-item mcq-option-card" data-opt="C">
                        <input type="radio" name="practice_option" value="C" required>
                        <span class="opt-badge">C</span>
                        <span class="opt-text">{opts['C']}</span>
                    </label>
                    <label class="option-item mcq-option-card" data-opt="D">
                        <input type="radio" name="practice_option" value="D" required>
                        <span class="opt-badge">D</span>
                        <span class="opt-text">{opts['D']}</span>
                    </label>
                </div>

                <!-- Dual response input: Click option card above OR type letter A, B, C, D below -->
                <div class="mcq-dual-response-bar">
                    <div class="dual-input-wrap">
                        <span class="dual-label">Selected Response:</span>
                        <input type="text" class="practice-text-input form-control" maxlength="1" placeholder="—" title="Type A, B, C, or D">
                    </div>
                    <button type="submit" class="btn-submit-mcq">
                        Submit Response ➔
                    </button>
                </div>

                <div class="practice-result" style="display: none; margin-top: 18px;"></div>
            </form>
        </div>
        '''

    # 7. ASSESSMENT INTRO SLIDE (Introduction to comprehensive test)
    elif slide_type == 'ASSESSMENT_INTRO':
        intro_desc = "Comprehensive Course Assessment covering all regulatory modules. 80% passing threshold required for certified track."
        for shp in shapes:
            t = shp.text_frame.text.strip()
            if 'Multiple Choice' in t or 'Pass Mark' in t:
                intro_desc = t

        body_inner = f'''
        <div class="presentation-assessment-intro">
            <div class="assessment-intro-card">
                <div class="assessment-intro-pill">COMPREHENSIVE ASSESSMENT</div>
                <h3 class="assessment-intro-headline">{title_clean}</h3>
                <p class="assessment-intro-lead">{intro_desc}</p>
                <div class="assessment-rules-grid">
                    <div class="rule-box">
                        <div class="rule-icon">🎯</div>
                        <div class="rule-title">Passing Standard</div>
                        <div class="rule-desc">80% Correct Score (16 of 20)</div>
                    </div>
                    <div class="rule-box">
                        <div class="rule-icon">⏱</div>
                        <div class="rule-title">Time Duration</div>
                        <div class="rule-desc">45 Minutes Allowed</div>
                    </div>
                    <div class="rule-box">
                        <div class="rule-icon">🔄</div>
                        <div class="rule-title">Attempts Allowed</div>
                        <div class="rule-desc">3 Attempts per Cycle</div>
                    </div>
                </div>
            </div>
        </div>
        '''

    # 8. COURSE COMPLETION & CERTIFICATION SLIDE (Final slide of presentation)
    elif slide_type == 'COMPLETION':
        body_inner = f'''
        <div class="presentation-completion-slide">
            <div class="completion-hero-card">
                <div class="completion-pill">COURSE COMPLETION & CERTIFICATION</div>
                <h2 class="completion-title">Congratulations on Completing the Curriculum!</h2>
                <p class="completion-subtitle">
                    You have successfully navigated through all instructional modules and knowledge checks.
                </p>
                
                <div class="completion-steps-box">
                    <h4>Next Steps to Finalize Your Accreditation:</h4>
                    <ol>
                        <li><strong>Complete Final Examination:</strong> 20 randomized multiple-choice questions with a passing mark of 80% (16/20).</li>
                        <li><strong>Payment Verification (Paid Track):</strong> Verify your payment order reference with Finance Administration.</li>
                        <li><strong>Download Certificate:</strong> Obtain your tamper-evident, cryptographically signed PDF certificate with live QR verification.</li>
                    </ol>
                </div>

                <div class="completion-cta-container">
                    <a href="/elearning/course/{course_slug}/test" class="btn-primary-action">
                        Take Final Certified Examination ➔
                    </a>
                </div>
            </div>
        </div>
        '''

    # 9. STANDARD LECTURE CONTENT SLIDE
    else:
        lead_text = ""
        bullet_items = []
        callout_text = ""

        filtered_shapes = []
        for shp in shapes:
            t = shp.text_frame.text.strip()
            if 'YTAL TECH E-LEARNING' in t or 'Platform' in t or t == title_clean or (t.isdigit() and len(t) < 4):
                continue
            filtered_shapes.append(shp)

        for shp in filtered_shapes:
            for p in shp.text_frame.paragraphs:
                raw_t = p.text.strip()
                if not raw_t:
                    continue
                cleaned_t = clean_slide_text(raw_t)
                if not cleaned_t:
                    continue
                if not lead_text and shp.top < 1800000 and not raw_t.startswith('▸') and not raw_t.startswith('✓') and not raw_t.startswith('•') and not raw_t.startswith('-'):
                    lead_text = cleaned_t
                elif 'NOTE:' in raw_t.upper() or 'IMPORTANT:' in raw_t.upper() or 'DEFINITION:' in raw_t.upper():
                    callout_text = cleaned_t
                else:
                    icon = '✓' if raw_t.startswith('✓') else ('▸' if raw_t.startswith('▸') else '•')
                    bullet_items.append((icon, cleaned_t))

        items_html = "".join(f'''
        <li class="lecture-list-item {'icon-check' if icon == '✓' else ('icon-arrow' if icon == '▸' else 'icon-bullet')}">
            <span class="item-symbol">{icon}</span>
            <span class="item-content">{text}</span>
        </li>
        ''' for icon, text in bullet_items)

        body_inner = f'''
        <div class="presentation-lecture-slide">
            {f'<div class="lecture-lead-text">{lead_text}</div>' if lead_text else ''}
            {f'<ul class="lecture-items-list">{items_html}</ul>' if items_html else ''}
            {f'<div class="lecture-callout-card">{callout_text}</div>' if callout_text else ''}
        </div>
        '''

    return f'''
    <div class="presentation-slide-card slide-type-{slide_type.lower()}">
        {header_html}
        <div class="slide-content-area">
            {body_inner}
        </div>
        {footer_html}
    </div>
    '''


def classify_slide(shapes, idx, total_slides):
    """Accurately classifies the slide into one of the specialized presentation types."""
    joined = ' '.join(shp.text_frame.text.strip() for shp in shapes)
    joined_upper = joined.upper()

    if idx == 1:
        return 'COVER'
    elif 'COURSE CURRICULUM' in joined_upper:
        return 'CURRICULUM'
    elif idx == total_slides or 'COURSE COMPLETION' in joined_upper or 'CONGRATULATIONS ON COMPLETING' in joined_upper:
        return 'COMPLETION'
    elif 'CASE STUDY' in joined_upper:
        return 'CASE_STUDY'
    elif ('CONTROLLED DOCUMENTS' in joined_upper and 'COMPLETED RECORDS' in joined_upper) or \
         ('VERSUS' in joined_upper and 'DISTINCTIONS' in joined_upper):
        return 'COMPARISON'
    elif 'KNOWLEDGE CHECK' in joined_upper and 'CORRECT ANSWER' in joined_upper:
        return 'KNOWLEDGE_CHECK'
    elif 'FINAL ASSESSMENT' in joined_upper and 'CORRECT ANSWER' in joined_upper:
        return 'FINAL_ASSESSMENT'
    elif 'COMPREHENSIVE' in joined_upper and 'ASSESSMENT' in joined_upper and 'CORRECT ANSWER' not in joined_upper:
        return 'ASSESSMENT_INTRO'
    elif re.search(r'MODULE\s+\d+', joined_upper) and ('MODULE STRUCTURE' in joined_upper or ('LEARNING OBJECTIVES' in joined_upper and 'UPON SUCCESSFUL' not in joined_upper)):
        return 'MODULE_COVER'
    else:
        return 'LECTURE'


def import_dedicated_mcqs_for_course(course, mcq_filename):
    """
    Parses dedicated MCQ presentation file for the course, separating questions
    into Part A (40%) and Part B (60%) pools, ensuring no mention of Part A or Part B
    is stored in the question text or options.
    """
    mcq_filepath = os.path.join(BASE_DIR, mcq_filename)
    if not os.path.exists(mcq_filepath):
        print(f"Warning: Dedicated MCQ file not found: {mcq_filepath}")
        return 0, 0
        
    prs = Presentation(mcq_filepath)
    part = 'A'
    part_a_count = 0
    part_b_count = 0
    
    for idx, slide in enumerate(prs.slides, start=1):
        shapes = sorted(
            [shp for shp in slide.shapes if shp.has_text_frame and shp.text_frame.text.strip()],
            key=lambda x: (x.top, x.left)
        )
        joined = ' '.join(shp.text_frame.text.strip() for shp in shapes)
        
        # Check part transition header
        for shp in shapes:
            t = shp.text_frame.text.strip().upper()
            if t == 'PART A' or ('PART A' in t and 'MODULE UNDERSTANDING' in joined.upper() and 'QUESTION' not in t):
                part = 'A'
                break
            elif t == 'PART B' or ('PART B' in t and 'FINAL COMPREHENSIVE' in joined.upper() and 'QUESTION' not in t):
                part = 'B'
                break
                
        # If question slide
        if 'CORRECT ANSWER' in joined.upper():
            q_prompt, opts, corr_opt, explanation = extract_mcq_data_from_slide(shapes, joined)
            
            # Clean prompt and explanation - ensure NO mention of Part A or Part B
            clean_prompt = re.sub(r'\bPART\s+[AB]\b', '', q_prompt, flags=re.IGNORECASE).strip()
            clean_explanation = re.sub(r'\bPART\s+[AB]\b', '', explanation, flags=re.IGNORECASE).strip()
            clean_prompt = re.sub(r'^(FINAL\s+ASSESSMENT\s*\|\s*Question\s*\d+\s*)+', '', clean_prompt, flags=re.IGNORECASE).strip()
            
            mcq = MCQ(
                course_id=course.id,
                slide_id=None,
                type='final_test',
                part=part,
                question_text=clean_prompt or q_prompt,
                option_a=opts['A'] or 'Option A',
                option_b=opts['B'] or 'Option B',
                option_c=opts['C'] or 'Option C',
                option_d=opts['D'] or 'Option D',
                correct_option=corr_opt,
                explanation=clean_explanation or explanation,
                difficulty='medium',
                marks=1,
                is_active=True
            )
            db.session.add(mcq)
            if part == 'A':
                part_a_count += 1
            else:
                part_b_count += 1
                
    db.session.commit()
    print(f"     Dedicated Examination MCQs: {part_a_count} Part A, {part_b_count} Part B (Total {part_a_count + part_b_count})")
    return part_a_count, part_b_count


def import_pptx_presentations():
    """
    Parses all 3 official training PowerPoint files and seeds courses, slides,
    and MCQ banks with 100% faithful sequence and presentation formatting.
    """
    for c_info in COURSES_CONFIG:
        pptx_path = os.path.join(BASE_DIR, c_info['filename'])
        if not os.path.exists(pptx_path):
            print(f"File not found: {pptx_path}")
            continue

        prs = Presentation(pptx_path)
        total_slides = len(prs.slides)
        print(f"\n=======================================================")
        print(f"Importing {c_info['title']} ({total_slides} slides)...")
        print(f"=======================================================")

        # 1. Create or update course record
        course = Course.query.filter_by(slug=c_info['slug']).first()
        if not course:
            course = Course(
                slug=c_info['slug'],
                title=c_info['title'],
                short_description=c_info['short_description'],
                overview=c_info['overview'],
                estimated_duration=c_info['estimated_duration'],
                language=c_info['language'],
                price_inr=c_info['price_inr'],
                gst_rate=c_info['gst_rate'],
                price_usd=c_info['price_usd'],
                version=c_info['version'],
                is_active=True
            )
            db.session.add(course)
            db.session.flush()
        else:
            course.title = c_info['title']
            course.short_description = c_info['short_description']
            course.overview = c_info['overview']
            course.price_inr = c_info['price_inr']
            course.gst_rate = c_info['gst_rate']
            course.price_usd = c_info['price_usd']
            course.version = c_info['version']
            db.session.flush()

        # Clear existing slides and MCQs for clean synchronization with the official files
        MCQ.query.filter_by(course_id=course.id).delete()
        Slide.query.filter_by(course_id=course.id).delete()
        db.session.commit()

        mcq_count = 0
        practice_count = 0
        final_test_count = 0

        # Iterate EVERY slide in exact presentation sequence from 1 to total_slides
        for idx, slide in enumerate(prs.slides, start=1):
            shapes = sorted(
                [shp for shp in slide.shapes if shp.has_text_frame and shp.text_frame.text.strip()],
                key=lambda x: (x.top, x.left)
            )
            joined_text = ' '.join(shp.text_frame.text.strip() for shp in shapes)
            slide_type = classify_slide(shapes, idx, total_slides)

            # Extract breadcrumb & title
            breadcrumb = ""
            title = ""
            for shp in shapes:
                t = shp.text_frame.text.strip()
                if 'YTAL TECH E-LEARNING' in t and shp.top < 400000:
                    breadcrumb = t
                elif not title and shp.top < 1100000 and len(t) < 120 and 'YTAL' not in t and 'Platform' not in t:
                    title = t

            if not title:
                title = shapes[0].text_frame.text.strip() if shapes else f"Slide {idx}"

            # MCQ extraction if this slide is a Knowledge Check or Final Assessment MCQ
            is_mcq_slide = slide_type in ['KNOWLEDGE_CHECK', 'FINAL_ASSESSMENT']
            q_data = None
            if is_mcq_slide:
                q_prompt, opts, corr_opt, explanation = extract_mcq_data_from_slide(shapes, joined_text)
                q_data = {
                    'question': q_prompt,
                    'options': opts,
                    'correct': corr_opt,
                    'explanation': explanation
                }

            # Build high-fidelity HTML matching presentation formatting
            slide_html = build_slide_html(
                slide_type=slide_type,
                breadcrumb=breadcrumb,
                title=title,
                shapes=shapes,
                idx=idx,
                total_slides=total_slides,
                course_slug=course.slug,
                q_data=q_data
            )

            # Create Slide entity preserving EXACT sequence index
            # Rule: 3 seconds for standard lecture slides (for testing); 0 seconds (no timer) for MCQ slides
            dwell_seconds = 0 if is_mcq_slide else 3

            db_slide = Slide(
                course_id=course.id,
                slide_number=idx,
                title=title,
                content_html=slide_html,
                minimum_dwell_seconds=dwell_seconds,
                has_practice_mcq=is_mcq_slide,
                is_active=True
            )
            db.session.add(db_slide)
            db.session.flush()

            # Attach MCQ entity to this exact slide
            if is_mcq_slide and q_data:
                mcq_kind = 'practice' if slide_type == 'KNOWLEDGE_CHECK' else 'lecture_review'
                mcq = MCQ(
                    course_id=course.id,
                    slide_id=db_slide.id,
                    type=mcq_kind,
                    part=None,
                    question_text=q_data['question'],
                    option_a=q_data['options']['A'] or 'Option A',
                    option_b=q_data['options']['B'] or 'Option B',
                    option_c=q_data['options']['C'] or 'Option C',
                    option_d=q_data['options']['D'] or 'Option D',
                    correct_option=q_data['correct'],
                    explanation=q_data['explanation'],
                    difficulty='medium',
                    marks=1,
                    is_active=True
                )
                db.session.add(mcq)
                db.session.flush()

                # Substitute actual mcq.id into the slide HTML placeholder
                db_slide.content_html = db_slide.content_html.replace('__MCQ_ID_PLACEHOLDER__', str(mcq.id))

                mcq_count += 1
                if mcq_kind == 'practice':
                    practice_count += 1
                else:
                    final_test_count += 1

        db.session.commit()
        print(f"[OK] {course.title} lecture slides imported successfully:")
        print(f"     Total Slides: {total_slides} (Slide numbers 1 to {total_slides})")
        print(f"     Total Practice MCQs: {practice_count}")

        # Now import the dedicated examination MCQ banks for Part A (40%) and Part B (60%)
        if c_info.get('mcq_filename'):
            import_dedicated_mcqs_for_course(course, c_info['mcq_filename'])

        # Adjust any existing learner enrolments so highest_slide_completed does not exceed the new total_slides
        enrolments = Enrolment.query.filter_by(course_id=course.id).all()
        for enr in enrolments:
            if enr.highest_slide_completed > total_slides:
                enr.highest_slide_completed = total_slides
            if enr.current_slide_number > total_slides:
                enr.current_slide_number = total_slides
        db.session.commit()

    print("\nAll 3 training presentations synchronized and seeded successfully!")
