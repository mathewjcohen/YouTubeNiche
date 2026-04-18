import { render, screen } from '@testing-library/react'
import { GateToggle } from '@/components/gate-toggle'

test('shows ON when enabled', () => {
  render(<GateToggle gateNumber={3} nicheId={null} enabled={true} onToggle={jest.fn()} />)
  expect(screen.getByText('ON')).toBeInTheDocument()
})

test('shows OFF when disabled', () => {
  render(<GateToggle gateNumber={3} nicheId={null} enabled={false} onToggle={jest.fn()} />)
  expect(screen.getByText('OFF')).toBeInTheDocument()
})
