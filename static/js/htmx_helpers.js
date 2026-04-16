/* AI Company — HTMX helpers & Mermaid init */

// Initialize Mermaid diagrams whenever new content is loaded
document.addEventListener('htmx:afterSwap', function (evt) {
  if (typeof mermaid !== 'undefined') {
    mermaid.init(undefined, evt.detail.target.querySelectorAll('.mermaid'));
  }
});

document.addEventListener('DOMContentLoaded', function () {
  // Init Mermaid on page load
  if (typeof mermaid !== 'undefined') {
    mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
  }

  // Auto-resize textarea
  document.querySelectorAll('textarea[data-autoresize]').forEach(function (ta) {
    ta.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = this.scrollHeight + 'px';
    });
  });
});

// Show thinking indicator while HTMX request is in-flight
document.addEventListener('htmx:beforeRequest', function (evt) {
  var indicator = document.querySelector('.thinking-indicator');
  if (indicator) indicator.classList.add('visible');
});
document.addEventListener('htmx:afterRequest', function (evt) {
  var indicator = document.querySelector('.thinking-indicator');
  if (indicator) indicator.classList.remove('visible');
});
