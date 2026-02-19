document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('wizard-form');
    const steps = Array.from(document.querySelectorAll('.step[data-step]'));
    const nextBtn = document.getElementById('next-btn');
    const prevBtn = document.getElementById('prev-btn');
    const submitBtn = document.getElementById('submit-btn');
    const progressFill = document.getElementById('progress-fill');
    const overlay = document.getElementById('loading-overlay');
    const successStep = document.getElementById('success-step');
    const navigation = document.getElementById('wizard-navigation');

    let currentStep = 1;
    const totalSteps = 3; // Logical steps: 1, 2, 3 (Optional 4 is injected)
    let nameExists = false;

    // Real-time name check
    const nameInput = document.getElementById('project-name-input');
    const nameError = document.getElementById('name-error');
    let nameTimeout;

    if (nameInput) {
        nameInput.addEventListener('input', () => {
            clearTimeout(nameTimeout);
            const name = nameInput.value.trim();

            if (!name) {
                nameInput.classList.remove('invalid');
                nameError.style.display = 'none';
                nameExists = false;
                return;
            }

            nameTimeout = setTimeout(async () => {
                try {
                    const response = await fetch(`/init/check-name/?name=${encodeURIComponent(name)}`);
                    const data = await response.json();

                    if (data.exists) {
                        nameInput.classList.add('invalid');
                        nameError.style.display = 'block';
                        nameExists = true;
                    } else {
                        nameInput.classList.remove('invalid');
                        nameError.style.display = 'none';
                        nameExists = false;
                    }
                } catch (err) {
                    console.error('Error checking name:', err);
                }
            }, 300);
        });
    }

    // Handle Metadata Import UI toggle
    const importRadios = document.querySelectorAll('input[name="import_metadata"]');
    const sourceDetails = document.getElementById('source-details');
    importRadios.forEach(radio => {
        radio.addEventListener('change', () => {
            sourceDetails.style.display = radio.value === 'true' ? 'block' : 'none';
        });
    });

    const sourceTypeSelect = document.getElementById('source-type-select');
    const fileLabel = document.getElementById('file-label');
    const fileInput = document.getElementById('source-file-input');

    if (sourceTypeSelect) {
        sourceTypeSelect.addEventListener('change', () => {
            if (sourceTypeSelect.value === 'excel') {
                fileLabel.textContent = 'Excel File (.xlsx)';
                fileInput.accept = '.xlsx';
            } else {
                fileLabel.textContent = 'SQLite Database (.db)';
                fileInput.accept = '.db';
            }
        });
    }

    function updateProgress() {
        if (progressFill) {
            const percentage = ((currentStep - 1) / totalSteps) * 100;
            progressFill.style.width = `${percentage}%`;
        }
    }

    function showStep(stepNum) {
        steps.forEach(s => s.classList.remove('active'));
        const stepToShow = document.querySelector(`.step[data-step="${stepNum}"]`);
        if (stepToShow) stepToShow.classList.add('active');

        if (prevBtn) prevBtn.disabled = stepNum === 1;

        const modifyDefaultsEl = document.querySelector('input[name="modify_defaults"]:checked');
        const modifyDefaults = modifyDefaultsEl ? modifyDefaultsEl.value === 'true' : false;

        if (stepNum === 3) {
            if (modifyDefaults) {
                if (nextBtn) nextBtn.style.display = 'inline-flex';
                if (submitBtn) submitBtn.style.display = 'none';
            } else {
                if (nextBtn) nextBtn.style.display = 'none';
                if (submitBtn) submitBtn.style.display = 'inline-flex';
            }
        } else if (stepNum === 4) {
            if (nextBtn) nextBtn.style.display = 'none';
            if (submitBtn) submitBtn.style.display = 'inline-flex';
        } else {
            if (nextBtn) nextBtn.style.display = 'inline-flex';
            if (submitBtn) submitBtn.style.display = 'none';
        }

        updateProgress();
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            // Validation for Step 1
            if (currentStep === 1) {
                const name = nameInput.value.trim();
                if (!name) {
                    alert('Project name is required');
                    return;
                }
                if (nameExists) {
                    alert('Please choose a different project name.');
                    return;
                }
            }

            // Step logic
            if (currentStep === 3) {
                const modifyDefaultsEl = document.querySelector('input[name="modify_defaults"]:checked');
                const modifyDefaults = modifyDefaultsEl ? modifyDefaultsEl.value === 'true' : false;
                if (modifyDefaults) {
                    currentStep = 4;
                } else {
                    return;
                }
            } else {
                currentStep++;
            }
            showStep(currentStep);
        });
    }

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentStep === 4) {
                currentStep = 3;
            } else {
                currentStep--;
            }
            showStep(currentStep);
        });
    }

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (overlay) overlay.style.display = 'flex';

            const formData = new FormData(form);

            try {
                const response = await fetch('/init/create/', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.status === 'success') {
                    // Show success
                    steps.forEach(s => s.classList.remove('active'));
                    if (successStep) successStep.classList.add('active');
                    if (navigation) navigation.style.display = 'none';
                    if (progressFill) progressFill.style.width = '100%';
                    const successMsgEl = document.getElementById('success-message');
                    if (successMsgEl) successMsgEl.textContent = result.message;
                } else {
                    alert('Error: ' + result.message);
                }
            } catch (err) {
                alert('An unexpected error occurred: ' + err.message);
            } finally {
                if (overlay) overlay.style.display = 'none';
            }
        });
    }

    updateProgress();
});
