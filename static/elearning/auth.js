/**
 * Ytal Tech Registration & Password Strength Validator
 */
document.addEventListener('DOMContentLoaded', function () {
    const passwordInput = document.getElementById('regPassword');
    const confirmInput = document.getElementById('regConfirmPassword');
    const meterFill = document.getElementById('passwordMeterFill');
    const strengthLabel = document.getElementById('passwordStrengthLabel');
    const matchLabel = document.getElementById('passwordMatchLabel');
    
    if (passwordInput && meterFill && strengthLabel) {
        passwordInput.addEventListener('input', function () {
            const val = passwordInput.value;
            let score = 0;
            if (val.length >= 8) score += 1;
            if (val.length >= 12) score += 1;
            if (/[A-Z]/.test(val) && /[a-z]/.test(val)) score += 1;
            if (/[0-9]/.test(val)) score += 1;
            if (/[!@#$%^&*(),.?":{}|<>_\-+=~/]/.test(val)) score += 1;
            
            const widths = ['0%', '20%', '40%', '60%', '80%', '100%'];
            const colors = ['#e2e8f0', '#ef4444', '#f97316', '#eab308', '#3b82f6', '#10b981'];
            const labels = ['None', 'Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong'];
            
            meterFill.style.width = widths[score];
            meterFill.style.backgroundColor = colors[score];
            strengthLabel.textContent = `Strength: ${labels[score]}`;
            strengthLabel.style.color = colors[score];
            
            checkPasswordMatch();
        });
    }
    
    function checkPasswordMatch() {
        if (!confirmInput || !passwordInput || !matchLabel) return;
        const p1 = passwordInput.value;
        const p2 = confirmInput.value;
        if (!p2) {
            matchLabel.textContent = '';
            return;
        }
        if (p1 === p2) {
            matchLabel.textContent = '✓ Passwords match';
            matchLabel.style.color = '#10b981';
        } else {
            matchLabel.textContent = '✗ Passwords do not match';
            matchLabel.style.color = '#ef4444';
        }
    }
    
    if (confirmInput) {
        confirmInput.addEventListener('input', checkPasswordMatch);
    }
});
