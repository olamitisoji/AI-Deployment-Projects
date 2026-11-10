const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#main-nav');
function closeMenu() {
  menuButton?.setAttribute('aria-expanded', 'false');
  navigation?.classList.remove('is-open');
}
if (menuButton && navigation) {
  menuButton.addEventListener('click', () => {
    const expanded = menuButton.getAttribute('aria-expanded') === 'true';
    menuButton.setAttribute('aria-expanded', String(!expanded));
    navigation.classList.toggle('is-open', !expanded);
  });
  navigation.addEventListener('click', event => {
    if (event.target.closest('a')) closeMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menuButton.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      menuButton.focus();
    }
  });
  window.matchMedia('(min-width: 761px)').addEventListener('change', event => {
    if (event.matches) closeMenu();
  });
}

const filterButtons = document.querySelectorAll('[data-filter]');
const projects = document.querySelectorAll('[data-category]');
filterButtons.forEach(button => button.addEventListener('click', () => {
  const filter = button.dataset.filter;
  let visible = 0;
  filterButtons.forEach(item => {
    const selected = item === button;
    item.classList.toggle('active', selected);
    item.setAttribute('aria-pressed', String(selected));
  });
  projects.forEach(project => {
    const show = filter === 'all' || project.dataset.category === filter;
    project.hidden = !show;
    if (show) visible += 1;
  });
  const grid = document.querySelector('.project-grid');
  if (grid) grid.hidden = !Array.from(grid.children).some(child => !child.hidden);
  const rows = document.querySelector('.experience-projects');
  if (rows) rows.hidden = !Array.from(rows.children).some(child => !child.hidden);
  document.querySelector('#work-count').textContent = `${visible} projects`;
}));

const copyButton = document.querySelector('.copy-email');
copyButton?.addEventListener('click', async () => {
  const status = document.querySelector('.copy-status');
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(copyButton.dataset.email);
    status.textContent = 'Email copied.';
  } catch {
    status.textContent = `Copy this address: ${copyButton.dataset.email}`;
  }
});
