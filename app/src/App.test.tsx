import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { makeFixtureFetcher, notFound } from './test/fixtureFetch'

describe('App', () => {
  it('shows a clear empty state when index.json is missing', async () => {
    const { fetcher } = makeFixtureFetcher({ 'index.json': notFound })
    vi.stubGlobal('fetch', fetcher)

    render(<App />)

    expect(await screen.findByRole('heading', { name: /No storms exported yet/ })).toBeTruthy()
    expect(screen.getByText(/blackout export/)).toBeTruthy()
  })

  it('renders the report for the first storm', async () => {
    const { fetcher } = makeFixtureFetcher()
    vi.stubGlobal('fetch', fetcher)

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: /Expected policies without power at hour 72/ }),
    ).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/Milton/)
    // The lead county on the first night after landfall is preselected.
    expect(screen.getByRole('heading', { name: /Alpha, ZZ/ })).toBeTruthy()
    // The night slider shows the date and works from the keyboard natively.
    const slider = screen.getByRole('slider', { name: /night/i })
    expect(slider.getAttribute('aria-valuetext')).toMatch(/Wed 9 Oct 2024/)
    expect(screen.getByText(/CC BY 4\.0/)).toBeTruthy()
  })

  it('shows a readable error when a storm file is missing', async () => {
    const { fetcher } = makeFixtureFetcher({ 'milton2024/scorecard.json': notFound })
    vi.stubGlobal('fetch', fetcher)

    render(<App />)

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toMatch(/milton2024\/scorecard\.json/)
  })
})
