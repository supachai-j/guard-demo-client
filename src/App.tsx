import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import AdminConsole from './pages/AdminConsole'

function App() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/admin" element={<AdminConsole />} />
      </Routes>
    </div>
  )
}

export default App

