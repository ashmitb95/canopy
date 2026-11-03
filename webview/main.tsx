import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { SideApp } from './app/side/side-app'

// The primary sidebar and the chat share one bundle; the host says which this webview is.
createRoot(document.getElementById('root')!).render(document.body.dataset.surface === 'side' ? <SideApp /> : <App />)
