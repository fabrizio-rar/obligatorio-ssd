import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type CSSProperties } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'

import App from './App.tsx'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
      <Toaster
        richColors
        position="top-right"
        closeButton
        toastOptions={{ closeButtonAriaLabel: 'Cerrar aviso' }}
        // sonner puts the ✕ on the top-left corner; these variables move it to the top-right one
        style={
          {
            '--toast-close-button-start': 'unset',
            '--toast-close-button-end': '0',
            '--toast-close-button-transform': 'translate(35%, -35%)',
          } as CSSProperties
        }
      />
    </QueryClientProvider>
  </StrictMode>,
)
