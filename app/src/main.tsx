import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/ibm-plex-sans/latin-600.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/layout.css'
import './styles/controls.css'
import './styles/map.css'
import './styles/county.css'
import './styles/claims.css'
import './styles/states.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

const root = document.getElementById('root')
if (!root) throw new Error('index.html is missing its #root element')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
