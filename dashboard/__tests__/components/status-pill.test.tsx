import { render, screen } from '@testing-library/react'
import { StatusPill } from '@/components/status-pill'

test('renders candidate label', () => {
  render(<StatusPill status="candidate" />)
  expect(screen.getByText('candidate')).toBeInTheDocument()
})

test('renders promoted with green class', () => {
  const { container } = render(<StatusPill status="promoted" />)
  expect(container.firstChild).toHaveClass('bg-green-100')
})
