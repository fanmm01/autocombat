export const classicPages = [
  'home',
  'setup',
  'battle',
  'sim',
  'library',
  'editor',
  'tournament',
  'settings',
  'help/mechanics',
  'help/characters',
  'story',
  'story/play',
  'story/editor',
] as const;

export const autochessPage = 'autochess' as const;
export const pages = [...classicPages, autochessPage] as const;

export type ClassicPage = (typeof classicPages)[number];
export type AppPage = (typeof pages)[number];

export function isAutoChessPage(page: string): boolean {
  return page === autochessPage;
}

export function pageFromPath(path: string): AppPage {
  const page = path.replace(/^\/ui\/?/, '').replace(/\/$/, '');
  return (pages as readonly string[]).includes(page) ? (page as AppPage) : 'home';
}

export function pageUrl(page: string, search = '') {
  return '/ui/' + page + search;
}
