import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { api, ApiError } from '../api'
import { Button } from '../components/Button'
import { Field } from '../components/Field'
import { Mascot } from '../components/Mascot'
import styles from './Login.module.css'

export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [shy, setShy] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const login = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['me'] })
      navigate('/')
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate()
  }
  return (
    <main className={styles.page}>
      <Mascot mood={shy ? 'shy' : 'happy'} watch className={styles.mascot}>
        <p className={styles.pitch}>Same steps, every day. Zero AI until something drifts.</p>
      </Mascot>
      <form className={`tile ${styles.form}`} onSubmit={submit}>
        <h1 className={styles.wordmark}>groundhog</h1>
        <p className="muted">Sign in to see what your cases did.</p>
        <Field label="Email">
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={password}
            onFocus={() => setShy(true)} onBlur={() => setShy(false)} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {login.error && <p className="fail" role="alert">{loginMessage(login.error)}</p>}
        <Button variant="primary" type="submit" disabled={login.isPending}>Sign in</Button>
      </form>
    </main>
  )
}

function loginMessage(error: Error): string {
  return error instanceof ApiError ? error.message : 'The console API is not answering. Start it with ./start.sh.'
}
