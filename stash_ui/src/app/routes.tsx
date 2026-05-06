import { createBrowserRouter } from 'react-router';
import { DocumentsPage } from './pages/DocumentsPage';

export const router = createBrowserRouter(
  [
    {
      path: '/',
      Component: DocumentsPage,
    },
    {
      path: '/*',
      Component: DocumentsPage,
    },
  ],
  {
    basename: '/ui',
  }
);
