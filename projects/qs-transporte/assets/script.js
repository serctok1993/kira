/* ========================================
   QS Transporte — script.js
   Hamburger-Menü + Form-Validation
   ======================================== */

(function () {
  'use strict';

  /* ---- Hamburger-Menü ---- */
  const hamburger = document.querySelector('.hamburger');
  const mainNav = document.querySelector('.main-nav');
  const body = document.body;

  // Overlay erstellen
  const overlay = document.createElement('div');
  overlay.className = 'nav-overlay';
  body.appendChild(overlay);

  function toggleMenu() {
    hamburger.classList.toggle('active');
    mainNav.classList.toggle('open');
    overlay.classList.toggle('active');

    const isOpen = mainNav.classList.contains('open');
    hamburger.setAttribute('aria-expanded', isOpen);
    body.style.overflow = isOpen ? 'hidden' : '';
  }

  function closeMenu() {
    hamburger.classList.remove('active');
    mainNav.classList.remove('open');
    overlay.classList.remove('active');
    hamburger.setAttribute('aria-expanded', 'false');
    body.style.overflow = '';
  }

  if (hamburger && mainNav) {
    hamburger.addEventListener('click', toggleMenu);
    overlay.addEventListener('click', closeMenu);

    // Menü schließen bei Klick auf Link
    mainNav.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', closeMenu);
    });

    // ESC schließt Menü
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && mainNav.classList.contains('open')) {
        closeMenu();
      }
    });

    // Bei Resize auf Desktop → Menü zurücksetzen
    window.addEventListener('resize', function () {
      if (window.innerWidth >= 900) {
        closeMenu();
      }
    });
  }

  /* ---- Form-Validation ---- */
  const form = document.querySelector('.contact-form');

  if (form) {
    const fields = form.querySelectorAll('input[required], textarea[required], select[required]');

    // E-Mail-Regex
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    // Telefon-Regex (erlaubt +, Leerzeichen, Klammern, Zahlen, Bindestrich)
    const phoneRegex = /^[+]?[\d\s/()\-]{6,}$/;

    function showError(field, message) {
      field.classList.add('error');
      const errorEl = field.parentElement.querySelector('.form-error');
      if (errorEl) {
        errorEl.textContent = message;
        errorEl.classList.add('show');
      }
    }

    function clearError(field) {
      field.classList.remove('error');
      const errorEl = field.parentElement.querySelector('.form-error');
      if (errorEl) {
        errorEl.classList.remove('show');
      }
    }

    function validateField(field) {
      const value = field.value.trim();
      const type = field.type;
      const name = field.name;

      // Pflichtfeld-Check
      if (field.hasAttribute('required') && value === '') {
        showError(field, 'Dieses Feld ist erforderlich.');
        return false;
      }

      // E-Mail-Check
      if (type === 'email' && value !== '') {
        if (!emailRegex.test(value)) {
          showError(field, 'Bitte geben Sie eine gültige E-Mail-Adresse ein.');
          return false;
        }
      }

      // Telefon-Check (falls ausgefüllt)
      if (name === 'telefon' && value !== '') {
        if (!phoneRegex.test(value)) {
          showError(field, 'Bitte geben Sie eine gültige Telefonnummer ein.');
          return false;
        }
      }

      // Datenschutz-Checkbox
      if (field.type === 'checkbox' && field.hasAttribute('required') && !field.checked) {
        showError(field, 'Bitte stimmen Sie der Datenschutzerklärung zu.');
        return false;
      }

      clearError(field);
      return true;
    }

    // Live-Validation beim Verlassen des Feldes
    fields.forEach(function (field) {
      field.addEventListener('blur', function () {
        validateField(field);
      });

      // Fehler sofort entfernen beim Tippen
      field.addEventListener('input', function () {
        if (field.classList.contains('error')) {
          clearError(field);
        }
      });

      if (field.type === 'checkbox') {
        field.addEventListener('change', function () {
          validateField(field);
        });
      }
    });

    // Submit-Handler
    form.addEventListener('submit', function (e) {
      e.preventDefault();

      let allValid = true;

      fields.forEach(function (field) {
        if (!validateField(field)) {
          allValid = false;
        }
      });

      if (allValid) {
        // Erfolgsmeldung anzeigen
        const successEl = form.querySelector('.form-success');
        if (successEl) {
          successEl.classList.add('show');
        }

        // Formular zurücksetzen
        form.reset();

        // Zur Erfolgsmeldung scrollen
        if (successEl) {
          successEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        // Nach 5 Sekunden Erfolgsmeldung ausblenden
        setTimeout(function () {
          if (successEl) {
            successEl.classList.remove('show');
          }
        }, 5000);
      } else {
        // Zum ersten Fehler-Feld scrollen
        const firstError = form.querySelector('.error');
        if (firstError) {
          firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
          firstError.focus();
        }
      }
    });
  }

  /* ---- Smooth Scroll für Anker-Links ---- */
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#' || targetId === '') return;

      const target = document.querySelector(targetId);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

})();
