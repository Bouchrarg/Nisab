import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext'
import { DossierProvider } from './context/DossierContext'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <DossierProvider>
        <App />
      </DossierProvider>
    </AuthProvider>
  </StrictMode>,
)
