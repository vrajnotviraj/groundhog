import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes, useNavigate } from 'react-router'
import { api, meQuery } from './api'
import { LoadingRows } from './mascot/Loading'
import { TopBar } from './layout/TopBar'
import { Case } from './pages/Case'
import { Cases } from './pages/Cases'
import { Coverage } from './pages/Coverage'
import { Flow } from './pages/Flow'
import { Flows } from './pages/Flows'
import { Login } from './pages/Login'
import { NewCase } from './pages/NewCase'
import { NewFlow } from './pages/NewFlow'
import { Overview } from './pages/Overview'
import { Run } from './pages/Run'
import { Runs } from './pages/Runs'
import { Settings } from './pages/Settings'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<SignedIn />}>
        <Route index element={<Overview />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/new" element={<NewCase />} />
        <Route path="cases/:name" element={<Case />} />
        <Route path="coverage" element={<Coverage />} />
        <Route path="coverage/suggestions" element={<Coverage />} />
        <Route path="flows" element={<Flows />} />
        <Route path="flows/new" element={<NewFlow />} />
        <Route path="flows/:name" element={<Flow />} />
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:id" element={<Run />} />
        <Route path="settings/:tab?" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

// The layout for signed-in screens; without a session it redirects to /login.
function SignedIn() {
  const me = useQuery(meQuery)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  if (me.isError) return <Navigate to="/login" replace />
  if (!me.data) return <main className="page"><LoadingRows /></main>
  const signOut = async () => {
    await api.logout().catch(() => {})
    queryClient.clear()
    navigate('/login')
  }
  return (
    <>
      <TopBar email={me.data.email} onSignOut={signOut} />
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
