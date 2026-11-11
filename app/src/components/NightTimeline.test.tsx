import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NightTimeline } from './NightTimeline'

const NIGHTS = ['2024-10-08', '2024-10-09', '2024-10-10', '2024-10-11'] as const
const LANDFALL = '2024-10-09'

function renderTimeline(value: string = LANDFALL) {
  const onChange = vi.fn()
  render(<NightTimeline nights={NIGHTS} value={value} landfall={LANDFALL} clearShare={[1, 0.5, 0.25, 0]} onChange={onChange} />)
  return { onChange, slider: screen.getByRole('slider', { name: 'Night' }) }
}

describe('NightTimeline keyboard access', () => {
  it('End moves to the last night and Home to the first', () => {
    const { onChange, slider } = renderTimeline()

    fireEvent.keyDown(slider, { key: 'End' })
    fireEvent.keyDown(slider, { key: 'Home' })

    expect(onChange.mock.calls).toEqual([['2024-10-11'], ['2024-10-08']])
  })

  it('ArrowRight and ArrowUp move one night later', () => {
    const { onChange, slider } = renderTimeline()

    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    fireEvent.keyDown(slider, { key: 'ArrowUp' })

    expect(onChange.mock.calls).toEqual([['2024-10-10'], ['2024-10-10']])
  })

  it('ArrowLeft and ArrowDown move one night earlier', () => {
    const { onChange, slider } = renderTimeline()

    fireEvent.keyDown(slider, { key: 'ArrowLeft' })
    fireEvent.keyDown(slider, { key: 'ArrowDown' })

    expect(onChange.mock.calls).toEqual([['2024-10-08'], ['2024-10-08']])
  })

  it('handles its keys itself (so the browser does not step twice) and leaves others alone', () => {
    const { onChange, slider } = renderTimeline()

    // fireEvent returns false when a handler called preventDefault.
    expect(fireEvent.keyDown(slider, { key: 'End' })).toBe(false)
    expect(fireEvent.keyDown(slider, { key: 'Tab' })).toBe(true)
    expect(fireEvent.keyDown(slider, { key: 'a' })).toBe(true)

    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('stays quiet at the ends instead of re-selecting the same night', () => {
    const { onChange, slider } = renderTimeline('2024-10-08')

    fireEvent.keyDown(slider, { key: 'ArrowLeft' })
    fireEvent.keyDown(slider, { key: 'Home' })

    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('NightTimeline readout', () => {
  it('names the first pass after landfall in the slider value text and the readout', () => {
    const { slider } = renderTimeline()

    expect(slider.getAttribute('aria-valuetext')).toMatch(/Wed 9 Oct 2024, the first pass after landfall, 50% of counties seen clearly/)
    expect(screen.getByText(/the first pass after landfall/)).toBeTruthy()
  })

  it('steps with the previous and next buttons, which disable at the ends', () => {
    const { onChange } = renderTimeline('2024-10-11')

    expect(screen.getByRole('button', { name: 'Next night' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('button', { name: 'Previous night' }))

    expect(onChange).toHaveBeenCalledWith('2024-10-10')
  })
})
