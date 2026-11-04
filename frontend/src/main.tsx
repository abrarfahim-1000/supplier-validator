import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root is missing from index.html')
}

// The stylesheet has one palette per scheme; the class mirrors the operating system choice.
const colorSchemeQuery = window.matchMedia('(prefers-color-scheme: dark)')
const applyColorScheme = () => {
  document.documentElement.classList.toggle('dark', colorSchemeQuery.matches)
}
applyColorScheme()
colorSchemeQuery.addEventListener('change', applyColorScheme)

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
