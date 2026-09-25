import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { PendingProvider } from './hooks/pending';
import { AboutPage } from './pages/AboutPage';
import { EvalsPage } from './pages/EvalsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ReportRoute } from './pages/ReportPage';
import { ReportsPage } from './pages/ReportsPage';
import { UploadPage } from './pages/UploadPage';

export function App() {
  return (
    <BrowserRouter>
      <PendingProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/queue" replace />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="queue" element={<ReportsPage key="queue" mode="queue" />} />
            <Route path="reports" element={<ReportsPage key="all" mode="all" />} />
            <Route path="reports/:id" element={<ReportRoute />} />
            <Route path="evals" element={<EvalsPage />} />
            <Route path="about" element={<AboutPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </PendingProvider>
    </BrowserRouter>
  );
}
