import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './features/auth/AuthProvider'
import ProtectedRoute from './app/ProtectedRoute'
import TenantProtectedLayout from './app/TenantProtectedLayout'
import LoginPage from './pages/LoginPage'
import AuthCallbackPage from './pages/AuthCallbackPage'
import DashboardPage from './pages/DashboardPage'
import SubmissionDocumentsPage from './pages/SubmissionDocumentsPage'
import SubmissionDetailPage from './pages/SubmissionDetailPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<TenantProtectedLayout />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/submissions/:submissionId" element={<SubmissionDetailPage />} />
              <Route path="/submissions/:submissionId/documents" element={<SubmissionDocumentsPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
