import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { LanesApp } from './app/side/lanes-app'
import { NewLaneApp } from './app/side/new-lane-app'
import { ReviewApp } from './app/side/review-app'
import { SetupApp } from './app/side/setup-app'
import { SideApp } from './app/side/side-app'

// The primary sidebar and the chat share one bundle; the host says which this webview is.
const surface = document.body.dataset.surface
createRoot(document.getElementById('root')!).render(surface === 'side' ? <SideApp /> : surface === 'conversations' ? <SideApp conversationsOnly /> : surface === 'lanes' ? <LanesApp /> : surface === 'setup' ? <SetupApp /> : surface === 'review' ? <ReviewApp /> : surface === 'new-lane' ? <NewLaneApp /> : <App />)
