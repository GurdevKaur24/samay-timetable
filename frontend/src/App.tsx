import { useEffect, useState } from 'react'

type Status = 'checking' | 'connected' | 'offline'

export default function App() {
  const [status, setStatus] = useState<Status>('checking')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((body) => setStatus(body.status === 'ok' ? 'connected' : 'offline'))
      .catch(() => setStatus('offline'))
  }, [])

  const badge = {
    checking: 'bg-slate-100 text-slate-600',
    connected: 'bg-emerald-50 text-emerald-700',
    offline: 'bg-red-50 text-red-700',
  }[status]

  const label = {
    checking: 'Checking backend…',
    connected: 'Backend connected',
    offline: 'Backend offline. Start it with uvicorn on port 8000.',
  }[status]

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Samay</h1>
      <p className="mt-2 text-slate-600">Clash-free college timetables, generated in minutes.</p>
      <span className={`mt-6 inline-block rounded-md px-3 py-1 text-sm font-medium ${badge}`}>{label}</span>
    </main>
  )
}
