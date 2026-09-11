// Event Media Hub — small progressive enhancements.
// Everything here is optional: every form and link also works without JavaScript.
// There are no inline scripts, so the Content-Security-Policy can stay strict.
document.addEventListener('DOMContentLoaded', function () {
    // Ask before destructive actions (forms marked with data-confirm).
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    // Upload box: show chosen files, accept drag and drop, and prevent double submits.
    var input = document.getElementById('media-input');
    var dropZone = document.querySelector('[data-drop-zone]');
    var uploadForm = document.querySelector('[data-upload-form]');

    function showSelection() {
        var label = dropZone && dropZone.querySelector('.drop-text');
        if (!label) return;
        var count = input.files.length;
        if (count === 0) label.textContent = 'Choose photos or videos';
        else if (count === 1) label.textContent = input.files[0].name;
        else label.textContent = count + ' files selected';
    }

    if (input && dropZone) {
        input.addEventListener('change', showSelection);
        ['dragenter', 'dragover'].forEach(function (name) {
            dropZone.addEventListener(name, function (event) {
                event.preventDefault();
                dropZone.classList.add('is-dragover');
            });
        });
        ['dragleave', 'drop'].forEach(function (name) {
            dropZone.addEventListener(name, function () {
                dropZone.classList.remove('is-dragover');
            });
        });
        dropZone.addEventListener('drop', function (event) {
            event.preventDefault();
            if (event.dataTransfer && event.dataTransfer.files.length) {
                input.files = event.dataTransfer.files;
                showSelection();
            }
        });
    }

    if (uploadForm) {
        uploadForm.addEventListener('submit', function () {
            var button = uploadForm.querySelector('button[type="submit"]');
            if (button) {
                button.disabled = true;
                button.textContent = 'Uploading…';
            }
        });
    }

    // Copy the invite link to the clipboard.
    document.querySelectorAll('[data-copy-target]').forEach(function (button) {
        button.addEventListener('click', function () {
            var field = document.getElementById(button.dataset.copyTarget);
            if (!field) return;
            field.select();
            if (!navigator.clipboard || !window.isSecureContext) return; // text stays selected for manual copy
            navigator.clipboard.writeText(field.value).then(function () {
                var original = button.textContent;
                button.textContent = 'Copied!';
                setTimeout(function () { button.textContent = original; }, 2000);
            }).catch(function () { /* text stays selected for manual copy */ });
        });
    });

    // Event codes are upper case; show them that way as people type.
    var codeInput = document.getElementById('code');
    if (codeInput) {
        codeInput.addEventListener('input', function () {
            codeInput.value = codeInput.value.toUpperCase();
        });
    }
});
