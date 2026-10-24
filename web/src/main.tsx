import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './styles/tokens.css'
import './styles/base.css'
import { ApiError, meQuery } from './api'
import { AppRoutes } from './routes'

const isClientError = (error: Error) => error instanceof ApiError && error.status < 500

const queryClient: QueryClient = new QueryClient({
  // A 401 on any query re-checks the session, which sends the user to /login.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== meQuery.queryKey[0]) {
        queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
      }
    },
  }),
  defaultOptions: { queries: { retry: (failures, error) => !isClientError(error) && failures < 2 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
