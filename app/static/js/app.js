const root = document.documentElement;
const themeToggle = document.getElementById('themeToggle');
const savedTheme = localStorage.getItem('theme') || 'dark';
root.setAttribute('data-bs-theme', savedTheme);

function updateThemeIcon() {
  if (!themeToggle) return;
  const icon = themeToggle.querySelector('i');
  if (icon) icon.className = root.getAttribute('data-bs-theme') === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
}
updateThemeIcon();

themeToggle?.addEventListener('click', () => {
  const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-bs-theme', next);
  localStorage.setItem('theme', next);
  updateThemeIcon();
});

const sidebar = document.getElementById('sidebar');
const backdrop = document.getElementById('sidebarBackdrop');
function openSidebar(){ sidebar?.classList.add('open'); backdrop?.classList.add('show'); }
function closeSidebar(){ sidebar?.classList.remove('open'); backdrop?.classList.remove('show'); }
document.getElementById('sidebarOpen')?.addEventListener('click', openSidebar);
document.getElementById('sidebarClose')?.addEventListener('click', closeSidebar);
backdrop?.addEventListener('click', closeSidebar);
