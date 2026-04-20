'use client'
import { createContext, useContext, useTransition } from 'react'
import { toast } from 'sonner'

const PendingCtx = createContext(false)

interface FormProps extends Omit<React.FormHTMLAttributes<HTMLFormElement>, 'action'> {
  action: (fd: FormData) => Promise<void>
  successMessage?: string
  children: React.ReactNode
}

export function Form({ action, successMessage = 'Done', children, ...props }: FormProps) {
  const [isPending, startTransition] = useTransition()

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    startTransition(async () => {
      try {
        await action(fd)
        toast.success(successMessage)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Something went wrong')
      }
    })
  }

  return (
    <PendingCtx value={isPending}>
      <form onSubmit={handleSubmit} {...props}>
        {children}
      </form>
    </PendingCtx>
  )
}

interface SubmitButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode
}

export function SubmitButton({ children, className = '', disabled, ...props }: SubmitButtonProps) {
  const isPending = useContext(PendingCtx)
  const isDisabled = disabled || isPending
  return (
    <button
      type="submit"
      disabled={isDisabled}
      className={`${className} disabled:opacity-50 disabled:cursor-not-allowed`}
      {...props}
    >
      {isPending ? (
        <span className="flex items-center gap-1.5 justify-center">
          <svg className="animate-spin h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {children}
        </span>
      ) : children}
    </button>
  )
}
