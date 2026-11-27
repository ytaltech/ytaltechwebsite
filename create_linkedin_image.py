import os
import math
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_linkedin_banner():
    W, H = 1200, 1200
    img = Image.new('RGBA', (W, H), (10, 25, 47, 255))
    draw = ImageDraw.Draw(img)

    # 1. Base Gradient Background (Deep Navy to Rich Midnight Blue)
    for y in range(H):
        ratio = y / H
        r = int(6 + ratio * 10)
        g = int(18 + ratio * 24)
        b = int(38 + ratio * 45)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # 2. Modern Subtle Grid Overlay / Hexagonal scientific nodes
    grid_spacing = 60
    for x in range(0, W, grid_spacing):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
    for y in range(0, H, grid_spacing):
        draw.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)

    # Ambient light glow top-right and bottom-left
    glow_overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_overlay)
    
    # Cyan ambient glow top right
    glow_draw.ellipse([850, -100, 1350, 400], fill=(0, 174, 239, 35))
    # Teal ambient glow bottom left
    glow_draw.ellipse([-150, 800, 450, 1400], fill=(13, 148, 136, 35))
    glow_overlay = glow_overlay.filter(ImageFilter.GaussianBlur(80))
    img = Image.alpha_composite(img, glow_overlay)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_path_bold = r'C:\Windows\Fonts\segoeuib.ttf'
    font_path_reg = r'C:\Windows\Fonts\segoeui.ttf'
    font_path_semi = r'C:\Windows\Fonts\segoeuib.ttf'

    font_brand = ImageFont.truetype(font_path_bold, 24)
    font_brand_sub = ImageFont.truetype(font_path_reg, 15)
    font_badge = ImageFont.truetype(font_path_bold, 16)
    font_h1 = ImageFont.truetype(font_path_bold, 44)
    font_h2 = ImageFont.truetype(font_path_bold, 28)
    font_body_bold = ImageFont.truetype(font_path_bold, 20)
    font_body = ImageFont.truetype(font_path_reg, 17)
    font_body_sm = ImageFont.truetype(font_path_reg, 15)
    font_cta = ImageFont.truetype(font_path_bold, 22)
    font_tag = ImageFont.truetype(font_path_bold, 14)

    # -------------------------------------------------------------
    # TOP HEADER: Brand Pill & Logo Bar
    # -------------------------------------------------------------
    # Brand Bar Top
    draw.rounded_rectangle([60, 45, 1140, 115], radius=16, fill=(15, 34, 64, 200), outline=(0, 174, 239, 100), width=1)
    
    # Brand Icon (Cross / Tech nodes)
    draw.rounded_rectangle([80, 57, 135, 103], radius=10, fill=(0, 174, 239, 255))
    draw.text((95, 63), "YT", font=ImageFont.truetype(font_path_bold, 26), fill=(255, 255, 255, 255))
    
    draw.text((150, 58), "YTAL TECH SOLUTIONS & SERVICES LLP", font=font_brand, fill=(255, 255, 255, 255))
    draw.text((150, 88), "Next-Generation Clinical Research E-Learning & Quality Assurance", font=font_brand_sub, fill=(148, 163, 184, 255))

    # ISO / ICH Q10 Top-Right Badges
    draw.rounded_rectangle([880, 60, 1120, 100], radius=8, fill=(13, 148, 136, 40), outline=(20, 184, 166, 180), width=1)
    draw.text((895, 70), "★  ICH Q10 & ISO COMPLIANT", font=font_tag, fill=(45, 212, 191, 255))

    # -------------------------------------------------------------
    # HERO SECTION: Question Hook & Sub-headline
    # -------------------------------------------------------------
    # Category Pill
    draw.rounded_rectangle([60, 145, 410, 180], radius=8, fill=(2, 132, 199, 40), outline=(56, 189, 248, 140), width=1)
    draw.text((75, 153), "CLINICAL RESEARCH PROFESSIONAL STANDARDS", font=font_tag, fill=(56, 189, 248, 255))

    # Main Headline
    draw.text((60, 200), "Are Your Training Certificates", font=font_h1, fill=(255, 255, 255, 255))
    draw.text((60, 255), "Truly Verifiable & Tamper-Proof?", font=font_h1, fill=(0, 174, 239, 255))

    # -------------------------------------------------------------
    # 2-COLUMN COMPARISON CARDS: Traditional vs Ytal Tech Standard
    # -------------------------------------------------------------
    card_top = 330
    card_h = 470
    card_w = 515

    # LEFT CARD: The Industry Gap (Traditional Certificates)
    draw.rounded_rectangle([60, card_top, 60 + card_w, card_top + card_h], radius=18, fill=(23, 37, 60, 180), outline=(239, 68, 68, 80), width=2)
    # Header strip inside left card
    draw.rounded_rectangle([60, card_top, 60 + card_w, card_top + 65], radius=18, fill=(153, 27, 27, 40))
    draw.text((85, card_top + 18), "⚠️  Traditional Training Certificates", font=font_body_bold, fill=(252, 165, 165, 255))
    draw.line([(60, card_top + 65), (60 + card_w, card_top + 65)], fill=(239, 68, 68, 60), width=1)

    points_left = [
        ("No Tamper-Proof Evidence", "Most paper or standard PDF certificates lack cryptographic validation and can easily be altered, spoofed, or falsified."),
        ("No Live QR Verification", "Inspectors and auditors cannot scan or verify authenticity against a live, central tamper-evident registry."),
        ("Passive Attendance Only", "Often awarded merely for clicking through slides without testing knowledge retention or genuine competency.")
    ]
    py = card_top + 85
    for title, desc in points_left:
        # Cross badge icon
        draw.ellipse([85, py + 2, 110, py + 27], fill=(239, 68, 68, 40), outline=(239, 68, 68, 200))
        draw.text((93, py + 5), "✕", font=font_tag, fill=(248, 113, 113, 255))
        
        draw.text((125, py + 2), title, font=font_body_bold, fill=(241, 245, 249, 255))
        # Word wrap desc
        words = desc.split()
        line1 = " ".join(words[:7])
        line2 = " ".join(words[7:14])
        line3 = " ".join(words[14:])
        draw.text((125, py + 30), line1, font=font_body_sm, fill=(148, 163, 184, 255))
        if line2:
            draw.text((125, py + 52), line2, font=font_body_sm, fill=(148, 163, 184, 255))
        if line3:
            draw.text((125, py + 74), line3, font=font_body_sm, fill=(148, 163, 184, 255))
        py += 120

    # RIGHT CARD: The Ytal Tech Solution (Tamper-Proof + ISO & ICH Q10)
    rx = 625
    draw.rounded_rectangle([rx, card_top, rx + card_w, card_top + card_h], radius=18, fill=(15, 38, 70, 220), outline=(0, 174, 239, 180), width=2)
    # Header strip inside right card
    draw.rounded_rectangle([rx, card_top, rx + card_w, card_top + 65], radius=18, fill=(0, 174, 239, 35))
    draw.text((rx + 25, card_top + 18), "🛡️  Ytal Tech Solutions Standard", font=font_body_bold, fill=(56, 189, 248, 255))
    draw.line([(rx, card_top + 65), (rx + card_w, card_top + 65)], fill=(0, 174, 239, 100), width=1)

    points_right = [
        ("Instant QR Code Verification", "Every certificate features a unique QR code linked directly to our live, public tamper-evident registry at www.ytaltech.com."),
        ("Cryptographic SHA-256 Hash", "A secure digital signature hash is mathematically computed from learner ID, course metadata, and date of issuance."),
        ("Mandated Competency Exam", "Rigorous 20-question randomized examination with strict 80% passing threshold, fulfilling ISO and ICH Q10 quality mandates.")
    ]
    py = card_top + 85
    for title, desc in points_right:
        # Checkmark badge icon
        draw.ellipse([rx + 25, py + 2, rx + 50, py + 27], fill=(16, 185, 129, 40), outline=(16, 185, 129, 200))
        draw.text((rx + 32, py + 5), "✓", font=font_tag, fill=(52, 211, 153, 255))
        
        draw.text((rx + 65, py + 2), title, font=font_body_bold, fill=(255, 255, 255, 255))
        words = desc.split()
        line1 = " ".join(words[:7])
        line2 = " ".join(words[7:14])
        line3 = " ".join(words[14:])
        draw.text((rx + 65, py + 30), line1, font=font_body_sm, fill=(203, 213, 225, 255))
        if line2:
            draw.text((rx + 65, py + 52), line2, font=font_body_sm, fill=(203, 213, 225, 255))
        if line3:
            draw.text((rx + 65, py + 74), line3, font=font_body_sm, fill=(203, 213, 225, 255))
        py += 120

    # -------------------------------------------------------------
    # LOWER BANNER: LIVE QR CODE DEMO & COMPLIANCE BADGES
    # -------------------------------------------------------------
    bot_y = 830
    bot_h = 240
    draw.rounded_rectangle([60, bot_y, 1140, bot_y + bot_h], radius=18, fill=(12, 30, 56, 230), outline=(30, 58, 102, 200), width=1)

    # Generate actual QR Code pointing to live verification portal
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=4,
        border=2,
    )
    qr.add_data("https://www.ytaltech.com/verify-certificate")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#0A192F", back_color="#FFFFFF").convert("RGBA")
    qr_img = qr_img.resize((170, 170), Image.Resampling.LANCZOS)
    
    # White card backdrop for QR code
    draw.rounded_rectangle([85, bot_y + 35, 275, bot_y + 205], radius=12, fill=(255, 255, 255, 255), outline=(0, 174, 239, 200), width=2)
    img.paste(qr_img, (95, bot_y + 45), qr_img)
    
    # QR Label below
    draw.text((105, bot_y + 15), "📱 SCAN TO VERIFY", font=font_tag, fill=(0, 174, 239, 255))

    # Center text explaining ISO & ICH Q10 mandate
    tx = 300
    draw.text((tx, bot_y + 30), "Why ISO & ICH Q10 Guidelines Demand Rigorous Testing", font=font_h2, fill=(255, 255, 255, 255))
    
    p1 = "• ISO 9001 (Clause 7.2) & ICH Q10 Pharmaceutical Quality System mandates"
    p2 = "  that personnel competency must be evaluated through documented, objective testing."
    p3 = "• Ytal Tech enforces a 20-question randomized assessment (80% passing threshold)"
    p4 = "  ensuring authentic, verified learning retention for clinical trial professionals."
    
    draw.text((tx, bot_y + 75), p1, font=font_body, fill=(226, 232, 240, 255))
    draw.text((tx, bot_y + 102), p2, font=font_body, fill=(148, 163, 184, 255))
    draw.text((tx, bot_y + 135), p3, font=font_body, fill=(226, 232, 240, 255))
    draw.text((tx, bot_y + 162), p4, font=font_body, fill=(148, 163, 184, 255))

    # Key Courses pills on the bottom right
    courses_bar_y = bot_y + 195
    tags = ["Good Documentation Practices (GDP)", "Good Clinical Practice (ICH GCP)", "NDCT Rules 2019"]
    tag_x = tx
    for t in tags:
        tw = int(draw.textlength(t, font=font_tag))
        draw.rounded_rectangle([tag_x, courses_bar_y, tag_x + tw + 18, courses_bar_y + 26], radius=6, fill=(30, 58, 102, 180), outline=(0, 174, 239, 120), width=1)
        draw.text((tag_x + 9, courses_bar_y + 5), t, font=font_tag, fill=(56, 189, 248, 255))
        tag_x += tw + 28

    # -------------------------------------------------------------
    # FOOTER BAR: Website & Call to Action
    # -------------------------------------------------------------
    foot_y = 1095
    draw.rounded_rectangle([60, foot_y, 1140, foot_y + 65], radius=14, fill=(0, 174, 239, 255))
    
    cta_text = "Advance your clinical career with tamper-proof certification: www.ytaltech.com"
    draw.text((95, foot_y + 18), "🎓  E-Learning Portal Live:", font=font_cta, fill=(10, 25, 47, 255))
    draw.text((375, foot_y + 18), "www.ytaltech.com", font=font_cta, fill=(255, 255, 255, 255))
    draw.text((615, foot_y + 20), "|  Instant QR Verification  |  ISO & ICH Q10 Compliant", font=font_body, fill=(10, 25, 47, 255))

    # Save outputs
    output_png = 'linkedin_post_ytaltech_square.png'
    img.save(output_png, format='PNG', dpi=(300, 300), quality=100)
    print(f"Successfully generated {output_png} ({W}x{H} px)")
    return output_png

if __name__ == '__main__':
    create_linkedin_banner()

def create_linkedin_landscape():
    W, H = 1200, 627
    img = Image.new('RGBA', (W, H), (10, 25, 47, 255))
    draw = ImageDraw.Draw(img)

    for y in range(H):
        ratio = y / H
        r = int(6 + ratio * 10)
        g = int(18 + ratio * 24)
        b = int(38 + ratio * 45)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    grid_spacing = 50
    for x in range(0, W, grid_spacing):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 7), width=1)
    for y in range(0, H, grid_spacing):
        draw.line([(0, y), (W, y)], fill=(255, 255, 255, 7), width=1)

    glow_overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_overlay)
    glow_draw.ellipse([850, -100, 1350, 400], fill=(0, 174, 239, 30))
    glow_draw.ellipse([-150, 400, 450, 800], fill=(13, 148, 136, 30))
    glow_overlay = glow_overlay.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img, glow_overlay)
    draw = ImageDraw.Draw(img)

    font_path_bold = r'C:\Windows\Fonts\segoeuib.ttf'
    font_path_reg = r'C:\Windows\Fonts\segoeui.ttf'

    font_brand = ImageFont.truetype(font_path_bold, 20)
    font_h1 = ImageFont.truetype(font_path_bold, 34)
    font_body_bold = ImageFont.truetype(font_path_bold, 18)
    font_body_sm = ImageFont.truetype(font_path_reg, 14)
    font_tag = ImageFont.truetype(font_path_bold, 12)
    font_cta = ImageFont.truetype(font_path_bold, 18)

    # Top Brand Bar
    draw.rounded_rectangle([40, 25, 1160, 75], radius=12, fill=(15, 34, 64, 200), outline=(0, 174, 239, 100), width=1)
    draw.rounded_rectangle([55, 33, 95, 67], radius=6, fill=(0, 174, 239, 255))
    draw.text((62, 38), "YT", font=ImageFont.truetype(font_path_bold, 18), fill=(255, 255, 255, 255))
    draw.text((110, 38), "YTAL TECH SOLUTIONS & SERVICES LLP  •  Clinical Research E-Learning", font=font_brand, fill=(255, 255, 255, 255))
    draw.rounded_rectangle([920, 33, 1145, 67], radius=6, fill=(13, 148, 136, 40), outline=(20, 184, 166, 180), width=1)
    draw.text((935, 42), "★ ISO & ICH Q10 COMPLIANT", font=font_tag, fill=(45, 212, 191, 255))

    # Hero Headline
    draw.text((40, 95), "Are Your Training Certificates Truly Verifiable?", font=font_h1, fill=(255, 255, 255, 255))
    draw.text((40, 138), "Tamper-Proof QR Registry  |  Mandatory Competency Testing", font=ImageFont.truetype(font_path_bold, 20), fill=(0, 174, 239, 255))

    # Two Main Cards
    cw = 545
    ch = 345
    cy = 185

    # Left Card
    draw.rounded_rectangle([40, cy, 40 + cw, cy + ch], radius=14, fill=(23, 37, 60, 180), outline=(239, 68, 68, 80), width=1)
    draw.rounded_rectangle([40, cy, 40 + cw, cy + 45], radius=14, fill=(153, 27, 27, 40))
    draw.text((60, cy + 12), "⚠️  The Problem with Traditional Certificates", font=font_body_bold, fill=(252, 165, 165, 255))
    
    pts_left = [
        ("No Tamper-Proof Evidence", "Easily altered or falsified; lacks cryptographic proof of authenticity."),
        ("No Live QR Verification", "Auditors cannot scan or verify credentials in real-time registry."),
        ("No Competency Assessment", "Often awarded for passive attendance without rigorous examination.")
    ]
    py = cy + 60
    for t, d in pts_left:
        draw.text((60, py), f"✕  {t}", font=font_body_bold, fill=(248, 113, 113, 255))
        draw.text((80, py + 24), d, font=font_body_sm, fill=(148, 163, 184, 255))
        py += 80

    # Right Card
    rx = 615
    draw.rounded_rectangle([rx, cy, rx + cw, cy + ch], radius=14, fill=(15, 38, 70, 220), outline=(0, 174, 239, 180), width=1)
    draw.rounded_rectangle([rx, cy, rx + cw, cy + 45], radius=14, fill=(0, 174, 239, 35))
    draw.text((rx + 20, cy + 12), "🛡️  The Ytal Tech GxP Standard", font=font_body_bold, fill=(56, 189, 248, 255))

    # QR Code on Right card
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data("https://www.ytaltech.com/verify-certificate")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#0A192F", back_color="#FFFFFF").convert("RGBA")
    qr_img = qr_img.resize((100, 100), Image.Resampling.LANCZOS)
    draw.rounded_rectangle([rx + cw - 125, cy + 60, rx + cw - 15, cy + 170], radius=8, fill=(255, 255, 255, 255), outline=(0, 174, 239, 200))
    img.paste(qr_img, (rx + cw - 120, cy + 65), qr_img)
    draw.text((rx + cw - 120, cy + 175), "SCAN TO VERIFY", font=ImageFont.truetype(font_path_bold, 11), fill=(0, 174, 239, 255))

    pts_right = [
        ("Instant QR Code Verification", "Every certificate links to live registry records."),
        ("Cryptographic SHA-256 Hash", "Tamper-proof digital seal prevents modification."),
        ("ISO & ICH Q10 Assessment", "Mandatory 20-question exam with 80% pass threshold.")
    ]
    py = cy + 60
    for t, d in pts_right:
        draw.text((rx + 20, py), f"✓  {t}", font=font_body_bold, fill=(52, 211, 153, 255))
        draw.text((rx + 40, py + 24), d, font=font_body_sm, fill=(203, 213, 225, 255))
        py += 80

    # Bottom Bar
    draw.rounded_rectangle([40, 550, 1160, 600], radius=10, fill=(0, 174, 239, 255))
    draw.text((60, 563), "🎓 Explore Courses (GDP • ICH GCP • NDCT 2019): www.ytaltech.com", font=font_cta, fill=(10, 25, 47, 255))

    out_path = 'linkedin_post_ytaltech_landscape.png'
    img.save(out_path, format='PNG', dpi=(300, 300), quality=100)
    print(f"Successfully generated {out_path} ({W}x{H} px)")
    return out_path
